import pandas as pd
from flask import Flask, render_template, request
import os 

app = Flask(__name__)

def getEvents():
    # Attempt 1: Look in the same folder as this script
    basedir = os.path.abspath(os.path.dirname(__file__))
    path1 = os.path.join(basedir, "data.xlsx")
    
    # Attempt 2: Look in the parent folder (root)
    path2 = os.path.join(os.getcwd(), "data.xlsx")

    final_path = None
    if os.path.exists(path1):
        final_path = path1
    elif os.path.exists(path2):
        final_path = path2

    if not final_path:
        # This will show up in Vercel Logs to tell us why it's empty
        print(f"CRITICAL: data.xlsx not found in {path1} or {path2}")
        return []

    try:
        # Use openpyxl as the engine specifically
        df = pd.read_excel(final_path, engine='openpyxl')
        df = df.fillna('')
        # Strip spaces from headers
        df.columns = [str(c).strip() for c in df.columns]
        return df.to_dict(orient='records')
    except Exception as e:
        print(f"ERROR reading Excel: {e}")
        return []

@app.route('/')
def index():
    # 1. Get all rows from Excel
    all_events = getEvents() 
    
    # 2. We send the whole list to the HTML, no filtering
    return render_template('index.html', events=all_events)
    