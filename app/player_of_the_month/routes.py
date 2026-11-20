import re
import secrets
from datetime import datetime, timezone
from typing import Any

import cloudinary.uploader
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
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from app.admin.auth import require_admin, verify_origin
from app.member_auth.auth import MemberPrincipal, require_member
from app.members.routes import read_member_image, upload_member_image
from app.middlewares.rate_limit import limiter
from app.player_of_the_month.schemas import (
    AdminCandidate,
    AdminPlayerRound,
    AdminPlayerRoundResponse,
    MemberPollStatus,
    MemberPollStatusResponse,
    NominatableMember,
    NominatableMembersResponse,
    NominationRequest,
    NominationTally,
    OpenRoundRequest,
    PlayerActionResponse,
    PlayerCandidate,
    PlayerWinner,
    PlayerWinnerResponse,
    PublicPlayerRound,
    PublicPlayerRoundResponse,
    VoteRequest,
)

player_of_the_month_router = APIRouter()
member_player_of_the_month_router = APIRouter()
admin_player_of_the_month_router = APIRouter(dependencies=[Depends(require_admin)])
MAX_CANDIDATES = 4


def serialize_winner(round_document: dict[str, Any]) -> PlayerWinner | None:
    winner = round_document.get("winner")
    if not isinstance(winner, dict):
        return None
    published_at = winner["published_at"]
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return PlayerWinner(
        round_id=round_document["_id"],
        award_period=round_document["award_period"],
        membership_id=winner["membership_id"],
        name=winner["name"],
        image_url=winner["image_url"],
        description=winner["description"],
        published_at=published_at,
    )


async def get_nomination_tallies(database: Any, round_id: str) -> list[dict[str, Any]]:
    cursor = await database["player_of_the_month_nominations"].aggregate(
        [
            {"$match": {"round_id": round_id}},
            {
                "$group": {
                    "_id": "$candidate_membership_id",
                    "name": {"$first": "$candidate_name"},
                    "image_url": {"$first": "$candidate_image_url"},
                    "nomination_count": {"$sum": 1},
                    "first_nominated_at": {"$min": "$created_at"},
                }
            },
            {
                "$sort": {
                    "nomination_count": -1,
                    "first_nominated_at": 1,
                    "_id": 1,
                }
            },
        ]
    )
    return [document async for document in cursor]


async def get_vote_counts(database: Any, round_id: str) -> dict[str, int]:
    cursor = await database["player_of_the_month_votes"].aggregate(
        [
            {"$match": {"round_id": round_id}},
            {
                "$group": {
                    "_id": "$candidate_membership_id",
                    "vote_count": {"$sum": 1},
                }
            },
        ]
    )
    return {document["_id"]: document["vote_count"] async for document in cursor}


async def serialize_admin_round(
    database: Any, round_document: dict[str, Any] | None
) -> AdminPlayerRound | None:
    if round_document is None:
        return None

    tallies = await get_nomination_tallies(database, round_document["_id"])
    vote_counts = await get_vote_counts(database, round_document["_id"])
    candidates = [
        AdminCandidate(
            membership_id=candidate["membership_id"],
            name=candidate["name"],
            image_url=candidate.get("image_url"),
            nomination_count=candidate["nomination_count"],
            vote_count=vote_counts.get(candidate["membership_id"], 0),
        )
        for candidate in round_document.get("candidates", [])
    ]
    return AdminPlayerRound(
        round_id=round_document["_id"],
        award_period=round_document["award_period"],
        phase=round_document["phase"],
        nomination_count=sum(item["nomination_count"] for item in tallies),
        nominations=[
            NominationTally(
                membership_id=item["_id"],
                name=item["name"],
                image_url=item.get("image_url"),
                nomination_count=item["nomination_count"],
            )
            for item in tallies
        ],
        candidates=candidates,
        winner=serialize_winner(round_document),
    )


@player_of_the_month_router.get(
    "",
    summary="Get the published Player of the Month",
    response_model=PlayerWinnerResponse,
)
async def get_player_of_the_month(
    request: Request,
) -> PlayerWinnerResponse:
    cursor = (
        request.app.state.database["player_of_the_month_rounds"]
        .find({"phase": "closed", "winner": {"$exists": True}})
        .sort("closed_at", -1)
        .limit(1)
    )
    documents = await cursor.to_list(length=1)
    round_document = documents[0] if documents else None
    return PlayerWinnerResponse(
        status="success",
        data=serialize_winner(round_document) if round_document else None,
    )


