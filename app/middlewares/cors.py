from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings


def set_up_cors(app: FastAPI) -> None:
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
        expose_headers=["Set-Cookie"],
    )
