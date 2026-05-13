from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """Risk severity returned by the patrol image anomaly agent."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MaintenancePriority(str, Enum):
    """Maintenance priority returned by the vacant-house recommendation agent."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class GeoDataLayerKind(str, Enum):
    """How a CSV layer can be joined to a coordinate query."""

    COORDINATE = "coordinate"
    ADMINISTRATIVE_AREA = "administrative_area"
    ADDRESS_UNRESOLVED = "address_unresolved"


@dataclass(frozen=True)
class Coordinate:
    """WGS84 latitude/longitude coordinate."""

    latitude: float = field(metadata={"description": "Latitude in decimal degrees."})
    longitude: float = field(metadata={"description": "Longitude in decimal degrees."})


@dataclass(frozen=True)
class GeoDataObject:
    """One row from a local public-data CSV, normalized around location.

    `source` identifies the CSV layer. `properties` preserves the original row
    so recommendation agents can inspect fields that are specific to one CSV.
    Rows without coordinates are still represented with `coordinate=None`; they
    can be geocoded later without changing the surrounding-data contract.
    """

    source: str = field(metadata={"description": "Human-readable source CSV layer name."})
    source_file: str = field(metadata={"description": "CSV file name."})
    row_number: int = field(metadata={"description": "1-based data row number in the source CSV."})
    name: str | None = field(default=None, metadata={"description": "Best-effort display name."})
    category: str | None = field(default=None, metadata={"description": "Best-effort row category/type."})
    address: str | None = field(default=None, metadata={"description": "Best-effort address field."})
    administrative_area: str | None = field(
        default=None,
        metadata={"description": "Best-effort administrative area such as 읍면동, 행정동, or 법정동."},
    )
    coordinate: Coordinate | None = field(
        default=None,
        metadata={"description": "Row coordinate when the CSV provides one."},
    )
    properties: dict[str, Any] = field(
        default_factory=dict,
        metadata={"description": "Original CSV row with empty values removed."},
    )


@dataclass(frozen=True)
class GeoDataLayer:
    """Objects loaded from one CSV file."""

    source: str = field(metadata={"description": "Human-readable source CSV layer name."})
    source_file: str = field(metadata={"description": "CSV file name."})
    kind: GeoDataLayerKind = field(metadata={"description": "Join strategy for this source CSV."})
    objects: list[GeoDataObject] = field(metadata={"description": "Rows from this CSV."})
    total_records: int = field(metadata={"description": "Total row count in the CSV."})
    coordinate_records: int = field(metadata={"description": "Rows with usable coordinates."})
    unresolved_records: int = field(metadata={"description": "Rows without usable coordinates."})


@dataclass(frozen=True)
class NearbyGeoDataObject:
    """A geospatial CSV row that falls within a requested radius."""

    object: GeoDataObject = field(metadata={"description": "Original normalized CSV object."})
    distance_km: float = field(metadata={"description": "Distance from query point in kilometers."})


@dataclass(frozen=True)
class NearbyGeoDataLayer:
    """Nearby objects grouped by their source CSV layer."""

    source: str = field(metadata={"description": "Human-readable source CSV layer name."})
    source_file: str = field(metadata={"description": "CSV file name."})
    kind: GeoDataLayerKind = field(metadata={"description": "Join strategy for this source CSV."})
    objects: list[NearbyGeoDataObject] = field(metadata={"description": "Nearby objects in this layer."})
    matched_records: int = field(metadata={"description": "Rows matched before query result limits."})
    returned_records: int = field(metadata={"description": "Rows returned after query result limits."})
    total_records: int = field(metadata={"description": "Total row count in the CSV."})
    coordinate_records: int = field(metadata={"description": "Rows with usable coordinates."})
    unresolved_records: int = field(metadata={"description": "Rows without usable coordinates."})


@dataclass(frozen=True)
class NearbyGeoDataBundle:
    """All nearby CSV data grouped by source layer."""

    center: Coordinate = field(metadata={"description": "Query center coordinate."})
    radius_km: float = field(metadata={"description": "Search radius in kilometers."})
    layers: list[NearbyGeoDataLayer] = field(metadata={"description": "Source-grouped nearby objects."})
    total_layers: int = field(metadata={"description": "Total CSV layers scanned."})
    matched_records: int = field(metadata={"description": "Total rows matched before query result limits."})
    returned_records: int = field(metadata={"description": "Total rows returned after query result limits."})
    coordinate_records: int = field(metadata={"description": "Total rows with usable coordinates scanned."})
    unresolved_records: int = field(metadata={"description": "Total rows without usable coordinates scanned."})
    max_records_per_layer: int | None = field(
        default=None,
        metadata={"description": "Maximum returned rows per layer, when applied."},
    )
    max_total_records: int | None = field(
        default=None,
        metadata={"description": "Maximum returned rows across all layers, when applied."},
    )
    administrative_area: str | None = field(
        default=None,
        metadata={"description": "Administrative area used to attach area-level layers."},
    )


