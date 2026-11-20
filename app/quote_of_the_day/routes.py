import json
import random
from pathlib import Path

from fastapi import APIRouter, status

from app.quote_of_the_day.schemas import Quote, QuoteResponse

QUOTES_FILE = Path(__file__).with_name("football_quotes.json")


def load_quotes() -> list[Quote]:
    with QUOTES_FILE.open("r", encoding="utf-8") as file:
        quotes = json.load(file)

    if not isinstance(quotes, list) or not quotes:
        raise RuntimeError("The football quotes JSON file is empty or invalid")

    return [Quote.model_validate(quote) for quote in quotes]


quote_router = APIRouter()


@quote_router.get(
    "",
    summary="Get a random football quote",
    response_model=QuoteResponse,
    status_code=status.HTTP_200_OK,
)
async def get_random_quote() -> QuoteResponse:
    quotes = load_quotes()
    return QuoteResponse(status="success", data=random.choice(quotes))
