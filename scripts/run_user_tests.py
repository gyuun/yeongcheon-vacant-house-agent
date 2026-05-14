#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
HOUSE_DATA_DIR = REPO_ROOT / "data" / "house"
MAPPING_PATH = HOUSE_DATA_DIR / "mapping.csv"
DEFAULT_OUTPUT_PATH = Path("test_result.json")
SERVER_LOG_PATH = Path("test_server.log")
MOCK_MARKERS = ("목업", "mock", "fallback", "structured_output_failure", "모델 미설정")
ROOF_MARKERS = ("지붕", "roof")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class HouseFixture:
    house_id: str
    simulated_house: str
    latitude: float
    longitude: float
    address: str


def load_env_file(env_path: Path = REPO_ROOT / ".env") -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_fixtures() -> list[HouseFixture]:
    with MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as mapping_file:
        reader = csv.DictReader(mapping_file)
        fixtures = []
        for row in reader:
            normalized = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
            house_id = normalized.get("house_id") or normalized.get("houde_id")
            if not house_id:
                raise ValueError(f"mapping row has no house_id: {row}")
            fixtures.append(
                HouseFixture(
                    house_id=house_id,
                    simulated_house=normalized["simulated_house"],
                    latitude=float(normalized["real_coord_x"]),
                    longitude=float(normalized["real_coord_y"]),
                    address=normalized["real_address"],
                )
            )
    return fixtures


