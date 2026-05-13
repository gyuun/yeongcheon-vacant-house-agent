from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha1
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from src.agents.prompts import load_prompt
from src.models import (
    BuildingLedgerInfo,
    NearbyGeoDataBundle,
    RedevelopmentRecommendation,
    RedevelopmentReportKind,
    RedevelopmentSubAgentReport,
    VacantHouseRecord,
)
from src.agents.tools import REDEVELOPMENT_RECOMMENDATION_TOOLS, get_building_ledger_info, get_nearby_public_data_bundle
from src.services.building_ledger import BuildingLedgerError, parse_yeongcheon_jibun_address
from src.services.public_data import MockPublicDataClient, PublicDataClient
from src.services.gemini import build_gemini_chat_model


class RedevelopmentState(TypedDict, total=False):
    house_id: str
    address: str
    photo_image_base64: str
    photo_image_mime_type: str
    latitude: float
    longitude: float
    radius_km: float
    administrative_area: str
    max_records_per_layer: int
    max_total_records: int
    record: VacantHouseRecord
    building_ledger: BuildingLedgerInfo
    building_ledger_report: RedevelopmentSubAgentReport
    photo_report: RedevelopmentSubAgentReport
    nearby_report: RedevelopmentSubAgentReport
    recommendation: RedevelopmentRecommendation
    error: str