@player_of_the_month_router.get(
    "/poll",
    summary="Get the current nomination round or poll",
    response_model=PublicPlayerRoundResponse,
)
async def get_public_player_round(
    request: Request,
) -> PublicPlayerRoundResponse:
    round_document = await request.app.state.database[
        "player_of_the_month_rounds"
    ].find_one({"active": True})
    if round_document is None:
        return PublicPlayerRoundResponse(status="success", data=None)

    phase = round_document["phase"]
    if phase not in {"nominations", "voting"}:
        return PublicPlayerRoundResponse(status="success", data=None)
    candidates = [
        PlayerCandidate(
            membership_id=candidate["membership_id"],
            name=candidate["name"],
            image_url=candidate.get("image_url"),
            nomination_count=candidate["nomination_count"],
        )
        for candidate in round_document.get("candidates", [])
    ]
    return PublicPlayerRoundResponse(
        status="success",
        data=PublicPlayerRound(
            round_id=round_document["_id"],
            award_period=round_document["award_period"],
            phase=phase,
            candidates=candidates,
        ),
    )


@member_player_of_the_month_router.get(
    "/poll",
    summary="Get the current member's poll participation",
    response_model=MemberPollStatusResponse,
)
async def get_member_poll_status(
    request: Request,
    member: MemberPrincipal = Depends(require_member),
) -> MemberPollStatusResponse:
    round_document = await request.app.state.database[
        "player_of_the_month_rounds"
    ].find_one({"active": True})
    if round_document is None:
        return MemberPollStatusResponse(
            status="success",
            data=MemberPollStatus(
                round_id=None,
                phase=None,
                has_nominated=False,
                has_voted=False,
            ),
        )

    nominations = request.app.state.database["player_of_the_month_nominations"]
    votes = request.app.state.database["player_of_the_month_votes"]
    has_nominated = (
        await nominations.find_one(
            {
                "round_id": round_document["_id"],
                "membership_id": member.membership_id,
            },
            {"_id": 1},
        )
        is not None
    )
    has_voted = (
        await votes.find_one(
            {
                "round_id": round_document["_id"],
                "membership_id": member.membership_id,
            },
            {"_id": 1},
        )
        is not None
    )
    return MemberPollStatusResponse(
        status="success",
        data=MemberPollStatus(
            round_id=round_document["_id"],
            phase=round_document["phase"],
            has_nominated=has_nominated,
            has_voted=has_voted,
        ),
    )


@member_player_of_the_month_router.get(
    "/members",
    summary="Search active members who can be nominated",
    response_model=NominatableMembersResponse,
)
async def list_nominatable_members(
    request: Request,
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    member: MemberPrincipal = Depends(require_member),
) -> NominatableMembersResponse:
    del member
    query: dict[str, Any] = {"status": "active"}
    if search and search.strip():
        term = re.escape(search.strip())
        query["name"] = {"$regex": term, "$options": "i"}
    cursor = (
        request.app.state.database["members"]
        .find(query, {"_id": 1, "name": 1, "image_url": 1, "preferred_position": 1})
        .sort("name", 1)
        .limit(limit)
    )
    members = [
        NominatableMember(
            membership_id=document["_id"],
            name=document["name"],
            image_url=document.get("image_url"),
            preferred_position=document.get("preferred_position"),
        )
        async for document in cursor
    ]
    return NominatableMembersResponse(status="success", data=members)


@member_player_of_the_month_router.post(
    "/nominations",
    summary="Nominate one active member for the current round",
    response_model=PlayerActionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def submit_player_nomination(
    request: Request,
    nomination: NominationRequest,
    member: MemberPrincipal = Depends(require_member),
) -> PlayerActionResponse:
    verify_origin(request)
    database = request.app.state.database
    round_document = await database["player_of_the_month_rounds"].find_one(
        {"active": True, "phase": "nominations"}
    )
    if round_document is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player nominations are not open",
        )
    candidate = await database["members"].find_one(
        {"_id": nomination.membership_id, "status": "active"},
        {"_id": 1, "name": 1, "image_url": 1},
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected player is not an active club member",
        )

    document = {
        "round_id": round_document["_id"],
        "membership_id": member.membership_id,
        "candidate_membership_id": candidate["_id"],
        "candidate_name": candidate["name"],
        "candidate_image_url": candidate.get("image_url"),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        result = await database["player_of_the_month_nominations"].insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already nominated a player for this round",
        ) from error

    current_round = await database["player_of_the_month_rounds"].find_one(
        {"_id": round_document["_id"], "active": True, "phase": "nominations"},
        {"_id": 1},
    )
    if current_round is None:
        await database["player_of_the_month_nominations"].delete_one(
            {"_id": result.inserted_id}
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The nomination period has closed",
        )
    return PlayerActionResponse(
        status="success",
        message="Your nomination has been recorded.",
    )


