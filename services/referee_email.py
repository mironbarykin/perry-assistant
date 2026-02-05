import re
import base64
from typing import Dict, List, Optional

from consts import BASKETBALL_EMAILS


MOJIBAKE_MAP = {
    "Ã¤": "ä",
    "Ã¶": "ö",
    "Ã¼": "ü",
    "Ã„": "Ä",
    "Ã–": "Ö",
    "Ãœ": "Ü",
    "ÃŸ": "ß",
}


def _fix_mojibake(text: str) -> str:
    if not text:
        return ""
    for bad, good in MOJIBAKE_MAP.items():
        text = text.replace(bad, good)
    return text


def get_basketball_emails(service, max_results=10):
    """Get basketball-related emails from Gmail."""
    query = " OR ".join(f"from:{email}" for email in BASKETBALL_EMAILS)
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return results.get("messages", [])


def get_email_content(service, msg_id):
    """Get full email content."""
    message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = message.get("payload", {})
    headers = {header["name"]: header["value"] for header in payload.get("headers", [])}

    if "parts" in payload:
        parts = payload["parts"]
        data = parts[0]["body"].get("data", "")
    else:
        data = payload.get("body", {}).get("data", "")

    if data:
        text = base64.urlsafe_b64decode(data).decode(errors="ignore")
    else:
        text = ""

    return {
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "date": headers.get("Date", ""),
        "content": text,
    }


def _extract_basic_fields(body: str) -> Dict[str, Optional[str]]:
    info: Dict[str, Optional[str]] = {
        "date": None,
        "time": None,
        "liga": None,
        "spielnummer": None,
        "teams": None,
        "hall_code": None,
        "location": None,
        "address": None,
        "referees": None,
    }

    liga_match = re.search(r"Liga:\s*([^\n]+)", body)
    if liga_match:
        info["liga"] = liga_match.group(1).strip()

    spielnr_match = re.search(r"Spielnummer:\s*([0-9]+)", body)
    if spielnr_match:
        info["spielnummer"] = spielnr_match.group(1).strip()

    spielbeginn_match = re.search(
        r"Spielbeginn:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
    )
    if spielbeginn_match:
        info["date"] = spielbeginn_match.group(1)
        info["time"] = spielbeginn_match.group(2)

    datetime_match = re.search(
        r"Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
    )
    if datetime_match and not info["date"]:
        info["date"] = datetime_match.group(1)
        info["time"] = datetime_match.group(2)

    home_match = re.search(r"Heimmannschaft:\s*([^\n]+)", body)
    away_match = re.search(r"Gastmannschaft:\s*([^\n]+)", body)
    if home_match and away_match:
        info["teams"] = f"{home_match.group(1).strip()} - {away_match.group(1).strip()}"

    hall_match = re.search(r"Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)", body)
    if hall_match:
        info["location"] = hall_match.group(1).strip()
        info["hall_code"] = hall_match.group(2).strip()
        address_match = re.search(r"Spielhalle:.*\)\s*\n\s*([^\n]+)", body)
        if address_match:
            info["address"] = address_match.group(1).strip()

    refs = []
    for label in ["SR1", "SR2", "Schiedsrichter 1", "Schiedsrichter 2"]:
        match = re.search(rf"{label}:\s*([^\n]+)", body)
        if not match:
            match = re.search(rf"{label}\s+([^\n]+)", body)
        if match:
            refs.append(match.group(1).strip())
    if refs:
        info["referees"] = refs

    return info


def _extract_old_new_fields(body: str) -> Dict[str, Optional[str]]:
    info: Dict[str, Optional[str]] = {
        "old_date": None,
        "old_time": None,
        "old_location": None,
        "old_hall_code": None,
        "old_address": None,
        "new_date": None,
        "new_time": None,
        "new_location": None,
        "new_hall_code": None,
        "new_address": None,
    }

    old_dt = re.search(
        r"Von bisher:.*?Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
        re.S,
    )
    if old_dt:
        info["old_date"] = old_dt.group(1)
        info["old_time"] = old_dt.group(2)
        old_hall = re.search(r"Von bisher:.*?Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)", body, re.S)
        if old_hall:
            info["old_location"] = old_hall.group(1).strip()
            info["old_hall_code"] = old_hall.group(2).strip()
            old_addr = re.search(r"Von bisher:.*?Spielhalle:.*\)\s*\n\s*([^\n]+)", body, re.S)
            if old_addr:
                info["old_address"] = old_addr.group(1).strip()

    new_dt = re.search(
        r"auf neu:.*?Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
        re.S | re.IGNORECASE,
    )
    if new_dt:
        info["new_date"] = new_dt.group(1)
        info["new_time"] = new_dt.group(2)
        new_hall = re.search(r"auf neu:.*?Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)", body, re.S | re.IGNORECASE)
        if new_hall:
            info["new_location"] = new_hall.group(1).strip()
            info["new_hall_code"] = new_hall.group(2).strip()
            new_addr = re.search(r"auf neu:.*?Spielhalle:.*\)\s*\n\s*([^\n]+)", body, re.S | re.IGNORECASE)
            if new_addr:
                info["new_address"] = new_addr.group(1).strip()

    return info


def _detect_email_type(subject: str, body: str) -> Optional[str]:
    subject_l = subject.lower()
    body_l = body.lower()

    if "sr-ansetzung" in subject_l:
        return "ANSETZUNG"
    if "umbesetzung" in subject_l or "umbesetzung" in body_l:
        return "UMBESETZUNG"
    if "spielverlegung/spielabsage" in subject_l or "spielverlegung" in subject_l:
        if "abgesagt" in body_l or "absage" in body_l or "aufgehoben" in body_l:
            return "ABSAGE"
        return "VERLEGUNG"
    if "ansetzungen" in subject_l and "geändert" in subject_l:
        return "AENDERUNG"
    if "ansetzungen" in body_l and "geändert" in body_l:
        return "AENDERUNG"
    if "sr-rückzug" in subject_l or "sr-rueckzug" in subject_l or "rückzug" in subject_l:
        return "RUECKZUG"
    return None


def parse_referee_email(content: Dict[str, str]) -> Optional[List[Dict[str, Optional[str]]]]:
    """Parse referee email content into assignment dicts."""
    subject = _fix_mojibake(content.get("subject", ""))
    body = _fix_mojibake(content.get("content", ""))

    email_type = _detect_email_type(subject, body)
    if not email_type:
        return None

    assignments: List[Dict[str, Optional[str]]] = []

    # Support multiple "Ansetzung" sections (legacy emails)
    if "1. Ansetzung:" in body:
        parts = re.split(r"\d+\.\s*Ansetzung:", body)[1:]
        for part in parts:
            info = _extract_basic_fields(part)
            old_new = _extract_old_new_fields(part)
            assignment = {"type": email_type, **info, **old_new}
            assignments.append(assignment)
        return assignments if assignments else None

    info = _extract_basic_fields(body)
    old_new = _extract_old_new_fields(body)

    assignment = {"type": email_type, **info, **old_new}

    # If email contains new values, prefer them as the main date/time for updates
    if assignment.get("new_date") and assignment.get("new_time"):
        assignment["date"] = assignment.get("new_date")
        assignment["time"] = assignment.get("new_time")
        assignment["location"] = assignment.get("new_location") or assignment.get("location")
        assignment["hall_code"] = assignment.get("new_hall_code") or assignment.get("hall_code")
        assignment["address"] = assignment.get("new_address") or assignment.get("address")

    assignments.append(assignment)
    return assignments if assignments else None


# Compatibility wrapper for existing imports
def parse_basketball_email(content):
    return parse_referee_email(content)