class SubAgentDecision(BaseModel):
    """Model-owned fields for a redevelopment-use workflow sub-agent report."""

    summary: str = Field(description="Concise Korean report summary.", min_length=1)
    context_signals: list[str] = Field(
        default_factory=list,
        description="Visible or locational context useful for redevelopment-use inference.",
    )
    opportunity_signals: list[str] = Field(
        default_factory=list,
        description="Signals that support reuse, redevelopment, or public value.",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Concrete follow-up actions for city staff.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def fetch_public_data(
    state: RedevelopmentState,
    public_data_client: PublicDataClient | None = None,
) -> RedevelopmentState:
    client = public_data_client or MockPublicDataClient()
    if "house_id" in state:
        record = client.get_vacant_house(state["house_id"])
    else:
        address = state["address"]
        record = _record_from_address(
            address,
            latitude=state.get("latitude"),
            longitude=state.get("longitude"),
        )

    latitude = state.get("latitude", record.latitude)
    longitude = state.get("longitude", record.longitude)
    if latitude is not None and longitude is not None:
        record = replace(record, latitude=latitude, longitude=longitude)

    address = state.get("address") or record.address
    building_ledger = fetch_building_ledger_by_address(address, record)
    building_ledger_report = _summarize_building_ledger(building_ledger, record)

    next_state: RedevelopmentState = {
        **state,
        "house_id": record.house_id,
        "address": address,
        "record": record,
        "building_ledger": building_ledger,
        "building_ledger_report": building_ledger_report,
    }
    if latitude is not None and longitude is not None:
        next_state["latitude"] = latitude
        next_state["longitude"] = longitude
    return next_state


def _record_from_address(
    address: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> VacantHouseRecord:
    address_id = int(sha1(address.encode("utf-8")).hexdigest()[:8], 16) % 100000
    return VacantHouseRecord(
        house_id=f"ADDR-{address_id}",
        address=address,
        building_age_years=35,
        vacancy_years=4,
        structure_grade="C",
        complaints_last_year=3,
        distance_to_road_m=30.0,
        distance_to_public_facility_m=180.0,
        land_area_m2=100.0,
        latitude=latitude,
        longitude=longitude,
        metadata={"source": "address-placeholder"},
    )


def fetch_building_ledger_by_address(
    address: str,
    record: VacantHouseRecord | None = None,
) -> BuildingLedgerInfo:
    """Resolve building-register information from a Yeongcheon jibun address."""

    try:
        return get_building_ledger_info(address)
    except BuildingLedgerError as exc:
        return _mock_building_ledger(address, record, error=str(exc))


def _mock_building_ledger(
    address: str,
    record: VacantHouseRecord | None = None,
    error: str | None = None,
) -> BuildingLedgerInfo:
    """Fallback ledger payload used when the live API cannot be called."""

    approval_year = None
    if record is not None:
        approval_year = datetime.now(UTC).year - record.building_age_years
    parsed_query = None
    try:
        parsed_query = parse_yeongcheon_jibun_address(address)
    except BuildingLedgerError:
        parsed_query = None

    return BuildingLedgerInfo(
        address=address,
        jibun_address=address,
        ledger_type="일반",
        ledger_category="일반건축물",
        plat_gb_cd=parsed_query.plat_gb_cd if parsed_query is not None else "0",
        bun=parsed_query.bun if parsed_query is not None else None,
        ji=parsed_query.ji if parsed_query is not None else None,
        main_use="단독주택",
        structure=record.structure_grade if record is not None else None,
        roof_structure=None,
        land_area_m2=record.land_area_m2 if record is not None else None,
        building_area_m2=None,
        total_floor_area_m2=record.land_area_m2 if record is not None else None,
        building_coverage_ratio=None,
        floor_area_ratio=None,
        parking_count=None,
        district_zone=None,
        approval_year=approval_year,
        source="mock-building-ledger",
        raw={
            "api_status": "fallback",
            "input_address_type": "jibun",
            "parsed_query": asdict(parsed_query) if parsed_query is not None else None,
            "target_apis": ["getBrBasisOulnInfo", "getBrTitleInfo"],
            "fallback_reason": error,
        },
    )


def _summarize_building_ledger(
    building_ledger: BuildingLedgerInfo,
    record: VacantHouseRecord,
) -> RedevelopmentSubAgentReport:
    context_signals = []
    if record.building_age_years:
        context_signals.append(f"건축물 노후도 {record.building_age_years}년")
    if record.structure_grade:
        context_signals.append(f"구조 등급 {record.structure_grade}")
    opportunity_signals = []
    if building_ledger.main_use:
        opportunity_signals.append(f"대장상 주용도 {building_ledger.main_use}")
    if building_ledger.land_area_m2:
        opportunity_signals.append(f"대장상 대지면적 {building_ledger.land_area_m2}㎡")
    if building_ledger.total_floor_area_m2:
        opportunity_signals.append(f"대장상 연면적 {building_ledger.total_floor_area_m2}㎡")
    if building_ledger.district_zone:
        opportunity_signals.append(f"지역/지구/구역 {building_ledger.district_zone}")

    return RedevelopmentSubAgentReport(
        kind=RedevelopmentReportKind.BUILDING_LEDGER,
        summary=(
            f"{building_ledger.address} 지번 기준 건축물대장 기본개요/표제부 조회 결과를 "
            "재건축 용도 추천에 반영합니다."
        ),
        context_signals=context_signals,
        opportunity_signals=opportunity_signals,
        recommended_actions=["지번을 시군구코드/법정동코드/번/지로 변환해 건축물대장 API 연동"],
        confidence=0.45 if building_ledger.source.startswith("mock") else 0.8,
    )


def interpret_photo(state: RedevelopmentState) -> RedevelopmentState:
    if "photo_image_base64" not in state:
        return {
            "photo_report": RedevelopmentSubAgentReport(
                kind=RedevelopmentReportKind.PHOTO_INTERPRETATION,
                summary="사진 입력이 없어 외관 및 주변 경관 해석을 보류했습니다.",
                recommended_actions=["현장 사진 확보"],
                confidence=0.1,
            )
        }

    model = build_gemini_chat_model()
    if model is None:
        return {"photo_report": _mock_photo_report(state)}

    mime_type = state.get("photo_image_mime_type", "image/jpeg")
    message = HumanMessage(
        content=[
            {"type": "text", "text": load_prompt("redevelopment_photo_interpretation_prompt.md")},
            {
                "type": "image_url",
                "image_url": f"data:{mime_type};base64,{state['photo_image_base64']}",
            },
        ]
    )
    structured_model = model.with_structured_output(SubAgentDecision)
    try:
        decision = structured_model.invoke([message])
        if not isinstance(decision, SubAgentDecision):
            decision = SubAgentDecision.model_validate(decision)
    except (ValidationError, ValueError, TypeError) as exc:
        return {"photo_report": _fallback_report(RedevelopmentReportKind.PHOTO_INTERPRETATION, exc)}

    return {"photo_report": _report_from_decision(RedevelopmentReportKind.PHOTO_INTERPRETATION, decision)}


def analyze_nearby_context(state: RedevelopmentState) -> RedevelopmentState:
    if "latitude" not in state or "longitude" not in state:
        return {
            "nearby_report": RedevelopmentSubAgentReport(
                kind=RedevelopmentReportKind.NEARBY_CONTEXT,
                summary="좌표 입력이 없어 주변 공공데이터 분석을 보류했습니다.",
                recommended_actions=["주소 지오코딩 또는 GPS 좌표 확보"],
                confidence=0.1,
            )
        }

    nearby_context = get_nearby_public_data_bundle(
        latitude=state["latitude"],
        longitude=state["longitude"],
        radius_km=state.get("radius_km", 0.5),
        administrative_area=state.get("administrative_area"),
        max_records_per_layer=state.get("max_records_per_layer", 5),
        max_total_records=state.get("max_total_records", 20),
    )
    return {"nearby_report": _summarize_nearby_context(nearby_context)}


def _mock_photo_report(state: RedevelopmentState) -> RedevelopmentSubAgentReport:
    image_size = len(state["photo_image_base64"])
    context_signals = ["사진 입력 존재, 모델 미설정으로 주변 경관 및 외관 맥락 판독 필요"]
    if image_size < 256:
        context_signals.append("사진 데이터가 짧아 판독 신뢰도 낮음")

    return RedevelopmentSubAgentReport(
        kind=RedevelopmentReportKind.PHOTO_INTERPRETATION,
        summary="목업 사진 리포트: 실제 Gemini 키가 없어 사진 내용 판독 대신 입력 상태만 반영했습니다.",
        context_signals=context_signals,
        recommended_actions=["GOOGLE_API_KEY 설정 후 사진 기반 경관/입지 맥락 판독 실행", "현장 담당자 육안 검토"],
        confidence=0.2,
    )


def _summarize_nearby_context(nearby_context: NearbyGeoDataBundle) -> RedevelopmentSubAgentReport:
    matched_layers = [layer for layer in nearby_context.layers if layer.objects]
    context_signals = []
    opportunity_signals = []

    for layer in matched_layers[:5]:
        layer_summary = f"{layer.source} {layer.returned_records}건"
        source_text = layer.source.lower()
        if any(keyword in source_text for keyword in ["재해", "산사태", "위험", "민원"]):
            context_signals.append(layer_summary)
        else:
            opportunity_signals.append(layer_summary)

    return RedevelopmentSubAgentReport(
        kind=RedevelopmentReportKind.NEARBY_CONTEXT,
        summary=(
            f"반경 {nearby_context.radius_km}km 내 공공데이터 {len(matched_layers)}개 레이어, "
            f"{nearby_context.returned_records}건을 분석했습니다."
        ),
        context_signals=context_signals,
        opportunity_signals=opportunity_signals,
        recommended_actions=["주변 시설, 생활권, 경관 자원 확인 후 재건축 용도 구체화"],
        confidence=0.75 if nearby_context.returned_records else 0.35,
    )


def _report_from_decision(
    kind: RedevelopmentReportKind,
    decision: SubAgentDecision,
) -> RedevelopmentSubAgentReport:
    return RedevelopmentSubAgentReport(
        kind=kind,
        summary=decision.summary,
        context_signals=decision.context_signals,
        opportunity_signals=decision.opportunity_signals,
        recommended_actions=decision.recommended_actions,
        confidence=decision.confidence,
    )


def _fallback_report(kind: RedevelopmentReportKind, error: Exception) -> RedevelopmentSubAgentReport:
    return RedevelopmentSubAgentReport(
        kind=kind,
        summary="모델 응답을 구조화된 서브에이전트 리포트로 변환하지 못했습니다.",
        context_signals=["structured_output_failure"],
        recommended_actions=["담당자 육안 검토"],
        confidence=0.1,
        raw_model_output=str(error),
    )


def _recommend_use(record: VacantHouseRecord, reports: list[RedevelopmentSubAgentReport]) -> str:
    signal_text = " ".join(
        signal
        for report in reports
        for signal in [*report.context_signals, *report.opportunity_signals]
    )
    if any(keyword in signal_text for keyword in ["공원", "녹지", "경관", "쉼터"]):
        return "마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간"
    if any(keyword in signal_text for keyword in ["보건", "복지", "노인", "급식", "무더위쉼터"]):
        return "생활복지 거점 또는 돌봄 연계 커뮤니티 시설"
    if any(keyword in signal_text for keyword in ["숙박", "음식점", "착한가격", "테마파크"]):
        return "체류형 로컬 상권 연계 공간 또는 관광 안내 거점"
    if any(keyword in signal_text for keyword in ["공장", "제조", "일자리"]):
        return "소규모 창업, 작업장, 일자리 지원 거점"
    if record.distance_to_public_facility_m <= 120 and record.land_area_m2 >= 70:
        return "마을 공유공간 또는 생활 SOC 연계 거점"
    if record.distance_to_road_m <= 30:
        return "소규모 주차장 또는 골목 환경개선 부지"
    return "임시 녹지 및 경관 정비"


def recommend_redevelopment_use(state: RedevelopmentState) -> RedevelopmentState:
    record = state["record"]
    reports = [
        report
        for report in (
            state.get("building_ledger_report"),
            state.get("photo_report"),
            state.get("nearby_report"),
        )
        if report is not None
    ]
    rationale = [
        f"건축물 노후도 {record.building_age_years}년",
        f"공실 기간 {record.vacancy_years}년",
        f"구조 등급 {record.structure_grade}",
        f"최근 1년 민원 {record.complaints_last_year}건",
    ]

    for report in reports:
        rationale.append(f"{report.kind.value}: {report.summary}")
        rationale.extend(report.context_signals[:3])
        rationale.extend(report.opportunity_signals[:3])

    recommendation = RedevelopmentRecommendation(
        house_id=record.house_id,
        recommended_use=_recommend_use(record, reports),
        rationale=rationale,
        required_data=[
            "소유자 동의 여부",
            "토지/건축물대장 상세",
            "정비 예산",
            "인근 주민 수요",
        ],
    )
    return {**state, "recommendation": recommendation}


def build_redevelopment_recommendation_graph(public_data_client: PublicDataClient | None = None):
    graph = StateGraph(RedevelopmentState)
    graph.add_node("fetch_public_data", lambda state: fetch_public_data(state, public_data_client))
    graph.add_node("interpret_photo", interpret_photo)
    graph.add_node("analyze_nearby_context", analyze_nearby_context)
    graph.add_node("recommend_redevelopment_use", recommend_redevelopment_use)
    graph.set_entry_point("fetch_public_data")
    graph.add_edge("fetch_public_data", "interpret_photo")
    graph.add_edge("fetch_public_data", "analyze_nearby_context")
    graph.add_edge(["interpret_photo", "analyze_nearby_context"], "recommend_redevelopment_use")
    graph.add_edge("recommend_redevelopment_use", END)
    return graph.compile()


redevelopment_recommendation_tools = REDEVELOPMENT_RECOMMENDATION_TOOLS
