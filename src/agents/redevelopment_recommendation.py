from __future__ import annotations

import logging
import csv
from dataclasses import replace
from hashlib import sha1
from pathlib import Path
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
from src.services.building_ledger import BuildingLedgerError
from src.services.gemini import build_gemini_chat_model


logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
HOUSE_MAPPING_PATH = REPO_ROOT / "data" / "house" / "mapping.csv"


class RedevelopmentState(TypedDict, total=False):
    trace_id: str
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
) -> RedevelopmentState:
    trace_id = state.get("trace_id", "-")
    logger.info(
        "redevelopment.fetch_public_data.start trace_id=%s house_id=%s address=%r has_coordinates=%s",
        trace_id,
        state.get("house_id"),
        state.get("address"),
        "latitude" in state and "longitude" in state,
    )
    if "address" in state:
        record = _record_from_address(
            state["address"],
            house_id=state.get("house_id"),
            latitude=state.get("latitude"),
            longitude=state.get("longitude"),
            source="request",
        )
    elif "house_id" in state:
        record = _record_from_house_mapping(state["house_id"])
    else:
        raise ValueError("Either address or house_id is required.")

    latitude = state.get("latitude", record.latitude)
    longitude = state.get("longitude", record.longitude)
    if latitude is not None and longitude is not None:
        record = replace(record, latitude=latitude, longitude=longitude)

    address = state.get("address") or record.address
    building_ledger = fetch_building_ledger_by_address(address, record)
    building_ledger_report = _summarize_building_ledger(building_ledger, record)
    logger.info(
        "redevelopment.fetch_public_data.complete trace_id=%s house_id=%s address=%r latitude=%s longitude=%s ledger_source=%s ledger_confidence=%s",
        trace_id,
        record.house_id,
        address,
        latitude,
        longitude,
        building_ledger.source,
        building_ledger_report.confidence,
    )

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
    house_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    source: str = "request",
) -> VacantHouseRecord:
    address_id = int(sha1(address.encode("utf-8")).hexdigest()[:8], 16) % 100000
    return VacantHouseRecord(
        house_id=house_id or f"ADDR-{address_id}",
        address=address,
        building_age_years=0,
        vacancy_years=0,
        structure_grade="미확인",
        complaints_last_year=0,
        distance_to_road_m=0.0,
        distance_to_public_facility_m=0.0,
        land_area_m2=0.0,
        latitude=latitude,
        longitude=longitude,
        metadata={"source": source},
    )


def _record_from_house_mapping(house_id: str) -> VacantHouseRecord:
    if not HOUSE_MAPPING_PATH.exists():
        raise FileNotFoundError(f"House mapping file not found: {HOUSE_MAPPING_PATH}")

    with HOUSE_MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as mapping_file:
        reader = csv.DictReader(mapping_file)
        for row in reader:
            normalized = {key.strip(): value.strip() for key, value in row.items() if key is not None and value is not None}
            row_house_id = normalized.get("house_id") or normalized.get("houde_id")
            if row_house_id != house_id:
                continue
            address = normalized.get("real_address")
            if not address:
                raise ValueError(f"Missing real_address for house_id={house_id}")
            latitude = _parse_float(normalized.get("real_coord_x"))
            longitude = _parse_float(normalized.get("real_coord_y"))
            return _record_from_address(
                address,
                house_id=house_id,
                latitude=latitude,
                longitude=longitude,
                source="house-mapping",
            )

    raise ValueError(f"No house mapping found for house_id={house_id}")


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def fetch_building_ledger_by_address(
    address: str,
    record: VacantHouseRecord | None = None,
) -> BuildingLedgerInfo:
    """Resolve building-register information from a Yeongcheon jibun address."""

    try:
        logger.info("redevelopment.building_ledger.start address=%r", address)
        ledger = get_building_ledger_info(address)
        logger.info(
            "redevelopment.building_ledger.success address=%r source=%s main_use=%r approval_year=%s",
            address,
            ledger.source,
            ledger.main_use,
            ledger.approval_year,
        )
        return ledger
    except BuildingLedgerError as exc:
        logger.exception("redevelopment.building_ledger.failed address=%r", address)
        raise RuntimeError(f"Building ledger lookup failed for address={address!r}: {exc}") from exc


