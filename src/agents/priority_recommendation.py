from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from src.models import (
    BuildingLedgerInfo,
    MaintenancePriority,
    NearbyGeoDataBundle,
    PriorityRecommendation,
    PriorityReportKind,
    PrioritySubAgentReport,
    VacantHouseRecord,
)
from src.agents.tools import PRIORITY_RECOMMENDATION_TOOLS, get_nearby_public_data_bundle
from src.services.public_data import MockPublicDataClient, PublicDataClient
from src.services.gemini import build_gemini_chat_model


class PriorityState(TypedDict, total=False):
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
    building_ledger_report: PrioritySubAgentReport
    nearby_context: NearbyGeoDataBundle
    photo_report: PrioritySubAgentReport
    nearby_report: PrioritySubAgentReport
    recommendation: PriorityRecommendation
    error: str


class SubAgentDecision(BaseModel):
    """Model-owned fields for a priority workflow sub-agent report."""

    summary: str = Field(description="Concise Korean report summary.", min_length=1)
    risk_signals: list[str] = Field(
        default_factory=list,
        description="Signals that increase maintenance priority.",
    )
    opportunity_signals: list[str] = Field(
        default_factory=list,
        description="Signals that support reuse, lower urgency, or public value.",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Concrete follow-up actions for city staff.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def fetch_public_data(
    state: PriorityState,
    public_data_client: PublicDataClient | None = None,
) -> PriorityState:
    client = public_data_client or MockPublicDataClient()
    if "house_id" in state:
        record = client.get_vacant_house(state["house_id"])
    else:
        address = state["address"]
        record = _record_from_address(address)

    address = state.get("address") or record.address
    building_ledger = fetch_building_ledger_by_address(address, record)
    building_ledger_report = _summarize_building_ledger(building_ledger, record)

    return {
        **state,
        "house_id": record.house_id,
        "address": address,
        "record": record,
        "building_ledger": building_ledger,
        "building_ledger_report": building_ledger_report,
    }


def _record_from_address(address: str) -> VacantHouseRecord:
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
        metadata={"source": "address-placeholder"},
    )


def fetch_building_ledger_by_address(
    address: str,
    record: VacantHouseRecord | None = None,
) -> BuildingLedgerInfo:
    """Resolve building-register information by address.

    TODO: Replace this placeholder with the target building-register API
    adapter. Keeping it as a function boundary lets the main agent flow run
    before the external service contract is finalized.
    """

    approval_year = None
    if record is not None:
        approval_year = datetime.now(UTC).year - record.building_age_years

    return BuildingLedgerInfo(
        address=address,
        main_use="단독주택",
        structure=record.structure_grade if record is not None else None,
        total_floor_area_m2=record.land_area_m2 if record is not None else None,
        approval_year=approval_year,
        source="mock-building-ledger",
        raw={"implementation_status": "planned"},
    )


def _summarize_building_ledger(
    building_ledger: BuildingLedgerInfo,
    record: VacantHouseRecord,
) -> PrioritySubAgentReport:
    risk_signals = []
    if record.building_age_years >= 30:
        risk_signals.append(f"건축물 노후도 {record.building_age_years}년")
    if record.structure_grade.upper() in {"D", "E"}:
        risk_signals.append(f"구조 등급 {record.structure_grade}")

    opportunity_signals = []
    if building_ledger.total_floor_area_m2:
        opportunity_signals.append(f"대장상 면적 {building_ledger.total_floor_area_m2}㎡")

    return PrioritySubAgentReport(
        kind=PriorityReportKind.BUILDING_LEDGER,
        summary=f"{building_ledger.address} 건축물대장 정보 조회 결과를 우선순위 판단에 반영합니다.",
        risk_signals=risk_signals,
        opportunity_signals=opportunity_signals,
        recommended_actions=["실제 건축물대장 API 연동 후 소유/위반/멸실 여부 확인"],
        confidence=0.45 if building_ledger.source.startswith("mock") else 0.8,
    )


