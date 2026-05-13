from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from src.agents.patrol_image import build_patrol_image_graph
from src.agents.priority_recommendation import (
    build_priority_recommendation_graph,
)
from src.models import PatrolImageInput
from src.services.local_csv_data import LocalCsvGeoDataRepository


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def run_patrol_demo() -> dict[str, Any]:
    graph = build_patrol_image_graph()
    result = graph.invoke(
        {
            "request": PatrolImageInput(
                house_id="YC-001",
                spot_id="front-gate",
                baseline_image_base64="baseline-image-placeholder",
                captured_image_base64="captured-image-placeholder-with-visible-difference",
            )
        }
    )
    return result


def run_priority_demo(
    house_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 2.0,
    administrative_area: str | None = None,
) -> dict[str, Any]:
    graph = build_priority_recommendation_graph()
    payload: dict[str, Any] = {"house_id": house_id}
    if latitude is not None and longitude is not None:
        payload.update({"latitude": latitude, "longitude": longitude, "radius_km": radius_km})
    if administrative_area is not None:
        payload["administrative_area"] = administrative_area
    return graph.invoke(payload)


def run_nearby_data(
    latitude: float,
    longitude: float,
    radius_km: float,
    administrative_area: str | None = None,
) -> dict[str, Any]:
    repository = LocalCsvGeoDataRepository()
    bundle = repository.find_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        administrative_area=administrative_area,
    )
    return {
        "center": bundle.center,
        "radius_km": bundle.radius_km,
        "administrative_area": bundle.administrative_area,
        "layers": bundle.layers,
        "summary": {
            "csv_layers": bundle.total_layers,
            "layers_with_matches": len(bundle.layers),
            "nearby_objects": sum(len(layer.objects) for layer in bundle.layers),
            "coordinate_layers_with_matches": sum(
                1 for layer in bundle.layers if layer.kind.value == "coordinate"
            ),
            "administrative_layers_with_matches": sum(
                1 for layer in bundle.layers if layer.kind.value == "administrative_area"
            ),
            "coordinate_records": bundle.coordinate_records,
            "unresolved_records": bundle.unresolved_records,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Yeongcheon vacant house agent demos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("patrol", help="Run patrol image assessment demo")

    priority_parser = subparsers.add_parser("priority", help="Run priority recommendation demo")
    priority_parser.add_argument("--house-id", default="YC-001", help="Vacant house identifier")
    priority_parser.add_argument("--lat", type=float, help="Latitude for nearby CSV context")
    priority_parser.add_argument("--lon", type=float, help="Longitude for nearby CSV context")
    priority_parser.add_argument("--radius-km", type=float, default=2.0, help="Nearby context radius")
    priority_parser.add_argument("--admin-area", help="Administrative area resolved from the coordinate")

    nearby_parser = subparsers.add_parser("nearby", help="Find local CSV objects near a coordinate")
    nearby_parser.add_argument("--lat", type=float, required=True, help="Latitude in decimal degrees")
    nearby_parser.add_argument("--lon", type=float, required=True, help="Longitude in decimal degrees")
    nearby_parser.add_argument("--radius-km", type=float, default=2.0, help="Search radius in kilometers")
    nearby_parser.add_argument("--admin-area", help="Administrative area resolved from the coordinate")
    args = parser.parse_args()

    if args.command == "patrol":
        result = run_patrol_demo()
    elif args.command == "priority":
        result = run_priority_demo(args.house_id, args.lat, args.lon, args.radius_km, args.admin_area)
    else:
        result = run_nearby_data(args.lat, args.lon, args.radius_km, args.admin_area)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
