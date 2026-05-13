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


DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CACHE_PATH = DEFAULT_DATA_DIR / ".geocoding_cache.json"

LATITUDE_COLUMN = "위도"
LONGITUDE_COLUMN = "경도"
ROAD_HINT_COLUMNS = ("도로명주소", "소재지도로명주소", "영업장주소(도로명)", "도로명 주소", "도로명소재지")
PARCEL_HINT_COLUMNS = ("지번주소", "지번 주소", "주소(지번)", "공장대표주소(지번)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add WGS84 위도/경도 columns to address-only CSV rows.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--limit", type=int, help="Maximum API requests to make in this run")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    geocoder = VWorldGeocoder()
    cache = _load_cache(args.cache_path)
    requests_made = 0
    summary = {
        "files_changed": 0,
        "rows_filled": 0,
        "rows_failed": 0,
        "cache_hits": 0,
        "api_requests": 0,
    }

    for csv_path in sorted(args.data_dir.glob("*.csv")):
        file_result = augment_csv_file(
            csv_path,
            geocoder,
            cache,
            sleep_seconds=args.sleep_seconds,
            dry_run=args.dry_run,
            request_budget=None if args.limit is None else args.limit - requests_made,
        )
        requests_made += file_result["api_requests"]
        for key in summary:
            summary[key] += file_result.get(key, 0)
        if not args.dry_run:
            _save_cache(args.cache_path, cache)
        if args.limit is not None and requests_made >= args.limit:
            break

    if not args.dry_run:
        _save_cache(args.cache_path, cache)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def augment_csv_file(
    csv_path: Path,
    geocoder: VWorldGeocoder,
    cache: dict[str, dict[str, float | str | None]],
    *,
    sleep_seconds: float,
    dry_run: bool,
    request_budget: int | None,
) -> dict[str, int]:
    rows, fieldnames, encoding = _read_csv(csv_path)
    if not rows:
        return _empty_result()

    address_column = _select_address_column(fieldnames)
    if address_column is None:
        return _empty_result()

    updated = False
    result = _empty_result()
    latitude_column = _coordinate_column(fieldnames, LATITUDE_COLUMNS) or LATITUDE_COLUMN
    longitude_column = _coordinate_column(fieldnames, LONGITUDE_COLUMNS) or LONGITUDE_COLUMN
    new_fieldnames = list(fieldnames)
    if latitude_column not in new_fieldnames:
        new_fieldnames.append(latitude_column)
    if longitude_column not in new_fieldnames:
        new_fieldnames.append(longitude_column)

    for row in rows:
        if _has_coordinate(row, latitude_column, longitude_column):
            continue
        raw_address = (row.get(address_column) or "").strip()
        if not raw_address:
            continue

        candidates = _address_candidates(raw_address, address_column)
        coordinate = None
        for address, address_type in candidates:
            cache_key = f"{address_type}|{address}"
            if cache_key in cache:
                cached = cache[cache_key]
                if cached.get("latitude") is not None and cached.get("longitude") is not None:
                    coordinate = (cached["latitude"], cached["longitude"])
                    result["cache_hits"] += 1
                    break
                continue

            if request_budget is not None and result["api_requests"] >= request_budget:
                return _write_result(csv_path, rows, new_fieldnames, encoding, updated, dry_run, result)

            try:
                geocoded = geocoder.geocode(address, address_type)
            except GeocodingError as exc:
                cache[cache_key] = {"latitude": None, "longitude": None, "error": str(exc)}
                result["api_requests"] += 1
                time.sleep(sleep_seconds)
                continue

            cache[cache_key] = {
                "latitude": geocoded.latitude,
                "longitude": geocoded.longitude,
                "matched_address": geocoded.matched_address,
            }
            coordinate = (geocoded.latitude, geocoded.longitude)
            result["api_requests"] += 1
            time.sleep(sleep_seconds)
            break

        if coordinate is None:
            result["rows_failed"] += 1
            continue

        row[latitude_column] = _format_coordinate(coordinate[0])
        row[longitude_column] = _format_coordinate(coordinate[1])
        result["rows_filled"] += 1
        updated = True

    return _write_result(csv_path, rows, new_fieldnames, encoding, updated, dry_run, result)


def _write_result(
    csv_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
    encoding: str,
    updated: bool,
    dry_run: bool,
    result: dict[str, int],
) -> dict[str, int]:
    if updated:
        result["files_changed"] = 1
    if updated and not dry_run:
        with csv_path.open("w", encoding=encoding, newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    return result


def _empty_result() -> dict[str, int]:
    return {
        "files_changed": 0,
        "rows_filled": 0,
        "rows_failed": 0,
        "cache_hits": 0,
        "api_requests": 0,
    }


def _read_csv(csv_path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with csv_path.open("r", encoding=encoding, newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                return list(reader), list(reader.fieldnames or []), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, f"Unsupported CSV encoding: {csv_path}")


def _coordinate_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized_to_original = {_normalize_name(field): field for field in fieldnames}
    for column in candidates:
        match = normalized_to_original.get(_normalize_name(column))
        if match:
            return match
    return None


def _has_coordinate(row: dict[str, str], latitude_column: str, longitude_column: str) -> bool:
    return bool((row.get(latitude_column) or "").strip() and (row.get(longitude_column) or "").strip())


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
    if "영천시" not in address:
        address = f"경상북도 영천시 {address}"
    elif not address.startswith(("경상북도", "경북")):
        address = f"경상북도 {address}"
    return address


def _is_road_address_column(column: str) -> bool:
    normalized = _normalize_name(column)
    return any(_normalize_name(candidate) == normalized for candidate in ROAD_HINT_COLUMNS)


def _looks_like_road_address(address: str) -> bool:
    return bool(re.search(r"(?:로|길)\s*\d", address))


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value).strip()).casefold()


def _format_coordinate(value: float | str | None) -> str:
    return f"{float(value):.8f}"


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
