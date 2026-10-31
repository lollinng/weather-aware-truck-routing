"""Test settings: production settings plus a throwaway secret and relaxed throttles."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret")

from .settings import *  # noqa: F403
from .settings import REST_FRAMEWORK

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"plan": "1000/min", "geocode": "1000/min"},
}
