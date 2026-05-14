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

BUILDING_LEDGER_AGENT_FIELD_DESCRIPTIONS = {
    "address": "대표 지번 주소. 입력 주소와 대장 조회 결과를 대조할 때 사용합니다.",
    "jibun_address": "건축물대장에 등록된 지번 주소입니다.",
    "road_name_address": "건축물대장에 등록된 도로명주소입니다. 현장 확인용 보조 주소입니다.",
    "ledger_type": "대장 구분입니다. 일반/집합 등 권리·건물 단위 해석에 참고합니다.",
    "ledger_category": "대장 종류입니다. 표제부/일반건축물 등 조회 결과 성격을 확인합니다.",
    "plat_gb_cd": "대지구분코드입니다. 0은 대지, 1은 산, 2는 블록입니다.",
    "bun": "지번의 본번입니다. 건축물대장 API 재조회용 식별값입니다.",
    "ji": "지번의 부번입니다. 없으면 0000으로 정규화됩니다.",
    "main_use": "대장상 주용도입니다. 주거, 근린생활, 창고, 노유자시설 등 활용 방향 판단의 핵심 근거입니다.",
    "structure": "대장상 주구조입니다. 철근콘크리트, 벽돌, 목조 등 재사용 가능성과 철거 위험 판단에 씁니다.",
    "roof_structure": "대장상 지붕 구조입니다. 노후 상태와 보수 범위 판단의 보조 근거입니다.",
    "land_area_m2": "대지면적입니다. 공유공간, 주차장, 녹지 등 외부 공간 확보 가능성을 봅니다.",
    "building_area_m2": "건축면적입니다. 기존 건물이 차지하는 바닥 규모를 봅니다.",
    "total_floor_area_m2": "연면적입니다. 리모델링이나 재사용 가능한 전체 실내 규모를 봅니다.",
    "building_coverage_ratio": "건폐율입니다. 대지 대비 건축면적 비율로 증축·외부공간 여지를 판단합니다.",
    "floor_area_ratio": "용적률입니다. 대지 대비 연면적 비율로 추가 개발 여지를 판단합니다.",
    "parking_count": "대장상 주차대수입니다. 접근성, 생활 SOC 전환, 주차장 활용 판단의 보조 근거입니다.",
    "district_zone": "용도지역·지구·구역 정보입니다. 행정·법적 제약 가능성을 판단합니다.",
    "approval_year": "사용승인연도입니다. 건축물 노후도 산정과 구조 안전성 검토 필요성을 판단합니다.",
    "source": "데이터 출처 어댑터 이름입니다.",
}


def get_building_ledger_info(jibun_address: str) -> BuildingLedgerInfo:
    """Return normalized building-register info for one Yeongcheon parcel."""

    return fetch_building_ledger_by_jibun_address(jibun_address)


@tool
def search_building_ledger_by_jibun(jibun_address: str) -> dict[str, Any]:
    """Fetch Yeongcheon building-register basis/title info by parcel address.

    The input must be a parcel-lot address, not a road-name address. The tool
    parses the address into building-register API request parameters, calls
    `/getBrBasisOulnInfo` and `/getBrTitleInfo`, and returns only normalized
    fields used by the redevelopment recommendation agent plus field
    descriptions.
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
        "ledger": _ledger_agent_payload(ledger),
        "field_descriptions": BUILDING_LEDGER_AGENT_FIELD_DESCRIPTIONS,
    }


def _ledger_agent_payload(ledger: BuildingLedgerInfo) -> dict[str, Any]:
    payload = asdict(ledger)
    payload.pop("raw", None)
    return payload
