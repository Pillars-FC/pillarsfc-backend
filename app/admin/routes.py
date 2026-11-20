import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError

from app.admin.auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_PATH,
    create_session_token,
    require_admin,
    verify_origin,
)
from app.admin.schemas import AdminLoginRequest, AdminSessionResponse
from app.core.config import get_settings
from app.middlewares.rate_limit import limiter

logger = logging.getLogger(__name__)
admin_router = APIRouter()
password_hasher = PasswordHash.recommended()


@admin_router.post(
    "/login",
    summary="Sign in to member administration",
    response_model=AdminSessionResponse,
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    credentials: AdminLoginRequest,
) -> AdminSessionResponse:
    verify_origin(request)
    settings = get_settings()
    username = settings.ADMIN_USERNAME
    password_hash = settings.ADMIN_PASSWORD_HASH
    secret = settings.ADMIN_SESSION_SECRET
    missing_settings = [
        name
        for name, value in (
            ("ADMIN_USERNAME", username),
            ("ADMIN_PASSWORD_HASH", password_hash),
            ("ADMIN_SESSION_SECRET", secret),
        )
        if not value
    ]
    if secret and len(secret) < 32:
        missing_settings.append("ADMIN_SESSION_SECRET (must be at least 32 characters)")
    if missing_settings:
        logger.error(
            "Admin login configuration is incomplete: %s",
            ", ".join(missing_settings),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        )

    try:
        password_matches = password_hasher.verify(credentials.password, password_hash)
    except (HashVerificationError, UnknownHashError) as error:
        logger.error("Admin password hash configuration is invalid")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        ) from error

    if not (hmac.compare_digest(credentials.username, username) and password_matches):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_session_token(username, settings),
        max_age=settings.ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.ADMIN_SESSION_COOKIE_SECURE,
        samesite=settings.ADMIN_SESSION_COOKIE_SAMESITE,
        path=ADMIN_SESSION_PATH,
    )
    return AdminSessionResponse(status="success", username=username)


@admin_router.get(
    "/session",
    summary="Check the admin session",
    response_model=AdminSessionResponse,
)
async def get_admin_session(request: Request) -> AdminSessionResponse:
    username = await require_admin(request)
    return AdminSessionResponse(status="success", username=username)


@admin_router.post("/logout", summary="Sign out of member administration")
async def logout(request: Request, response: Response) -> dict[str, str]:
    verify_origin(request)
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path=ADMIN_SESSION_PATH,
        httponly=True,
        secure=get_settings().ADMIN_SESSION_COOKIE_SECURE,
        samesite=get_settings().ADMIN_SESSION_COOKIE_SAMESITE,
    )
    return {"status": "success"}
