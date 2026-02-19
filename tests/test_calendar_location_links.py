from perry_assistant.integrations.calendar_client import _location_link_parts


def test_location_link_parts_rso():
    label, query = _location_link_parts("Urban high school Osterath, G\u00f6rresstra\u00dfe 6")
    assert label == "RSO"
    assert "Goerresstrasse 6" in query


def test_location_link_parts_smg():
    label, query = _location_link_parts("St\u00e4dtisches Meerbusch-Gymnasium, M\u00f6nkesweg 58")
    assert label == "SMG"
    assert "Moenkesweg 58" in query


def test_location_link_parts_generic():
    label, query = _location_link_parts("Some Random Hall")
    assert label == "Some Random Hall"
    assert query == "Some Random Hall"

