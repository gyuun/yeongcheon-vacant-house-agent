from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen


VWORLD_ADDRESS_URL = "https://api.vworld.kr/req/address"
DEFAULT_CRS = "EPSG:4326"


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    matched_address: str | None = None


class GeocodingError(RuntimeError):
    """Raised when the geocoding API cannot return a usable coordinate."""


def load_env_file(env_path: Path | str = ".env") -> None:
    """Load simple KEY=VALUE lines from .env without overriding the process env."""

    path = Path(env_path)
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


class VWorldGeocoder:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        load_env_file()
        self.api_key = api_key or os.getenv("GEO_CODING_API_KEY")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise GeocodingError("GEO_CODING_API_KEY is not set")

    def geocode(self, address: str, address_type: str) -> GeocodeResult:
        query = urlencode(
            {
                "service": "address",
                "version": "2.0",
                "request": "GetCoord",
                "format": "json",
                "errorFormat": "json",
                "type": address_type,
                "address": address,
                "refine": "true",
                "simple": "false",
                "crs": DEFAULT_CRS,
                "key": self.api_key,
            }
        )
        try:
            with urlopen(f"{VWORLD_ADDRESS_URL}?{query}", timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, URLError, OSError) as exc:
            raise GeocodingError(f"geocoding request failed: {exc}") from exc

        return _parse_vworld_response(payload)


def _parse_vworld_response(payload: dict[str, Any]) -> GeocodeResult:
    response = payload.get("response") or {}
    status = str(response.get("status") or "").upper()
    if status != "OK":
        error = response.get("error") or {}
        message = error.get("text") or error.get("message") or status or "unknown geocoding failure"
        raise GeocodingError(str(message))

    result = response.get("result") or {}
    point = result.get("point") or {}
    try:
        longitude = float(point["x"])
        latitude = float(point["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("geocoding response did not include EPSG:4326 point.x/point.y") from exc

    matched = result.get("text") or result.get("structure", {}).get("level4L")
    return GeocodeResult(latitude=latitude, longitude=longitude, matched_address=matched)
