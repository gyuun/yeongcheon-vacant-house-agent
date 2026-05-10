from __future__ import annotations

import os

from langchain_google_genai import ChatGoogleGenerativeAI


DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


def build_gemini_chat_model(model: str = DEFAULT_GEMINI_MODEL) -> ChatGoogleGenerativeAI | None:
    """Build a Gemini chat model when credentials are configured.

    Returning None keeps local demos and tests deterministic while preserving the
    production integration point.
    """

    if not os.getenv("GOOGLE_API_KEY"):
        return None

    return ChatGoogleGenerativeAI(model=model, temperature=0)
