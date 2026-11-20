import re
import secrets
from datetime import datetime, timezone
from typing import Any

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.admin.auth import require_admin, verify_origin
from app.core.config import get_settings
from app.members.schemas import (
    Member,
    MemberApplication,
    MemberApplicationCreate,
    MemberApplicationResponse,
    MemberApplicationsResponse,
    MemberApplicationSubmitted,
    MemberApplicationSubmittedResponse,
    MemberCreate,
    MemberDetail,
    MemberDetailResponse,
    MemberRegistration,
    MemberRegistrationCreate,
    MemberResponse,
    MembersResponse,
    PreferredPosition,
)
from app.middlewares.rate_limit import limiter

members_router = APIRouter()
member_applications_router = APIRouter()
admin_members_router = APIRouter(dependencies=[Depends(require_admin)])
admin_applications_router = APIRouter(dependencies=[Depends(require_admin)])
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


def generate_membership_id(created_at: datetime) -> str:
    return f"PFC-{created_at.year % 100:02d}{secrets.token_hex(4).upper()}"


def serialize_member(document: dict[str, Any]) -> Member:
    joined_at = document["joined_at"]
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=timezone.utc)
    return Member(
        membership_id=document["_id"],
        name=document["name"],
        joined_at=joined_at,
        status=document.get("status", "active"),
        preferred_position=document.get("preferred_position"),
        image_url=document.get("image_url"),
    )


def serialize_member_detail(document: dict[str, Any]) -> MemberDetail:
    registrations = []
    for registration in document.get("registrations", []):
        registered_at = registration["registered_at"]
        if registered_at.tzinfo is None:
            registered_at = registered_at.replace(tzinfo=timezone.utc)
        registrations.append(
            MemberRegistration(
                year=registration["year"],
                registered_at=registered_at,
            )
        )
    registrations.sort(key=lambda registration: registration.year)
    return MemberDetail(
        **serialize_member(document).model_dump(),
        registrations=registrations,
    )


def serialize_application(document: dict[str, Any]) -> MemberApplication:
    return MemberApplication(
        application_id=document["_id"],
        first_name=document["first_name"],
        last_name=document["last_name"],
        email=document["email"],
        phone=document["phone"],
        address=document["address"],
        preferred_position=document["preferred_position"],
        date_of_birth=document.get("date_of_birth"),
        image_url=document.get("image_url"),
        status=document["status"],
        submitted_at=document["submitted_at"],
        consented_at=document["consented_at"],
        membership_id=document.get("membership_id"),
    )


async def read_member_image(image: UploadFile | None) -> bytes | None:
    if image is None:
        return None

    if not image.filename and image.size in (0, None):
        if not await image.read(1):
            return None
        await image.seek(0)

    if image.size is not None and image.size > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image must be {MAX_IMAGE_SIZE // (1024 * 1024)} MB or smaller",
        )

    signature_prefixes = ALLOWED_IMAGE_TYPES.get(image.content_type or "")
    if signature_prefixes is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG, or WebP image",
        )

    content = await image.read(MAX_IMAGE_SIZE + 1)
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image must be {MAX_IMAGE_SIZE // (1024 * 1024)} MB or smaller",
        )

    signature_matches = any(content.startswith(prefix) for prefix in signature_prefixes)
    if image.content_type == "image/webp":
        signature_matches = (
            signature_matches and len(content) >= 12 and content[8:12] == b"WEBP"
        )
    if not signature_matches:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file does not match its image type",
        )
    return content


async def upload_member_image(
    content: bytes,
    public_id: str,
    folder: str = "pillars-fc/members",
) -> dict[str, Any]:
    settings = get_settings()
    credentials = (
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )
    if not all(credentials):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image uploads are not configured",
        )

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    try:
        result = await run_in_threadpool(
            cloudinary.uploader.upload,
            content,
            public_id=public_id,
            folder=folder,
            resource_type="image",
            overwrite=False,
            unique_filename=True,
            allowed_formats=["jpg", "jpeg", "png", "webp"],
        )
    except CloudinaryError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image upload failed",
        ) from error

    if not isinstance(result.get("secure_url"), str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image service returned an invalid response",
        )
    return result


@members_router.get(
    "",
    summary="List registered members",
    response_model=MembersResponse,
    status_code=status.HTTP_200_OK,
)
async def list_members(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    preferred_position: PreferredPosition | None = Query(default=None),
) -> MembersResponse:
    query: dict[str, Any] = {"status": {"$in": ["active", "inactive"]}}
    if preferred_position:
        query["preferred_position"] = preferred_position
    if search and search.strip():
        term = re.escape(search.strip())
        query["$or"] = [
            {"name": {"$regex": term, "$options": "i"}},
            {"_id": {"$regex": term, "$options": "i"}},
        ]

    collection = request.app.state.database["members"]
    total = await collection.count_documents(query)
    cursor = (
        collection.find(
            query,
            {
                "email": 0,
                "phone": 0,
                "address": 0,
                "image_public_id": 0,
                "registrations": 0,
                "date_of_birth": 0,
                "consent": 0,
                "consented_at": 0,
                "source_application_id": 0,
            },
        )
        .sort("joined_at", -1)
        .skip(skip)
        .limit(limit)
    )
    members = [serialize_member(document) async for document in cursor]
    return MembersResponse(status="success", data=members, total=total)


