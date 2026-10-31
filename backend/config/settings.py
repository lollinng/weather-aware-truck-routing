"""Django settings.

The app is stateless (no models): everything is computed per request from third-party
routing/weather APIs, with an in-process cache in front of them. Configuration is
environment-driven so the same image runs locally and in production.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-insecure-key-do-not-use-in-production" if DEBUG else ""
)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render injects the public hostname; accept it automatically.
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# No models -> no database. Django is happy with an empty mapping.
DATABASES: dict = {}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = False

# --- Static files / single-page app -------------------------------------------------------
# The React build (frontend/dist) is served from the site root by WhiteNoise, so the whole app
# ships as one service. Hashed files under /assets/ are cached forever.
STATIC_URL = "/static/"
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist"))
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_INDEX_FILE = True


def _immutable_file_test(path: str, url: str) -> bool:
    return url.startswith("/assets/")


WHITENOISE_IMMUTABLE_FILE_TEST = _immutable_file_test

# --- Security ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# --- CORS ----------------------------------------------------------------------------------
# The API is public and read-only (no cookies), so cross-origin access is safe. The frontend
# can be served from the same origin (Docker image) or a static host such as GitHub Pages.
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "https://lollinng.github.io,https://prathameshjadhav.in,http://prathameshjadhav.in",
)
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOW_CREDENTIALS = False

# --- Cache ---------------------------------------------------------------------------------
# Weather, routes and geocoding results are cached in-process. Gunicorn runs a single
# multi-threaded worker so every request shares the same cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "planner",
        "OPTIONS": {"MAX_ENTRIES": 50_000},
    }
}

# --- REST framework ------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_RATES": {
        "plan": os.environ.get("PLAN_RATE_LIMIT", "12/min"),
        "geocode": os.environ.get("GEOCODE_RATE_LIMIT", "90/min"),
    },
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "1")),
}

# --- Third-party services --------------------------------------------------------------------
DEFAULT_USER_AGENT = (
    "weather-truck-routing/1.0 (+https://github.com/lollinng/weather-aware-truck-routing)"
)
PLANNER = {
    "VALHALLA_URL": os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de"),
    "VALHALLA_API_KEY": os.environ.get("VALHALLA_API_KEY", ""),
    # The public server rejects requests spanning > 1,500 km; 0 disables the check.
    "VALHALLA_MAX_KM": float(os.environ.get("VALHALLA_MAX_KM", "1500")),
    "OSRM_URL": os.environ.get("OSRM_URL", "https://router.project-osrm.org"),
    "OPEN_METEO_URL": os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com"),
    "OPEN_METEO_API_KEY": os.environ.get("OPEN_METEO_API_KEY", ""),
    # Forecast locations per plan (checkpoints + heatmap). The free tier allows ~600/minute;
    # raise this with a commercial key.
    "WEATHER_MAX_LOCATIONS": int(os.environ.get("WEATHER_MAX_LOCATIONS", "560")),
    "PHOTON_URL": os.environ.get("PHOTON_URL", "https://photon.komoot.io"),
    "USER_AGENT": os.environ.get("UPSTREAM_USER_AGENT", DEFAULT_USER_AGENT),
    "HTTP_TIMEOUT_S": float(os.environ.get("UPSTREAM_TIMEOUT_S", "25")),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
