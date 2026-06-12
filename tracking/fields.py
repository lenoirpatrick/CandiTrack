"""Custom model fields for CandiTrack.

`EncryptedCharField` transparently encrypts its value at rest using Fernet
(symmetric encryption from the `cryptography` package). The encryption key is
read from `settings.CANDITRACK_FERNET_KEY` and must be kept out of version
control (see `.env.example`). This is used to store job-site passwords
encrypted in the database (issue #366).
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _get_fernet():
    key = getattr(settings, 'CANDITRACK_FERNET_KEY', '')
    if not key:
        raise ImproperlyConfigured(
            'CANDITRACK_FERNET_KEY is not set. Generate one with '
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and add it to your .env.'
        )
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class EncryptedCharField(models.TextField):
    """A text field whose value is stored encrypted in the database.

    The plaintext is exposed normally in Python; encryption/decryption happens
    on the way to and from the database.
    """

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        token = _get_fernet().encrypt(str(value).encode())
        return token.decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value was not encrypted with the current key (or is corrupt).
            # Return it as-is rather than crashing the whole queryset.
            return value
