#!/usr/bin/env python3
import os
from flask import render_template

# 1. Import the Flask apps from interview_app.py and check_app.py
from interview_app import app as interview_app
from check_app import app as checker_app

# 2. Assign app instance
app = interview_app

# ----------------------------------------------------------------------
# Override / Route & Register Navigation Routes
# ----------------------------------------------------------------------

# Overwrite the existing "/" route from interview_app
@app.endpoint("index")
def homepage():
    """Main landing page with links to candidate interview and results checker."""
    return render_template("home.html")

# Define explicit sub-routes for the portals
@app.route("/interview_portal")
def interview_portal():
    """Render the main candidate interview start page."""
    return render_template("index.html")

@app.route("/results_checker")
def results_checker():
    """Render the candidate check results page."""
    return render_template("checker.html")


# ----------------------------------------------------------------------
# Register routes from check_app into the main application
# ----------------------------------------------------------------------
for rule in checker_app.url_map.iter_rules():
    if rule.endpoint not in app.view_functions and rule.endpoint != "static":
        view_func = checker_app.view_functions[rule.endpoint]
        app.add_url_rule(
            rule.rule,
            endpoint=f"checker_{rule.endpoint}",
            view_func=view_func,
            methods=rule.methods
        )

if __name__ == "__main__":
    print("Starting Unified Interview Application...")
    app.run(debug=True, host="0.0.0.0", port=5000)