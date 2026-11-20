import hashlib
import html
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import resend
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError
from pymongo.errors import DuplicateKeyError
from resend.exceptions import ResendError
from starlette.concurrency import run_in_threadpool

from app.admin.auth import verify_origin
from app.core.config import get_settings
from app.member_auth.auth import (
    MEMBER_SESSION_COOKIE,
    MEMBER_SESSION_PATH,
    MemberPrincipal,
    create_member_session_token,
    get_member_session_serializer,
    require_member,
)
from app.member_auth.schemas import (
    MemberAccountMessage,
    MemberAccountRegistration,
    MemberEmailVerification,
    MemberLoginRequest,
    MemberSessionResponse,
)
from app.middlewares.rate_limit import limiter

logger = logging.getLogger(__name__)
member_auth_router = APIRouter()
password_hasher = PasswordHash.recommended()
ACCOUNT_MESSAGE = (
    "If the email matches an active club member, an account activation link "
    "will be sent."
)


async def send_verification_email(email: str, name: str, token: str) -> None:
    settings = get_settings()
    if not settings.RESEND_API_KEY or not settings.MAIL_FROM_RESEND:
        logger.error("Member activation email service is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Member activation email is not configured",
        )

    activation_url = (
        f"{settings.FRONTEND_ORIGIN.rstrip('/')}/member/verify?token={quote(token)}"
    )
    safe_name = html.escape(name)
    safe_url = html.escape(activation_url, quote=True)
    resend.api_key = settings.RESEND_API_KEY
    try:
        await run_in_threadpool(
            resend.Emails.send,
            {
                "from": settings.MAIL_FROM_RESEND,
                "to": [email],
                "subject": "Activate your Pillars FC member account",
                "text": (
                    f"Hello {name},\n\n"
                    "Use the link below to verify your email and activate your "
                    f"Pillars FC member account:\n{activation_url}\n\n"
                    "This link expires in one hour. If you did not request this, "
                    "you can ignore this email."
                ),
                "html": (
                    f"<p>Hello {safe_name},</p>"
                    "<p>Use the link below to verify your email and activate your "
                    "Pillars FC member account:</p>"
                    f'<p><a href="{safe_url}">Activate member account</a></p>'
                    "<p>This link expires in one hour. If you did not request "
                    "this, you can ignore this email.</p>"
                ),
            },
        )
    except ResendError as error:
        logger.exception("Resend failed to send a member activation email")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to send the activation email right now",
        ) from error


@member_auth_router.post(
    "/register",
    summary="Request a verified member account",
    response_model=MemberAccountMessage,
)
@limiter.limit("5/minute")
async def register_member_account(
    request: Request,
    registration: MemberAccountRegistration,
) -> MemberAccountMessage:
    verify_origin(request)
    get_member_session_serializer(get_settings())
    normalized_email = str(registration.email).casefold()
    email_pattern = f"^{re.escape(normalized_email)}$"
    member_cursor = (
        request.app.state.database["members"]
        .find(
            {
                "email": {"$regex": email_pattern, "$options": "i"},
                "status": "active",
            },
            {"_id": 1, "name": 1, "email": 1},
        )
        .limit(2)
    )
    matching_members = await member_cursor.to_list(length=2)
    if len(matching_members) != 1:
        return MemberAccountMessage(status="success", message=ACCOUNT_MESSAGE)

    member = matching_members[0]
    accounts = request.app.state.database["member_accounts"]
    existing = await accounts.find_one({"membership_id": member["_id"]})
    if existing is not None and (
        existing.get("email_normalized") != normalized_email
        or existing.get("email_verified") is True
    ):
        return MemberAccountMessage(status="success", message=ACCOUNT_MESSAGE)

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    account_fields = {
        "membership_id": member["_id"],
        "email_normalized": normalized_email,
        "password_hash": password_hasher.hash(registration.password),
        "email_verified": False,
        "email_verification_token_hash": hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest(),
        "email_verification_expires_at": now + timedelta(hours=1),
        "created_at": now,
    }

    if existing is not None:
        await accounts.update_one(
            {"_id": existing["_id"], "email_verified": False},
            {"$set": account_fields},
        )
    else:
        try:
            await accounts.insert_one(account_fields)
        except DuplicateKeyError:
            return MemberAccountMessage(status="success", message=ACCOUNT_MESSAGE)

    await send_verification_email(normalized_email, member["name"], token)
    return MemberAccountMessage(status="success", message=ACCOUNT_MESSAGE)


