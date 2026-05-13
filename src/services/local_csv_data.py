from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Iterable

from src.models import (
    Coordinate,
    GeoDataLayer,
    GeoDataLayerKind,
    GeoDataObject,
    NearbyGeoDataBundle,
    NearbyGeoDataLayer,
    NearbyGeoDataObject,
)


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CSV_DATE_SUFFIX = re.compile(r"[_ ]\d{4}_?\d{4}$")

LATITUDE_COLUMNS = ("위도", "latitude", "lat")
LONGITUDE_COLUMNS = ("경도", "longitude", "lon", "lng")
NAME_COLUMNS = (
    "업소명",
    "상호명",
    "명칭",
    "시설명",
    "사업장명",
    "회사명",
    "기관명",
    "정류소",
    "쉼터명칭",
    "모텔_민박 명칭",
    "공정표 관리번호",
)
ADDRESS_COLUMNS = (
    "소재지도로명주소",
    "도로명주소",
    "영업장주소(도로명)",
    "도로명소재지",
    "소재지주소",
    "주소",
    "대지위치",
    "공장대표주소(지번)",
    "지번주소",
    "지번 주소",
    "주소(지번)",
    "소재지",
)
ADMINISTRATIVE_AREA_COLUMNS = (
    "행정동",
    "읍면동",
    "법정동",
    "법정동명",
    "지역",
)
CATEGORY_COLUMNS = (
    "구분",
    "업종",
    "업종명",
    "대표업종",
    "유형명",
    "취약지역유형",
    "지역",
    "법정동",
    "법정동명",
    "행정동",
    "읍면동",
)


class LocalCsvGeoDataRepository:
    """Loads Yeongcheon local CSV files as source-grouped geospatial objects."""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)

    def load_layers(self, include_unresolved: bool = True) -> list[GeoDataLayer]:
        layers: list[GeoDataLayer] = []
        for csv_path in sorted(self.data_dir.glob("*.csv")):
            objects: list[GeoDataObject] = []
            total_records = 0
            coordinate_records = 0
            first_row: dict[str, str] | None = None

            for row_number, row in enumerate(self._read_csv(csv_path), start=1):
                total_records += 1
                clean_row = _clean_row(row)
                if first_row is None:
                    first_row = clean_row
                coordinate = _extract_coordinate(clean_row)
                if coordinate is None and not include_unresolved:
                    continue
                if coordinate is not None:
                    coordinate_records += 1

                objects.append(
                    GeoDataObject(
                        source=_source_name(csv_path),
                        source_file=csv_path.name,
                        row_number=row_number,
                        name=_first_present(clean_row, NAME_COLUMNS),
                        category=_first_present(clean_row, CATEGORY_COLUMNS),
                        address=_first_present(clean_row, ADDRESS_COLUMNS),
                        administrative_area=_first_present(clean_row, ADMINISTRATIVE_AREA_COLUMNS),
                        coordinate=coordinate,
                        properties=clean_row,
                    )
                )

            kind = _layer_kind(csv_path, first_row or {}, coordinate_records)
            layers.append(
                GeoDataLayer(
                    source=_source_name(csv_path),
                    source_file=csv_path.name,
                    kind=kind,
                    objects=objects,
                    total_records=total_records,
                    coordinate_records=coordinate_records,
                    unresolved_records=total_records - coordinate_records,
                )
            )

        return layers

    def find_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        administrative_area: str | None = None,
        sources: Iterable[str] | None = None,
        include_empty_layers: bool = False,
    ) -> NearbyGeoDataBundle:
        """Return CSV rows relevant to a coordinate query, grouped by CSV.

        Coordinate layers are filtered by `radius_km`. Administrative-area
        layers are included only when `administrative_area` is supplied.
        Address-only unresolved layers are intentionally left out until the
        address-to-coordinate enrichment step is available.
        """

        center = Coordinate(latitude=latitude, longitude=longitude)
        source_filter = {source.casefold() for source in sources} if sources else None
        nearby_layers: list[NearbyGeoDataLayer] = []
        total_layers = 0
        coordinate_records = 0
        unresolved_records = 0

        for layer in self.load_layers(include_unresolved=True):
            if source_filter and layer.source.casefold() not in source_filter:
                continue
            total_layers += 1
            coordinate_records += layer.coordinate_records
            unresolved_records += layer.unresolved_records

            if layer.kind == GeoDataLayerKind.COORDINATE:
                nearby_objects = _find_coordinate_objects(layer, center, radius_km)
            elif layer.kind == GeoDataLayerKind.ADMINISTRATIVE_AREA and administrative_area:
                nearby_objects = _find_administrative_objects(layer, administrative_area)
            else:
                nearby_objects = []

            nearby_objects.sort(key=lambda item: item.distance_km)
            if not nearby_objects and not include_empty_layers:
                continue

            nearby_layers.append(
                NearbyGeoDataLayer(
                    source=layer.source,
                    source_file=layer.source_file,
                    kind=layer.kind,
                    objects=nearby_objects,
                    total_records=layer.total_records,
                    coordinate_records=layer.coordinate_records,
                    unresolved_records=layer.unresolved_records,
                )
            )

        return NearbyGeoDataBundle(
            center=center,
            radius_km=radius_km,
            layers=nearby_layers,
            total_layers=total_layers,
            coordinate_records=coordinate_records,
            unresolved_records=unresolved_records,
            administrative_area=administrative_area,
        )

    def find_by_administrative_area(
        self,
        administrative_area: str,
        sources: Iterable[str] | None = None,
    ) -> list[GeoDataLayer]:
        """Return administrative-area layers matching an 읍면동/행정동/법정동 name."""

        source_filter = {source.casefold() for source in sources} if sources else None
        matched_layers: list[GeoDataLayer] = []
        for layer in self.load_layers(include_unresolved=True):
            if layer.kind != GeoDataLayerKind.ADMINISTRATIVE_AREA:
                continue
            if source_filter and layer.source.casefold() not in source_filter:
                continue
            matched_objects = [
                obj
                for obj in layer.objects
                if _same_administrative_area(obj.administrative_area, administrative_area)
            ]
            if not matched_objects:
                continue
            matched_layers.append(
                GeoDataLayer(
                    source=layer.source,
                    source_file=layer.source_file,
                    kind=layer.kind,
                    objects=matched_objects,
                    total_records=layer.total_records,
                    coordinate_records=layer.coordinate_records,
                    unresolved_records=layer.unresolved_records,
                )
            )

        return matched_layers

    def _read_csv(self, csv_path: Path) -> list[dict[str, str]]:
        for encoding in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                with csv_path.open("r", encoding=encoding, newline="") as csv_file:
                    return list(csv.DictReader(csv_file))
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("csv", b"", 0, 1, f"Unsupported CSV encoding: {csv_path}")


