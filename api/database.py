import json
import os

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
        cached = r.get(f"events:{data_hash}")
        return json.loads(cached) if cached else None
    except Exception as e:
        print(f"Cache read error: {e}")
        return None

def save_cached_events(data_hash, raw_events, classified_events):
    try:
        r = get_redis()
        # Get all keys and delete old cache
        old_keys = r.keys("events:*")
        if old_keys:
            r.delete(*old_keys)
        # Save new cache — expires in 24 hours just in case
        r.set(f"events:{data_hash}", json.dumps(classified_events), ex=86400)
    except Exception as e:
        print(f"Cache write error: {e}")
