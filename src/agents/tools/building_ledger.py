from __future__ import annotations

from dataclasses import asdict
from typing import Any

from langchain_core.tools import tool

from src.models import BuildingLedgerInfo
from src.services.building_ledger import (
    BuildingLedgerError,
    fetch_building_ledger_by_jibun_address,
    parse_yeongcheon_jibun_address,
)


def get_building_ledger_info(jibun_address: str) -> BuildingLedgerInfo:
    """Return normalized building-register info for one Yeongcheon parcel."""

    return fetch_building_ledger_by_jibun_address(jibun_address)


@tool
def search_building_ledger_by_jibun(jibun_address: str) -> dict[str, Any]:
    """Fetch Yeongcheon building-register basis/title info by parcel address.

    The input must be a parcel-lot address, not a road-name address. The tool
    parses the address into building-register API request parameters, calls
    `/getBrBasisOulnInfo` and `/getBrTitleInfo`, and returns only the fields
    used by the redevelopment recommendation agent plus raw API payloads.
    """

    try:
        ledger = get_building_ledger_info(jibun_address)
    except BuildingLedgerError as exc:
        parsed_query: dict[str, Any] | None = None
        try:
            parsed_query = asdict(parse_yeongcheon_jibun_address(jibun_address))
        except BuildingLedgerError:
            parsed_query = None
        return {
            "ok": False,
            "error": str(exc),
            "jibun_address": jibun_address,
            "parsed_query": parsed_query,
        }

    return {
        "ok": True,
        "ledger": asdict(ledger),
    }
