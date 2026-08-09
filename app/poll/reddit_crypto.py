from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class TokenEncryptionError(Exception):
    """Raised when the deployment key is missing or cannot decrypt a token."""


def _fernet():
    key = settings.REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY
    if not key:
        raise TokenEncryptionError('Reddit automation token encryption is not configured.')
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise TokenEncryptionError('Reddit automation token encryption key is invalid.') from exc


def encrypt_refresh_token(refresh_token):
    if not refresh_token:
        raise TokenEncryptionError('A refresh token is required.')
    return _fernet().encrypt(refresh_token.encode('utf-8')).decode('ascii')


def decrypt_refresh_token(encrypted_token):
    if not encrypted_token:
        raise TokenEncryptionError('No Reddit refresh token is stored.')
    try:
        return _fernet().decrypt(encrypted_token.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError, TypeError) as exc:
        raise TokenEncryptionError('The stored Reddit refresh token could not be decrypted.') from exc
