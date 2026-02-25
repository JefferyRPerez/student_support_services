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
    # 1. Get all rows from Excel
    all_events = getEvents() 
    
    # 2. We send the whole list to the HTML, no filtering
    return render_template('index.html', events=all_events)
    