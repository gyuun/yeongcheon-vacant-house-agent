#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = REPO_ROOT / "data" / "house" / "mapping.csv"
BUILDING_LEDGER_BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
DEFAULT_ENDPOINTS = ("getBrBasisOulnInfo", "getBrTitleInfo")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agents.tools.building_ledger import (  # noqa: E402
    BUILDING_LEDGER_AGENT_FIELD_DESCRIPTIONS,
    _ledger_agent_payload,
)
from src.services.building_ledger import (  # noqa: E402
    BuildingLedgerError,
    BuildingLedgerQuery,
    _first_item,
    _xml_to_dict,
    normalize_building_ledger_response,
    parse_yeongcheon_jibun_address,
)


def load_env_file(env_path: Path = REPO_ROOT / ".env") -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def building_open_api_key() -> tuple[str | None, str | None]:
    for name in (
        "BUILDING_OPEN_API_KEY_DECODING",
        "BUILDING_OPEN_API_KEY_ENCODING",
        "BUILDING_OPEN_API_KEY",
    ):
        value = os.getenv(name)
        if value:
            return value, name
    return None, None


def load_mapping_rows(mapping_path: Path) -> list[dict[str, str]]:
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as mapping_file:
        reader = csv.DictReader(mapping_file)
        return [
            {
                (key or "").strip(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        ]


def request_raw_body(endpoint: str, params: dict[str, str], service_key: str, timeout: float) -> tuple[int, str]:
    request_params = {"serviceKey": unquote(service_key.strip()), **params}
    url = f"{BUILDING_LEDGER_BASE_URL}/{endpoint}?{urlencode(request_params)}"
    request = Request(url, headers={"User-Agent": "curl/8.0", "Accept": "*/*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (TimeoutError, URLError, OSError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def print_response_dump(
    *,
    house_id: str,
    address: str,
    endpoint: str,
    query: dict[str, str],
    status: int,
    body: str,
) -> None:
    print("=" * 100)
    print(f"house_id: {house_id}")
    print(f"address: {address}")
    print(f"endpoint: {endpoint}")
    print(f"query: {query}")
    print(f"status: {status}")
    print(f"body_length: {len(body)}")
    print("-" * 100)
    print(body)
    print()


def parse_response_body(body: str) -> dict[str, object]:
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return _xml_to_dict(body)


def print_agent_view_dump(
    *,
    house_id: str,
    address: str,
    query: BuildingLedgerQuery,
    basis_payload: dict[str, object],
    title_payload: dict[str, object],
) -> None:
    print("=" * 100)
    print(f"house_id: {house_id}")
    print(f"address: {address}")
    print("agent_view: normalized fields shown to redevelopment agent")
    print("-" * 100)
    try:
        basis_item = _first_item(basis_payload) or {}
        title_item = _first_item(title_payload) or {}
        if not basis_item and not title_item:
            raise BuildingLedgerError(f"No building ledger result for {address}")
        ledger = normalize_building_ledger_response(
            query=query,
            basis_item=basis_item,
            title_item=title_item,
            raw={"basis": basis_payload, "title": title_payload},
        )
        agent_view = {
            "ok": True,
            "ledger": _ledger_agent_payload(ledger),
            "field_descriptions": BUILDING_LEDGER_AGENT_FIELD_DESCRIPTIONS,
        }
    except BuildingLedgerError as exc:
        agent_view = {
            "ok": False,
            "error": str(exc),
            "jibun_address": address,
        }
    print(json.dumps(agent_view, ensure_ascii=False, indent=2))
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dump raw Building Ledger API responses for every row in data/house/mapping.csv.",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=MAPPING_PATH,
        help=f"Mapping CSV path. Default: {MAPPING_PATH}",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        choices=DEFAULT_ENDPOINTS,
        help="Endpoint to call. Repeat to call multiple endpoints. Default: both basis and title endpoints.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout seconds. Default: 10.",
    )
    parser.add_argument(
        "--debug-key-source",
        action="store_true",
        help="Print selected API key environment variable name and non-secret shape metadata.",
    )
    parser.add_argument(
        "--no-agent-view",
        action="store_true",
        help="Do not print the normalized fields and descriptions seen by the redevelopment agent.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_env_file()
    service_key, service_key_source = building_open_api_key()
    if not service_key:
        print(
            "Missing BUILDING_OPEN_API_KEY_ENCODING, BUILDING_OPEN_API_KEY_DECODING, or BUILDING_OPEN_API_KEY.",
            file=sys.stderr,
        )
        return 2
    if args.debug_key_source:
        print(
            "selected_key_source: "
            f"{service_key_source} "
            f"length={len(service_key)} "
            f"has_percent={'%' in service_key} "
            f"has_plus={'+' in service_key}",
            file=sys.stderr,
        )

    endpoints = tuple(args.endpoint or DEFAULT_ENDPOINTS)
    rows = load_mapping_rows(args.mapping)
    for row in rows:
        house_id = row.get("house_id") or row.get("houde_id") or "-"
        address = row.get("real_address") or ""
        try:
            query = parse_yeongcheon_jibun_address(address)
        except BuildingLedgerError as exc:
            print("=" * 100)
            print(f"house_id: {house_id}")
            print(f"address: {address}")
            print(f"parse_error: {exc}")
            print()
            continue

        params = {
            "sigunguCd": query.sigungu_cd,
            "bjdongCd": query.bjdong_cd,
            "bun": query.bun,
            "ji": query.ji,
        }
        parsed_payloads: dict[str, dict[str, object]] = {}
        for endpoint in endpoints:
            status, body = request_raw_body(endpoint, params, service_key, args.timeout)
            print_response_dump(
                house_id=house_id,
                address=address,
                endpoint=endpoint,
                query=params,
                status=status,
                body=body,
            )
            try:
                parsed_payloads[endpoint] = parse_response_body(body)
            except BuildingLedgerError as exc:
                parsed_payloads[endpoint] = {
                    "parse_error": str(exc),
                    "raw_body_preview": body[:200],
                }

        if not args.no_agent_view:
            print_agent_view_dump(
                house_id=house_id,
                address=address,
                query=query,
                basis_payload=parsed_payloads.get("getBrBasisOulnInfo", {}),
                title_payload=parsed_payloads.get("getBrTitleInfo", {}),
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
