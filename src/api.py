from __future__ import annotations

import logging
import os
from uuid import uuid4
from dataclasses import asdict, is_dataclass
from enum import Enum
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from src.agents.patrol_image import build_patrol_image_graph
from src.agents.redevelopment_recommendation import build_redevelopment_recommendation_graph
from src.models import PatrolImageInput
from src.services.geocoding import GeocodingError, GeocodeResult, VWorldGeocoder
from src.services.local_csv_data import LocalCsvGeoDataRepository


JIBUN_ADDRESS_TYPE = "PARCEL"
ROAD_ADDRESS_TYPE = "ROAD"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class RedevelopmentRecommendationRequest(BaseModel):
    house_id: str | None = Field(default=None, description="Vacant house identifier.")
    address: str = Field(description="Vacant house jibun address.")
    photo_image_base64: str = Field(description="Base64-encoded vacant-house photo.")
    photo_image_mime_type: str = Field(default="image/jpeg", description="Photo MIME type.")
    radius_km: float = Field(default=0.5, description="Nearby context radius.")
    administrative_area: str | None = Field(default=None, description="Administrative area name.")
    max_records_per_layer: int | None = Field(default=5, description="Maximum results per CSV layer.")
    max_total_records: int | None = Field(default=20, description="Maximum results across all CSV layers.")


class NearbyDataRequest(BaseModel):
    latitude: float = Field(description="WGS84 latitude.")
    longitude: float = Field(description="WGS84 longitude.")
    radius_km: float = Field(default=0.5, description="Search radius in kilometers.")
    administrative_area: str | None = Field(default=None, description="Administrative area name.")
    max_records_per_layer: int | None = Field(default=5, description="Maximum results per CSV layer.")
    max_total_records: int | None = Field(default=20, description="Maximum results across all CSV layers.")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


@lru_cache(maxsize=1)
def _patrol_graph():
    return build_patrol_image_graph()


@lru_cache(maxsize=1)
def _redevelopment_graph():
    return build_redevelopment_recommendation_graph()


@lru_cache(maxsize=1)
def _local_csv_repository():
    return LocalCsvGeoDataRepository()


@lru_cache(maxsize=1)
def _geocoder():
    return VWorldGeocoder()


def _geocode_jibun_address(address: str, trace_id: str = "-") -> GeocodeResult:
    errors: list[str] = []
    for address_type in (JIBUN_ADDRESS_TYPE, ROAD_ADDRESS_TYPE):
        try:
            logger.info("api.geocode.attempt trace_id=%s address=%r address_type=%s", trace_id, address, address_type)
            return _geocoder().geocode(address, address_type)
        except GeocodingError as exc:
            errors.append(f"{address_type}: {exc}")
            logger.warning(
                "api.geocode.failed trace_id=%s address=%r address_type=%s error=%s",
                trace_id,
                address,
                address_type,
                exc,
            )
            if "GEO_CODING_API_KEY" in str(exc):
                detail = f"주소를 좌표로 변환하지 못했습니다: {exc}"
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    detail = f"주소를 좌표로 변환하지 못했습니다: {'; '.join(errors)}"
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _is_model_quota_error(exc: Exception) -> bool:
    message = str(exc)
    return "RESOURCE_EXHAUSTED" in message or "429" in message or "quota" in message.lower()


def _model_error_response(exc: Exception) -> HTTPException:
    if _is_model_quota_error(exc):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API quota exceeded or rate limited. Check API quota/billing or retry later.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Model call failed: {exc}",
    )


app = FastAPI(
    title="Yeongcheon Vacant House Agent API",
    description="Localhost API endpoints for Yeongcheon vacant-house LangGraph agents.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agents/patrol-image")
def run_patrol_image_agent(request: PatrolImageInput) -> dict[str, Any]:
    trace_id = uuid4().hex[:12]
    logger.info("api.patrol.start trace_id=%s house_id=%s", trace_id, request.house_id)
    try:
        result = _patrol_graph().invoke({"request": request})
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("api.patrol.invalid_fixture trace_id=%s house_id=%s error=%s", trace_id, request.house_id, exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("api.patrol.model_failed trace_id=%s house_id=%s", trace_id, request.house_id)
        raise _model_error_response(exc) from exc
    assessment = result["assessment"]
    logger.info(
        "api.patrol.complete trace_id=%s house_id=%s is_anomaly=%s risk_level=%s",
        trace_id,
        assessment.house_id,
        assessment.is_anomaly,
        assessment.risk_level.value,
    )
    return _jsonable(assessment)


@app.post("/agents/redevelopment-recommendation")
def run_redevelopment_recommendation_agent(request: RedevelopmentRecommendationRequest) -> dict[str, Any]:
    trace_id = uuid4().hex[:12]
    logger.info(
        "api.redevelopment.start trace_id=%s house_id=%s address=%r radius_km=%s has_photo=%s",
        trace_id,
        request.house_id,
        request.address,
        request.radius_km,
        bool(request.photo_image_base64),
    )
    payload = request.model_dump(exclude_none=True)
    geocode_result = _geocode_jibun_address(request.address, trace_id)
    payload["latitude"] = geocode_result.latitude
    payload["longitude"] = geocode_result.longitude
    payload["trace_id"] = trace_id
    logger.info(
        "api.redevelopment.geocoded trace_id=%s address=%r latitude=%s longitude=%s matched_address=%r",
        trace_id,
        request.address,
        geocode_result.latitude,
        geocode_result.longitude,
        geocode_result.matched_address,
    )

    try:
        result = _redevelopment_graph().invoke(payload)
    except Exception as exc:
        logger.exception("api.redevelopment.model_failed trace_id=%s house_id=%s", trace_id, request.house_id)
        raise _model_error_response(exc) from exc
    recommendation = result["recommendation"]
    logger.info(
        "api.redevelopment.complete trace_id=%s house_id=%s recommended_use=%r rationale_count=%s",
        trace_id,
        recommendation.house_id,
        recommendation.recommended_use,
        len(recommendation.rationale),
    )
    return _jsonable(recommendation)


@app.post("/nearby")
def find_nearby_data(request: NearbyDataRequest) -> dict[str, Any]:
    logger.info(
        "api.nearby.start latitude=%s longitude=%s radius_km=%s administrative_area=%r",
        request.latitude,
        request.longitude,
        request.radius_km,
        request.administrative_area,
    )
    bundle = _local_csv_repository().find_nearby(
        latitude=request.latitude,
        longitude=request.longitude,
        radius_km=request.radius_km,
        administrative_area=request.administrative_area,
        max_records_per_layer=request.max_records_per_layer,
        max_total_records=request.max_total_records,
    )
    logger.info(
        "api.nearby.complete latitude=%s longitude=%s layers=%s returned_records=%s",
        request.latitude,
        request.longitude,
        len(bundle.layers),
        bundle.returned_records,
    )
    return _jsonable(
        {
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
    )
