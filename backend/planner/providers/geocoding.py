"""Place search via Photon (OpenStreetMap data, no API key)."""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from .http import UpstreamError, UpstreamRateLimited, session, timeout

CACHE_TTL_S = 24 * 3600


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    lat: float
    lon: float


def _label(props: dict) -> str:
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    parts = [props.get("name") or street, props.get("city"), props.get("state")]
    if props.get("countrycode") != "US":
        parts.append(props.get("country"))
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def search_places(query: str, limit: int = 6) -> list[Place]:
    query = " ".join(query.split())
    key = f"geocode:v1:{query.lower()}:{limit}"
    if (hit := cache.get(key)) is not None:
        return hit
    try:
        response = session().get(
            f"{settings.PLANNER['PHOTON_URL']}/api/",
            params={"q": query, "limit": limit, "lang": "en"},
            timeout=timeout(),
        )
    except requests.RequestException as exc:
        raise UpstreamError("geocoder", "place search is unavailable") from exc
    if response.status_code == 429:
        raise UpstreamRateLimited("geocoder", "too many searches, slow down")
    if not response.ok:
        raise UpstreamError("geocoder", f"place search failed (HTTP {response.status_code})")

    places: list[Place] = []
    for feature in response.json().get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        label = _label(feature.get("properties", {}))
        if label and all(p.label != label for p in places):
            places.append(Place(label=label, lat=round(lat, 6), lon=round(lon, 6)))
    cache.set(key, places, CACHE_TTL_S)
    return places
