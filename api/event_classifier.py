import json 
from collections import OrderedDict 

from openai import OpenAI 


client = OpenAI() 

EVENT_CATEGORIES = [
    "club_events",
    "professional_development",
    "faith",
    "community_service",
    "academic_support",
    "wellness",
    "arts_culture",
    "social",
    "other",
]

CATEGORY_LABELS = {
    "club_events": "Club Events",
    "professional_development": "Professional Development",
    "faith": "Faith",
    "community_service": "Community Service",
    "academic_support": "Academic Support",
    "wellness": "Wellness",
    "arts_culture": "Arts & Culture",
    "social": "Social",
    "other": "Other",
}


CLASSIFIER_SYSTEM_PROMPT = """
You classify student events into one fixed category list.

Rules:
- Choose exactly one category from the allowed list.
- Do not invent new categories.
- Base the choice on the event's overall purpose and theme.
- Prioritize the description over the event title.
- If the category is unclear, choose "other".
""" 

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": EVENT_CATEGORIES,
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "reason": {
            "type": "string",
        },
    },
    "required": ["category", "confidence", "reason"],
    "additionalProperties": False,
}

def build_event_text(event):
    return "\n".join([
        f"Event Name: {event.get('Event Name', '')}",
        f"Description: {event.get('Description', '')}",
        f"Date: {event.get('Date', '')}",
        f"Time: {event.get('Time', '')}",
        f"Location: {event.get('Location', '')}",
    ]) 


def classify_event(event):
    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": build_event_text(event)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "event_category_result",
                "strict": True,
                "schema": CATEGORY_SCHEMA,
            }
        },
    )

    result = json.loads(response.output_text)

    return {
        "category": result["category"],
        "category_label": CATEGORY_LABELS[result["category"]],
        "confidence": result["confidence"],
        "reason": result["reason"],
    }


def group_events_by_category(events):
    grouped = OrderedDict((category, []) for category in EVENT_CATEGORIES)

    for event in events:
        category_result = classify_event(event)
        enriched_event = dict(event)
        enriched_event["ai_category"] = category_result
        grouped[category_result["category"]].append(enriched_event)

    return grouped