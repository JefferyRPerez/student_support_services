import pandas as pd
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import io
import requests
import sys
from collections import OrderedDict
from datetime import datetime, timezone
import hmac
from pathlib import Path
from openai import OpenAI 
import os
import json
import hashlib 
import uuid

sys.path.insert(0, str(Path(__file__).parent))

from database import (
    init_db,
    get_cached_events,
    get_cached_translation,
    get_organizer_events,
    save_cached_events,
    save_organizer_events,
    save_cached_translation,
)

init_db() 
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY","").strip())  

ORGANIZER_USERNAME = os.getenv("ORGANIZER_USERNAME", "organizer")
ORGANIZER_PASSWORD = os.getenv("ORGANIZER_PASSWORD", "change-me")
ORGANIZER_SESSION_KEY = "organizer_authenticated"

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

def hash_event_collection(events):
    serialized = json.dumps(events, sort_keys=True)
    return hashlib.md5(serialized.encode()).hexdigest()

def organizer_is_authenticated():
    return session.get(ORGANIZER_SESSION_KEY, False)

def require_organizer_login():
    if organizer_is_authenticated():
        return None
    flash("Please log in to manage organizer events.", "error")
    return redirect(url_for("organizer_portal"))

def build_organizer_event(form_data):
    event_name = form_data.get("event_name", "").strip()
    description = form_data.get("description", "").strip()
    date = form_data.get("date", "").strip()
    time_value = form_data.get("time", "").strip()
    location = form_data.get("location", "").strip()
    organizer_name = form_data.get("organizer_name", "").strip()

    if not event_name or not description or not date or not location or not organizer_name:
        raise ValueError("Event name, description, date, location, and organizer name are required.")

    return {
        "id": str(uuid.uuid4()),
        "Event Name": event_name,
        "Description": description,
        "Date": date,
        "Time": time_value,
        "Location": location,
        "Organizer Name": organizer_name,
        "Last Updated": datetime.now(timezone.utc).date().isoformat(),
        "Submitted Source": "Organizer Portal",
    }

def build_public_events_context(lang):
    raw_events, data_hash, sheet_hash, _, sheet_cache_hit = getEvents()
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

    if sheet_hash and not sheet_cache_hit:
        save_cached_events(
            sheet_hash,
            [event for event in raw_events if event.get("Submitted Source") != "Organizer Portal"],
        )

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

    return {
        "events": all_events,
        "categories": visible_categories,
        "current_lang": lang,
        "category_filters": [
            {
                "key": "all",
                "label": "Todas las Categorías" if lang == "es" else "All Categories",
            },
            *[
                {"key": category["key"], "label": category["label"]}
                for category in visible_categories
            ],
        ],
    }

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

def get_sheet_events():
    try:
        # Fetch the data from Google Sheets
        response = requests.get(SHEET_CSV_URL, timeout=15)
        response.raise_for_status() # Check if the link is working
        raw_text = response.text 
        data_hash = hash_events(raw_text) 
        
        cached = get_cached_events(data_hash) 
        if cached:
            print("DEBUG: Serving from DB Cache no API Calls Needed")
            return cached, data_hash, True

        # Turn the text into a format Pandas understands
        df = pd.read_csv(io.StringIO(response.text))
        
        df = df.fillna('')
        df.columns = [str(c).strip() for c in df.columns]
        raw_events = df.to_dict(orient='records') 
        return raw_events, data_hash, False
    except Exception as e:
        print(f"Error fetching from Google Sheets: {e}")
        return [], None, False

def getEvents():
    sheet_events, sheet_hash, sheet_cache_hit = get_sheet_events()
    organizer_events = get_organizer_events()
    combined_events = [*sheet_events, *organizer_events]
    organizer_hash = hash_event_collection(organizer_events)
    combined_hash = hash_events(f"{sheet_hash or 'no-sheet'}:{organizer_hash}")
    return combined_events, combined_hash, sheet_hash, organizer_events, sheet_cache_hit

@app.route('/')
@app.route('/events')
def index():
    lang = request.args.get('lang','en')
    return render_template('index.html', **build_public_events_context(lang))

@app.route('/aiagent')
def aiagent():
    lang = request.args.get('lang', 'en')
    return render_template(
        'aiagent.html',
        current_lang=lang,
    )

@app.route('/organizer', methods=['GET', 'POST'])
def organizer_portal():
    if request.method == 'POST':
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        username_matches = hmac.compare_digest(username, ORGANIZER_USERNAME)
        password_matches = hmac.compare_digest(password, ORGANIZER_PASSWORD)

        if username_matches and password_matches:
            session[ORGANIZER_SESSION_KEY] = True
            flash("You are now logged in.", "success")
            return redirect(url_for("organizer_portal"))

        flash("Invalid organizer username or password.", "error")
        return redirect(url_for("organizer_portal"))

    return render_template(
        'organizer.html',
        is_authenticated=organizer_is_authenticated(),
        organizer_events=get_organizer_events(),
    )

@app.route('/organizer/events', methods=['POST'])
def organizer_add_event():
    auth_redirect = require_organizer_login()
    if auth_redirect:
        return auth_redirect

    try:
        new_event = build_organizer_event(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("organizer_portal"))

    organizer_events = get_organizer_events()
    organizer_events.append(new_event)
    save_organizer_events(organizer_events)
    flash("Event added successfully.", "success")
    return redirect(url_for("organizer_portal"))

@app.route('/organizer/logout', methods=['POST'])
def organizer_logout():
    session.pop(ORGANIZER_SESSION_KEY, None)
    flash("You have been logged out.", "success")
    return redirect(url_for("organizer_portal"))

@app.route('/chat', methods=['POST'])
def chat():
    user_query = request.json.get('message', '')
    lang = request.json.get('lang', 'en')
    if not user_query:
        return {"response": "I didn't catch that. What would you like to know?"}, 400

    # 1. Get the latest event data
    current_events, _, _, _, _ = getEvents()
    event_context = [
        {
            "event_name": e.get("Event Name", ""),
            "description": e.get("Description", ""),
            "date": e.get("Date", ""),
            "time": e.get("Time", ""),
            "location": e.get("Location", ""),
            "last_updated": e.get("Last Updated", ""),
            "organizer_name": e.get("Organizer Name", ""),
            "source": e.get("Submitted Source", "Spreadsheet"),
        }
        for e in current_events
    ]

    response_language = "Spanish" if lang == "es" else "English"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a helpful community events assistant. "
                        "Answer questions ONLY using the provided event data. "
                        "Be especially helpful with date, time, and location questions. "
                        "If multiple events match, summarize the matching events clearly. "
                        "If the answer is not in the data, say that you do not have that information. "
                        f"Respond in {response_language}."
                    )
                },
                {
                    "role": "system",
                    "content": (
                        f"Today's date is {datetime.now(timezone.utc).date().isoformat()}.\n"
                        "Event data JSON:\n"
                        f"{json.dumps(event_context, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": user_query}
            ]
        )
        return {"response": response.choices[0].message.content}
    except Exception as e:
        return {"response": f"Sorry, I'm having trouble connecting to my brain. Error: {e}"}, 500
