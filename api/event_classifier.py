import json
import os
from collections import OrderedDict
from functools import lru_cache

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

KEYWORD_CATEGORY_RULES = {
    "club_events": [
        "club",
        "organization",
        "student org",
        "association",
        "chapter",
    ],
    "professional_development": [
        "career",
        "resume",
        "internship",
        "interview",
        "professional",
        "networking",
        "linkedin",
        "job",
    ],
    "faith": [
        "faith",
        "church",
        "worship",
        "bible",
        "prayer",
        "spiritual",
        "ministry",
    ],
    "community_service": [
        "volunteer",
        "service",
        "donation",
        "fundraiser",
        "community cleanup",
        "charity",
    ],
    "academic_support": [
        "tutoring",
        "study",
        "academic",
        "workshop",
        "exam",
        "homework",
        "advising",
    ],
    "wellness": [
        "wellness",
        "mental health",
        "health",
        "counseling",
        "mindfulness",
        "fitness",
        "self-care",
    ],
    "arts_culture": [
        "art",
        "music",
        "dance",
        "theater",
        "culture",
        "gallery",
        "performance",
    ],
    "social": [
        "social",
        "mixer",
        "hangout",
        "game night",
        "celebration",
        "party",
        "welcome",
    ],
}

AI_BATCH_EVENT_LIMIT = int(os.getenv("AI_BATCH_EVENT_LIMIT", "8"))


CLASSIFIER_SYSTEM_PROMPT = """
You classify student events into one fixed category list.

Rules:
- Choose categories from the allowed list that match with each event,an event can match with multiple categories.
- Allowed categories: club_events, professional_development, faith, community_service, academic_support, wellness, arts_culture, social, other.
- Do not invent new categories.
- Base the choice on the event's overall purpose and theme.
- Prioritize the description over the event title.
- If the category is unclear try to match it with other similar events and give it a category that it may fit under, otherwise it can be "other".
""" 

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_index": {
                        "type": "integer",
                    },
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
                "required": ["event_index", "category", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
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


def use_ai_categorization():
    return os.getenv("ENABLE_AI_EVENT_CATEGORIZATION", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed in this deployment.") from exc
    return OpenAI(api_key=api_key)


def fallback_category_result():
    return {
        "category": "other",
        "category_label": CATEGORY_LABELS["other"],
        "confidence": "low",
        "reason": "AI categorization is unavailable, so this event was placed in Other.",
    }


def keyword_category_result(event):
    searchable_text = " ".join(
        [
            str(event.get("Event Name", "")),
            str(event.get("Description", "")),
            str(event.get("Location", "")),
        ]
    ).lower()

    best_category = "other"
    best_score = 0

    for category, keywords in KEYWORD_CATEGORY_RULES.items():
        score = sum(1 for keyword in keywords if keyword in searchable_text)
        if score > best_score:
            best_category = category
            best_score = score

    confidence = "medium" if best_score > 0 else "low"
    reason = (
        "Matched the event against the local category keyword rules."
        if best_score > 0
        else "No strong local category match was found, so the event was placed in Other."
    )

    return {
        "category": best_category,
        "category_label": CATEGORY_LABELS[best_category],
        "confidence": confidence,
        "reason": reason,
    }


@lru_cache(maxsize=256)
def classify_event_batch(event_texts):
    if not use_ai_categorization():
        return {}

    if len(event_texts) > AI_BATCH_EVENT_LIMIT:
        print(
            "Skipping AI categorization because the event batch exceeds the configured limit."
        )
        return {}

    try:
        client = get_openai_client()
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            "Classify each event and return one result for every event_index.",
                            *[
                                f"event_index: {index}\n{event_text}"
                                for index, event_text in enumerate(event_texts)
                            ],
                        ]
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "event_category_batch_result",
                    "strict": True,
                    "schema": CATEGORY_SCHEMA,
                }
            },
        )

        result = json.loads(response.output_text)
        mapped_results = {}

        for item in result.get("results", []):
            category_key = item["category"]
            mapped_results[item["event_index"]] = {
                "category": category_key,
                "category_label": CATEGORY_LABELS[category_key],
                "confidence": item["confidence"],
                "reason": item["reason"],
            }

        return mapped_results
    except Exception as e:
        print(f"Error classifying events: {e}")
        return {}


def group_events_by_category(events):
    grouped = OrderedDict((category, []) for category in EVENT_CATEGORIES)
    event_texts = tuple(build_event_text(event) for event in events)
    classified_results = classify_event_batch(event_texts) if event_texts else {}

    for index, event in enumerate(events):
        category_result = classified_results.get(index, keyword_category_result(event))
        enriched_event = dict(event)
        enriched_event["ai_category"] = category_result
        grouped[category_result["category"]].append(enriched_event)

    return grouped
