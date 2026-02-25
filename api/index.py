import pandas as pd
from flask import Flask, render_template, request
import os 

app = Flask(__name__)

def getEvents():
    # This finds the directory where index.py lives
    basedir = os.path.abspath(os.path.dirname(__file__))
    # This points to data.xlsx in that same folder
    excel_path = os.path.join(basedir, "data.xlsx") 
    
    try:
        df = pd.read_excel(excel_path) 
        df = df.fillna('') 
        return df.to_dict(orient='records') 
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return [] # Return empty list so the site doesn't crash

@app.route('/')
def index():
    all_events = getEvents() 
    selected_category = request.args.get('cat') 

    # If NO category is picked, show everything
    if not selected_category:
        filtered = all_events
    else:
        # If a category IS picked, filter the list
        filtered = [e for e in all_events if str(e.get('Status', '')).lower() == selected_category.lower()]
    
    return render_template('index.html', events=filtered, active_cat=selected_category)
