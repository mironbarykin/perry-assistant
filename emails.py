import re
from consts import BASKETBALL_EMAILS

def get_basketball_emails(service, max_results=10):
    """Get basketball-related emails from Gmail from the last 15 minutes only."""
    import datetime

    query = " OR ".join(f"from:{email}" for email in BASKETBALL_EMAILS)

    now = datetime.datetime.utcnow()
    since = now - datetime.timedelta(minutes=15)

    after = since.strftime("%Y/%m/%d %H:%M:%S")

    query = f"{query} after:{after}"

    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()
    return results.get('messages', [])

def get_email_content(service, msg_id):
    """Get full email content."""
    message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = message['payload']
    headers = {header['name']: header['value'] for header in payload.get('headers', [])}
    
    if 'parts' in payload:
        parts = payload['parts']
        data = parts[0]['body'].get('data', '')
    else:
        data = payload['body'].get('data', '')
    
    if data:
        import base64
        text = base64.urlsafe_b64decode(data).decode()
    else:
        text = ""
    
    return {
        'subject': headers.get('Subject', ''),
        'from': headers.get('From', ''),
        'date': headers.get('Date', ''),
        'content': text
    }

def parse_basketball_email(content):
    """Parse basketball email content."""
    subject = content['subject']
    body = content['content']
    
    email_type = None
    if "offene Umbesetzung" in subject:
        email_type = "Umbesetzung"
    elif "SR-Ansetzung" in subject:
        email_type = "Ansetzung"
    elif "Spieländerung" in subject:
        email_type = "Spieländerung"
    elif "Spielverlegung" in subject:
        email_type = "Spielverlegung"
    
    if not email_type:
        return None

    assignments = []
    if "1. Ansetzung:" in body:
        parts = re.split(r'\d+\.\s*Ansetzung:', body)[1:]
        for part in parts:
            info = {
                'type': email_type,
                'date': None,
                'time': None,
                'liga': None,
                'location': None,
                'teams': None,
                'hall_code': None
            }
            
            date_match = re.search(r'Datum:\s*\w+,\s*(\d{2}\.\d{2}\.\d{4})', part)
            if date_match:
                info['date'] = date_match.group(1)
            
            time_match = re.search(r'Zeit:\s*(\d{2}:\d{2})', part)
            if time_match:
                info['time'] = time_match.group(1)
            
            liga_match = re.search(r'Liga:\s*([^\n]+)', part)
            if liga_match:
                info['liga'] = liga_match.group(1).strip()
            
            teams_match = re.search(r'Begegnung:\s*([^\n]+)', part)
            hall_match = re.search(r'Halle:\s*([^\n]+)', part)
            
            if teams_match:
                info['teams'] = teams_match.group(1).strip()
            if hall_match:
                hall_text = hall_match.group(1).strip()
                hall_code_match = re.search(r'\d{3}[A-Z]\d{3}', hall_text)
                if hall_code_match:
                    info['hall_code'] = hall_code_match.group(0)
                info['location'] = hall_text
            
            if info['date'] and info['time']:
                assignments.append(info)
    else:
        info = {
            'type': email_type,
            'date': None,
            'time': None,
            'liga': None,
            'location': None,
            'teams': None,
            'hall_code': None
        }
        
        datetime_match = re.search(r'Spielbeginn:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})', body)
        if datetime_match:
            info['date'] = datetime_match.group(1)
            info['time'] = datetime_match.group(2)
        
        liga_match = re.search(r'Liga:\s*([^\n]+)', body)
        if liga_match:
            info['liga'] = liga_match.group(1).strip()
        
        location_match = re.search(r'Spielhalle:\s*([^\n]+)\s+\((\d{3}[A-Z]\d{3})\)', body)
        if location_match:
            info['location'] = location_match.group(1).strip()
            info['hall_code'] = location_match.group(2)
        
        home_match = re.search(r'Heimmannschaft:\s*([^\n]+)', body)
        away_match = re.search(r'Gastmannschaft:\s*([^\n]+)', body)
        if home_match and away_match:
            info['teams'] = f"{home_match.group(1).strip()} - {away_match.group(1).strip()}"
        
        if info['date'] and info['time']:
            assignments.append(info)
    
    return assignments if assignments else None