import pandas as pd
from flask import Flask, render_template, request
import io
import requests
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI 
import os
import json
import hashlib 

sys.path.insert(0, str(Path(__file__).parent))

from database import (
    init_db,
    get_cached_events,
    get_cached_translation,
    save_cached_events,
    save_cached_translation,
)

init_db() 
app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY","").strip())  

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

from event_classifier import CATEGORY_LABELS, EVENT_CATEGORIES, group_events_by_category

# Replace this with the URL you copied from 'Publish to Web'
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1K-VlChD1zeeOGQGxI97GqcyAWAEd3FrEQQVUZSn8uYs/export?format=csv"

CATEGORY_LABELS_ES = {
    "club_events": "Eventos de Clubes",
    "professional_development": "Desarrollo Profesional",
    "faith": "Fe",
    "community_service": "Servicio Comunitario",
    "academic_support": "Apoyo Académico",
    "wellness": "Bienestar",
    "arts_culture": "Arte y Cultura",
    "social": "Social",
    "other": "Otros",
}

def get_category_labels(lang):
    if lang == "es":
        return CATEGORY_LABELS_ES
    return CATEGORY_LABELS

def hash_events(raw_csv_text):
    return hashlib.md5(raw_csv_text.encode()).hexdigest()

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

translation_cache = {}

def flatten_grouped_events(grouped_events):
    flattened = []
    for category_key in EVENT_CATEGORIES:
        flattened.extend(grouped_events.get(category_key, []))
    return flattened

def regroup_events_by_existing_category(events):
    grouped = OrderedDict((category, []) for category in EVENT_CATEGORIES)

    for event in events:
        category_key = event.get("ai_category", {}).get("category", "other")
        if category_key not in grouped:
            category_key = "other"
        grouped[category_key].append(event)

    return grouped

def enrich_events(events, lang='en', cache_scope='default'):
    if not events:
        return []

    # 1. ALWAYS calculate verification status first (Fixes your disappearing badges)
    enriched_events = []
    for event in events:
        event_record = dict(event)
        event_record["verification_status"] = get_verification_status(
            event.get("Last Updated", "")
        )
        enriched_events.append(event_record)

    # 2. If it's English, stop here.
    if lang != 'es':
        return enriched_events

    # 3. Check Cache
    cache_key = f"{cache_scope}_es_{len(events)}"
    if cache_key in translation_cache:
        print("DEBUG: Loading from cache")
        return translation_cache[cache_key]

    persisted_translation = None
    if cache_scope and cache_scope != "default":
        persisted_translation = get_cached_translation(cache_scope, lang)

    if persisted_translation:
        print("DEBUG: Loading translated events from DB cache")
        translation_cache[cache_key] = persisted_translation
        return persisted_translation

    try:
        print("DEBUG: Starting Batch Translation...")
        # Prepare the list for OpenAI
        to_translate = [
            {"id": i, "name": e.get("Event Name", ""), "desc": e.get("Description", "")} 
            for i, e in enumerate(enriched_events)
        ]

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional translator. Translate the 'name' and 'desc' fields to Spanish. Return ONLY a JSON object with a key 'translations' containing the array of objects. Maintain the 'id' for each."},
                {"role": "user", "content": json.dumps(to_translate)}
            ],
            response_format={ "type": "json_object" }
        )

        # Parse AI response
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)
        
        # OpenAI usually wraps the list in a key (e.g., {"translations": [...]})
        # We need to get that list.
        t_list = data.get('translations', [])

        # 4. MERGE logic (Matching by the ID we sent)
        for t_item in t_list:
            idx = t_item.get("id")
            if idx is not None and idx < len(enriched_events):
                enriched_events[idx]["Event Name"] = t_item.get("name")
                enriched_events[idx]["Description"] = t_item.get("desc")
                # Location is usually a name/address, but you can add it if needed

        # Save to cache
        translation_cache[cache_key] = enriched_events
        if cache_scope and cache_scope != "default":
            save_cached_translation(cache_scope, lang, enriched_events)
        print("DEBUG: Translation Successful")
        
    except Exception as e:
        print(f"DEBUG: Translation Error: {e}")

    return enriched_events

def getEvents():
    try:
        # Fetch the data from Google Sheets
        response = requests.get(SHEET_CSV_URL, timeout=15)
        response.raise_for_status() # Check if the link is working
        raw_text = response.text 
        data_hash = hash_events(raw_text) 
        
        cached = get_cached_events(data_hash) 
        if cached:
            print("DEBUG: Serving from DB Cache no API Calls Needed")
            return cached, data_hash

        # Turn the text into a format Pandas understands
        df = pd.read_csv(io.StringIO(response.text))
        
        df = df.fillna('')
        df.columns = [str(c).strip() for c in df.columns]
        raw_events = df.to_dict(orient='records') 
        return raw_events, data_hash 
    except Exception as e:
        print(f"Error fetching from Google Sheets: {e}")
        return [], None

@app.route('/')
def index():

    lang = request.args.get('lang','en') 
    raw_events, data_hash = getEvents() 
    cache_scope = data_hash or "events"
    category_labels = get_category_labels(lang)

    base_events = enrich_events(raw_events, lang='en', cache_scope=cache_scope)
    grouped_events = group_events_by_category(base_events)

    if lang == 'es':
        classified_events = flatten_grouped_events(grouped_events)
        all_events = enrich_events(
            classified_events,
            lang='es',
            cache_scope=f"{cache_scope}_classified",
        )
        grouped_events = regroup_events_by_existing_category(all_events)
    else:
        all_events = flatten_grouped_events(grouped_events)

    if data_hash:
        save_cached_events(data_hash, raw_events)


    visible_categories = [
        {
            "key": key,
            "label": category_labels[key],
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
        current_lang=lang,
        category_filters=[
            {
                "key": "all",
                "label": "Todas las Categorías" if lang == "es" else "All Categories",
            },
            *[
                {"key": category["key"], "label": category["label"]}
                for category in visible_categories
            ],
        ],
    )

@app.route('/chat', methods=['POST'])
def chat():
    user_query = request.json.get('message', '')
    if not user_query:
        return {"response": "I didn't catch that. What would you like to know?"}, 400

    # 1. Get the latest data from your existing getEvents function
    current_events, _ = getEvents()
    
    # 2. Format that data into a string the AI can read
    context_str = "Here are the current events:\n"
    for e in current_events:
        context_str += f"- {e.get('Event Name')}: {e.get('Description')} at {e.get('Location')} on {e.get('Date')}\n"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a helpful community assistant. "
                        "Answer questions ONLY using the provided event context. "
                        "If the answer isn't in the data, politely say you don't have information on that."
                    )
                },
                {"role": "system", "content": f"CONTEXT: {context_str}"},
                {"role": "user", "content": user_query}
            ]
        )
        return {"response": response.choices[0].message.content}
    except Exception as e:
        return {"response": f"Sorry, I'm having trouble connecting to my brain. Error: {e}"}, 500
