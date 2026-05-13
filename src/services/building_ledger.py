from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
import unicodedata
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from src.models import BuildingLedgerInfo


BUILDING_LEDGER_BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
YEONGCHEON_SIGUNGU_CD = "47230"
DEFAULT_TIMEOUT_SECONDS = 10
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class BuildingLedgerQuery:
    jibun_address: str
    sigungu_cd: str
    bjdong_cd: str
    plat_gb_cd: str
    bun: str
    ji: str
    legal_area_name: str


class BuildingLedgerError(RuntimeError):
    """Raised when parcel parsing or the public API lookup fails."""


def fetch_building_ledger_by_jibun_address(
    jibun_address: str,
    *,
    service_key: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> BuildingLedgerInfo:
    """Fetch and normalize building ledger basis/title info for a parcel address."""

    query = parse_yeongcheon_jibun_address(jibun_address)
    key = service_key or _building_open_api_key()
    if not key:
        raise BuildingLedgerError(
            "BUILDING_OPEN_API_KEY_ENCODING or BUILDING_OPEN_API_KEY_DECODING is not set"
        )

    basis_payload = _request_endpoint(
        "getBrBasisOulnInfo",
        query,
        service_key=key,
        timeout_seconds=timeout_seconds,
    )
    title_payload = _request_endpoint(
        "getBrTitleInfo",
        query,
        service_key=key,
        timeout_seconds=timeout_seconds,
    )
    basis_item = _first_item(basis_payload)
    title_item = _first_item(title_payload)
    if not basis_item and not title_item:
        raise BuildingLedgerError(f"No building ledger result for {jibun_address}")

    return normalize_building_ledger_response(
        query=query,
        basis_item=basis_item or {},
        title_item=title_item or {},
        raw={"basis": basis_payload, "title": title_payload},
    )


def parse_yeongcheon_jibun_address(jibun_address: str) -> BuildingLedgerQuery:
    """Parse a Yeongcheon parcel address into building-register request params."""

    normalized = _normalize_address(jibun_address)
    lot_match = re.search(r"(산\s*)?(\d+)(?:\s*-\s*(\d+))?", normalized)
    if lot_match is None:
        raise BuildingLedgerError(f"Cannot parse parcel number from address: {jibun_address}")

    legal_area, sigungu_cd, bjdong_cd = _resolve_legal_area(normalized[: lot_match.start()].strip())

    return BuildingLedgerQuery(
        jibun_address=normalized,
        sigungu_cd=sigungu_cd,
        bjdong_cd=bjdong_cd,
        plat_gb_cd="1" if lot_match.group(1) else "0",
        bun=lot_match.group(2).zfill(4),
        ji=(lot_match.group(3) or "0").zfill(4),
        legal_area_name=legal_area,
    )


def normalize_building_ledger_response(
    *,
    query: BuildingLedgerQuery,
    basis_item: dict[str, Any],
    title_item: dict[str, Any],
    raw: dict[str, Any],
) -> BuildingLedgerInfo:
    source = "building-ledger-api"
    address = _first_value(title_item, basis_item, "platPlc") or query.jibun_address
    district_zone = " / ".join(
        value
        for value in (
            _first_value(basis_item, title_item, "jiyukCdNm", "etcJiyuk"),
            _first_value(basis_item, title_item, "jiguCdNm", "etcJigu"),
            _first_value(basis_item, title_item, "guyukCdNm", "etcGuyuk"),
        )
        if value
    ) or None

    return BuildingLedgerInfo(
        address=address,
        jibun_address=_first_value(title_item, basis_item, "platPlc") or query.jibun_address,
        road_name_address=_first_value(title_item, basis_item, "newPlatPlc"),
        ledger_type=_first_value(basis_item, title_item, "regstrGbCdNm"),
        ledger_category=_first_value(basis_item, title_item, "regstrKindCdNm"),
        plat_gb_cd=_first_value(title_item, basis_item, "platGbCd") or query.plat_gb_cd,
        bun=_first_value(title_item, basis_item, "bun") or query.bun,
        ji=_first_value(title_item, basis_item, "ji") or query.ji,
        main_use=_first_value(title_item, basis_item, "mainPurpsCdNm", "etcPurps"),
        structure=_first_value(title_item, basis_item, "strctCdNm", "etcStrct"),
        roof_structure=_first_value(title_item, basis_item, "roofCdNm", "etcRoof"),
        land_area_m2=_to_float(_first_value(title_item, basis_item, "platArea")),
        building_area_m2=_to_float(_first_value(title_item, basis_item, "archArea")),
        total_floor_area_m2=_to_float(_first_value(title_item, basis_item, "totArea")),
        building_coverage_ratio=_to_float(_first_value(title_item, basis_item, "bcRat")),
        floor_area_ratio=_to_float(_first_value(title_item, basis_item, "vlRat")),
        parking_count=_to_int(_first_value(title_item, basis_item, "totPkngCnt", "indrMechUtcnt", "oudrMechUtcnt")),
        district_zone=district_zone,
        approval_year=_approval_year(_first_value(title_item, basis_item, "useAprDay")),
        source=source,
        raw={
            "query": asdict(query),
            **raw,
        },
    )


def _request_endpoint(
    endpoint: str,
    query: BuildingLedgerQuery,
    *,
    service_key: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    params = {
        "sigunguCd": query.sigungu_cd,
        "bjdongCd": query.bjdong_cd,
        "platGbCd": query.plat_gb_cd,
        "bun": query.bun,
        "ji": query.ji,
        "numOfRows": "10",
        "pageNo": "1",
        "_type": "json",
    }
    url = f"{BUILDING_LEDGER_BASE_URL}/{endpoint}?{urlencode(params)}&serviceKey={service_key}"
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except URLError as exc:
        raise BuildingLedgerError(f"Building ledger API request failed: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return _xml_to_dict(body)


def _first_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {})
    item = items.get("item") if isinstance(items, dict) else None
    if isinstance(item, list):
        return item[0] if item else None
    if isinstance(item, dict):
        return item
    return None


def _xml_to_dict(body: str) -> dict[str, Any]:
    root = ElementTree.fromstring(body)

    def convert(element: ElementTree.Element) -> Any:
        children = list(element)
        if not children:
            return element.text or ""
        result: dict[str, Any] = {}
        for child in children:
            value = convert(child)
            if child.tag in result:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(value)
            else:
                result[child.tag] = value
        return result

    return {root.tag: convert(root)}


def _normalize_address(address: str) -> str:
    address = unicodedata.normalize("NFC", address)
    address = re.sub(r"\([^)]*\)", " ", address)
    address = re.sub(r"\s+", " ", address)
    return address.strip()


def _building_open_api_key() -> str | None:
    return (
        os.getenv("BUILDING_OPEN_API_KEY_ENCODING")
        or os.getenv("BUILDING_OPEN_API_KEY_DECODING")
        or os.getenv("BUILDING_OPEN_API_KEY")
    )


def _resolve_legal_area(address_prefix: str) -> tuple[str, str, str]:
    normalized_prefix = _normalize_address(address_prefix)
    if not normalized_prefix:
        raise BuildingLedgerError("Cannot parse legal area from empty address")

    for candidate_name, legal_dong_code in _legal_dong_candidates():
        if normalized_prefix == candidate_name or normalized_prefix.endswith(f" {candidate_name}"):
            return candidate_name, legal_dong_code[:5], legal_dong_code[5:]

    env_codes = _env_bjdong_codes()
    for candidate_name in sorted(env_codes, key=len, reverse=True):
        if normalized_prefix == candidate_name or normalized_prefix.endswith(f" {candidate_name}"):
            return candidate_name, YEONGCHEON_SIGUNGU_CD, env_codes[candidate_name]

    raise BuildingLedgerError(f"Unsupported Yeongcheon legal area in address: {address_prefix}")


@lru_cache(maxsize=1)
def _legal_dong_candidates() -> tuple[tuple[str, str], ...]:
    csv_path = _legal_dong_code_csv_path()
    candidates: dict[str, str] = {}
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                code = (row.get("법정동코드") or "").strip()
                legal_name = _normalize_address(row.get("법정동명") or "")
                if not code.startswith(YEONGCHEON_SIGUNGU_CD) or len(code) != 10 or not legal_name:
                    continue
                if code.endswith("00000"):
                    continue
                short_name = _short_legal_area_name(legal_name)
                candidates[legal_name] = code
                candidates[short_name] = code
    except OSError as exc:
        raise BuildingLedgerError(f"Cannot read legal dong code CSV: {csv_path}") from exc

    return tuple(sorted(candidates.items(), key=lambda item: len(item[0]), reverse=True))


def _legal_dong_code_csv_path() -> Path:
    for path in DATA_DIR.iterdir():
        normalized_name = unicodedata.normalize("NFC", path.name)
        if path.is_file() and "법정동코드" in normalized_name and "조회자료" in normalized_name:
            return path
    raise BuildingLedgerError(f"Legal dong code CSV not found in {DATA_DIR}")


def _short_legal_area_name(legal_name: str) -> str:
    tokens = legal_name.split()
    if len(tokens) >= 2 and tokens[-2].endswith(("읍", "면")) and tokens[-1].endswith("리"):
        return f"{tokens[-2]} {tokens[-1]}"
    return tokens[-1]


def _env_bjdong_codes() -> dict[str, str]:
    raw_extra_codes = os.getenv("BUILDING_LEGAL_DONG_CODES")
    if not raw_extra_codes:
        return {}
    try:
        extra_codes = json.loads(raw_extra_codes)
    except json.JSONDecodeError as exc:
        raise BuildingLedgerError("BUILDING_LEGAL_DONG_CODES must be JSON") from exc
    return {str(key): str(value).zfill(5) for key, value in extra_codes.items()}


def _first_value(*args: Any) -> str | None:
    rows = [arg for arg in args if isinstance(arg, dict)]
    keys = [arg for arg in args if isinstance(arg, str)]
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _approval_year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None
