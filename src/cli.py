from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from src.agents.patrol_image import build_patrol_image_graph
from src.agents.priority_recommendation import (
    build_priority_recommendation_graph,
)
from src.models import PatrolImageInput


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def run_patrol_demo() -> dict[str, Any]:
    graph = build_patrol_image_graph()
    result = graph.invoke(
        {
            "request": PatrolImageInput(
                house_id="YC-001",
                spot_id="front-gate",
                baseline_image_base64="baseline-image-placeholder",
                captured_image_base64="captured-image-placeholder-with-visible-difference",
            )
        }
    )
    return result


def run_priority_demo(house_id: str) -> dict[str, Any]:
    graph = build_priority_recommendation_graph()
    return graph.invoke({"house_id": house_id})


def main() -> None:
    parser = argparse.ArgumentParser(description="Yeongcheon vacant house agent demos")
    parser.add_argument(
        "agent",
        choices=["patrol", "priority"],
        help="Agent demo to run",
    )
    parser.add_argument("--house-id", default="YC-001", help="Vacant house identifier")
    args = parser.parse_args()

    result = run_patrol_demo() if args.agent == "patrol" else run_priority_demo(args.house_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