def interpret_photo(state: PriorityState) -> PriorityState:
    if "photo_image_base64" not in state:
        return {
            "photo_report": PrioritySubAgentReport(
                kind=PriorityReportKind.PHOTO_INTERPRETATION,
                summary="사진 입력이 없어 외관 위험도 판정을 보류했습니다.",
                recommended_actions=["현장 사진 확보"],
                confidence=0.1,
            )
        }

    model = build_gemini_chat_model()
    if model is None:
        return {"photo_report": _mock_photo_report(state)}

    mime_type = state.get("photo_image_mime_type", "image/jpeg")
    prompt = (
        "당신은 영천시 빈집 사진 해석 서브에이전트입니다. "
        "입력 사진에서 붕괴, 균열, 화재 흔적, 폐기물, 출입 흔적, 안전 위해 요소와 "
        "재활용 가능성을 한국어 구조화 리포트로 판단하세요."
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
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
        return {"photo_report": _fallback_report(PriorityReportKind.PHOTO_INTERPRETATION, exc)}

    return {"photo_report": _report_from_decision(PriorityReportKind.PHOTO_INTERPRETATION, decision)}


def analyze_nearby_context(state: PriorityState) -> PriorityState:
    if "latitude" not in state or "longitude" not in state:
        return {
            "nearby_report": PrioritySubAgentReport(
                kind=PriorityReportKind.NEARBY_CONTEXT,
                summary="좌표 입력이 없어 주변 공공데이터 분석을 보류했습니다.",
                recommended_actions=["주소 지오코딩 또는 GPS 좌표 확보"],
                confidence=0.1,
            )
        }

    nearby_context = get_nearby_public_data_bundle(
        latitude=state["latitude"],
        longitude=state["longitude"],
        radius_km=state.get("radius_km", 2.0),
        administrative_area=state.get("administrative_area"),
        max_records_per_layer=state.get("max_records_per_layer", 20),
        max_total_records=state.get("max_total_records", 100),
    )
    return {
        "nearby_context": nearby_context,
        "nearby_report": _summarize_nearby_context(nearby_context),
    }


def _mock_photo_report(state: PriorityState) -> PrioritySubAgentReport:
    image_size = len(state["photo_image_base64"])
    risk_signals = ["사진 입력 존재, 모델 미설정으로 육안 검토 필요"]
    if image_size < 256:
        risk_signals.append("사진 데이터가 짧아 판독 신뢰도 낮음")

    return PrioritySubAgentReport(
        kind=PriorityReportKind.PHOTO_INTERPRETATION,
        summary="목업 사진 리포트: 실제 Gemini 키가 없어 사진 내용 판독 대신 입력 상태만 반영했습니다.",
        risk_signals=risk_signals,
        recommended_actions=["GOOGLE_API_KEY 설정 후 사진 기반 외관 판정 실행", "현장 담당자 육안 검토"],
        confidence=0.2,
    )


def _summarize_nearby_context(nearby_context: NearbyGeoDataBundle) -> PrioritySubAgentReport:
    matched_layers = [layer for layer in nearby_context.layers if layer.objects]
    risk_signals = []
    opportunity_signals = []

    for layer in matched_layers[:5]:
        layer_summary = f"{layer.source} {layer.returned_records}건"
        source_text = layer.source.lower()
        if any(keyword in source_text for keyword in ["재해", "산사태", "위험", "민원"]):
            risk_signals.append(layer_summary)
        else:
            opportunity_signals.append(layer_summary)

    return PrioritySubAgentReport(
        kind=PriorityReportKind.NEARBY_CONTEXT,
        summary=(
            f"반경 {nearby_context.radius_km}km 내 공공데이터 {len(matched_layers)}개 레이어, "
            f"{nearby_context.returned_records}건을 분석했습니다."
        ),
        risk_signals=risk_signals,
        opportunity_signals=opportunity_signals,
        recommended_actions=["주변 시설/위험 레이어 확인 후 정비 방식 조정"],
        confidence=0.75 if nearby_context.returned_records else 0.35,
    )


def _report_from_decision(
    kind: PriorityReportKind,
    decision: SubAgentDecision,
) -> PrioritySubAgentReport:
    return PrioritySubAgentReport(
        kind=kind,
        summary=decision.summary,
        risk_signals=decision.risk_signals,
        opportunity_signals=decision.opportunity_signals,
        recommended_actions=decision.recommended_actions,
        confidence=decision.confidence,
    )


def _fallback_report(kind: PriorityReportKind, error: Exception) -> PrioritySubAgentReport:
    return PrioritySubAgentReport(
        kind=kind,
        summary="모델 응답을 구조화된 서브에이전트 리포트로 변환하지 못했습니다.",
        risk_signals=["structured_output_failure"],
        recommended_actions=["담당자 육안 검토"],
        confidence=0.1,
        raw_model_output=str(error),
    )


def _score(record: VacantHouseRecord) -> float:
    grade_scores = {"A": 0, "B": 10, "C": 25, "D": 40, "E": 55}
    score = 0.0
    score += min(record.building_age_years, 60) * 0.6
    score += min(record.vacancy_years, 10) * 4.0
    score += grade_scores.get(record.structure_grade.upper(), 25)
    score += min(record.complaints_last_year, 10) * 3.0
    score += 8.0 if record.distance_to_road_m < 20 else 0.0
    return round(min(score, 100.0), 2)


def _priority(score: float) -> MaintenancePriority:
    if score >= 80:
        return MaintenancePriority.URGENT
    if score >= 60:
        return MaintenancePriority.HIGH
    if score >= 35:
        return MaintenancePriority.MEDIUM
    return MaintenancePriority.LOW


def _recommend_use(record: VacantHouseRecord, priority: MaintenancePriority) -> str:
    if priority in {MaintenancePriority.URGENT, MaintenancePriority.HIGH}:
        return "안전조치 후 철거 또는 구조 보강 우선 검토"
    if record.distance_to_public_facility_m <= 120 and record.land_area_m2 >= 70:
        return "마을 공유공간 또는 생활 SOC 연계 거점"
    if record.distance_to_road_m <= 30:
        return "소규모 주차장 또는 골목 환경개선 부지"
    return "임시 녹지 및 경관 정비"


def recommend_priority(state: PriorityState) -> PriorityState:
    record = state["record"]
    score = _score(record)
    reports = [
        report
        for report in (
            state.get("building_ledger_report"),
            state.get("photo_report"),
            state.get("nearby_report"),
        )
        if report is not None
    ]
    score = _adjust_score_with_reports(score, reports)
    priority = _priority(score)
    rationale = [
        f"건축물 노후도 {record.building_age_years}년",
        f"공실 기간 {record.vacancy_years}년",
        f"구조 등급 {record.structure_grade}",
        f"최근 1년 민원 {record.complaints_last_year}건",
    ]

    nearby_context = state.get("nearby_context")
    if nearby_context is not None:
        matched_layers = [layer for layer in nearby_context.layers if layer.objects]
        if nearby_context.matched_records:
            rationale.append(
                f"반경 {nearby_context.radius_km}km 내 공공데이터 {len(matched_layers)}개 레이어 "
                f"{nearby_context.matched_records}건 확인, {nearby_context.returned_records}건 반영"
            )
        if nearby_context.administrative_area:
            rationale.append(f"{nearby_context.administrative_area} 행정구역 단위 데이터 포함")

    for report in reports:
        rationale.append(f"{report.kind.value}: {report.summary}")
        rationale.extend(report.risk_signals[:3])

    recommendation = PriorityRecommendation(
        house_id=record.house_id,
        priority=priority,
        score=score,
        recommended_use=_recommend_use(record, priority),
        rationale=rationale,
        required_data=[
            "소유자 동의 여부",
            "토지/건축물대장 상세",
            "정비 예산",
            "인근 주민 수요",
        ],
    )
    return {**state, "recommendation": recommendation}


def _adjust_score_with_reports(
    base_score: float,
    reports: list[PrioritySubAgentReport],
) -> float:
    score = base_score
    for report in reports:
        risk_weight = 4.0 if report.kind is PriorityReportKind.PHOTO_INTERPRETATION else 2.5
        opportunity_weight = 1.5
        score += min(len(report.risk_signals), 4) * risk_weight * report.confidence
        score -= min(len(report.opportunity_signals), 3) * opportunity_weight * report.confidence
    return round(max(0.0, min(score, 100.0)), 2)


def build_priority_recommendation_graph(public_data_client: PublicDataClient | None = None):
    graph = StateGraph(PriorityState)
    graph.add_node("fetch_public_data", lambda state: fetch_public_data(state, public_data_client))
    graph.add_node("interpret_photo", interpret_photo)
    graph.add_node("analyze_nearby_context", analyze_nearby_context)
    graph.add_node("recommend_priority", recommend_priority)
    graph.set_entry_point("fetch_public_data")
    graph.add_edge("fetch_public_data", "interpret_photo")
    graph.add_edge("fetch_public_data", "analyze_nearby_context")
    graph.add_edge(["interpret_photo", "analyze_nearby_context"], "recommend_priority")
    graph.add_edge("recommend_priority", END)
    return graph.compile()


priority_recommendation_tools = PRIORITY_RECOMMENDATION_TOOLS