@members_router.get(
    "/{membership_id}",
    summary="Get a member profile and registration history",
    response_model=MemberDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_member(
    request: Request,
    membership_id: str = Path(min_length=1, max_length=40),
) -> MemberDetailResponse:
    collection = request.app.state.database["members"]
    document = await collection.find_one(
        {"_id": membership_id, "status": {"$in": ["active", "inactive"]}},
        {
            "email": 0,
            "phone": 0,
            "address": 0,
            "image_public_id": 0,
            "date_of_birth": 0,
            "consent": 0,
            "consented_at": 0,
            "source_application_id": 0,
        },
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    return MemberDetailResponse(
        status="success", data=serialize_member_detail(document)
    )


@member_applications_router.post(
    "",
    summary="Submit a membership application",
    response_model=MemberApplicationSubmittedResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def submit_member_application(
    request: Request,
    first_name: str = Form(),
    last_name: str = Form(),
    email: str = Form(),
    phone: str = Form(),
    address: str = Form(),
    preferred_position: str = Form(),
    date_of_birth: str = Form(default=""),
    consent: str = Form(),
    image: UploadFile | None = File(default=None),
) -> MemberApplicationSubmittedResponse:
    try:
        application_data = MemberApplicationCreate.model_validate(
            {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "address": address,
                "preferred_position": preferred_position,
                "date_of_birth": date_of_birth or None,
                "consent": consent,
            }
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.errors(include_input=False, include_context=False),
        ) from error

    image_content = await read_member_image(image)
    submitted_at = datetime.now(timezone.utc)
    application_id = f"APP-{submitted_at.year % 100:02d}{secrets.token_hex(6).upper()}"
    image_result = (
        await upload_member_image(
            image_content,
            application_id,
            folder="pillars-fc/applications",
        )
        if image_content is not None
        else None
    )
    document = {
        "_id": application_id,
        "first_name": application_data.first_name,
        "last_name": application_data.last_name,
        "email": str(application_data.email),
        "phone": application_data.phone,
        "address": application_data.address,
        "preferred_position": application_data.preferred_position,
        "date_of_birth": (
            application_data.date_of_birth.isoformat()
            if application_data.date_of_birth
            else None
        ),
        "image_url": image_result.get("secure_url") if image_result else None,
        "image_public_id": image_result.get("public_id") if image_result else None,
        "consent": application_data.consent,
        "consented_at": submitted_at,
        "submitted_at": submitted_at,
        "status": "pending",
    }
    await request.app.state.database["member_applications"].insert_one(document)
    return MemberApplicationSubmittedResponse(
        status="success",
        data=MemberApplicationSubmitted(
            application_id=application_id,
            status="pending",
        ),
    )


@admin_members_router.post(
    "",
    summary="Add a member",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_member(
    request: Request,
    name: str = Form(),
    email: str = Form(),
    phone: str = Form(),
    address: str = Form(),
    preferred_position: str = Form(),
    image: UploadFile | None = File(default=None),
) -> MemberResponse:
    verify_origin(request)
    try:
        member_data = MemberCreate.model_validate(
            {
                "name": name,
                "email": email,
                "phone": phone,
                "address": address,
                "preferred_position": preferred_position,
            }
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.errors(include_input=False, include_context=False),
        ) from error

    image_content = await read_member_image(image)
    collection = request.app.state.database["members"]
    joined_at = datetime.now(timezone.utc)

    for _ in range(3):
        membership_id = generate_membership_id(joined_at)
        image_result = (
            await upload_member_image(image_content, membership_id)
            if image_content is not None
            else None
        )
        document = {
            "_id": membership_id,
            "name": member_data.name,
            "email": str(member_data.email),
            "phone": member_data.phone,
            "address": member_data.address,
            "preferred_position": member_data.preferred_position,
            "image_url": image_result.get("secure_url") if image_result else None,
            "image_public_id": image_result.get("public_id") if image_result else None,
            "joined_at": joined_at,
            "status": "active",
            "registrations": [{"year": joined_at.year, "registered_at": joined_at}],
        }
        try:
            await collection.insert_one(document)
        except DuplicateKeyError:
            if image_result is not None:
                await run_in_threadpool(
                    cloudinary.uploader.destroy, image_result["public_id"]
                )
            continue
        return MemberResponse(status="success", data=serialize_member(document))

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unable to generate a unique membership ID",
    )


@admin_applications_router.get(
    "",
    summary="List pending membership applications",
    response_model=MemberApplicationsResponse,
    status_code=status.HTTP_200_OK,
)
async def list_member_applications(
    request: Request,
) -> MemberApplicationsResponse:
    collection = request.app.state.database["member_applications"]
    query = {"status": {"$in": ["pending", "approving"]}}
    total = await collection.count_documents(query)
    cursor = collection.find(query, {"image_public_id": 0}).sort("submitted_at", -1)
    applications = [serialize_application(document) async for document in cursor]
    return MemberApplicationsResponse(status="success", data=applications, total=total)


@admin_applications_router.post(
    "/{application_id}/approve",
    summary="Approve a membership application",
    response_model=MemberApplicationResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_member_application(
    request: Request,
    application_id: str = Path(min_length=1, max_length=40),
) -> MemberApplicationResponse:
    verify_origin(request)
    database = request.app.state.database
    applications = database["member_applications"]
    members = database["members"]
    application = await applications.find_one({"_id": application_id})
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership application not found",
        )

    if application["status"] == "approved":
        return MemberApplicationResponse(
            status="success", data=serialize_application(application)
        )
    if application["status"] == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application has already been rejected",
        )

    if application["status"] == "pending":
        await applications.update_one(
            {"_id": application_id, "status": "pending"},
            {"$set": {"status": "approving"}},
        )
        application = await applications.find_one({"_id": application_id})
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership application not found",
            )
        if application["status"] == "approved":
            return MemberApplicationResponse(
                status="success", data=serialize_application(application)
            )
        if application["status"] != "approving":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This application has already been reviewed",
            )

    membership_id = application.get("membership_id")
    if not membership_id:
        membership_id = generate_membership_id(datetime.now(timezone.utc))
        await applications.update_one(
            {"_id": application_id, "status": "approving"},
            {"$set": {"membership_id": membership_id}},
        )
        application = await applications.find_one({"_id": application_id})
        membership_id = application["membership_id"]

    approved_at = datetime.now(timezone.utc)
    member_document = {
        "_id": membership_id,
        "source_application_id": application_id,
        "name": f"{application['first_name']} {application['last_name']}",
        "email": application["email"],
        "phone": application["phone"],
        "address": application["address"],
        "preferred_position": application["preferred_position"],
        "date_of_birth": application.get("date_of_birth"),
        "image_url": application.get("image_url"),
        "image_public_id": application.get("image_public_id"),
        "consent": application["consent"],
        "consented_at": application["consented_at"],
        "joined_at": approved_at,
        "status": "active",
        "registrations": [
            {
                "year": approved_at.year,
                "registered_at": approved_at,
            }
        ],
    }
    try:
        await members.insert_one(member_document)
    except DuplicateKeyError:
        existing_member = await members.find_one({"_id": membership_id})
        if (
            existing_member is None
            or existing_member.get("source_application_id") != application_id
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to assign a unique membership ID",
            )

    await applications.update_one(
        {"_id": application_id, "status": "approving"},
        {
            "$set": {
                "status": "approved",
                "approved_at": datetime.now(timezone.utc),
            }
        },
    )
    approved_application = await applications.find_one({"_id": application_id})
    if approved_application is None or approved_application["status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The application status changed before approval completed",
        )
    return MemberApplicationResponse(
        status="success",
        data=serialize_application(approved_application),
    )


