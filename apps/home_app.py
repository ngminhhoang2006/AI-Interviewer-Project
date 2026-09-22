#!/usr/bin/env python3
import sys
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, InterviewResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure `apps` directory is on python path so module imports work smoothly
apps_dir = Path(__file__).resolve().parent
if str(apps_dir) not in sys.path:
    sys.path.append(str(apps_dir))

# 1. Import the Flask apps from interview_app.py and check_app.py
from interview_app import app as interview_app
from check_app import app as checker_app

# 2. Assign app instance from interview_app
app = interview_app

# Ensure template and static paths point to project root folders
app.template_folder = str(PROJECT_ROOT / "templates")
app.static_folder = str(PROJECT_ROOT / "static")

# 1. App Configuration
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///interview_portal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# 2. Setup Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize Database and Create Default Admin
with app.app_context():
    db.create_all()
    if not User.query.filter_by(role='admin').first():
        admin = User(username='Nguyen Minh Hoang', email='hoangdeptrai61@gmail.com', role='admin')
        admin.set_password('PennyPolendina69420!')
        db.session.add(admin)
        db.session.commit()

# ----------------------------------------------------------------------
# Authentication Routes
# ----------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('results_checker'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

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

@app.route("/mic_test")
def mic_test():
    """Render the microphone test page."""
    candidate = request.args.get("candidate", None)
    language = request.args.get("lang", "English")
    return render_template("mic_test.html", candidate=candidate, language=language)

@app.route("/results_checker")
@login_required
def results_checker():
    """
    Candidate: Sees ONLY their own interview results.
    Admin: Sees ALL candidates' interview results.
    """
    if current_user.is_admin:
        results = InterviewResult.query.order_by(InterviewResult.created_at.desc()).all()
    else:
        results = InterviewResult.query.filter_by(user_id=current_user.id).order_by(InterviewResult.created_at.desc()).all()

    return render_template("checker.html", results=results, is_admin=current_user.is_admin)


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