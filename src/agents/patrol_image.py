from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from src.agents.prompts import load_prompt
from src.models import (
    PatrolImageAssessment,
    PatrolImageInput,
    RiskLevel,
)
from src.services.gemini import build_gemini_chat_model


logger = logging.getLogger(__name__)


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


def image_to_base64(image_path: str | Path) -> str:
    """Return an image file as a plain base64 string."""

    return base64.b64encode(Path(image_path).read_bytes()).decode("ascii")


def _build_prompt(request: PatrolImageInput) -> list[dict[str, object]]:
    return [
        {"type": "text", "text": load_prompt("patrol_prompt.md")},
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
    logger.info(
        "patrol.infer_image_anomaly.start house_id=%s spot_id=%s baseline_base64_length=%s captured_base64_length=%s",
        request.house_id,
        request.spot_id,
        len(request.baseline_image_base64),
        len(request.captured_image_base64),
    )
    model = build_gemini_chat_model()
    if model is None:
        logger.warning(
            "patrol.infer_image_anomaly.fallback house_id=%s spot_id=%s reason=no_gemini_model",
            request.house_id,
            request.spot_id,
        )
        assessment = _mock_assessment(request)
        logger.info(
            "patrol.infer_image_anomaly.complete house_id=%s spot_id=%s is_anomaly=%s risk_level=%s source=mock",
            assessment.house_id,
            assessment.spot_id,
            assessment.is_anomaly,
            assessment.risk_level.value,
        )
        return {"request": request, "assessment": assessment}

    message = HumanMessage(content=_build_prompt(request))
    structured_model = model.with_structured_output(PatrolImageDecision)
    try:
        logger.info("patrol.infer_image_anomaly.invoke_model house_id=%s spot_id=%s", request.house_id, request.spot_id)
        decision = structured_model.invoke([message])
        if not isinstance(decision, PatrolImageDecision):
            decision = PatrolImageDecision.model_validate(decision)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.exception("patrol.infer_image_anomaly.structured_output_failed house_id=%s spot_id=%s", request.house_id, request.spot_id)
        assessment = _fallback_assessment(request, exc)
        return {"request": request, "assessment": assessment}

    assessment = _build_assessment(request, decision)
    logger.info(
        "patrol.infer_image_anomaly.complete house_id=%s spot_id=%s is_anomaly=%s risk_level=%s evidence_count=%s source=gemini",
        assessment.house_id,
        assessment.spot_id,
        assessment.is_anomaly,
        assessment.risk_level.value,
        len(assessment.evidence),
    )
    return {"request": request, "assessment": assessment}


def build_patrol_image_graph():
    graph = StateGraph(PatrolImageState)
    graph.add_node("infer_image_anomaly", infer_image_anomaly)
    graph.set_entry_point("infer_image_anomaly")
    graph.add_edge("infer_image_anomaly", END)
    return graph.compile()
