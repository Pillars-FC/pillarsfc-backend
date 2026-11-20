from fastapi import FastAPI

from app.middlewares.cors import set_up_cors
from app.middlewares.errors import set_up_error_handlers
from app.middlewares.logging import set_up_logging
from app.middlewares.rate_limit import set_up_limiter


def register_middleware(app: FastAPI):
    set_up_cors(app)
    set_up_error_handlers(app)
    set_up_limiter(app)
    set_up_logging(app)
