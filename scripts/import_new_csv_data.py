from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.geocoding import GeocodingError, VWorldGeocoder
from src.services.local_csv_data import ADDRESS_COLUMNS, LATITUDE_COLUMNS, LONGITUDE_COLUMNS


DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "new_data"
DEFAULT_TARGET_DIR = PROJECT_ROOT / "data"
DEFAULT_CACHE_PATH = DEFAULT_TARGET_DIR / ".geocoding_cache.json"
INPUT_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr")
OUTPUT_ENCODING = "utf-8-sig"
LATITUDE_COLUMN = "위도"
LONGITUDE_COLUMN = "경도"
ROAD_HINT_COLUMNS = (
    "도로명주소",
    "소재지도로명주소",
    "영업장주소(도로명)",
    "영업소 주소(도로명)",
    "도로명전체주소",
    "주소(도로명)",
    "소재지(도로명)",
    "소재지(도로명 주소)",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize data/new_data CSV files, add coordinates where possible, and copy them into data/."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--limit", type=int, help="Maximum geocoding API requests to make")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--no-geocode", action="store_true")
    args = parser.parse_args()

    cache = _load_cache(args.cache_path)
    geocoder = None if args.no_geocode else _build_geocoder()
    summary = {
        "files_written": 0,
        "rows_total": 0,
        "rows_with_coordinates": 0,
        "rows_geocoded": 0,
        "rows_failed_geocoding": 0,
        "cache_hits": 0,
        "api_requests": 0,
        "non_utf8_inputs": 0,
    }

    args.target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(args.source_dir.glob("*.csv")):
        if args.limit is not None and summary["api_requests"] >= args.limit:
            break

        result = import_csv_file(
            source_path=source_path,
            target_dir=args.target_dir,
            geocoder=geocoder,
            cache=cache,
            sleep_seconds=args.sleep_seconds,
            request_budget=None if args.limit is None else args.limit - summary["api_requests"],
        )
        for key, value in result.items():
            summary[key] += value
        _save_cache(args.cache_path, cache)

    _save_cache(args.cache_path, cache)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def import_csv_file(
    *,
    source_path: Path,
    target_dir: Path,
    geocoder: VWorldGeocoder | None,
    cache: dict[str, dict[str, float | str | None]],
    sleep_seconds: float,
    request_budget: int | None,
) -> dict[str, int]:
    rows, fieldnames, encoding = _read_csv(source_path)
    fieldnames, rows = _normalize_table(fieldnames, rows)
    latitude_column = _coordinate_column(fieldnames, LATITUDE_COLUMNS) or LATITUDE_COLUMN
    longitude_column = _coordinate_column(fieldnames, LONGITUDE_COLUMNS) or LONGITUDE_COLUMN

    if latitude_column not in fieldnames:
        fieldnames.append(latitude_column)
    if longitude_column not in fieldnames:
        fieldnames.append(longitude_column)

    result = {
        "files_written": 1,
        "rows_total": len(rows),
        "rows_with_coordinates": 0,
        "rows_geocoded": 0,
        "rows_failed_geocoding": 0,
        "cache_hits": 0,
        "api_requests": 0,
        "non_utf8_inputs": 0 if encoding == "utf-8-sig" else 1,
    }

    address_column = _select_address_column(fieldnames)
    for row in rows:
        _copy_known_coordinate(row, latitude_column, longitude_column)
        if _has_coordinate(row, latitude_column, longitude_column):
            result["rows_with_coordinates"] += 1
            continue

        if geocoder is None or address_column is None:
            continue

        coordinate = _geocode_row(
            row=row,
            address_column=address_column,
            geocoder=geocoder,
            cache=cache,
            sleep_seconds=sleep_seconds,
            result=result,
            request_budget=request_budget,
        )
        if coordinate is None:
            result["rows_failed_geocoding"] += 1
            continue

        row[latitude_column] = _format_coordinate(coordinate[0])
        row[longitude_column] = _format_coordinate(coordinate[1])
        result["rows_geocoded"] += 1
        result["rows_with_coordinates"] += 1

    target_path = target_dir / unicodedata.normalize("NFC", source_path.name)
    with target_path.open("w", encoding=OUTPUT_ENCODING, newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return result


def _geocode_row(
    *,
    row: dict[str, str],
    address_column: str,
    geocoder: VWorldGeocoder,
    cache: dict[str, dict[str, float | str | None]],
    sleep_seconds: float,
    result: dict[str, int],
    request_budget: int | None,
) -> tuple[float, float] | None:
    raw_address = (row.get(address_column) or "").strip()
    if not raw_address:
        return None

    for address, address_type in _address_candidates(raw_address, address_column):
        cache_key = f"{address_type}|{address}"
        cached = cache.get(cache_key)
        if cached is not None:
            if cached.get("latitude") is not None and cached.get("longitude") is not None:
                result["cache_hits"] += 1
                return float(cached["latitude"]), float(cached["longitude"])
            continue

        if request_budget is not None and result["api_requests"] >= request_budget:
            return None

        try:
            geocoded = geocoder.geocode(address, address_type)
        except GeocodingError as exc:
            error = str(exc)
            if "request failed" not in error:
                cache[cache_key] = {"latitude": None, "longitude": None, "error": error}
            result["api_requests"] += 1
            time.sleep(sleep_seconds)
            continue

        cache[cache_key] = {
            "latitude": geocoded.latitude,
            "longitude": geocoded.longitude,
            "matched_address": geocoded.matched_address,
        }
        result["api_requests"] += 1
        time.sleep(sleep_seconds)
        return geocoded.latitude, geocoded.longitude

    return None


def _read_csv(csv_path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    for encoding in INPUT_ENCODINGS:
        try:
            with csv_path.open("r", encoding=encoding, newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                return list(reader), list(reader.fieldnames or []), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, f"Unsupported CSV encoding: {csv_path}")


def _normalize_table(
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    normalized_fields: list[str] = []
    field_map: dict[str, str] = {}
    for field in fieldnames:
        clean_field = _clean_header(field)
        field_map[field] = clean_field
        if clean_field not in normalized_fields:
            normalized_fields.append(clean_field)

    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        clean_row: dict[str, str] = {}
        for raw_key, raw_value in row.items():
            if raw_key is None:
                continue
            key = field_map.get(raw_key, _clean_header(raw_key))
            value = "" if raw_value is None else unicodedata.normalize("NFC", raw_value).strip()
            if key and value and key not in clean_row:
                clean_row[key] = value
        normalized_rows.append(clean_row)

    return normalized_fields, normalized_rows


def _copy_known_coordinate(row: dict[str, str], latitude_column: str, longitude_column: str) -> None:
    if _has_coordinate(row, latitude_column, longitude_column):
        return

    coordinate_x = _to_float(row.get("좌표정보(X)"))
    coordinate_y = _to_float(row.get("좌표정보(Y)"))
    if coordinate_x is None or coordinate_y is None:
        return
    if _looks_like_korean_lat_lon(latitude=coordinate_x, longitude=coordinate_y):
        row[latitude_column] = _format_coordinate(coordinate_x)
        row[longitude_column] = _format_coordinate(coordinate_y)
    elif _looks_like_korean_lat_lon(latitude=coordinate_y, longitude=coordinate_x):
        row[latitude_column] = _format_coordinate(coordinate_y)
        row[longitude_column] = _format_coordinate(coordinate_x)


def _coordinate_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized_to_original = {_normalize_name(field): field for field in fieldnames}
    for column in candidates:
        match = normalized_to_original.get(_normalize_name(column))
        if match:
            return match
    return None


def _select_address_column(fieldnames: list[str]) -> str | None:
    normalized_to_original = {_normalize_name(field): field for field in fieldnames}
    for column in ADDRESS_COLUMNS:
        match = normalized_to_original.get(_normalize_name(column))
        if match:
            return match
    return None


def _address_candidates(raw_address: str, column: str) -> list[tuple[str, str]]:
    address = _normalize_address(raw_address)
    preferred = "ROAD" if _is_road_address_column(column) or _looks_like_road_address(address) else "PARCEL"
    alternate = "PARCEL" if preferred == "ROAD" else "ROAD"
    return [(address, preferred), (address, alternate)]


def _normalize_address(raw_address: str) -> str:
    address = unicodedata.normalize("NFC", raw_address)
    address = re.sub(r"\s+", " ", address).strip()
    if _starts_with_province(address):
        return address
    if "영천시" not in address:
        address = f"경상북도 영천시 {address}"
    elif not address.startswith(("경상북도", "경북")):
        address = f"경상북도 {address}"
    return address


def _starts_with_province(address: str) -> bool:
    prefixes = (
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충청북도", "충남", "충청남도", "전북", "전라북도",
        "전남", "전라남도", "경북", "경상북도", "경남", "경상남도", "제주",
    )
    return address.startswith(prefixes)


def _is_road_address_column(column: str) -> bool:
    normalized = _normalize_name(column)
    return any(_normalize_name(candidate) == normalized for candidate in ROAD_HINT_COLUMNS)


def _looks_like_road_address(address: str) -> bool:
    return bool(re.search(r"(?:로|길)\s*\d", address))


def _has_coordinate(row: dict[str, str], latitude_column: str, longitude_column: str) -> bool:
    return bool((row.get(latitude_column) or "").strip() and (row.get(longitude_column) or "").strip())


def _clean_header(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip())


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value).strip()).casefold()


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


def _format_coordinate(value: float | str | None) -> str:
    return f"{float(value):.8f}"


def _looks_like_korean_lat_lon(latitude: float, longitude: float) -> bool:
    return 33.0 <= latitude <= 39.5 and 124.0 <= longitude <= 132.5


def _build_geocoder() -> VWorldGeocoder | None:
    try:
        return VWorldGeocoder()
    except GeocodingError:
        return None


def _load_cache(cache_path: Path) -> dict[str, dict[str, float | str | None]]:
    if not cache_path.exists():
        return {}
    with cache_path.open("r", encoding="utf-8") as cache_file:
        return json.load(cache_file)


def _save_cache(cache_path: Path, cache: dict[str, dict[str, float | str | None]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as cache_file:
        json.dump(cache, cache_file, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
