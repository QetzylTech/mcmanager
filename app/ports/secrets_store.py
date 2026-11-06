"""SecretsStore port in front of the ``secrets`` table (Document 7 section 2.24).

Consumers (AuthenticationService, sync adapters, RCON session provisioning)
depend on this interface only. Implementations must ensure
``secrets.encrypted_value`` is ciphertext at rest (ARCHITECTURE ruling 14);
plaintext never touches a client-facing query path.
"""

from __future__ import annotations

import enum
from typing import Protocol


class SecretType(enum.Enum):
    """Closed secret-type set (Document 7 section 2.24)."""

    USER_PASSWORD = 'user_password'
    RCON_CREDENTIAL = 'rcon_credential'
    SYNC_CREDENTIAL = 'sync_credential'
    SESSION_SIGNING = 'session_signing'


class SecretsStore(Protocol):
    """Port: opaque secret_id references only; plaintext only via read()."""

    def store(
        self,
        *,
        secret_type: SecretType,
        associated_entity_type: str,
        associated_entity_id: str,
        plaintext: str,
    ) -> str:
        """Persist an encrypted secret and return the new opaque secret_id."""

    def read(self, secret_id: str) -> str:
        """Decrypt and return the stored secret plaintext."""

    def rotate(
        self,
        secret_id: str,
        *,
        new_plaintext: str,
        associated_entity_type: str,
        associated_entity_id: str,
    ) -> str:
        """Insert a chained rotated secret (``rotation_of``, ``rotated_at``).

        Returns the new secret_id; the caller re-points the owning entity
        (e.g. ``users.secret_id``) at it.
        """
