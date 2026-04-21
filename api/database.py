import sqlite3
import json 
from pathlib import Path

DB_PATH = Path(__file__).parent / "events_cache.db" 

def get_connection():
    conn = sqlite3.connect(DB_PATH) 
    conn.row_factory = sqlite3.Row
    return conn 

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events_cache (
                id INTEGER PRIMARY KEY,
                data_hash TEXT NOT NULL UNIQUE,
                raw_events TEXT NOT NULL,
                classified_events TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit() 

def get_cached_events(data_hash):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT classified_events FROM events_cache WHERE data_hash = ?",
            (data_hash,)
        ).fetchone()
        return json.loads(row["classified_events"]) if row else None 

def save_cached_events(data_hash, raw_events, classified_events):
    with get_connection() as conn:
        conn.execute("DELETE FROM events_cache")  # only keep latest
        conn.execute(
            """INSERT INTO events_cache (data_hash, raw_events, classified_events)
               VALUES (?, ?, ?)""",
            (data_hash, json.dumps(raw_events), json.dumps(classified_events))
        )
        conn.commit()
