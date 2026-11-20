from fastapi import FastAPI
from pymongo import AsyncMongoClient

from app.core.config import get_settings

settings = get_settings()


async def init_db(app: FastAPI) -> AsyncMongoClient:
    """
    Initialize the database connection and store it in the app state.
    """
    client = AsyncMongoClient(settings.MONGO_URI)
    try:
        await client.admin.command("ping")
        app.state.mongo_client = client
        app.state.database = client[settings.MONGODB_DATABASE]
        await app.state.database["event_subscriptions"].create_index(
            "email",
            unique=True,
            name="event_subscription_email_unique",
        )
        await app.state.database["member_accounts"].create_index(
            "email_normalized",
            unique=True,
            name="member_account_email_unique",
        )
        await app.state.database["member_accounts"].create_index(
            "membership_id",
            unique=True,
            name="member_account_membership_unique",
        )
        await app.state.database["player_of_the_month_rounds"].create_index(
            "active",
            unique=True,
            partialFilterExpression={"active": True},
            name="player_month_single_active_round",
        )
        await app.state.database["player_of_the_month_nominations"].create_index(
            [("round_id", 1), ("membership_id", 1)],
            unique=True,
            name="player_month_one_nomination_per_member",
        )
        await app.state.database["player_of_the_month_nominations"].create_index(
            [("round_id", 1), ("candidate_membership_id", 1)],
            name="player_month_nomination_counts",
        )
        await app.state.database["player_of_the_month_votes"].create_index(
            [("round_id", 1), ("membership_id", 1)],
            unique=True,
            name="player_month_one_vote_per_member",
        )
        await app.state.database["player_of_the_month_votes"].create_index(
            [("round_id", 1), ("candidate_membership_id", 1)],
            name="player_month_vote_counts",
        )
        await app.state.database["news"].create_index(
            "slug",
            unique=True,
            name="news_slug_unique",
        )
        await app.state.database["news"].create_index(
            [("published_at", -1)],
            name="news_published_at_desc",
        )
    except Exception:
        await client.close()
        raise
    return client
