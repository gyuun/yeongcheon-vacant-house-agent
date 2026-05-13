from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

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


class PatrolImageDecision(BaseModel):
    """Model-owned fields for one patrol image assessment."""

    is_anomaly: bool = Field(description="Whether the current patrol image shows abnormal changes.")
    risk_level: RiskLevel = Field(description="Risk severity of the detected condition.")
    summary: str = Field(description="Human-readable summary of the image assessment.", min_length=1)
    evidence: list[str] = Field(
        default_factory=list,
        description="Visible clues or model-observed differences supporting the assessment.",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up actions for city staff or patrol operations.",
    )


def _build_prompt(request: PatrolImageInput) -> list[dict[str, object]]:
    text = (
        "You are a vacant-house patrol inspection agent for Yeongcheon city. "
        "Compare the baseline image and current patrol image. Identify visible "
        "changes such as break-in traces, fire/smoke damage, illegal dumping, "
        "structural collapse, water leakage, vandalism, or safety hazards. "
        "Return the requested structured assessment only."
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


def _build_assessment(
    request: PatrolImageInput,
    decision: PatrolImageDecision,
    raw_model_output: str | None = None,
) -> PatrolImageAssessment:
    return PatrolImageAssessment(
        house_id=request.house_id,
        spot_id=request.spot_id,
        is_anomaly=decision.is_anomaly,
        risk_level=decision.risk_level,
        summary=decision.summary,
        evidence=decision.evidence,
        recommended_actions=decision.recommended_actions,
        raw_model_output=raw_model_output,
    )


def _fallback_assessment(request: PatrolImageInput, error: Exception) -> PatrolImageAssessment:
    return PatrolImageAssessment(
        house_id=request.house_id,
        spot_id=request.spot_id,
        is_anomaly=True,
        risk_level=RiskLevel.MEDIUM,
        summary="모델 응답을 구조화된 순찰 이미지 판정으로 변환하지 못했습니다.",
        evidence=["structured_output_failure"],
        recommended_actions=["담당자 육안 검토"],
        raw_model_output=str(error),
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
    structured_model = model.with_structured_output(PatrolImageDecision)
    try:
        decision = structured_model.invoke([message])
        if not isinstance(decision, PatrolImageDecision):
            decision = PatrolImageDecision.model_validate(decision)
    except (ValidationError, ValueError, TypeError) as exc:
        return {"request": request, "assessment": _fallback_assessment(request, exc)}

    return {"request": request, "assessment": _build_assessment(request, decision)}


def build_patrol_image_graph():
    graph = StateGraph(PatrolImageState)
    graph.add_node("infer_image_anomaly", infer_image_anomaly)
    graph.set_entry_point("infer_image_anomaly")
    graph.add_edge("infer_image_anomaly", END)
    return graph.compile()
