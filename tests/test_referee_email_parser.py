from perry_assistant.services.referee_service import detect_email_type, parse_referee_email


def test_detect_email_type_ansetzung():
    email_type = detect_email_type("SR-Ansetzung", "Body")
    assert email_type == "ANSETZUNG"


def test_parse_single_assignment():
    content = {
        "subject": "SR-Ansetzung",
        "content": (
            "Liga: U16\n"
            "Spielnummer: 12345\n"
            "Spielbeginn: 17.02.2026 18:30\n"
            "Heimmannschaft: Team A\n"
            "Gastmannschaft: Team B\n"
            "Spielhalle: Hall Name (123A456)\n"
            "Street 1\n"
            "SR1: Ref One\n"
            "SR2: Ref Two\n"
        ),
    }
    assignments = parse_referee_email(content)
    assert assignments is not None
    assert len(assignments) == 1
    assignment = assignments[0]
    assert assignment.type == "ANSETZUNG"
    assert assignment.date == "17.02.2026"
    assert assignment.time == "18:30"
    assert assignment.teams == "Team A - Team B"
    assert assignment.hall_code == "123A456"
    assert assignment.referees == ["Ref One", "Ref Two"]


def test_parse_multiple_assignments():
    content = {
        "subject": "SR-Ansetzung",
        "content": (
            "1. Ansetzung:\n"
            "Spielbeginn: 17.02.2026 18:30\n"
            "Heimmannschaft: Team A\n"
            "Gastmannschaft: Team B\n"
            "2. Ansetzung:\n"
            "Spielbeginn: 18.02.2026 20:00\n"
            "Heimmannschaft: Team C\n"
            "Gastmannschaft: Team D\n"
        ),
    }
    assignments = parse_referee_email(content)
    assert assignments is not None
    assert len(assignments) == 2
    assert assignments[0].teams == "Team A - Team B"
    assert assignments[1].teams == "Team C - Team D"


def test_parse_verlegung_uses_new_datetime():
    content = {
        "subject": "Spielverlegung",
        "content": (
            "Von bisher:\n"
            "Datum, Uhrzeit: 17.02.2026 18:30\n"
            "Spielhalle: Old Hall (111A111)\n"
            "Old Street\n"
            "auf neu:\n"
            "Datum, Uhrzeit: 19.02.2026 20:30\n"
            "Spielhalle: New Hall (222B222)\n"
            "New Street\n"
            "Heimmannschaft: Team A\n"
            "Gastmannschaft: Team B\n"
        ),
    }
    assignments = parse_referee_email(content)
    assert assignments is not None
    assignment = assignments[0]
    assert assignment.type == "VERLEGUNG"
    assert assignment.old_date == "17.02.2026"
    assert assignment.date == "19.02.2026"
    assert assignment.hall_code == "222B222"

