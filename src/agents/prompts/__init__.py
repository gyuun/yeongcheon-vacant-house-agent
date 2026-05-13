from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(file_name: str) -> str:
    prompt = (_PROMPT_DIR / file_name).read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt file is empty: {file_name}")
    return prompt
