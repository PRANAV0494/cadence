"""
JWT authentication helpers for admin access.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ── Configuration ──────────────────────────────────────────────
# No defaults. A shared fallback signing key is how this deployment previously
# shipped its production secret: the value was a CloudFormation parameter
# default, so `sam deploy` without an override signed real tokens with a string
# published in the repository. Failing to start is the safe behaviour.


def _required(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"{name} is not set. Configuration comes from the environment; there "
            f"are deliberately no defaults. Copy .env.example to .env and fill it "
            f"in, or export {name} before starting the API."
        ) from None


SECRET_KEY = _required("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("TOKEN_EXPIRE_MINUTES", "60"))

ADMIN_USERNAME = _required("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = _required("ADMIN_PASSWORD_HASH")

# ── Password hashing ──────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

security_scheme = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Return bcrypt hash of a password (utility for setup)."""
    return pwd_context.hash(password)


def authenticate_admin(username: str, password: str) -> bool:
    """Validate admin credentials."""
    if username != ADMIN_USERNAME:
        return False
    return verify_password(password, ADMIN_PASSWORD_HASH)


# ── JWT Token ──────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)) -> str:
    """
    FastAPI dependency: extracts and verifies the JWT from the
    Authorization: Bearer <token> header.  Returns the username.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
