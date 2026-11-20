import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import Settings, get_settings

MEMBER_SESSION_COOKIE = "pillars_member_session"
MEMBER_SESSION_PATH = "/api/v1"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemberPrincipal:
    membership_id: str
    name: str


def get_member_session_serializer(settings: Settings) -> URLSafeTimedSerializer:
    secret = settings.MEMBER_SESSION_SECRET
    if not secret or len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Member authentication is not configured",
        )
    return URLSafeTimedSerializer(secret, salt="pillars-member-session")


def create_member_session_token(membership_id: str, settings: Settings) -> str:
    return get_member_session_serializer(settings).dumps(
        {"membership_id": membership_id}
    )


async def require_member(request: Request) -> MemberPrincipal:
    token = request.cookies.get(MEMBER_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Member sign-in required",
        )

    settings = get_settings()
    try:
        session = get_member_session_serializer(settings).loads(
            token, max_age=settings.MEMBER_SESSION_TTL_SECONDS
        )
    except BadSignature as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Member session is invalid or expired",
        ) from error

    membership_id = session.get("membership_id") if isinstance(session, dict) else None
    if not isinstance(membership_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Member session is invalid",
        )

    database = request.app.state.database
    account = await database["member_accounts"].find_one(
        {"membership_id": membership_id, "email_verified": True},
        {"_id": 0, "membership_id": 1},
    )
    member = await database["members"].find_one(
        {"_id": membership_id, "status": "active"},
        {"_id": 1, "name": 1},
    )
    if account is None or member is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An active verified member account is required",
        )

    return MemberPrincipal(membership_id=membership_id, name=member["name"])
