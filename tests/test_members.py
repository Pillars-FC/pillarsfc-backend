from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.members import routes as member_routes


class MemberCursor:
    def sort(self, *_args: object) -> MemberCursor:
        return self

    def skip(self, _skip: int) -> MemberCursor:
        return self

    def limit(self, _limit: int) -> MemberCursor:
        return self

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        yield {
            "_id": "PFC-2600000001",
            "name": "Alex Defender",
            "joined_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "status": "active",
            "preferred_position": "Defender",
        }


@pytest.mark.anyio
async def test_list_members_filters_by_preferred_position() -> None:
    collection = SimpleNamespace(
        count_documents=AsyncMock(return_value=1),
        find=Mock(return_value=MemberCursor()),
    )
    app = FastAPI()
    app.state.database = {"members": collection}
    app.include_router(member_routes.members_router, prefix="/api/v1/members")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/members", params={"preferred_position": "Defender"}
        )

    expected_query = {
        "status": {"$in": ["active", "inactive"]},
        "preferred_position": "Defender",
    }
    assert response.status_code == 200
    assert response.json()["total"] == 1
    collection.count_documents.assert_awaited_once_with(expected_query)
    collection.find.assert_called_once()
    assert collection.find.call_args.args[0] == expected_query


@pytest.mark.anyio
async def test_list_members_rejects_unknown_position() -> None:
    app = FastAPI()
    app.include_router(member_routes.members_router, prefix="/api/v1/members")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/members", params={"preferred_position": "Sweeper"}
        )

    assert response.status_code == 422
