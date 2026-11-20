import json
from pathlib import Path

from fastapi import APIRouter, status

from app.executives.schemas import Executive, ExecutivesResponse

EXECUTIVES_FILE = Path(__file__).with_name("executives.json")
executives_router = APIRouter()


def load_executives() -> list[Executive]:
    with EXECUTIVES_FILE.open("r", encoding="utf-8") as file:
        executives = json.load(file)

    if not isinstance(executives, list):
        raise RuntimeError("The executives JSON file must contain a list")

    return [Executive.model_validate(executive) for executive in executives]


@executives_router.get(
    "",
    summary="Get club executives",
    response_model=ExecutivesResponse,
    status_code=status.HTTP_200_OK,
)
async def get_executives() -> ExecutivesResponse:
    return ExecutivesResponse(status="success", data=load_executives())