@dataclass(frozen=True)
class PatrolImageInput:
    """Image comparison request submitted by a patrol robot.

    The patrol agent compares `captured_image_base64` with
    `baseline_image_base64` for one house and one fixed camera spot.
    `metadata` can carry robot ID, GPS coordinates, weather, camera angle,
    or other sensor context that may help later routing and auditing.
    """

    house_id: str = field(metadata={"description": "Vacant house identifier."})
    spot_id: str = field(metadata={"description": "Fixed patrol camera spot identifier."})
    captured_image_base64: str = field(
        metadata={"description": "Base64-encoded image captured by the patrol robot."}
    )
    baseline_image_base64: str = field(
        metadata={"description": "Base64-encoded baseline image for normal-state comparison."}
    )
    captured_at: str | None = field(
        default=None,
        metadata={"description": "Image capture timestamp. ISO 8601 string is recommended."},
    )
    metadata: dict[str, Any] = field(
        default_factory=dict,
        metadata={"description": "Additional patrol context such as robot ID, GPS, weather, or angle."},
    )


@dataclass(frozen=True)
class PatrolImageAssessment:
    """Normalized anomaly assessment for one patrol image comparison.

    `is_anomaly` indicates whether the current image differs meaningfully from
    the baseline image. `risk_level` expresses response urgency, and
    `evidence` records visible clues or model-observed differences.
    `recommended_actions` lists next actions such as reinspection, staff
    notification, or keeping the regular patrol cadence. `raw_model_output`
    preserves the original Gemini response when available.
    """

    house_id: str = field(metadata={"description": "Vacant house identifier."})
    spot_id: str = field(metadata={"description": "Fixed patrol camera spot identifier."})
    is_anomaly: bool = field(
        metadata={"description": "Whether the current patrol image shows abnormal changes."}
    )
    risk_level: RiskLevel = field(metadata={"description": "Risk severity of the detected condition."})
    summary: str = field(metadata={"description": "Human-readable summary of the image assessment."})
    evidence: list[str] = field(
        metadata={"description": "Visible clues or model-observed differences supporting the assessment."}
    )
    recommended_actions: list[str] = field(
        metadata={"description": "Suggested follow-up actions for city staff or patrol operations."}
    )
    raw_model_output: str | None = field(
        default=None,
        metadata={"description": "Original model response text, when available."},
    )


@dataclass(frozen=True)
class VacantHouseRecord:
    """Source record for one vacant house from public data or a mock adapter.

    This model is the priority recommendation agent's main input. It captures
    condition, vacancy duration, complaints, accessibility, and land-size
    signals used by the current scoring heuristic. API-specific fields that do
    not yet belong in the core schema can be stored in `metadata`.
    """

    house_id: str = field(metadata={"description": "Vacant house identifier."})
    address: str = field(metadata={"description": "Address or administrative area of the vacant house."})
    building_age_years: int = field(metadata={"description": "Building age in years."})
    vacancy_years: int = field(metadata={"description": "Number of years the property has been vacant."})
    structure_grade: str = field(
        metadata={"description": "Structural condition grade. The current heuristic assumes A to E."}
    )
    complaints_last_year: int = field(
        metadata={"description": "Number of civil complaints reported in the last year."}
    )
    distance_to_road_m: float = field(metadata={"description": "Distance to the nearest road in meters."})
    distance_to_public_facility_m: float = field(
        metadata={"description": "Distance to the nearest public facility in meters."}
    )
    land_area_m2: float = field(metadata={"description": "Land area in square meters."})
    metadata: dict[str, Any] = field(
        default_factory=dict,
        metadata={"description": "Additional public-data source fields or raw API context."},
    )


@dataclass(frozen=True)
class PriorityRecommendation:
    """Maintenance priority and reuse recommendation for one vacant house.

    `priority` and `score` summarize how urgently the house should be handled.
    `recommended_use` describes the proposed direction, `rationale` explains
    the decision, and `required_data` lists administrative data needed before a
    real-world decision is finalized.
    """

    house_id: str = field(metadata={"description": "Vacant house identifier."})
    priority: MaintenancePriority = field(metadata={"description": "Recommended maintenance priority."})
    score: float = field(metadata={"description": "Priority score, currently normalized to a 0-100 range."})
    recommended_use: str = field(
        metadata={"description": "Suggested maintenance or reuse direction for the vacant property."}
    )
    rationale: list[str] = field(metadata={"description": "Decision rationale behind the recommendation."})
    required_data: list[str] = field(
        metadata={"description": "Additional administrative data needed before final action."}
    )
