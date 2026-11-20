from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoundPhase = Literal["nominations", "finalizing", "voting", "closed"]


class OpenRoundRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    award_period: str = Field(min_length=3, max_length=40)


class NominationRequest(BaseModel):
    membership_id: str = Field(min_length=1, max_length=40)


class VoteRequest(BaseModel):
    candidate_membership_id: str = Field(min_length=1, max_length=40)


class NominatableMember(BaseModel):
    membership_id: str
    name: str
    image_url: str | None = None
    preferred_position: str | None = None


class NominatableMembersResponse(BaseModel):
    status: Literal["success"]
    data: list[NominatableMember]


class PlayerCandidate(BaseModel):
    membership_id: str
    name: str
    image_url: str | None = None
    nomination_count: int


class PublicPlayerRound(BaseModel):
    round_id: str
    award_period: str
    phase: Literal["nominations", "voting"]
    candidates: list[PlayerCandidate] = Field(default_factory=list)


class PublicPlayerRoundResponse(BaseModel):
    status: Literal["success"]
    data: PublicPlayerRound | None


class PlayerWinner(BaseModel):
    round_id: str
    award_period: str
    membership_id: str
    name: str
    image_url: str
    description: str
    published_at: datetime


class PlayerWinnerResponse(BaseModel):
    status: Literal["success"]
    data: PlayerWinner | None


class MemberPollStatus(BaseModel):
    round_id: str | None
    phase: RoundPhase | None
    has_nominated: bool
    has_voted: bool


class MemberPollStatusResponse(BaseModel):
    status: Literal["success"]
    data: MemberPollStatus


class NominationTally(BaseModel):
    membership_id: str
    name: str
    image_url: str | None = None
    nomination_count: int


class AdminCandidate(PlayerCandidate):
    vote_count: int


class AdminPlayerRound(BaseModel):
    round_id: str
    award_period: str
    phase: RoundPhase
    nomination_count: int
    nominations: list[NominationTally] = Field(default_factory=list)
    candidates: list[AdminCandidate] = Field(default_factory=list)
    winner: PlayerWinner | None = None


class AdminPlayerRoundResponse(BaseModel):
    status: Literal["success"]
    data: AdminPlayerRound | None


class PlayerActionResponse(BaseModel):
    status: Literal["success"]
    message: str
