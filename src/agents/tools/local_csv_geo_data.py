from __future__ import annotations

from dataclasses import asdict
from typing import Any

from langchain_core.tools import tool

from src.models import NearbyGeoDataBundle
from src.services.local_csv_data import LocalCsvGeoDataRepository


def get_nearby_public_data_bundle(
    latitude: float,
    longitude: float,
    radius_km: float = 0.5,
    administrative_area: str | None = None,
    max_records_per_layer: int | None = 20,
    max_total_records: int | None = 100,
) -> NearbyGeoDataBundle:
    """Return nearby public CSV context as typed models for graph nodes."""

    return LocalCsvGeoDataRepository().find_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        administrative_area=administrative_area,
        max_records_per_layer=max_records_per_layer,
        max_total_records=max_total_records,
    )


@tool
def find_nearby_public_data(
    latitude: float,
    longitude: float,
    radius_km: float = 0.5,
    administrative_area: str | None = None,
    max_records_per_layer: int | None = 20,
    max_total_records: int | None = 100,
) -> dict[str, Any]:
    """Find Yeongcheon public CSV rows relevant to a coordinate query.

    Coordinate-backed CSV layers are filtered by distance and sorted by nearest
    first. Administrative-area layers are included when `administrative_area`
    is supplied. Address-only unresolved layers are skipped until geocoding is
    available. The result includes per-layer match counts and global limits.
    """

    bundle = get_nearby_public_data_bundle(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        administrative_area=administrative_area,
        max_records_per_layer=max_records_per_layer,
        max_total_records=max_total_records,
    )
    return asdict(bundle)


REDEVELOPMENT_RECOMMENDATION_TOOLS = [find_nearby_public_data]
