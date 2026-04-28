"""
security.py
-----------
Handles:
  - Password hashing (bcrypt)
  - JWT access + refresh token creation / verification
  - AES-256-GCM encryption / decryption helpers (for payload encryption)
"""

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────
def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, org_id: Optional[str] = None) -> str:
    return _create_token(
        {"sub": user_id, "org": org_id, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    """
    Returns decoded payload or raises JWTError.
    Callers should handle JWTError → 401.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# ── AES-256-GCM helpers ───────────────────────────────────────────────────────
def _derive_org_key(org_id: str) -> bytes:
    """
    Derives a 32-byte AES key per organisation using HKDF-like SHA-256.
    In production replace with AWS KMS GenerateDataKey.
    """
    master = settings.MASTER_ENCRYPTION_KEY.encode()
    return hashlib.sha256(master + org_id.encode()).digest()  # 32 bytes


def encrypt_payload(plaintext: bytes, org_id: str) -> str:
    """
    Encrypts bytes with AES-256-GCM.
    Returns base64(nonce + ciphertext) as a string for DB / API transport.
    """
    key = _derive_org_key(org_id)
    nonce = os.urandom(12)                     # 96-bit GCM nonce
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_payload(encoded: str, org_id: str) -> bytes:
    """
    Decrypts a string produced by encrypt_payload.
    """
    key = _derive_org_key(org_id)
    raw = base64.b64decode(encoded)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None)
