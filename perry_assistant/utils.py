from __future__ import annotations

import re


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^\w\s]", "", text).lower().strip()

