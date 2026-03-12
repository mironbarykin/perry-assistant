from __future__ import annotations

import sys
import types

sys.modules.setdefault("webuntis", types.SimpleNamespace())
sys.modules.setdefault(
    "webuntis.errors",
    types.SimpleNamespace(BadCredentialsError=Exception),
)

from perry_assistant.integrations.untis_client import _derive_status_code


def test_status_red_self_study():
    assert _derive_status_code(None, "eigenverantwortliches Arbeiten") == "cancelled"
    assert _derive_status_code(None, "EIGENVERANTWORTLICHES ARBEITEN") == "cancelled"


def test_status_yellow_other_subst_text():
    assert _derive_status_code(None, "Vertretung") == "irregular"


def test_status_green_empty():
    assert _derive_status_code(None, "") is None
