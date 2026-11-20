from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

health_router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


@health_router.get(
    "/",
    summary="Health Check",
    description="Check the health of the API.",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
