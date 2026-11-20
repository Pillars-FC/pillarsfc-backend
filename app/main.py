from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.admin.routes import admin_router
from app.contact.routes import contact_router
from app.db.connection import init_db
from app.event_subscriptions.routes import event_subscriptions_router
from app.executives.routes import executives_router
from app.health import health_router
from app.member_auth.routes import member_auth_router
from app.members.routes import (
    admin_applications_router,
    admin_members_router,
    member_applications_router,
    members_router,
)
from app.middlewares import register_middleware
from app.news.routes import admin_news_router, news_router
from app.player_of_the_month.routes import (
    admin_player_of_the_month_router,
    member_player_of_the_month_router,
    player_of_the_month_router,
)
from app.quiz.routes import quiz_router
from app.quote_of_the_day.routes import quote_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = None
    try:
        client = await init_db(app)
        yield
    finally:
        if client is not None:
            await client.close()


def register_routers(app: FastAPI) -> None:
    base_prefix = "/api/v1"

    app.include_router(health_router, prefix=f"{base_prefix}/health", tags=["Health"])
    app.include_router(
        quote_router,
        prefix=f"{base_prefix}/quote-of-the-day",
        tags=["Quote of the Day"],
    )
    app.include_router(quiz_router, prefix=f"{base_prefix}/quiz", tags=["Quiz"])
    app.include_router(
        contact_router, prefix=f"{base_prefix}/contact", tags=["Contact"]
    )
    app.include_router(
        event_subscriptions_router,
        prefix=f"{base_prefix}/event-subscriptions",
        tags=["Event Subscriptions"],
    )
    app.include_router(
        executives_router,
        prefix=f"{base_prefix}/executives",
        tags=["Executives"],
    )
    app.include_router(
        members_router, prefix=f"{base_prefix}/members", tags=["Members"]
    )
    app.include_router(
        member_applications_router,
        prefix=f"{base_prefix}/members/applications",
        tags=["Member Applications"],
    )
    app.include_router(admin_router, prefix=f"{base_prefix}/admin", tags=["Admin"])
    app.include_router(
        admin_members_router,
        prefix=f"{base_prefix}/admin/members",
        tags=["Admin"],
    )
    app.include_router(
        admin_applications_router,
        prefix=f"{base_prefix}/admin/applications",
        tags=["Admin"],
    )
    app.include_router(
        member_auth_router,
        prefix=f"{base_prefix}/member-auth",
        tags=["Member Authentication"],
    )
    app.include_router(
        player_of_the_month_router,
        prefix=f"{base_prefix}/player-of-the-month",
        tags=["Player of the Month"],
    )
    app.include_router(
        member_player_of_the_month_router,
        prefix=f"{base_prefix}/player-of-the-month/member",
        tags=["Player of the Month"],
    )
    app.include_router(
        admin_player_of_the_month_router,
        prefix=f"{base_prefix}/admin/player-of-the-month",
        tags=["Admin"],
    )
    app.include_router(
        news_router,
        prefix=f"{base_prefix}/news",
        tags=["News"],
    )
    app.include_router(
        admin_news_router,
        prefix=f"{base_prefix}/admin/news",
        tags=["Admin"],
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Pillars FC API", version="0.1.0", lifespan=lifespan)
    register_middleware(app)
    register_routers(app)
    return app


app = create_app()
