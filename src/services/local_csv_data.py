from __future__ import annotations

import csv
import math
import re
import unicodedata
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
    "상호",
    "명칭",
    "명   칭",
    "시 설 명",
    "시설명",
    "체육시설명",
    "사업장명",
    "회사명",
    "기관명",
    "의료기관명",
    "정류소",
    "쉼터명칭",
    "모텔_민박 명칭",
    "공정표 관리번호",
    "행사명",
    "관리기관명",
)
ADDRESS_COLUMNS = (
    "소재지도로명주소",
    "소재지지번주소",
    "도로명주소",
    "도로명전체주소",
    "영업장주소(도로명)",
    "영업소 주소(도로명)",
    "도로명소재지",
    "소재지(도로명)",
    "소재지(지번)",
    "소재지주소",
    "소재지전체주소",
    "주소",
    "주소(도로명)",
    "대지위치",
    "공장대표주소(지번)",
    "지번주소",
    "지번 주소",
    "주소(지번)",
    "소재지(도로명 주소)",
    "소재지(지번 주소)",
    "소재지",
    "주   소",
    "사업장 소재지",
    "허가지 주소",
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
PROPERTY_COLUMN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("빈집 현황", ("용도지역", "법정동", "빈집판정일자", "등급산정일자", "빈집점수", "등급판정결과")),
    ("읍면동별기초수급자", ("기초생계급여", "기초의료급여", "기초주거급여", "기초교육급여", "총인원", "데이터기준일자")),
    ("착한가격업소", ("주요품목", "전화번호", "데이터기준일자")),
    ("노인복지시설", ("전화번호", "데이터기준일자")),
    ("노인교실", ("시설종류", "운영주체", "인원수", "연락처", "운영상태", "데이터기준일자")),
    ("경로당", ("행정동명", "건물층수", "관리기관명", "담당부서명", "관리기관전화번호", "데이터기준일자")),
    ("보건지소", ("전화번호", "위치 안내")),
    ("의료기관", ("운영시간", "진료과목", "병상수", "전화번호")),
    ("의료기기판매업소", ("전화번호",)),
    ("한약방", ("전화번호", "담당부서", "데이터기준일")),
    ("동물병원", ("전화번호", "방사선 기기")),
    ("동물약국", ("전화번호", "기준일")),
    ("약국", ("전화번호", "기준일", "데이터기준일")),
    ("급식소", ("우편번호",)),
    ("도시공원", ("개수", "담당부서", "기준일자")),
    ("산사태", ("리", "지번", "기타지번", "소유별", "취약지역 지정사유 및 목적", "지정일")),
    ("공장", ("대표업종번호", "업종명", "전화번호", "생산품", "용지면적", "건축면적")),
    ("관내양돈농가", ("축종", "사육두수", "오폐수처리시설")),
    ("대기배출시설", ("대표업종", "종")),
    ("모텔", ("전화번호", "지역")),
    ("버스쉘터", ("온열체어 유무", "에어커튼 유무", "조명등 유무", "공공와이파이 유무", "비상벨 유무")),
    ("버스승강장", ("쉴터유형", "정류소안내기", "온열체어", "에어커튼", "조명등", "공공와이파이", "비상벨")),
    ("숙박업", ("전화번호", "데이터기준일자")),
    ("농어촌민박", ("인허가일자", "영업상태명", "소재지면적", "업태구분명", "객실수", "한실수", "양실수", "욕실수", "데이터기준일자")),
    ("캠핑장", ("전화번호",)),
    ("산불", ("일자", "원인", "피해면적(ha)", "데이터 기준일자")),
    ("원룸", ("허가일", "사용승인일", "주용도", "부속용도", "세대수", "호수", "가구수")),
    ("일자리유관기관", ("연락처", "홈페이지바로가기")),
    ("제조업체", ("대표업종", "업종명", "전화번호", "종업원수")),
    ("운영시설현황", ("전화번호", "연면적(m2)", "주요시설")),
    ("공원및녹지점용허가", ("유형명", "토지면적", "허가시작일자", "허가종료일자", "공시지가", "점용료", "데이터기준일자")),
    ("기타테마파크업소", ("전화번호",)),
    ("무더위쉼터", ("시설면적", "이용가능인원(명)", "운영일", "시작시간", "종료시간", "선풍기", "에어컨")),
    ("일반음식점", ("전화번호",)),
    ("CCTV", ("설치목적구분", "카메라대수", "카메라화소수", "촬영방면정보", "보관일수", "설치연월", "관리기관전화번호", "데이터기준일자")),
    ("동네체육시설", ()),
    ("체육시설업", ()),
    ("마을회관", ()),
    ("카페", ("소재지전화", "업종명", "업태명")),
    ("미용업", ("업종명", "데이터기준일")),
    ("영천시농산물산지", ("시군명", "주요품목")),
    ("장례식장", ("구분", "종류", "전화번호", "팩스번호", "설치년도", "시설면적", "빈소수")),
    ("장애인 복지시설", ("연락처", "시설장", "인원수")),
    ("지역아동센터", ("정원", "현원", "전화번호", "팩스", "운영시간", "운영형태", "급식")),
    ("토석채취", ("수허가자 상호", "연락처", "토석채취용도", "허가면적", "허가량", "허가시작일", "허가종료일", "데이터기준일자")),
    ("행사및축제", ("행사내용", "장소명", "담당부서명", "행사시작일자", "행사종료일자", "데이터기준일자")),
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
                source = _source_name(csv_path)
                if first_row is None:
                    first_row = clean_row
                coordinate = _extract_coordinate(clean_row)
                if coordinate is None and not include_unresolved:
                    continue
                if coordinate is not None:
                    coordinate_records += 1

                objects.append(
                    GeoDataObject(
                        source=source,
                        source_file=csv_path.name,
                        row_number=row_number,
                        name=_first_present(clean_row, NAME_COLUMNS),
                        category=_first_present(clean_row, CATEGORY_COLUMNS),
                        address=_first_present(clean_row, ADDRESS_COLUMNS),
                        administrative_area=_first_present(clean_row, ADMINISTRATIVE_AREA_COLUMNS),
                        coordinate=coordinate,
                        properties=_agent_properties(source, clean_row),
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
        max_records_per_layer: int | None = 5,
        max_total_records: int | None = 20,
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
        matched_layer_counts: dict[str, int] = {}
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

            nearby_objects.sort(key=lambda item: _nearby_sort_key(layer.kind, item))
            matched_layer_counts[layer.source_file] = len(nearby_objects)
            if max_records_per_layer is not None:
                nearby_objects = nearby_objects[:max_records_per_layer]
            if not nearby_objects and not include_empty_layers:
                continue

            nearby_layers.append(
                NearbyGeoDataLayer(
                    source=layer.source,
                    source_file=layer.source_file,
                    kind=layer.kind,
                    objects=nearby_objects,
                    matched_records=matched_layer_counts[layer.source_file],
                    returned_records=len(nearby_objects),
                    total_records=layer.total_records,
                    coordinate_records=layer.coordinate_records,
                    unresolved_records=layer.unresolved_records,
                )
            )

        nearby_layers = _limit_layers_by_total_records(
            nearby_layers,
            max_total_records=max_total_records,
        )
        nearby_layers.sort(key=_layer_sort_key)
        matched_records = sum(matched_layer_counts.values())
        returned_records = sum(layer.returned_records for layer in nearby_layers)

        return NearbyGeoDataBundle(
            center=center,
            radius_km=radius_km,
            layers=nearby_layers,
            total_layers=total_layers,
            matched_records=matched_records,
            returned_records=returned_records,
            coordinate_records=coordinate_records,
            unresolved_records=unresolved_records,
            max_records_per_layer=max_records_per_layer,
            max_total_records=max_total_records,
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


def _limit_layers_by_total_records(
    layers: list[NearbyGeoDataLayer],
    max_total_records: int | None,
) -> list[NearbyGeoDataLayer]:
    if max_total_records is None:
        return layers

    kept_items: list[tuple[NearbyGeoDataLayer, NearbyGeoDataObject]] = []
    for layer in layers:
        for obj in layer.objects:
            kept_items.append((layer, obj))

    kept_items.sort(key=lambda item: _nearby_sort_key(item[0].kind, item[1]))
    kept_items = kept_items[:max_total_records]

    limited_layers: list[NearbyGeoDataLayer] = []
    for layer in layers:
        objects = [obj for candidate_layer, obj in kept_items if candidate_layer.source_file == layer.source_file]
        if not objects:
            continue
        limited_layers.append(
            NearbyGeoDataLayer(
                source=layer.source,
                source_file=layer.source_file,
                kind=layer.kind,
                objects=objects,
                matched_records=layer.matched_records,
                returned_records=len(objects),
                total_records=layer.total_records,
                coordinate_records=layer.coordinate_records,
                unresolved_records=layer.unresolved_records,
            )
        )

    return limited_layers


def _nearby_sort_key(
    layer_kind: GeoDataLayerKind,
    item: NearbyGeoDataObject,
) -> tuple[int, float, str, int]:
    kind_order = 0 if layer_kind == GeoDataLayerKind.COORDINATE else 1
    return (
        kind_order,
        item.distance_km,
        item.object.source,
        item.object.row_number,
    )


def _layer_sort_key(layer: NearbyGeoDataLayer) -> tuple[int, float, str]:
    nearest_distance = min((item.distance_km for item in layer.objects), default=math.inf)
    kind_order = 0 if layer.kind == GeoDataLayerKind.COORDINATE else 1
    return (kind_order, nearest_distance, layer.source)


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


def _agent_properties(source: str, row: dict[str, str]) -> dict[str, str]:
    selected_columns = _property_columns_for_source(source)
    return {column: row[column] for column in selected_columns if row.get(column)}


def _property_columns_for_source(source: str) -> tuple[str, ...]:
    normalized_source = unicodedata.normalize("NFC", source)
    for source_key, columns in PROPERTY_COLUMN_RULES:
        if source_key in normalized_source:
            return columns
    return ()


def _extract_coordinate(row: dict[str, str]) -> Coordinate | None:
    latitude = _first_float(row, LATITUDE_COLUMNS)
    longitude = _first_float(row, LONGITUDE_COLUMNS)
    if latitude is not None and longitude is not None:
        return Coordinate(latitude=latitude, longitude=longitude)

    coordinate_x = _to_float(row.get("좌표정보(X)"))
    coordinate_y = _to_float(row.get("좌표정보(Y)"))
    if coordinate_x is not None and coordinate_y is not None:
        if _looks_like_korean_lat_lon(latitude=coordinate_x, longitude=coordinate_y):
            return Coordinate(latitude=coordinate_x, longitude=coordinate_y)
        if _looks_like_korean_lat_lon(latitude=coordinate_y, longitude=coordinate_x):
            return Coordinate(latitude=coordinate_y, longitude=coordinate_x)

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
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value).strip())


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


def _looks_like_korean_lat_lon(latitude: float, longitude: float) -> bool:
    return 33.0 <= latitude <= 39.5 and 124.0 <= longitude <= 132.5


def _source_name(csv_path: Path) -> str:
    return unicodedata.normalize("NFC", CSV_DATE_SUFFIX.sub("", csv_path.stem))