@member_auth_router.post(
    "/verify-email",
    summary="Verify a member account email",
    response_model=MemberAccountMessage,
)
@limiter.limit("10/minute")
async def verify_member_email(
    request: Request,
    verification: MemberEmailVerification,
) -> MemberAccountMessage:
    account = request.app.state.database["member_accounts"]
    result = await account.update_one(
        {
            "email_verification_token_hash": hashlib.sha256(
                verification.token.encode("utf-8")
            ).hexdigest(),
            "email_verification_expires_at": {"$gt": datetime.now(timezone.utc)},
            "email_verified": False,
        },
        {
            "$set": {
                "email_verified": True,
                "email_verified_at": datetime.now(timezone.utc),
            },
            "$unset": {
                "email_verification_token_hash": "",
                "email_verification_expires_at": "",
            },
        },
    )
    if result.modified_count != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This activation link is invalid or expired",
        )
    return MemberAccountMessage(
        status="success",
        message="Your email is verified. You can now sign in.",
    )


@member_auth_router.post(
    "/login",
    summary="Sign in to a verified member account",
    response_model=MemberSessionResponse,
)
@limiter.limit("5/minute")
async def login_member(
    request: Request,
    response: Response,
    credentials: MemberLoginRequest,
) -> MemberSessionResponse:
    verify_origin(request)
    settings = get_settings()
    get_member_session_serializer(settings)
    account = await request.app.state.database["member_accounts"].find_one(
        {"email_normalized": str(credentials.email).casefold()}
    )
    password_hash = account.get("password_hash") if account else None
    if not isinstance(password_hash, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect, or the account is not verified",
        )

    try:
        password_matches = password_hasher.verify(credentials.password, password_hash)
    except (HashVerificationError, UnknownHashError) as error:
        logger.error("A member account contains an invalid password hash")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Member authentication is not available",
        ) from error

    if not password_matches or account.get("email_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect, or the account is not verified",
        )

    member = await request.app.state.database["members"].find_one(
        {"_id": account["membership_id"], "status": "active"},
        {"_id": 1, "name": 1},
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An active club membership is required",
        )

    response.set_cookie(
        key=MEMBER_SESSION_COOKIE,
        value=create_member_session_token(account["membership_id"], settings),
        max_age=settings.MEMBER_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.ADMIN_SESSION_COOKIE_SECURE,
        samesite=settings.ADMIN_SESSION_COOKIE_SAMESITE,
        path=MEMBER_SESSION_PATH,
    )
    return MemberSessionResponse(
        status="success",
        membership_id=account["membership_id"],
        name=member["name"],
    )


@member_auth_router.get(
    "/session",
    summary="Check the current member session",
    response_model=MemberSessionResponse,
)
async def get_member_session(
    member: MemberPrincipal = Depends(require_member),
) -> MemberSessionResponse:
    return MemberSessionResponse(
        status="success",
        membership_id=member.membership_id,
        name=member.name,
    )


@member_auth_router.post("/logout", summary="Sign out of a member account")
async def logout_member(request: Request, response: Response) -> dict[str, str]:
    verify_origin(request)
    response.delete_cookie(
        key=MEMBER_SESSION_COOKIE,
        path=MEMBER_SESSION_PATH,
        httponly=True,
        secure=get_settings().ADMIN_SESSION_COOKIE_SECURE,
        samesite=get_settings().ADMIN_SESSION_COOKIE_SAMESITE,
    )
    return {"status": "success"}
