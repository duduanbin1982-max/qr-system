"""SMTP password encryption helpers"""
import base64, os
from cryptography.fernet import Fernet

def _derive_fernet_key():
    """Derive Fernet key from SECRET_KEY (deterministic)."""
    from modules.config import SECRET_KEY
    import hashlib
    h = hashlib.sha256(SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(h)

def encrypt_smtp_password(plaintext):
    """Encrypt password for DB storage."""
    if not plaintext:
        return ""
    f = Fernet(_derive_fernet_key())
    return f.encrypt(plaintext.encode()).decode()

def decrypt_smtp_password(ciphertext):
    """Decrypt password from DB storage."""
    if not ciphertext:
        return ""
    try:
        f = Fernet(_derive_fernet_key())
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # fallback: plaintext legacy