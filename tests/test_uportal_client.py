from __future__ import annotations

from bs4 import BeautifulSoup

from perry_assistant.integrations.uportal_client import UportalClient


def test_parse_games_reads_full_table_with_date_sections(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <table>
        <tr><th>Liga</th><th>Nr.</th><th>Heim</th><th></th><th>Gast</th><th>Datum</th><th>Zeit</th><th>Halle</th><th>ursp. SR</th><th>UST</th><th>Entf.</th></tr>
        <tr style="font-weight:bold;"><td colspan="11">Fre, 27.02.2026</td></tr>
        <tr>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13465">K-BeLU18MA</a></td>
          <td>24</td><td>BBV Köln-Nordwest 2</td><td>-</td><td>TSV Seelscheid 1920 e. V.</td>
          <td>Fre, 27.02.2026</td><td>19:30</td><td>109N581</td><td>N.B.(2)</td><td>K04</td><td>41 km</td>
        </tr>
        <tr style="font-weight:bold;"><td colspan="11">Sam, 28.02.2026</td></tr>
        <tr>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">D-KLH1</a></td>
          <td>80</td><td>SV Alte Freunde 95 Düsseldorf 3</td><td>-</td><td>Frei</td>
          <td>Sam, 28.02.2026</td><td>18:00</td><td>201A100</td><td>N.B.(1)</td><td>K06</td><td>13 km</td>
        </tr>
        <tr>
          <td>D-KLH1</td><td>80</td><td>SV Alte Freunde 95 Düsseldorf 3</td><td>-</td><td>Frei</td>
          <td colspan="3">Einladung</td><td>N.B.(1)</td><td>K06</td><td>13 km</td>
        </tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    rows = client._parse_games(soup)  # noqa: SLF001
    assert len(rows) == 2
    assert rows[0].detail_id == "13465"
    assert rows[0].date == "27.02.2026"
    assert rows[0].time == "19:30"
    assert rows[1].detail_id == "13637"
    assert rows[1].date == "28.02.2026"
    assert rows[1].distance_km == 13.0


def test_pagination_links_include_pages_not_detail_rows(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&start=50">Next</a>
      <a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&seite=3">Page 3</a>
      <a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=14366">Detail</a>
      <a href="https://example.com/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&start=100">External</a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    links = client._pagination_links(  # noqa: SLF001
        soup,
        base_url="https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen",
        root_url="https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen",
    )
    assert "https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&start=50" in links
    assert "https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&seite=3" in links
    assert all("id=14366" not in link for link in links)


def test_extract_offene_umb_url_from_page(app_config):
    client = UportalClient(app_config)
    html = """
    <ul>
      <li><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180">offene Umb.</a></li>
    </ul>
    """
    found = client._extract_offene_umb_url(html, "https://www.uportal-wbv.de/index.php")  # noqa: SLF001
    assert found == "https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180"


def test_extract_offene_umb_url_prefers_list_page_over_detail_links(app_config):
    client = UportalClient(app_config)
    html = """
    <div>
      <a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=13637">detail</a>
      <a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180">offene Umb.</a>
    </div>
    """
    found = client._extract_offene_umb_url(html, "https://www.uportal-wbv.de/index.php")  # noqa: SLF001
    assert found == "https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180"


def test_parse_games_uses_assignments_table_not_first_table(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <table><tr><td>not assignments</td></tr></table>
      <table>
        <tr><th>Liga</th><th>Nr.</th><th>Heim</th><th></th><th>Gast</th><th>Datum</th><th>Zeit</th><th>Halle</th><th>ursp. SR</th><th>UST</th><th>Entf.</th></tr>
        <tr><td colspan="11">Fre, 27.02.2026</td></tr>
        <tr>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13465">RE-KLH</a></td>
          <td>24</td><td>A</td><td>-</td><td>B</td><td>Fre, 27.02.2026</td><td>19:30</td><td>109N581</td><td>N.B.(2)</td><td>K04</td><td>41 km</td>
        </tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = client._parse_games(soup)  # noqa: SLF001
    assert len(rows) == 1


def test_parse_games_supports_three_row_compact_event_blocks(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <table>
        <tr><th>Liga</th><th>Nr.</th><th>Datum</th><th>Halle</th></tr>
        <tr style="font-weight:bold;"><td colspan="4">Son, 01.03.2026</td></tr>
        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">JLL4U16M</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">93</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">Son, 01.03.2026  12:00</a></td>
          <td align="center"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">407A511</a></td>
        </tr>
        <tr class="row_background_2">
          <td colspan="4"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">FC Schalke 04 - TuS Hiltrup 1930 e.V.</a></td>
        </tr>
        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">UST11</a></td>
          <td colspan="2"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">ursp.: N.B.(1)</a></td>
          <td>55 km</td>
        </tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = client._parse_games(soup)  # noqa: SLF001

    assert len(rows) == 1
    game = rows[0]
    assert game.detail_id == "14062"
    assert game.liga == "JLL4U16M"
    assert game.number == "93"
    assert game.date == "01.03.2026"
    assert game.time == "12:00"
    assert game.hall == "407A511"
    assert game.home_team == "FC Schalke 04"
    assert game.away_team == "TuS Hiltrup 1930 e.V."
    assert game.ust == "UST11"
    assert game.original_referee == "N.B.(1)"
    assert game.distance_km == 55.0


def test_parse_games_supports_multiple_compact_blocks_with_same_detail_id(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <table>
        <tr><th>Liga</th><th>Nr.</th><th>Datum</th><th>Halle</th></tr>
        <tr style="font-weight:bold;"><td colspan="4">Son, 01.03.2026</td></tr>

        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">JLL4U16M</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">93</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">Son, 01.03.2026  12:00</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">407A511</a></td>
        </tr>
        <tr class="row_background_2">
          <td colspan="4"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">FC Schalke 04 - TuS Hiltrup 1930 e.V.</a></td>
        </tr>
        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">UST11</a></td>
          <td colspan="2"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">ursp.: N.B.(1)</a></td>
          <td>55 km</td>
        </tr>

        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">JOL3U18M</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">93</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">Son, 01.03.2026  14:00</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">407A511</a></td>
        </tr>
        <tr class="row_background_2">
          <td colspan="4"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">FC Schalke 04 - ATV Haltern</a></td>
        </tr>
        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">UST11</a></td>
          <td colspan="2"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&zugang=sr60180&id=14062">ursp.: 37223</a></td>
          <td>55 km</td>
        </tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = client._parse_games(soup)  # noqa: SLF001

    assert len(rows) == 2
    assert rows[0].detail_id == "14062"
    assert rows[0].liga == "JLL4U16M"
    assert rows[0].time == "12:00"
    assert rows[0].home_team == "FC Schalke 04"
    assert rows[0].away_team == "TuS Hiltrup 1930 e.V."
    assert rows[0].original_referee == "N.B.(1)"

    assert rows[1].detail_id == "14062"
    assert rows[1].liga == "JOL3U18M"
    assert rows[1].time == "14:00"
    assert rows[1].home_team == "FC Schalke 04"
    assert rows[1].away_team == "ATV Haltern"
    assert rows[1].original_referee == "37223"


def test_parse_games_supports_datum_zeit_header_and_skips_einladung_rows(app_config):
    client = UportalClient(app_config)
    html = """
    <div id="col3_content">
      <table>
        <tr><th>Liga</th><th>Nr.</th><th>Datum/Zeit</th><th>Halle</th></tr>
        <tr><td colspan="4">Son, 01.03.2026</td></tr>

        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">D-KLH1</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">80</a></td>
          <td colspan="2" align="center"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">Einladung</a></td>
        </tr>
        <tr class="row_background_2">
          <td colspan="4"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">SV Alte Freunde 95 Dusseldorf 3 - Frei</a></td>
        </tr>
        <tr class="row_background_2">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">K06</a></td>
          <td colspan="2"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13637">ursp.: N.B.(1)</a></td>
          <td>13 km</td>
        </tr>

        <tr class="row_background_1">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">RE-BeLU12WER</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">28</a></td>
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">Son, 01.03.2026  10:00</a></td>
          <td align="center"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">105N311</a></td>
        </tr>
        <tr class="row_background_1">
          <td colspan="4"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">Pulheimer SC - DJK Koln-Nord</a></td>
        </tr>
        <tr class="row_background_1">
          <td><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">K02</a></td>
          <td colspan="2"><a href="index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=13829">ursp.: N.B.(1)</a></td>
          <td>34 km</td>
        </tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = client._parse_games(soup)  # noqa: SLF001

    assert len(rows) == 1
    game = rows[0]
    assert game.detail_id == "13829"
    assert game.liga == "RE-BeLU12WER"
    assert game.number == "28"
    assert game.date == "01.03.2026"
    assert game.time == "10:00"
    assert game.home_team == "Pulheimer SC"
    assert game.away_team == "DJK Koln-Nord"
    assert game.hall == "105N311"
    assert game.original_referee == "N.B.(1)"
    assert game.ust == "K02"
    assert game.distance_km == 34.0