@member_player_of_the_month_router.post(
    "/votes",
    summary="Vote once for a Player of the Month candidate",
    response_model=PlayerActionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def submit_player_vote(
    request: Request,
    vote: VoteRequest,
    member: MemberPrincipal = Depends(require_member),
) -> PlayerActionResponse:
    verify_origin(request)
    database = request.app.state.database
    round_document = await database["player_of_the_month_rounds"].find_one(
        {"active": True, "phase": "voting"}
    )
    if round_document is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player voting is not open",
        )
    candidate_ids = {
        candidate["membership_id"] for candidate in round_document.get("candidates", [])
    }
    if vote.candidate_membership_id not in candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected player is not in this poll",
        )

    document = {
        "round_id": round_document["_id"],
        "membership_id": member.membership_id,
        "candidate_membership_id": vote.candidate_membership_id,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        result = await database["player_of_the_month_votes"].insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already voted in this poll",
        ) from error

    current_round = await database["player_of_the_month_rounds"].find_one(
        {"_id": round_document["_id"], "active": True, "phase": "voting"},
        {"_id": 1},
    )
    if current_round is None:
        await database["player_of_the_month_votes"].delete_one(
            {"_id": result.inserted_id}
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The poll has closed",
        )
    return PlayerActionResponse(
        status="success",
        message="Your vote has been recorded.",
    )


@admin_player_of_the_month_router.get(
    "",
    summary="Get the active or most recently closed Player of the Month round",
    response_model=AdminPlayerRoundResponse,
)
async def get_admin_player_round(
    request: Request,
) -> AdminPlayerRoundResponse:
    database = request.app.state.database
    round_document = await database["player_of_the_month_rounds"].find_one(
        {"active": True}
    )
    if round_document is None:
        cursor = (
            database["player_of_the_month_rounds"]
            .find({"phase": "closed"})
            .sort("closed_at", -1)
            .limit(1)
        )
        documents = await cursor.to_list(length=1)
        round_document = documents[0] if documents else None
    return AdminPlayerRoundResponse(
        status="success",
        data=await serialize_admin_round(database, round_document),
    )


@admin_player_of_the_month_router.post(
    "",
    summary="Open a member nomination round",
    response_model=AdminPlayerRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_player_round(
    request: Request,
    round_data: OpenRoundRequest,
) -> AdminPlayerRoundResponse:
    verify_origin(request)
    database = request.app.state.database
    now = datetime.now(timezone.utc)
    document = {
        "_id": f"{now.strftime('%Y%m')}-{secrets.token_hex(4).upper()}",
        "award_period": round_data.award_period,
        "phase": "nominations",
        "active": True,
        "created_at": now,
    }
    try:
        await database["player_of_the_month_rounds"].insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another Player of the Month round is already active",
        ) from error
    return AdminPlayerRoundResponse(
        status="success",
        data=await serialize_admin_round(database, document),
    )