def read_base64(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8").strip()


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Request timed out after {timeout:.1f}s: POST {path}") from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"Cannot reach API server at {base_url}: {exc}") from exc


def get_json(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    request = Request(f"{base_url.rstrip('/')}{path}", method="GET")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_is_ready(base_url: str, timeout: float = 2.0) -> bool:
    try:
        response = get_json(base_url, "/health", timeout)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    return response.get("status") == "ok"


def has_building_open_api_key() -> bool:
    return bool(
        os.getenv("BUILDING_OPEN_API_KEY_ENCODING")
        or os.getenv("BUILDING_OPEN_API_KEY_DECODING")
        or os.getenv("BUILDING_OPEN_API_KEY")
    )


def validate_building_ledger_api(fixtures: list[HouseFixture]) -> dict[str, Any]:
    from src.services.building_ledger import BuildingLedgerError, fetch_building_ledger_by_jibun_address

    fixture = fixtures[0]
    try:
        ledger = fetch_building_ledger_by_jibun_address(fixture.address)
    except BuildingLedgerError as exc:
        return result(
            False,
            "preflight:building_ledger_api",
            f"Building ledger API check failed for {fixture.address}: {exc}",
            {"fixture": asdict(fixture)},
        )
    return result(
        True,
        "preflight:building_ledger_api",
        f"building ledger API returned {ledger.source} for {fixture.address}",
        {"fixture": asdict(fixture), "ledger_source": ledger.source},
    )


def uvicorn_command() -> list[str]:
    if importlib.util.find_spec("uvicorn") is not None:
        return [sys.executable, "-m", "uvicorn"]
    if (REPO_ROOT / "uv.lock").exists() and shutil.which("uv"):
        return ["uv", "run", "python", "-m", "uvicorn"]
    return [sys.executable, "-m", "uvicorn"]


def start_api_server(base_url: str, timeout: float) -> subprocess.Popen[str] | None:
    if api_is_ready(base_url):
        print(f"Using existing API server: {base_url}", file=sys.stderr)
        return None

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    server_log_path = REPO_ROOT / SERVER_LOG_PATH
    server_log = server_log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                *uvicorn_command(),
                "src.api:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        server_log.close()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = _tail_text(server_log_path)
            raise RuntimeError(f"API server exited before becoming ready:\n{output}")
        if api_is_ready(base_url):
            print(f"Started API server: {base_url}", file=sys.stderr)
            return process
        time.sleep(0.5)

    stop_api_server(process)
    raise RuntimeError(f"API server did not become ready within {timeout:.1f}s: {base_url}")


def _tail_text(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def stop_api_server(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def contains_marker(value: Any, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in json.dumps(value, ensure_ascii=False).lower() for marker in markers)


def result(passed: bool, name: str, detail: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"passed": passed, "name": name, "detail": detail, "payload": payload or {}}


def print_case_start(name: str) -> float:
    print(f"RUN {name}", flush=True)
    return time.monotonic()


def print_case_result(item: dict[str, Any], started_at: float) -> None:
    status = "PASS" if item["passed"] else "FAIL"
    elapsed = time.monotonic() - started_at
    print(f"{status} {item['name']} ({elapsed:.1f}s) - {item['detail']}", flush=True)


def run_patrol_case(base_url: str, fixture: HouseFixture, timeout: float) -> dict[str, Any]:
    captured = read_base64(HOUSE_DATA_DIR / f"{fixture.simulated_house}_without_roof.txt")
    response = post_json(
        base_url,
        "/agents/patrol-image",
        {
            "house_id": fixture.house_id,
            "captured_image_base64": captured,
            "captured_at": "2026-05-13T10:00:00+09:00",
        },
        timeout,
    )

    failures = []
    if "spot_id" in response:
        failures.append("response still contains spot_id")
    if not response.get("is_anomaly"):
        failures.append("roof removal was not classified as anomaly")
    if contains_marker(response, MOCK_MARKERS):
        failures.append("response contains mock/fallback marker")
    if not contains_marker(response, ROOF_MARKERS):
        failures.append("response does not mention roof change")

    return result(
        passed=not failures,
        name=f"patrol:{fixture.house_id}",
        detail="; ".join(failures) if failures else "roof-change anomaly detected by live model response",
        payload=response,
    )


def run_redevelopment_case(base_url: str, fixture: HouseFixture, timeout: float) -> dict[str, Any]:
    photo = read_base64(HOUSE_DATA_DIR / f"{fixture.simulated_house}_without_roof.txt")
    response = post_json(
        base_url,
        "/agents/redevelopment-recommendation",
        {
            "house_id": fixture.house_id,
            "address": fixture.address,
            "photo_image_base64": photo,
            "photo_image_mime_type": "image/jpeg",
            "radius_km": 0.5,
            "max_records_per_layer": 5,
            "max_total_records": 20,
        },
        timeout,
    )

    failures = []
    if not response.get("recommended_use"):
        failures.append("recommended_use is empty")
    if not response.get("explanation"):
        failures.append("explanation is empty")
    if not response.get("rationale"):
        failures.append("rationale is empty")
    if contains_marker(response, MOCK_MARKERS):
        failures.append("response contains mock/fallback marker")

    return result(
        passed=not failures,
        name=f"redevelopment:{fixture.house_id}",
        detail="; ".join(failures) if failures else "recommendation generated without visible mock/fallback markers",
        payload=response,
    )


def run_geocode_checks(fixtures: list[HouseFixture], max_distance_m: float) -> list[dict[str, Any]]:
    from src.models import Coordinate
    from src.services.geocoding import GeocodingError, VWorldGeocoder
    from src.services.local_csv_data import haversine_km

    try:
        geocoder = VWorldGeocoder()
    except GeocodingError as exc:
        return [result(False, "geocode:preflight", str(exc))]

    checks = []
    for fixture in fixtures:
        try:
            geocoded = geocoder.geocode(fixture.address, "PARCEL")
        except GeocodingError as exc:
            checks.append(result(False, f"geocode:{fixture.house_id}", str(exc), {"fixture": asdict(fixture)}))
            continue
        distance_m = haversine_km(
            Coordinate(fixture.latitude, fixture.longitude),
            Coordinate(geocoded.latitude, geocoded.longitude),
        ) * 1000
        checks.append(
            result(
                passed=distance_m <= max_distance_m,
                name=f"geocode:{fixture.house_id}",
                detail=f"distance_m={distance_m:.2f}",
                payload={
                    "fixture": asdict(fixture),
                    "geocoded": asdict(geocoded),
                    "distance_m": distance_m,
                },
            )
        )
    return checks


def update_mapping_coordinates(geocode_results: list[dict[str, Any]]) -> dict[str, Any]:
    replacements = {
        item["payload"]["fixture"]["house_id"]: item["payload"]["geocoded"]
        for item in geocode_results
        if "fixture" in item.get("payload", {}) and "geocoded" in item.get("payload", {})
    }
    if not replacements:
        return result(False, "mapping:update", "no successful geocode results available")

    with MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as mapping_file:
        reader = csv.DictReader(mapping_file)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if fieldnames is None:
        return result(False, "mapping:update", "mapping.csv has no header")

    updated = 0
    for row in rows:
        normalized = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
        house_id = normalized.get("house_id") or normalized.get("houde_id")
        if house_id in replacements:
            if " real_coord_x" in row:
                row[" real_coord_x"] = f"{replacements[house_id]['latitude']:.7f}"
            if " real_coord_y" in row:
                row[" real_coord_y"] = f"{replacements[house_id]['longitude']:.7f}"
            if "real_coord_x" in row:
                row["real_coord_x"] = f"{replacements[house_id]['latitude']:.7f}"
            if "real_coord_y" in row:
                row["real_coord_y"] = f"{replacements[house_id]['longitude']:.7f}"
            updated += 1

    with MAPPING_PATH.open("w", encoding="utf-8", newline="") as mapping_file:
        writer = csv.DictWriter(mapping_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return result(True, "mapping:update", f"updated {updated} rows", {"path": str(MAPPING_PATH)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run six-sample user acceptance tests against the local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Running API server base URL.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout in seconds.")
    parser.add_argument("--server-timeout", type=float, default=30.0, help="API server startup timeout in seconds.")
    parser.add_argument(
        "--no-start-server",
        action="store_true",
        help="Do not start the local API server; use an already running server.",
    )
    parser.add_argument("--skip-patrol", action="store_true", help="Skip patrol image API tests.")
    parser.add_argument("--skip-redevelopment", action="store_true", help="Skip redevelopment recommendation API tests.")
    parser.add_argument("--skip-geocode", action="store_true", help="Skip direct VWorld geocoding checks.")
    parser.add_argument("--max-geocode-distance-m", type=float, default=30.0, help="Allowed mapping/geocoder distance delta.")
    parser.add_argument(
        "--update-mapping-coordinates",
        action="store_true",
        help="Replace mapping.csv coordinates with successful VWorld geocoding results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="JSON report path. Defaults to test_result.json.",
    )
    args = parser.parse_args()

    load_env_file()
    fixtures = load_fixtures()
    results: list[dict[str, Any]] = []
    server_process: subprocess.Popen[str] | None = None
    needs_api_server = not (args.skip_patrol and args.skip_redevelopment)
    needs_gemini = needs_api_server
    needs_geocoding = not (args.skip_redevelopment and args.skip_geocode)
    api_server_ready = not needs_api_server
    gemini_ready = not needs_gemini
    geocoding_ready = not needs_geocoding
    building_ledger_ready = args.skip_redevelopment

    try:
        if needs_api_server and not args.no_start_server:
            try:
                server_process = start_api_server(args.base_url, args.server_timeout)
                api_server_ready = True
            except RuntimeError as exc:
                results.append(result(False, "preflight:api_server", str(exc)))
        elif needs_api_server and not api_is_ready(args.base_url):
            results.append(result(False, "preflight:api_server", f"API server is not ready: {args.base_url}"))
        elif needs_api_server:
            api_server_ready = True

        if needs_gemini and not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            results.append(result(False, "preflight:gemini_key", "GOOGLE_API_KEY or GEMINI_API_KEY is required"))
        else:
            gemini_ready = True
        if needs_geocoding and not os.getenv("GEO_CODING_API_KEY"):
            results.append(result(False, "preflight:geocoding_key", "GEO_CODING_API_KEY is required for geocoding tests"))
        else:
            geocoding_ready = True
        if not args.skip_redevelopment and not has_building_open_api_key():
            results.append(
                result(
                    False,
                    "preflight:building_open_api_key",
                    "BUILDING_OPEN_API_KEY_ENCODING or BUILDING_OPEN_API_KEY_DECODING is required for redevelopment tests",
                )
            )
        else:
            building_ledger_ready = True
        if building_ledger_ready and not args.skip_redevelopment:
            item = validate_building_ledger_api(fixtures)
            results.append(item)
            building_ledger_ready = item["passed"]

        if not args.skip_patrol and api_server_ready and gemini_ready:
            for fixture in fixtures:
                started_at = print_case_start(f"patrol:{fixture.house_id}")
                try:
                    item = run_patrol_case(args.base_url, fixture, args.timeout)
                except (RuntimeError, FileNotFoundError) as exc:
                    item = result(False, f"patrol:{fixture.house_id}", str(exc), {"fixture": asdict(fixture)})
                results.append(item)
                print_case_result(item, started_at)

        if not args.skip_redevelopment and api_server_ready and gemini_ready and geocoding_ready and building_ledger_ready:
            for fixture in fixtures:
                started_at = print_case_start(f"redevelopment:{fixture.house_id}")
                try:
                    item = run_redevelopment_case(args.base_url, fixture, args.timeout)
                except (RuntimeError, FileNotFoundError) as exc:
                    item = result(False, f"redevelopment:{fixture.house_id}", str(exc), {"fixture": asdict(fixture)})
                results.append(item)
                print_case_result(item, started_at)

        if not args.skip_geocode and geocoding_ready:
            print("RUN geocode:*", flush=True)
            started_at = time.monotonic()
            geocode_results = run_geocode_checks(fixtures, args.max_geocode_distance_m)
            results.extend(geocode_results)
            for item in geocode_results:
                print_case_result(item, started_at)
            if args.update_mapping_coordinates:
                item = update_mapping_coordinates(geocode_results)
                results.append(item)
                print_case_result(item, started_at)
    finally:
        stop_api_server(server_process)

    report = {
        "passed": all(item["passed"] for item in results),
        "base_url": args.base_url,
        "fixture_count": len(fixtures),
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote JSON report: {args.output}", file=sys.stderr)
    passed_count = sum(1 for item in results if item["passed"])
    failed = len(results) - passed_count
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "fixture_count": len(fixtures),
                "passed_count": passed_count,
                "failed": failed,
                "output": str(args.output) if args.output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
