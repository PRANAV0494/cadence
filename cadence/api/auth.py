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
    """
    Read a required setting, treating empty as missing.

    Trapping only KeyError was not enough: `JWT_SECRET_KEY=` is *set* to the
    empty string, so import succeeded and every admin token was signed with an
    empty key. That is the same failure the no-defaults rule exists to prevent,
    reached by a different route — and `.env.example` shipped exactly that line.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set, or is empty. Configuration comes from the "
            f"environment and there are deliberately no defaults. Export it "
            f"before starting the API, for example:\n"
            f"  export {name}=...\n"
            f"Nothing in this project reads a .env file automatically; "
            f".env.example documents the variables, it does not load them. "
            f"To use one, run: uvicorn cadence.api.main:app --env-file .env"
        )
    return value


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
