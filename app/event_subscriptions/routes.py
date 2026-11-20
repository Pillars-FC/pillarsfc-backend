from datetime import datetime, timezone

from fastapi import APIRouter, Request, status
from pymongo.errors import DuplicateKeyError

from app.event_subscriptions.schemas import (
    EventSubscriptionRequest,
    EventSubscriptionResponse,
)
from app.middlewares.rate_limit import limiter

event_subscriptions_router = APIRouter()


@event_subscriptions_router.post(
    "",
    summary="Subscribe to club event updates",
    response_model=EventSubscriptionResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def subscribe_to_club_events(
    request: Request,
    subscription: EventSubscriptionRequest,
) -> EventSubscriptionResponse:
    email = str(subscription.email).casefold()
    try:
        result = await request.app.state.database["event_subscriptions"].update_one(
            {"email": email},
            {
                "$setOnInsert": {
                    "email": email,
                    "subscribed_at": datetime.now(timezone.utc),
                    "status": "active",
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        message = "You are already subscribed to club event updates."
    else:
        message = (
            "You are already subscribed to club event updates."
            if result.upserted_id is None
            else "Thanks for subscribing to club event updates."
        )
    return EventSubscriptionResponse(status="success", message=message)
