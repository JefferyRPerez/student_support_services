import pandas as pd 
from flask import Flask, render_template, request
import os 

app = Flask(__name__)

# Mock database of events
def getEvents():
    df = pd.read_excel("data.xlsx") 

    df = df.fillna('') 

    return df.to_dict(orient='records') 

@app.route('/')
def index():
    all_events = getEvents() 
    selected_category = request.args.get('cat') 

    if selected_category:
        filtered = [e for e in all_events if e['Status'] == selected_category] 
    else:
        filtered = all_events
    
    return render_template('index.html', events=filtered, active_cat=selected_category)
