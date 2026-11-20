import hmac
import logging

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import Settings, get_settings

ADMIN_SESSION_COOKIE = "pillars_admin_session"
ADMIN_SESSION_PATH = "/api/v1/admin"
logger = logging.getLogger(__name__)


def get_session_serializer(settings: Settings) -> URLSafeTimedSerializer:
    secret = settings.ADMIN_SESSION_SECRET
    if not secret or len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        )
    return URLSafeTimedSerializer(secret, salt="pillars-admin-session")


def create_session_token(username: str, settings: Settings) -> str:
    return get_session_serializer(settings).dumps({"username": username})


def verify_origin(request: Request) -> None:
    expected_origin = get_settings().FRONTEND_ORIGIN.rstrip("/")
    api_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("origin") not in {expected_origin, api_origin}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )


async def require_admin(request: Request) -> str:
    settings = get_settings()
    username = settings.ADMIN_USERNAME
    secret = settings.ADMIN_SESSION_SECRET
    missing_settings = [
        name
        for name, value in (
            ("ADMIN_USERNAME", username),
            ("ADMIN_SESSION_SECRET", secret),
        )
        if not value
    ]
    if secret and len(secret) < 32:
        missing_settings.append("ADMIN_SESSION_SECRET (must be at least 32 characters)")
    if missing_settings:
        logger.error(
            "Admin session configuration is incomplete: %s",
            ", ".join(missing_settings),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        )

    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login required",
        )

    try:
        session = get_session_serializer(settings).loads(
            token, max_age=settings.ADMIN_SESSION_TTL_SECONDS
        )
    except BadSignature as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session is invalid or expired",
        ) from error

    session_username = session.get("username") if isinstance(session, dict) else None
    if not isinstance(session_username, str) or not hmac.compare_digest(
        session_username, username
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session is invalid",
        )
    return username
