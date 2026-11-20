from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from resend.exceptions import ResendError

from app.contact import routes as contact_routes
from app.middlewares import cors as cors_middleware
from app.middlewares import register_middleware
from app.middlewares.rate_limit import limiter


@pytest.fixture
def mail_settings() -> SimpleNamespace:
    return SimpleNamespace(
        RESEND_API_KEY="re_test_key",
        MAIL_FROM_RESEND="Pillars FC <contact@example.com>",
        MAIL_USERNAME="club@example.com",
        FRONTEND_ORIGIN="http://localhost:3000",
    )


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch, mail_settings: SimpleNamespace
) -> Generator[FastAPI, None, None]:
    monkeypatch.setattr(contact_routes, "get_settings", lambda: mail_settings)
    monkeypatch.setattr(
        cors_middleware,
        "get_settings",
        lambda: SimpleNamespace(FRONTEND_ORIGIN=mail_settings.FRONTEND_ORIGIN),
    )
    monkeypatch.setattr(contact_routes.resend, "api_key", "original-api-key")

    test_app = FastAPI()
    register_middleware(test_app)
    test_app.include_router(contact_routes.contact_router, prefix="/api/v1/contact")

    limiter.reset()
    yield test_app
    limiter.reset()


async def post_contact(app: FastAPI, payload: dict[str, object]) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post("/api/v1/contact", json=payload)


@pytest.mark.anyio
async def test_contact_message_sends_email_with_escaped_html(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    send_email = Mock(return_value={"id": "email-id"})
    monkeypatch.setattr(contact_routes.resend.Emails, "send", send_email)

    response = await post_contact(
        app,
        {
            "name": "<Coach>",
            "email": "coach@example.com",
            "phone": None,
            "message": "<script>alert(1)</script>",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Your message has been sent successfully.",
    }
    send_email.assert_called_once()
    params = send_email.call_args.args[0]
    assert params["from"] == "Pillars FC <contact@example.com>"
    assert params["to"] == ["club@example.com"]
    assert params["reply_to"] == "coach@example.com"
    assert "&lt;Coach&gt;" in params["html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in params["html"]
    assert "Phone: Not provided" in params["text"]


@pytest.mark.parametrize(
    "missing_setting",
    ["RESEND_API_KEY", "MAIL_FROM_RESEND", "MAIL_USERNAME"],
)
@pytest.mark.anyio
async def test_contact_message_requires_email_configuration(
    app: FastAPI,
    mail_settings: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    missing_setting: str,
) -> None:
    setattr(mail_settings, missing_setting, None)
    send_email = Mock()
    monkeypatch.setattr(contact_routes.resend.Emails, "send", send_email)

    response = await post_contact(
        app,
        {
            "name": "Club Support",
            "email": "support@example.com",
            "message": "Please contact me.",
        },
    )

    assert response.status_code == 503
    assert response.json()["message"] == "Contact email service is not configured"
    send_email.assert_not_called()


@pytest.mark.anyio
async def test_contact_message_maps_resend_failure_to_bad_gateway(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    send_email = Mock(
        side_effect=ResendError(
            500,
            "api_error",
            "Resend is unavailable",
            "Try again later",
        )
    )
    monkeypatch.setattr(contact_routes.resend.Emails, "send", send_email)

    response = await post_contact(
        app,
        {
            "name": "Club Support",
            "email": "support@example.com",
            "message": "Please contact me.",
        },
    )

    assert response.status_code == 502
    assert response.json()["message"] == "Unable to send your message right now"
    send_email.assert_called_once()
