import requests
from bs4 import BeautifulSoup

from helpers import load_json, save_json
from consts import GYM_CACHE_FILE

def get_gym_address(gym_id):
    """Efficiently get gym address using local cache, scraping only if needed."""

    cache = load_json(GYM_CACHE_FILE)

    if gym_id in cache:
        return cache[gym_id]

    url = "https://www.basketball-bund.net/halleSearch.do?reqCode=list"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en,de;q=0.9,ru;q=0.8",
        "cache-control": "max-age=0",
        "content-type": "application/x-www-form-urlencoded",
        "priority": "u=0, i",
        "sec-ch-ua": "\"Chromium\";v=\"142\", \"Google Chrome\";v=\"142\", \"Not_A Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "referer": "https://www.basketball-bund.net/halleSearch.do?reqCode=onVerband"
    }
    data = (
        "defaultview=1"
        "&verbandBezirkKreisVereinSelection.verband_id=0"
        "&verbandBezirkKreisVereinSelection.verein="
        "&spielfeldklassifikation_id=-1"
        "&bezeichnung="
        f"&kurzbezeichnung={gym_id}"
        "&postleitzahl="
        "&ort="
    )

    session = requests.Session()
    response = session.post(url, headers=headers, data=data)
    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    tables = soup.find_all("table", {"class": "sportView"})
    found = None
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) >= 5:
                code = cols[1].get_text(strip=True)
                if code.replace(" ", "") == gym_id.replace(" ", ""):
                    street = cols[2].get_text(strip=True)
                    plz = cols[3].get_text(strip=True)
                    city = cols[4].get_text(strip=True)
                    found = f"{street}, {plz} {city}"
                    break
        if found:
            break

    if found:
        cache[gym_id] = found
        save_json(GYM_CACHE_FILE, cache)
    
    return found


