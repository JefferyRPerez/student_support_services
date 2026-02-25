import pandas as pd
from flask import Flask, render_template
import io
import requests

app = Flask(__name__)

# Replace this with the URL you copied from 'Publish to Web'
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTUHsbsw4bC_qbSz23COuzJrsfH7vF7K1yZEbgo2d35ohbzTRYO3fAHilgfRx9xUQ/pub?output=csv"

def getEvents():
    try:
        # Fetch the data from Google Sheets
        response = requests.get(SHEET_CSV_URL)
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
    all_events = getEvents()
    return render_template('index.html', events=all_events)
    