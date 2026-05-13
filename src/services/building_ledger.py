from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from src.models import BuildingLedgerInfo


BUILDING_LEDGER_BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
YEONGCHEON_SIGUNGU_CD = "47230"
DEFAULT_TIMEOUT_SECONDS = 10

# Only legal dongs that are already present in local fixtures or common demos.
# Add ri-level codes through BUILDING_LEGAL_DONG_CODES when production data
# includes eup/myeon parcel addresses.
YEONGCHEON_BJDONG_CODES: dict[str, str] = {
    "야사동": "10300",
    "문내동": "10400",
    "문외동": "10500",
    "창구동": "10600",
    "교촌동": "10700",
    "과전동": "10800",
    "성내동": "10900",
    "화룡동": "11000",
    "도동": "11100",
    "금노동": "11200",
    "완산동": "11300",
}


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
    key = service_key or os.getenv("BUILDING_OPEN_API_KEY")
    if not key:
        raise BuildingLedgerError("BUILDING_OPEN_API_KEY is not set")

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

    legal_area = _legal_area_name(normalized[: lot_match.start()].strip())
    bjdong_cd = _bjdong_codes().get(legal_area)
    if bjdong_cd is None:
        raise BuildingLedgerError(f"Unsupported Yeongcheon legal area: {legal_area}")

    return BuildingLedgerQuery(
        jibun_address=normalized,
        sigungu_cd=YEONGCHEON_SIGUNGU_CD,
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
    address = re.sub(r"\([^)]*\)", " ", address)
    address = re.sub(r"\s+", " ", address)
    return address.strip()


def _legal_area_name(address_prefix: str) -> str:
    tokens = address_prefix.split()
    if not tokens:
        raise BuildingLedgerError("Cannot parse legal area from empty address")
    if len(tokens) >= 2 and tokens[-2].endswith(("읍", "면")) and tokens[-1].endswith("리"):
        return f"{tokens[-2]} {tokens[-1]}"
    return tokens[-1]


def _bjdong_codes() -> dict[str, str]:
    codes = dict(YEONGCHEON_BJDONG_CODES)
    raw_extra_codes = os.getenv("BUILDING_LEGAL_DONG_CODES")
    if raw_extra_codes:
        try:
            extra_codes = json.loads(raw_extra_codes)
        except json.JSONDecodeError as exc:
            raise BuildingLedgerError("BUILDING_LEGAL_DONG_CODES must be JSON") from exc
        codes.update({str(key): str(value) for key, value in extra_codes.items()})
    return codes


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
