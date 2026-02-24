from perry_assistant.bot.handlers.absences import _parse_excuse_groups


def test_parse_excuse_groups_success():
    groups = _parse_excuse_groups(["02-24", "M,PH,CH", "02-25", "M,PH,R"])
    assert groups == [("02-24", ["M", "PH", "CH"]), ("02-25", ["M", "PH", "R"])]


def test_parse_excuse_groups_rejects_invalid_shape():
    assert _parse_excuse_groups(["02-24"]) is None
    assert _parse_excuse_groups(["02-24", "M,PH", "02-25"]) is None
    assert _parse_excuse_groups(["2026-02-24", "M"]) is None
