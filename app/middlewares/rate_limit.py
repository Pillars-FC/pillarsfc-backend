from fastapi import APIRouter, FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def set_up_limiter(app: FastAPI):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)


def apply_rate_limit_to_router(router: APIRouter, rate: str):
    for route in router.routes:
        if hasattr(route.endpoint, "__call__"):
            limited_endpoint = limiter.limit(rate)(route.endpoint)
            route.endpoint = limited_endpoint
            if hasattr(route, "dependant"):
                route.dependant.call = limited_endpoint
