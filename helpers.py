import json
from typing import Any
import os
import re

def load_json(file: str, default: Any) -> Any:
    """Load JSON from file, return default if file does not exist."""
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return default

def save_json(file: str, data: Any) -> None:
    """Save data as JSON to file."""
    with open(file, "w") as f:
        json.dump(data, f)

def clean_text(text: str) -> str:
    """Remove emojis and special symbols for easier matching."""
    return re.sub(r"[^\w\s]", "", text).lower() if text else ""
