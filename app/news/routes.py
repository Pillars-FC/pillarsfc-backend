import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

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
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.concurrency import run_in_threadpool

from app.admin.auth import require_admin, verify_origin
from app.members.routes import read_member_image, upload_member_image
from app.news.schemas import (
    NewsArticle,
    NewsArticleResponse,
    NewsCard,
    NewsCreate,
    NewsCreatedResponse,
    NewsImage,
    NewsListResponse,
)

logger = logging.getLogger(__name__)
news_router = APIRouter()
admin_news_router = APIRouter(dependencies=[Depends(require_admin)])
MAX_GALLERY_IMAGES = 10


def create_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return slug or f"news-{secrets.token_hex(4)}"


def serialize_news_card(document: dict[str, Any]) -> NewsCard:
    published_at = document["published_at"]
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return NewsCard(
        slug=document["slug"],
        title=document["title"],
        category=document["category"],
        summary=document["summary"],
        cover_image_url=document["cover_image_url"],
        published_at=published_at,
    )


def serialize_news_article(document: dict[str, Any]) -> NewsArticle:
    return NewsArticle(
        **serialize_news_card(document).model_dump(),
        content=document["content"],
        gallery=[
            NewsImage(url=image["url"], alt=image["alt"])
            for image in document.get("gallery", [])
        ],
    )


async def cleanup_uploaded_images(images: list[dict[str, Any]]) -> None:
    for image in images:
        try:
            await run_in_threadpool(cloudinary.uploader.destroy, image["public_id"])
        except CloudinaryError:
            logger.exception(
                "Could not remove an uncommitted news image from Cloudinary"
            )


@news_router.get(
    "",
    summary="List published news articles",
    response_model=NewsListResponse,
)
async def list_news(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> NewsListResponse:
    collection = request.app.state.database["news"]
    total = await collection.count_documents({})
    cursor = (
        collection.find(
            {},
            {
                "_id": 0,
                "slug": 1,
                "title": 1,
                "category": 1,
                "summary": 1,
                "cover_image_url": 1,
                "published_at": 1,
            },
        )
        .sort("published_at", -1)
        .skip(skip)
        .limit(limit)
    )
    articles = [serialize_news_card(document) async for document in cursor]
    return NewsListResponse(
        status="success",
        data=articles,
        total=total,
    )


@news_router.get(
    "/{slug}",
    summary="Get a published news article",
    response_model=NewsArticleResponse,
)
async def get_news_article(
    request: Request,
    slug: str = Path(min_length=1, max_length=200),
) -> NewsArticleResponse:
    document = await request.app.state.database["news"].find_one(
        {"slug": slug},
        {"_id": 0},
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News article not found",
        )
    return NewsArticleResponse(
        status="success",
        data=serialize_news_article(document),
    )


@admin_news_router.post(
    "",
    summary="Create and publish a news article",
    response_model=NewsCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_news_article(
    request: Request,
    title: str = Form(),
    category: str = Form(),
    summary: str = Form(),
    content: str = Form(),
    cover_image: UploadFile = File(),
    gallery: list[UploadFile] | None = File(default=None),
) -> NewsCreatedResponse:
    verify_origin(request)
    gallery_files = gallery or []
    if len(gallery_files) > MAX_GALLERY_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A news gallery can contain at most {MAX_GALLERY_IMAGES} images",
        )

    try:
        news_data = NewsCreate.model_validate(
            {
                "title": title,
                "category": category,
                "summary": summary,
                "content": content,
            }
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.errors(include_input=False, include_context=False),
        ) from error

    cover_content = await read_member_image(cover_image)
    if cover_content is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A cover image is required",
        )

    gallery_contents: list[bytes] = []
    for gallery_image in gallery_files:
        image_content = await read_member_image(gallery_image)
        if image_content is not None:
            gallery_contents.append(image_content)

    collection = request.app.state.database["news"]
    base_slug = create_slug(news_data.title)
    slug = base_slug
    if await collection.find_one({"slug": slug}, {"_id": 1}) is not None:
        slug = f"{base_slug}-{secrets.token_hex(3)}"

    upload_key = secrets.token_hex(4)
    uploaded_images: list[dict[str, Any]] = []
    try:
        cover_result = await upload_member_image(
            cover_content,
            f"{slug}-cover-{upload_key}",
            folder="pillars-fc/news",
        )
        uploaded_images.append(cover_result)
        gallery_results: list[dict[str, Any]] = []
        for index, image_content in enumerate(gallery_contents, start=1):
            image_result = await upload_member_image(
                image_content,
                f"{slug}-gallery-{index}-{upload_key}",
                folder="pillars-fc/news",
            )
            uploaded_images.append(image_result)
            gallery_results.append(image_result)
    except HTTPException:
        await cleanup_uploaded_images(uploaded_images)
        raise

    published_at = datetime.now(timezone.utc)
    document = {
        "slug": slug,
        "title": news_data.title,
        "category": news_data.category,
        "summary": news_data.summary,
        "content": news_data.content,
        "cover_image_url": cover_result["secure_url"],
        "cover_image_public_id": cover_result["public_id"],
        "gallery": [
            {
                "url": image["secure_url"],
                "public_id": image["public_id"],
                "alt": f"{news_data.title} gallery photo {index}",
            }
            for index, image in enumerate(gallery_results, start=1)
        ],
        "published_at": published_at,
    }
    try:
        await collection.insert_one(document)
    except DuplicateKeyError as error:
        await cleanup_uploaded_images(uploaded_images)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A news article with this URL already exists; please retry",
        ) from error
    except PyMongoError as error:
        await cleanup_uploaded_images(uploaded_images)
        logger.exception("Could not save a news article")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to save this news article right now",
        ) from error

    return NewsCreatedResponse(
        status="success",
        data=serialize_news_article(document),
    )
