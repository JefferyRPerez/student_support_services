import pandas as pd
from flask import Flask, render_template, request
import io
import requests
import sys
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI 
import os

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY","").strip())  

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

from event_classifier import CATEGORY_LABELS, EVENT_CATEGORIES, group_events_by_category

# Replace this with the URL you copied from 'Publish to Web'
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1K-VlChD1zeeOGQGxI97GqcyAWAEd3FrEQQVUZSn8uYs/export?format=csv"

def translate_text(text,target_language="Spanish"):
    if not text or pd.isna(text) or text == '':
        return ""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": f"You are a professional translator. Translate the following text to {target_language}. Maintain the tone and formatting. RETURN ONLY THE TRANSLATE TEXT"}, 
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message.content.strip() 
    except Exception as e:
        print(f"Translation Error: {e}") 
        return text # If failure fall back to original text 

def get_verification_status(last_updated_value):
    parsed_date = pd.to_datetime(last_updated_value, errors='coerce')
    if pd.isna(parsed_date):
        return {
            "label": "Verification Unknown",
            "class": "verification-unknown",
        }

    days_since_update = (datetime.now(timezone.utc).date() - parsed_date.date()).days

    if days_since_update <= 14:
        return {
            "label": "Recently Verified",
            "class": "verification-recent",
        }
    if days_since_update <= 30:
        return {
            "label": "Needs Verification Soon",
            "class": "verification-warning",
        }
    return {
        "label": "Verification Overdue",
        "class": "verification-stale",
    }


def enrich_events(events, lang='en'):
    enriched_events = []

    for event in events:
        event_record = dict(event)
        event_record["verification_status"] = get_verification_status(
            event.get("Last Updated", "")
        )

        if lang == 'es':
            fields_to_translate = ["Name","Description","Location"]
            for field in fields_to_translate:
                if field in event_record:
                    event_record[field] = translate_text(event_record[field],"Spanish")

        enriched_events.append(event_record)

    return enriched_events

def getEvents():
    try:
        # Fetch the data from Google Sheets
        response = requests.get(SHEET_CSV_URL, timeout=15)
        response.raise_for_status() # Check if the link is working
        
        # Turn the text into a format Pandas understands
        df = pd.read_csv(io.StringIO(response.text))
        
        df = df.fillna('')
        df.columns = [str(c).strip() for c in df.columns]
        return df.to_dict(orient='records')
    except Exception as e:
        print(f"Error fetching from Google Sheets: {e}")
        return []

@app.route('/')
def index():

    lang = request.args.get('lang','en')

    all_events = enrich_events(getEvents(),lang=lang)
    visible_categories = []

    try:
        grouped_events = group_events_by_category(all_events)
        visible_categories = [
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "events": grouped_events[key],
                "count": len(grouped_events[key]),
            }
            for key in EVENT_CATEGORIES
            if grouped_events[key]
        ]
    except Exception as e:
        print(f"Error grouping events by category: {e}")

    return render_template(
        'index.html',
        events=all_events,
        categories=visible_categories,
        current_lang=lang,
        category_filters=[
            {"key": "all", "label": "All Categories"},
            *[
                {"key": category["key"], "label": category["label"]}
                for category in visible_categories
            ],
        ],
    )
