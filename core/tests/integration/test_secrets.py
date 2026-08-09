"""SecretsStore ciphertext-at-rest contract (Doc 7 §10, Doc 8 §9)."""

from __future__ import annotations

from app.bootstrap import Container
from app.infrastructure.secrets import _FERNET_PREFIX
from app.ports.secrets_store import SecretType


def test_encrypted_value_is_ciphertext_not_plaintext(container: Container) -> None:
    plaintext = 'super-secret-rcon-password'
    secret_id = container.secrets.store(
        secret_type=SecretType.RCON_CREDENTIAL,
        associated_entity_type='runtime_session',
        associated_entity_id='rs_test',
        plaintext=plaintext,
    )
    row = container.store.reader().execute(
        'SELECT encrypted_value FROM secrets WHERE secret_id = ?', (secret_id,)
    ).fetchone()
    stored = row['encrypted_value']
    assert plaintext not in stored
    assert stored.startswith(_FERNET_PREFIX)


def test_read_roundtrip(container: Container) -> None:
    plaintext = 'another-secret-value'
    secret_id = container.secrets.store(
        secret_type=SecretType.SYNC_CREDENTIAL,
        associated_entity_type='manager',
        associated_entity_id='mgr',
        plaintext=plaintext,
    )
    assert container.secrets.read(secret_id) == plaintext


def test_rotate_chains_secrets(container: Container) -> None:
    old_id = container.secrets.store(
        secret_type=SecretType.USER_PASSWORD,
        associated_entity_type='user',
        associated_entity_id='u_test',
        plaintext='old-hash-value',
    )
    new_id = container.secrets.rotate(
        old_id,
        new_plaintext='new-hash-value',
        associated_entity_type='user',
        associated_entity_id='u_test',
    )
    row = container.store.reader().execute(
        'SELECT rotation_of, rotated_at FROM secrets WHERE secret_id = ?', (new_id,)
    ).fetchone()
    assert row['rotation_of'] == old_id
    old_row = container.store.reader().execute(
        'SELECT rotated_at FROM secrets WHERE secret_id = ?', (old_id,)
    ).fetchone()
    assert old_row['rotated_at'] is not None
