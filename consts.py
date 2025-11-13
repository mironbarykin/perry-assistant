import os

DATA_DIR = os.getenv("DATA_DIR", "/data")

# -- ENVIRONMENT
TG_TOKEN = os.getenv("TG_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

## -- TELEGRAM
MIRON_ID = 1955285579
PEOPLE = ['@barykinmiron', '@barykinamarina', '@bar_and_bar']

## -- GOOGLE
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'google_calendar_benny_access.json')
TOKEN_PICKLE = os.path.join(DATA_DIR, 'token.pickle')
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/gmail.readonly"]

HOME = {"lat": 51.261838, "lon": 6.677088}
SCHOOL = {"lat": 51.305463, "lon": 6.743720}
BASKETBALL_EMAILS = ["*@uportal-wbv.de", "noreply@basketball-bund.net", "bekettgregory@gmail.com"]

## -- FILES
STORED_EMAIL_IDS_FILE = os.path.join(DATA_DIR, 'processed_emails.json')
NOTIFICATION_FILE = os.path.join(DATA_DIR, 'notification_times.json')
PARENTS_FILE = os.path.join(DATA_DIR, 'parents.json')

## -- OTHER

SET_TIME = range(1)