def _summarize_building_ledger(
    building_ledger: BuildingLedgerInfo,
    record: VacantHouseRecord,
) -> RedevelopmentSubAgentReport:
    context_signals = []
    if record.building_age_years:
        context_signals.append(f"건축물 노후도 {record.building_age_years}년")
    if record.structure_grade and record.structure_grade != "미확인":
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
        confidence=0.8,
    )


def interpret_photo(state: RedevelopmentState) -> RedevelopmentState:
    trace_id = state.get("trace_id", "-")
    logger.info(
        "redevelopment.interpret_photo.start trace_id=%s house_id=%s has_photo=%s mime_type=%s",
        trace_id,
        state.get("house_id"),
        "photo_image_base64" in state,
        state.get("photo_image_mime_type", "image/jpeg"),
    )
    if "photo_image_base64" not in state:
        logger.info("redevelopment.interpret_photo.skipped trace_id=%s reason=no_photo", trace_id)
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
        raise RuntimeError("Gemini model is not configured. Set GOOGLE_API_KEY or GEMINI_API_KEY.")

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
        logger.info(
            "redevelopment.interpret_photo.invoke_model trace_id=%s image_base64_length=%s",
            trace_id,
            len(state["photo_image_base64"]),
        )
        decision = structured_model.invoke([message])
        if not isinstance(decision, SubAgentDecision):
            decision = SubAgentDecision.model_validate(decision)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.exception("redevelopment.interpret_photo.structured_output_failed trace_id=%s", trace_id)
        raise RuntimeError("Gemini photo interpretation response could not be parsed.") from exc

    report = _report_from_decision(RedevelopmentReportKind.PHOTO_INTERPRETATION, decision)
    logger.info(
        "redevelopment.interpret_photo.complete trace_id=%s confidence=%s context_signals=%s opportunity_signals=%s",
        trace_id,
        report.confidence,
        len(report.context_signals),
        len(report.opportunity_signals),
    )
    return {"photo_report": report}


def analyze_nearby_context(state: RedevelopmentState) -> RedevelopmentState:
    trace_id = state.get("trace_id", "-")
    logger.info(
        "redevelopment.nearby_context.start trace_id=%s house_id=%s latitude=%s longitude=%s radius_km=%s",
        trace_id,
        state.get("house_id"),
        state.get("latitude"),
        state.get("longitude"),
        state.get("radius_km", 0.5),
    )
    if "latitude" not in state or "longitude" not in state:
        logger.info("redevelopment.nearby_context.skipped trace_id=%s reason=no_coordinates", trace_id)
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
    report = _summarize_nearby_context(nearby_context)
    logger.info(
        "redevelopment.nearby_context.complete trace_id=%s layers=%s returned_records=%s confidence=%s",
        trace_id,
        len(nearby_context.layers),
        nearby_context.returned_records,
        report.confidence,
    )
    return {"nearby_report": report}


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
    if 0 < record.distance_to_public_facility_m <= 120 and record.land_area_m2 >= 70:
        return "마을 공유공간 또는 생활 SOC 연계 거점"
    if 0 < record.distance_to_road_m <= 30:
        return "소규모 주차장 또는 골목 환경개선 부지"
    return "임시 녹지 및 경관 정비"


def _build_recommendation_explanation(
    recommended_use: str,
    record: VacantHouseRecord,
    reports: list[RedevelopmentSubAgentReport],
) -> str:
    nearby_report = next((report for report in reports if report.kind == RedevelopmentReportKind.NEARBY_CONTEXT), None)
    photo_report = next(
        (report for report in reports if report.kind == RedevelopmentReportKind.PHOTO_INTERPRETATION),
        None,
    )

    condition_parts = []
    if record.building_age_years:
        condition_parts.append(f"건축물 노후도 {record.building_age_years}년")
    if record.vacancy_years:
        condition_parts.append(f"공실 {record.vacancy_years}년")
    if record.structure_grade and record.structure_grade != "미확인":
        condition_parts.append(f"구조 등급 {record.structure_grade}")
    condition_sentence = (
        f"대상지는 {', '.join(condition_parts)} 정보로 정비 필요성을 검토했습니다."
        if condition_parts
        else "대상지는 요청 주소, 건축물대장, 현장 사진, 주변 공공데이터를 기준으로 활용 가능성을 검토했습니다."
    )
    use_sentence = f"사진 해석과 주변 공공데이터를 함께 보면 {_explanation_basis(recommended_use, nearby_report, photo_report)}"
    follow_up_sentence = "최종 실행 전에는 소유자 동의, 상세 공부 확인, 예산과 주민 수요를 추가로 확인해야 합니다."
    return "\n".join([condition_sentence, use_sentence, follow_up_sentence])


