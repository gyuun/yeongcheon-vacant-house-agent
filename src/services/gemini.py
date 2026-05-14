from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI


DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_RETRIES = 0
GEMINI_API_KEY_ENV_NAMES = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
logger = logging.getLogger(__name__)


def _load_env_file(env_path: Path | str = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and not os.getenv(key):
                os.environ[key] = value


def _gemini_api_key() -> str | None:
    _load_env_file()
    for env_name in GEMINI_API_KEY_ENV_NAMES:
        api_key = os.getenv(env_name)
        if api_key:
            logger.info("gemini.api_key.loaded env_name=%s", env_name)
            return api_key
    return None


def build_gemini_chat_model(model: str = DEFAULT_GEMINI_MODEL) -> ChatGoogleGenerativeAI | None:
    """Build a Gemini chat model when credentials are configured.

    Returning None keeps local demos and tests deterministic while preserving the
    production integration point.
    """

    api_key = _gemini_api_key()
    if not api_key:
        logger.warning("gemini.model.unavailable reason=no_api_key env_names=%s", ",".join(GEMINI_API_KEY_ENV_NAMES))
        return None

    logger.info(
        "gemini.model.build model=%s temperature=1.0 top_p=0.95 top_k=64 include_thoughts=True thinking_level=high retries=%s",
        model,
        DEFAULT_GEMINI_RETRIES,
    )
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=1.0,
        top_p=0.95,
        top_k=64,
        retries=DEFAULT_GEMINI_RETRIES,
        include_thoughts=True,
        thinking_level="high",
        api_key=api_key,
    )
