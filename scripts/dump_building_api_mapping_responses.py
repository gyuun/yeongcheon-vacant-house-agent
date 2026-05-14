#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = REPO_ROOT / "data" / "house" / "mapping.csv"
BUILDING_LEDGER_BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
DEFAULT_ENDPOINTS = ("getBrBasisOulnInfo", "getBrTitleInfo")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.building_ledger import BuildingLedgerError, parse_yeongcheon_jibun_address  # noqa: E402


def load_env_file(env_path: Path = REPO_ROOT / ".env") -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def building_open_api_key() -> str | None:
    return (
        os.getenv("BUILDING_OPEN_API_KEY_ENCODING")
        or os.getenv("BUILDING_OPEN_API_KEY_DECODING")
        or os.getenv("BUILDING_OPEN_API_KEY")
    )


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
    url = f"{BUILDING_LEDGER_BASE_URL}/{endpoint}?{urlencode(params)}&serviceKey={service_key}"
    try:
        with urlopen(url, timeout=timeout) as response:
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_env_file()
    service_key = building_open_api_key()
    if not service_key:
        print(
            "Missing BUILDING_OPEN_API_KEY_ENCODING, BUILDING_OPEN_API_KEY_DECODING, or BUILDING_OPEN_API_KEY.",
            file=sys.stderr,
        )
        return 2

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
            "platGbCd": query.plat_gb_cd,
            "bun": query.bun,
            "ji": query.ji,
            "numOfRows": "10",
            "pageNo": "1",
            "_type": "json",
        }
        query_dump = asdict(query)
        for endpoint in endpoints:
            status, body = request_raw_body(endpoint, params, service_key, args.timeout)
            print_response_dump(
                house_id=house_id,
                address=address,
                endpoint=endpoint,
                query=query_dump,
                status=status,
                body=body,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
