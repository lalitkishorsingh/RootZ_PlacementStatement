from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models
from django.core.exceptions import ImproperlyConfigured
import hashlib
import hmac

def email_digest(value):
    return hmac.new(settings.LOOKUP_KEY.encode(), value.strip().lower().encode(), hashlib.sha256).hexdigest()

def keyring():
    return dict(pair.split(':', 1) for pair in settings.DATA_KEYS.split(','))

def encrypt(value):
    keys = keyring()
    version = next(iter(keys))
    return version + ':' + Fernet(keys[version].encode()).encrypt(str(value).encode()).decode()

def decrypt(value):
    if not value:
        return ''
    version, token = value.split(':', 1)
    try:
        return Fernet(keyring()[version].encode()).decrypt(token.encode()).decode()
    except (KeyError, InvalidToken) as exc:
        raise ImproperlyConfigured('Encrypted data cannot be decrypted with configured keys') from exc

class EncryptedTextField(models.TextField):
    """Only use exact lookups against separate identifiers, never ciphertext."""
    def from_db_value(self, value, expression, connection):
        return decrypt(value) if value is not None else value

    def get_prep_value(self, value):
        return encrypt(value) if value not in (None, '') else value
