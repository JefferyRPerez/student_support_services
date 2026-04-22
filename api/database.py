import json
import os

CACHE_VERSION = "v2"
EVENTS_PREFIX = f"events:{CACHE_VERSION}"
TRANSLATIONS_PREFIX = f"translations:{CACHE_VERSION}"

def get_redis():
    from upstash_redis import Redis
    return Redis(
        url=os.getenv("UPSTASH_REDIS_REST_URL"),
        token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
    )

def init_db():
    pass  # no setup needed

def get_cached_events(data_hash):
    try:
        r = get_redis()
        cached = r.get(f"{EVENTS_PREFIX}:{data_hash}")
        return json.loads(cached) if cached else None
    except Exception as e:
        print(f"Cache read error: {e}")
        return None

def get_cached_translation(data_hash, lang):
    try:
        r = get_redis()
        cached = r.get(f"{TRANSLATIONS_PREFIX}:{data_hash}:{lang}")
        return json.loads(cached) if cached else None
    except Exception as e:
        print(f"Translation cache read error: {e}")
        return None

def save_cached_events(data_hash, raw_events):
    try:
        r = get_redis()
        # Get all keys and delete old cache
        old_keys = r.keys(f"{EVENTS_PREFIX}:*")
        if old_keys:
            r.delete(*old_keys)
        old_translation_keys = r.keys(f"{TRANSLATIONS_PREFIX}:*")
        if old_translation_keys:
            r.delete(*old_translation_keys)
        # Save new cache — expires in 24 hours just in case
        r.set(f"{EVENTS_PREFIX}:{data_hash}", json.dumps(raw_events), ex=86400)
    except Exception as e:
        print(f"Cache write error: {e}")

def save_cached_translation(data_hash, lang, translated_events):
    try:
        r = get_redis()
        r.set(
            f"{TRANSLATIONS_PREFIX}:{data_hash}:{lang}",
            json.dumps(translated_events),
            ex=86400,
        )
    except Exception as e:
        print(f"Translation cache write error: {e}")
