from flask import Flask, render_template, request

app = Flask(__name__)

# Mock database of events
EVENTS = [
    {"title": "Community Job Fair", "category": "job", "desc": "Local companies hiring entry-level roles."},
    {"title": "Mental Health Workshop", "category": "counseling", "desc": "Free session with licensed therapists."},
    {"title": "Social Security Assistance", "category": "social services", "desc": "Help with filing paperwork."},
    {"title": "Resume Building 101", "category": "job", "desc": "Optimize your CV for modern ATS."},
]

@app.route('/')
def index():
    # Get the category from the URL (e.g., /?cat=job)
    selected_category = request.args.get('cat')
    
    if selected_category:
        # Filter the list based on the user's choice
        filtered_events = [e for e in EVENTS if e['category'] == selected_category]
    else:
        filtered_events = EVENTS

    return render_template('index.html', events=filtered_events, active_cat=selected_category)