def haversine_km(first: Coordinate, second: Coordinate) -> float:
    earth_radius_km = 6371.0088
    lat1 = math.radians(first.latitude)
    lat2 = math.radians(second.latitude)
    delta_lat = math.radians(second.latitude - first.latitude)
    delta_lon = math.radians(second.longitude - first.longitude)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_coordinate_objects(
    layer: GeoDataLayer,
    center: Coordinate,
    radius_km: float,
) -> list[NearbyGeoDataObject]:
    nearby_objects: list[NearbyGeoDataObject] = []
    for obj in layer.objects:
        if obj.coordinate is None:
            continue
        distance_km = haversine_km(center, obj.coordinate)
        if distance_km <= radius_km:
            nearby_objects.append(
                NearbyGeoDataObject(
                    object=obj,
                    distance_km=round(distance_km, 4),
                )
            )
    return nearby_objects


def _find_administrative_objects(
    layer: GeoDataLayer,
    administrative_area: str,
) -> list[NearbyGeoDataObject]:
    return [
        NearbyGeoDataObject(object=obj, distance_km=0.0)
        for obj in layer.objects
        if _same_administrative_area(obj.administrative_area, administrative_area)
    ]


def _clean_row(row: dict[str, str | None]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        clean_key = key.strip()
        clean_value = "" if value is None else value.strip()
        if clean_key and clean_value:
            clean[clean_key] = clean_value
    return clean


def _extract_coordinate(row: dict[str, str]) -> Coordinate | None:
    latitude = _first_float(row, LATITUDE_COLUMNS)
    longitude = _first_float(row, LONGITUDE_COLUMNS)
    if latitude is not None and longitude is not None:
        return Coordinate(latitude=latitude, longitude=longitude)

    dms_latitude = _dms_to_decimal(row, "위도")
    dms_longitude = _dms_to_decimal(row, "경도")
    if dms_latitude is not None and dms_longitude is not None:
        return Coordinate(latitude=dms_latitude, longitude=dms_longitude)

    return None


def _layer_kind(
    csv_path: Path,
    first_row: dict[str, str],
    coordinate_records: int,
) -> GeoDataLayerKind:
    if coordinate_records > 0:
        return GeoDataLayerKind.COORDINATE

    source = _source_name(csv_path)
    has_address = _first_present(first_row, ADDRESS_COLUMNS) is not None
    has_admin_area = _first_present(first_row, ADMINISTRATIVE_AREA_COLUMNS) is not None
    if "읍면동별" in source or (has_admin_area and not has_address):
        return GeoDataLayerKind.ADMINISTRATIVE_AREA

    return GeoDataLayerKind.ADDRESS_UNRESOLVED


def _same_administrative_area(value: str | None, administrative_area: str) -> bool:
    if value is None:
        return False
    return _normalize_area_name(value) == _normalize_area_name(administrative_area)


def _normalize_area_name(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _dms_to_decimal(row: dict[str, str], prefix: str) -> float | None:
    degrees = _to_float(row.get(f"{prefix} 도"))
    minutes = _to_float(row.get(f"{prefix} 분"))
    seconds = _to_float(row.get(f"{prefix} 초"))
    if degrees is None or minutes is None or seconds is None:
        return None
    return degrees + minutes / 60 + seconds / 3600


def _first_present(row: dict[str, str], columns: Iterable[str]) -> str | None:
    for column in columns:
        value = row.get(column)
        if value:
            return value
    return None


def _first_float(row: dict[str, str], columns: Iterable[str]) -> float | None:
    for column in columns:
        value = _to_float(row.get(column))
        if value is not None:
            return value
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip().replace(",", "")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _source_name(csv_path: Path) -> str:
    return CSV_DATE_SUFFIX.sub("", csv_path.stem)