@admin_applications_router.post(
    "/{application_id}/reject",
    summary="Reject a membership application",
    response_model=MemberApplicationResponse,
    status_code=status.HTTP_200_OK,
)
async def reject_member_application(
    request: Request,
    application_id: str = Path(min_length=1, max_length=40),
) -> MemberApplicationResponse:
    verify_origin(request)
    collection = request.app.state.database["member_applications"]
    result = await collection.update_one(
        {"_id": application_id, "status": "pending"},
        {
            "$set": {
                "status": "rejected",
                "reviewed_at": datetime.now(timezone.utc),
            }
        },
    )
    application = await collection.find_one({"_id": application_id})
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership application not found",
        )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application has already been reviewed",
        )
    return MemberApplicationResponse(
        status="success", data=serialize_application(application)
    )


@admin_members_router.post(
    "/{membership_id}/registrations",
    summary="Record a member's registration for a year",
    response_model=MemberDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_member_for_year(
    request: Request,
    membership_id: str = Path(min_length=1, max_length=40),
    registration_data: MemberRegistrationCreate = ...,
) -> MemberDetailResponse:
    verify_origin(request)
    collection = request.app.state.database["members"]
    member = await collection.find_one(
        {"_id": membership_id},
        {"joined_at": 1},
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    joined_at = member["joined_at"]
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=timezone.utc)
    current_year = datetime.now(timezone.utc).year
    if not joined_at.year <= registration_data.year <= current_year:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Registration year must be between the member's join year and the current year",
        )

    registered_at = datetime.now(timezone.utc)
    update_result = await collection.update_one(
        {
            "_id": membership_id,
            "registrations.year": {"$ne": registration_data.year},
        },
        {
            "$push": {
                "registrations": {
                    "year": registration_data.year,
                    "registered_at": registered_at,
                }
            }
        },
    )
    if update_result.modified_count == 0:
        existing_member = await collection.find_one({"_id": membership_id}, {"_id": 1})
        if existing_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration for this year already exists",
        )

    updated_member = await collection.find_one(
        {"_id": membership_id},
        {"email": 0, "phone": 0, "address": 0, "image_public_id": 0},
    )
    if updated_member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    return MemberDetailResponse(
        status="success", data=serialize_member_detail(updated_member)
    )
