from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.models import (
    MaintenancePriority,
    PriorityRecommendation,
    VacantHouseRecord,
)
from src.services.public_data import MockPublicDataClient, PublicDataClient


class PriorityState(TypedDict, total=False):
    house_id: str
    record: VacantHouseRecord
    recommendation: PriorityRecommendation


def fetch_public_data(
    state: PriorityState,
    public_data_client: PublicDataClient | None = None,
) -> PriorityState:
    client = public_data_client or MockPublicDataClient()
    record = client.get_vacant_house(state["house_id"])
    return {"house_id": state["house_id"], "record": record}


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
    priority = _priority(score)
    recommendation = PriorityRecommendation(
        house_id=record.house_id,
        priority=priority,
        score=score,
        recommended_use=_recommend_use(record, priority),
        rationale=[
            f"건축물 노후도 {record.building_age_years}년",
            f"공실 기간 {record.vacancy_years}년",
            f"구조 등급 {record.structure_grade}",
            f"최근 1년 민원 {record.complaints_last_year}건",
        ],
        required_data=[
            "소유자 동의 여부",
            "토지/건축물대장 상세",
            "정비 예산",
            "인근 주민 수요",
        ],
    )
    return {**state, "recommendation": recommendation}


def build_priority_recommendation_graph(public_data_client: PublicDataClient | None = None):
    graph = StateGraph(PriorityState)
    graph.add_node("fetch_public_data", lambda state: fetch_public_data(state, public_data_client))
    graph.add_node("recommend_priority", recommend_priority)
    graph.set_entry_point("fetch_public_data")
    graph.add_edge("fetch_public_data", "recommend_priority")
    graph.add_edge("recommend_priority", END)
    return graph.compile()
