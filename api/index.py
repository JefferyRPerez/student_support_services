import pandas as pd
from flask import Flask, render_template
import io
import requests

from event_classifier import group_events_by_category, EVENT_CATEGORIES, CATEGORY_LABELS

app = Flask(__name__)

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTUHsbsw4bC_qbSz23COuzJrsfH7vF7K1yZEbgo2d35ohbzTRYO3fAHilgfRx9xUQ/pub?output=csv"


def getEvents():
    try:
        response = requests.get(SHEET_CSV_URL)
        response.raise_for_status()

        df = pd.read_csv(io.StringIO(response.text))
        df = df.fillna('')
        df.columns = [str(c).strip() for c in df.columns]
        return df.to_dict(orient='records')
    except Exception as e:
        print(f"Error fetching from Google Sheets: {e}")
        return []


@app.route('/')
def index():
    all_events = getEvents()
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

    return render_template(
        'index.html',
        events=all_events,
        categories=visible_categories,
        category_filters=[
            {"key": "all", "label": "All Categories"},
            *[
                {"key": category["key"], "label": category["label"]}
                for category in visible_categories
            ],
        ],
    )
    
