from __future__ import annotations

import json
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from src.models import (
    PatrolImageAssessment,
    PatrolImageInput,
    RiskLevel,
)
from src.services.gemini import build_gemini_chat_model


class PatrolImageState(TypedDict, total=False):
    request: PatrolImageInput
    assessment: PatrolImageAssessment
    error: str


def _build_prompt(request: PatrolImageInput) -> list[dict[str, object]]:
    text = (
        "You are a vacant-house patrol inspection agent for Yeongcheon city. "
        "Compare the baseline image and current patrol image. Identify visible "
        "changes such as break-in traces, fire/smoke damage, illegal dumping, "
        "structural collapse, water leakage, vandalism, or safety hazards. "
        "Return compact JSON with keys: is_anomaly, risk_level, summary, "
        "evidence, recommended_actions."
    )
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{request.baseline_image_base64}",
        },
        {
            "type": "image_url",
            "image_url": f"data:image/jpeg;base64,{request.captured_image_base64}",
        },
    ]


def _parse_model_output(request: PatrolImageInput, raw: str) -> PatrolImageAssessment:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return PatrolImageAssessment(
            house_id=request.house_id,
            spot_id=request.spot_id,
            is_anomaly=True,
            risk_level=RiskLevel.MEDIUM,
            summary=raw.strip() or "모델 응답을 JSON으로 파싱하지 못했습니다.",
            evidence=["unstructured_model_output"],
            recommended_actions=["담당자 육안 검토"],
            raw_model_output=raw,
        )

    try:
        risk_level = RiskLevel(parsed.get("risk_level", RiskLevel.MEDIUM.value))
    except ValueError:
        risk_level = RiskLevel.MEDIUM

    evidence = parsed.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]

    recommended_actions = parsed.get("recommended_actions", [])
    if isinstance(recommended_actions, str):
        recommended_actions = [recommended_actions]

    return PatrolImageAssessment(
        house_id=request.house_id,
        spot_id=request.spot_id,
        is_anomaly=bool(parsed.get("is_anomaly", False)),
        risk_level=risk_level,
        summary=str(parsed.get("summary", "")),
        evidence=list(evidence),
        recommended_actions=list(recommended_actions),
        raw_model_output=raw,
    )


def _mock_assessment(request: PatrolImageInput) -> PatrolImageAssessment:
    """Local deterministic behavior for skeleton runs without Gemini credentials."""

    image_delta_hint = abs(len(request.captured_image_base64) - len(request.baseline_image_base64))
    is_anomaly = image_delta_hint > 32
    return PatrolImageAssessment(
        house_id=request.house_id,
        spot_id=request.spot_id,
        is_anomaly=is_anomaly,
        risk_level=RiskLevel.MEDIUM if is_anomaly else RiskLevel.LOW,
        summary=(
            "목업 판정: 입력 이미지 크기 차이가 커 이상 가능성이 있습니다."
            if is_anomaly
            else "목업 판정: 기준 이미지와 큰 차이를 발견하지 못했습니다."
        ),
        evidence=[f"base64_length_delta={image_delta_hint}"],
        recommended_actions=["현장 재확인", "담당자 알림"] if is_anomaly else ["정기 순찰 유지"],
    )


def infer_image_anomaly(state: PatrolImageState) -> PatrolImageState:
    request = state["request"]
    model = build_gemini_chat_model()
    if model is None:
        return {"request": request, "assessment": _mock_assessment(request)}

    message = HumanMessage(content=_build_prompt(request))
    response = model.invoke([message])
    raw = str(response.content)
    return {"request": request, "assessment": _parse_model_output(request, raw)}


def build_patrol_image_graph():
    graph = StateGraph(PatrolImageState)
    graph.add_node("infer_image_anomaly", infer_image_anomaly)
    graph.set_entry_point("infer_image_anomaly")
    graph.add_edge("infer_image_anomaly", END)
    return graph.compile()
