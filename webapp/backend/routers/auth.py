import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import bcrypt
import jwt

router = APIRouter()
_security = HTTPBearer()


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _secret() -> str:
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY environment variable is not set")
    return secret


def create_token() -> str:
    payload = {
        "sub": "user",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    return verify_token(credentials.credentials)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    password_hash = os.getenv("PASSWORD_HASH", "")
    if not password_hash:
        raise HTTPException(status_code=500, detail="Server not configured: PASSWORD_HASH missing")

    if not bcrypt.checkpw(req.password.encode("utf-8"), password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid password")

    return TokenResponse(access_token=create_token())
