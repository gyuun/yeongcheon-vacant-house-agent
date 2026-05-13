from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from src.agents.patrol_image import build_patrol_image_graph
from src.agents.redevelopment_recommendation import (
    build_redevelopment_recommendation_graph,
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
    return result["assessment"]


def run_redevelopment_demo(
    house_id: str | None = None,
    address: str | None = None,
    photo_image_base64: str | None = None,
    photo_image_mime_type: str = "image/jpeg",
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 0.5,
    administrative_area: str | None = None,
    max_records_per_layer: int | None = 20,
    max_total_records: int | None = 100,
) -> dict[str, Any]:
    graph = build_redevelopment_recommendation_graph()
    payload: dict[str, Any] = {}
    if house_id is not None:
        payload["house_id"] = house_id
    if address is not None:
        payload["address"] = address
    if "house_id" not in payload and "address" not in payload:
        payload["house_id"] = "YC-001"
    if photo_image_base64 is not None:
        payload["photo_image_base64"] = photo_image_base64
        payload["photo_image_mime_type"] = photo_image_mime_type
    if latitude is not None and longitude is not None:
        payload.update(
            {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "max_records_per_layer": max_records_per_layer,
                "max_total_records": max_total_records,
            }
        )
    if administrative_area is not None:
        payload["administrative_area"] = administrative_area
    return graph.invoke(payload)["recommendation"]


def run_nearby_data(
    latitude: float,
    longitude: float,
    radius_km: float,
    administrative_area: str | None = None,
    max_records_per_layer: int | None = 20,
    max_total_records: int | None = 100,
) -> dict[str, Any]:
    repository = LocalCsvGeoDataRepository()
    bundle = repository.find_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        administrative_area=administrative_area,
        max_records_per_layer=max_records_per_layer,
        max_total_records=max_total_records,
    )
    return {
        "center": bundle.center,
        "radius_km": bundle.radius_km,
        "administrative_area": bundle.administrative_area,
        "layers": bundle.layers,
        "summary": {
            "csv_layers": bundle.total_layers,
            "layers_with_matches": len(bundle.layers),
            "matched_objects": bundle.matched_records,
            "returned_objects": bundle.returned_records,
            "coordinate_layers_with_matches": sum(
                1 for layer in bundle.layers if layer.kind.value == "coordinate"
            ),
            "administrative_layers_with_matches": sum(
                1 for layer in bundle.layers if layer.kind.value == "administrative_area"
            ),
            "coordinate_records": bundle.coordinate_records,
            "unresolved_records": bundle.unresolved_records,
            "max_records_per_layer": bundle.max_records_per_layer,
            "max_total_records": bundle.max_total_records,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Yeongcheon vacant house agent demos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run localhost API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="API bind host")
    serve_parser.add_argument("--port", type=int, default=8000, help="API bind port")
    serve_parser.add_argument("--reload", action="store_true", help="Reload API server on code changes")

    subparsers.add_parser("patrol", help="Run patrol image assessment demo")

    redevelopment_parser = subparsers.add_parser("redevelopment", help="Run redevelopment recommendation demo")
    redevelopment_parser.add_argument("--house-id", help="Vacant house identifier")
    redevelopment_parser.add_argument("--address", help="Vacant house address")
    redevelopment_parser.add_argument("--photo-base64", help="Base64-encoded vacant-house photo")
    redevelopment_parser.add_argument("--photo-mime-type", default="image/jpeg", help="Photo MIME type")
    redevelopment_parser.add_argument("--lat", type=float, help="Latitude for nearby CSV context")
    redevelopment_parser.add_argument("--lon", type=float, help="Longitude for nearby CSV context")
    redevelopment_parser.add_argument("--radius-km", type=float, default=0.5, help="Nearby context radius")
    redevelopment_parser.add_argument("--admin-area", help="Administrative area resolved from the coordinate")
    redevelopment_parser.add_argument("--max-per-layer", type=int, default=20, help="Maximum results per CSV layer")
    redevelopment_parser.add_argument("--max-total", type=int, default=100, help="Maximum results across all layers")

    nearby_parser = subparsers.add_parser("nearby", help="Find local CSV objects near a coordinate")
    nearby_parser.add_argument("--lat", type=float, required=True, help="Latitude in decimal degrees")
    nearby_parser.add_argument("--lon", type=float, required=True, help="Longitude in decimal degrees")
    nearby_parser.add_argument("--radius-km", type=float, default=0.5, help="Search radius in kilometers")
    nearby_parser.add_argument("--admin-area", help="Administrative area resolved from the coordinate")
    nearby_parser.add_argument("--max-per-layer", type=int, default=20, help="Maximum results per CSV layer")
    nearby_parser.add_argument("--max-total", type=int, default=100, help="Maximum results across all layers")
    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        uvicorn.run("src.api:app", host=args.host, port=args.port, reload=args.reload)
        return
    if args.command == "patrol":
        result = run_patrol_demo()
    elif args.command == "redevelopment":
        result = run_redevelopment_demo(
            house_id=args.house_id,
            address=args.address,
            photo_image_base64=args.photo_base64,
            photo_image_mime_type=args.photo_mime_type,
            latitude=args.lat,
            longitude=args.lon,
            radius_km=args.radius_km,
            administrative_area=args.admin_area,
            max_records_per_layer=args.max_per_layer,
            max_total_records=args.max_total,
        )
    else:
        result = run_nearby_data(
            args.lat,
            args.lon,
            args.radius_km,
            args.admin_area,
            args.max_per_layer,
            args.max_total,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
