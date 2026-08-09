"""SecretsStore implementation: Fernet encrypt-at-rest in ``secrets``.
(Document 7 section 2.24 / section 10, ARCHITECTURE ruling 14.)

The encryption key lives in a server-side keyfile *outside* the database
(never a table), provisioned at first setup. Keyfile loss = documented
unrecoverable secret loss; rotation inserts a chained row (``rotation_of``)
and re-points the owning entity.
"""

from __future__ import annotations

import uuid
import time
from pathlib import Path
from typing import cast

from cryptography.fernet import Fernet

from app.infrastructure.sqlite.connection import SqliteStore
from app.ports.secrets_store import SecretType

# Fernet token prefix before the ciphertext; used by tests to assert
# ciphertext-at-rest (secrets.encrypted_value must not contain plaintext).
_FERNET_PREFIX = 'gAAAAA'


class SecretsError(Exception):
    """Secrets-store failure (missing keyfile, invalid token, missing row)."""


def provision_keyfile(path: str | Path) -> Path:
    """Create the server-side keyfile at ``path`` (never inside the DB).

    Generates a fresh Fernet key when the file does not exist. Refuses to
    overwrite an existing keyfile.
    """
    keyfile = Path(path)
    if keyfile.exists():
        return keyfile
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    keyfile.write_bytes(key)
    return keyfile


class SqliteSecretsStore:
    """Fernet-encrypted secrets rows backed by :class:`SqliteStore`."""

    def __init__(self, store: SqliteStore, keyfile_path: str | Path) -> None:
        self._store = store
        self._keyfile = Path(keyfile_path)
        self._fernet: Fernet | None = None

    def _cipher(self) -> Fernet:
        if self._fernet is None:
            if not self._keyfile.exists():
                raise SecretsError(f'keyfile missing at {self._keyfile}')
            self._fernet = Fernet(self._keyfile.read_bytes())
        return self._fernet

    # -- port -----------------------------------------------------------------

    def store(
        self,
        *,
        secret_type: SecretType,
        associated_entity_type: str,
        associated_entity_id: str,
        plaintext: str,
    ) -> str:
        secret_id = f'sec_{uuid.uuid4().hex[:16]}'
        token = self._cipher().encrypt(plaintext.encode('utf-8'))
        connection = self._store.writer()
        connection.execute(
            'INSERT INTO secrets ('
            '  secret_id, secret_type, encrypted_value,'
            '  associated_entity_type, associated_entity_id,'
            '  rotation_of, created_at, rotated_at'
            ') VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)',
            (
                secret_id,
                secret_type.value,
                token.decode('utf-8'),
                associated_entity_type,
                associated_entity_id,
                int(time.time()),
            ),
        )
        connection.commit()
        return secret_id

    def read(self, secret_id: str) -> str:
        connection = self._store.reader()
        row = connection.execute(
            'SELECT encrypted_value FROM secrets WHERE secret_id = ?', (secret_id,)
        ).fetchone()
        if row is None:
            raise SecretsError(f'secret not found: {secret_id}')
        try:
            plaintext = self._cipher().decrypt(
                cast(bytes, row['encrypted_value'].encode('utf-8'))
            )
        except Exception as exc:  # cryptography raises InvalidToken
            raise SecretsError(f'cannot decrypt secret {secret_id}') from exc
        return plaintext.decode('utf-8')

    def rotate(
        self,
        secret_id: str,
        *,
        new_plaintext: str,
        associated_entity_type: str,
        associated_entity_id: str,
    ) -> str:
        connection = self._store.writer()
        row = connection.execute(
            'SELECT secret_type FROM secrets WHERE secret_id = ?', (secret_id,)
        ).fetchone()
        if row is None:
            raise SecretsError(f'secret not found: {secret_id}')
        secret_type = SecretType(row['secret_type'])
        connection.execute(
            'UPDATE secrets SET rotated_at = ? WHERE secret_id = ?',
            (int(time.time()), secret_id),
        )
        connection.commit()
        new_id = self.store(
            secret_type=secret_type,
            associated_entity_type=associated_entity_type,
            associated_entity_id=associated_entity_id,
            plaintext=new_plaintext,
        )
        connection.execute(
            'UPDATE secrets SET rotation_of = ? WHERE secret_id = ?',
            (secret_id, new_id),
        )
        connection.commit()
        return new_id
