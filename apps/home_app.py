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

# Ensure local "database" directory exists
DB_DIR = PROJECT_ROOT / "database"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "interview_portal.db"

# 1. Import the Flask apps from interview_app.py and check_app.py
from interview_app import app as interview_app
from check_app import app as checker_app

# 2. Assign app instance from interview_app
app = interview_app

# Ensure template and static paths point to project root folders
app.template_folder = str(PROJECT_ROOT / "templates")
app.static_folder = str(PROJECT_ROOT / "static")

# App Configuration
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Setup Flask-Login
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
    if current_user.is_authenticated:
        return redirect(url_for('results_checker'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('results_checker'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('results_checker'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Basic validation
        if not username or not email or not password:
            flash('Please fill out all required fields.', 'danger')
            return render_template('signup.html')

        if password != confirm_password:
            flash('Passwords do not match. Please try again.', 'danger')
            return render_template('signup.html')

        # Check existing user/email
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            if existing_user.username == username:
                flash('Username is already taken. Please choose another.', 'danger')
            else:
                flash('An account with this email already exists.', 'danger')
            return render_template('signup.html')

        # Create new candidate account
        new_user = User(
            username=username,
            email=email,
            role='candidate'  # Default role for new signups
        )
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! You can now log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while creating your account. Please try again.', 'danger')

    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ----------------------------------------------------------------------
# Navigation Routes
# ----------------------------------------------------------------------
@app.endpoint("index")
def homepage():
    """Main landing page with links to candidate interview and results checker."""
    return render_template("home.html")

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

# Register routes from check_app into the main application
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