@admin_player_of_the_month_router.post(
    "/{round_id}/advance",
    summary="Close nominations and start voting with the top four nominees",
    response_model=AdminPlayerRoundResponse,
)
async def advance_player_round(
    request: Request,
    round_id: str = Path(min_length=1, max_length=40),
) -> AdminPlayerRoundResponse:
    verify_origin(request)
    database = request.app.state.database
    rounds = database["player_of_the_month_rounds"]
    round_document = await rounds.find_one({"_id": round_id, "active": True})
    if round_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active Player of the Month round not found",
        )
    if round_document["phase"] in {"voting", "closed"}:
        return AdminPlayerRoundResponse(
            status="success",
            data=await serialize_admin_round(database, round_document),
        )
    if round_document["phase"] not in {"nominations", "finalizing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The nomination round cannot be advanced right now",
        )

    if round_document["phase"] == "nominations":
        reserved = await rounds.update_one(
            {"_id": round_id, "active": True, "phase": "nominations"},
            {"$set": {"phase": "finalizing"}},
        )
        if reserved.modified_count != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The nomination round has already changed",
            )

    tallies = await get_nomination_tallies(database, round_id)
    if len(tallies) < MAX_CANDIDATES:
        await rounds.update_one(
            {"_id": round_id, "phase": "finalizing"},
            {"$set": {"phase": "nominations"}},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least four different members must be nominated before voting can begin",
        )

    candidates = [
        {
            "membership_id": item["_id"],
            "name": item["name"],
            "image_url": item.get("image_url"),
            "nomination_count": item["nomination_count"],
            "first_nominated_at": item["first_nominated_at"],
        }
        for item in tallies[:MAX_CANDIDATES]
    ]
    result = await rounds.update_one(
        {"_id": round_id, "active": True, "phase": "finalizing"},
        {
            "$set": {
                "phase": "voting",
                "candidates": candidates,
                "voting_started_at": datetime.now(timezone.utc),
            }
        },
    )
    if result.modified_count != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The nomination round changed before voting could begin",
        )
    updated_round = await rounds.find_one({"_id": round_id})
    return AdminPlayerRoundResponse(
        status="success",
        data=await serialize_admin_round(database, updated_round),
    )


@admin_player_of_the_month_router.post(
    "/{round_id}/close",
    summary="Close voting and publish the Player of the Month",
    response_model=AdminPlayerRoundResponse,
)
async def close_player_round(
    request: Request,
    round_id: str = Path(min_length=1, max_length=40),
    description: str = Form(min_length=10, max_length=2000),
    image: UploadFile = File(),
) -> AdminPlayerRoundResponse:
    verify_origin(request)
    database = request.app.state.database
    rounds = database["player_of_the_month_rounds"]
    round_document = await rounds.find_one({"_id": round_id, "active": True})
    if round_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active Player of the Month round not found",
        )
    if round_document["phase"] == "closed":
        return AdminPlayerRoundResponse(
            status="success",
            data=await serialize_admin_round(database, round_document),
        )
    if round_document["phase"] != "voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voting must be open before the round can be closed",
        )
    if len(description.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The winner description must be at least 10 characters",
        )

    vote_counts = await get_vote_counts(database, round_id)
    candidates = round_document.get("candidates", [])
    if not candidates or not vote_counts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one vote is required before publishing a winner",
        )
    winner_candidate = min(
        candidates,
        key=lambda candidate: (
            -vote_counts.get(candidate["membership_id"], 0),
            -candidate["nomination_count"],
            candidate["first_nominated_at"],
            candidate["membership_id"],
        ),
    )
    if vote_counts.get(winner_candidate["membership_id"], 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one candidate must receive a vote before publishing a winner",
        )

    image_content = await read_member_image(image)
    if image_content is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A winner image is required to publish the Player of the Month",
        )
    image_result = await upload_member_image(
        image_content,
        f"{round_id}-winner",
        folder="pillars-fc/player-of-the-month",
    )
    published_at = datetime.now(timezone.utc)
    winner = {
        "membership_id": winner_candidate["membership_id"],
        "name": winner_candidate["name"],
        "image_url": image_result["secure_url"],
        "image_public_id": image_result["public_id"],
        "description": description.strip(),
        "vote_count": vote_counts[winner_candidate["membership_id"]],
        "published_at": published_at,
    }
    result = await rounds.update_one(
        {"_id": round_id, "active": True, "phase": "voting"},
        {
            "$set": {
                "phase": "closed",
                "active": False,
                "winner": winner,
                "closed_at": published_at,
            }
        },
    )
    if result.modified_count != 1:
        await run_in_threadpool(cloudinary.uploader.destroy, image_result["public_id"])
        latest_round = await rounds.find_one({"_id": round_id})
        if latest_round is not None and latest_round["phase"] == "closed":
            return AdminPlayerRoundResponse(
                status="success",
                data=await serialize_admin_round(database, latest_round),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The round changed before the winner could be published",
        )

    closed_round = await rounds.find_one({"_id": round_id})
    return AdminPlayerRoundResponse(
        status="success",
        data=await serialize_admin_round(database, closed_round),
    )
