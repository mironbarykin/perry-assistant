import datetime as dt

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.integrations.calendar_client import _location_link_parts, utc_day_bounds


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


def test_utc_day_bounds_uses_local_berlin_day():
    target = dt.datetime(2026, 3, 1, 10, 0, tzinfo=BERLIN_TZ)
    start, end = utc_day_bounds(target)
    assert start.startswith("2026-02-28T23:00:00")
    assert end.startswith("2026-03-01T22:59:59")