def _explanation_basis(
    recommended_use: str,
    nearby_report: RedevelopmentSubAgentReport | None,
    photo_report: RedevelopmentSubAgentReport | None,
) -> str:
    nearby_has_matches = bool(nearby_report and nearby_report.confidence >= 0.5)
    photo_has_signal = bool(
        photo_report
        and photo_report.confidence >= 0.4
        and (photo_report.context_signals or photo_report.opportunity_signals)
    )

    if any(keyword in recommended_use for keyword in ["쉼터", "정원", "경관", "녹지"]):
        return "여유 부지, 경관, 녹지 활용 가능성이 있어 주민 휴식형 공간으로 전환하는 방향이 적합합니다."
    if any(keyword in recommended_use for keyword in ["복지", "돌봄", "생활복지"]):
        return "생활권 복지 수요와 공공서비스 연계 가능성이 있어 돌봄 또는 생활복지 거점으로 검토할 수 있습니다."
    if any(keyword in recommended_use for keyword in ["상권", "관광", "체류"]):
        return "주변 상권 및 체류 자원과 연결될 여지가 있어 관광 안내 또는 로컬 상권 연계 공간으로 활용할 수 있습니다."
    if any(keyword in recommended_use for keyword in ["창업", "작업장", "일자리"]):
        return "제조, 일자리, 작업 수요와 연결될 가능성이 있어 소규모 창업 또는 작업장 거점으로 검토할 수 있습니다."
    if "주차장" in recommended_use or "골목" in recommended_use:
        return "도로 접근성이 비교적 좋아 소규모 주차장이나 골목 환경개선 부지로 활용하기 쉽습니다."
    if nearby_has_matches or photo_has_signal:
        return "현장 사진과 주변 입지 신호를 바탕으로 공공성이 있는 저강도 활용부터 검토하는 것이 적합합니다."
    return "현재 확보된 정보만으로는 고강도 개발보다 임시 정비와 경관 개선을 우선 검토하는 것이 적합합니다."


def recommend_redevelopment_use(state: RedevelopmentState) -> RedevelopmentState:
    trace_id = state.get("trace_id", "-")
    logger.info(
        "redevelopment.recommend.start trace_id=%s house_id=%s report_kinds=%s",
        trace_id,
        state.get("house_id"),
        [
            report.kind.value
            for report in (
                state.get("building_ledger_report"),
                state.get("photo_report"),
                state.get("nearby_report"),
            )
            if report is not None
        ],
    )
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
        f"주소: {record.address}",
        f"데이터 출처: {record.metadata.get('source', 'request')}",
    ]
    if record.building_age_years:
        rationale.append(f"건축물 노후도 {record.building_age_years}년")
    if record.vacancy_years:
        rationale.append(f"공실 기간 {record.vacancy_years}년")
    if record.structure_grade and record.structure_grade != "미확인":
        rationale.append(f"구조 등급 {record.structure_grade}")
    if record.complaints_last_year:
        rationale.append(f"최근 1년 민원 {record.complaints_last_year}건")

    for report in reports:
        rationale.append(f"{report.kind.value}: {report.summary}")
        rationale.extend(report.context_signals[:3])
        rationale.extend(report.opportunity_signals[:3])

    recommended_use = _recommend_use(record, reports)
    recommendation = RedevelopmentRecommendation(
        house_id=record.house_id,
        recommended_use=recommended_use,
        explanation=_build_recommendation_explanation(recommended_use, record, reports),
        rationale=rationale,
        required_data=[
            "소유자 동의 여부",
            "토지/건축물대장 상세",
            "정비 예산",
            "인근 주민 수요",
        ],
    )
    logger.info(
        "redevelopment.recommend.complete trace_id=%s house_id=%s recommended_use=%r rationale_count=%s",
        trace_id,
        recommendation.house_id,
        recommendation.recommended_use,
        len(recommendation.rationale),
    )
    return {**state, "recommendation": recommendation}


def build_redevelopment_recommendation_graph():
    graph = StateGraph(RedevelopmentState)
    graph.add_node("fetch_public_data", fetch_public_data)
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
