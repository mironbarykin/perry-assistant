import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

PEOPLE = ['@barykinmiron', '@barykinamarina', '@bar_and_bar']
MIRON_ID = 1955285579

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = './google_calendar_benny_access.json'
TOKEN_PICKLE = 'token.pickle'

NOTIFICATION_FILE = 'notification_times.json'
PARENTS_FILE = 'parents.json'

HOME = {"lat": 51.261838, "lon": 6.677088}
SCHOOL = {"lat": 51.305463, "lon": 6.743720}
