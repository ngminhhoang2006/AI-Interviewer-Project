#!/usr/bin/env python3
import os
import sys
import random
import time
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from models import db, User, InterviewResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure `apps` directory is on python path so module imports work smoothly
apps_dir = Path(__file__).resolve().parent
if str(apps_dir) not in sys.path:
    sys.path.append(str(apps_dir))

from interview_app import app as interview_app
from check_app import app as checker_app

app = interview_app

# Set templates and static paths relative to true root
app.template_folder = str(PROJECT_ROOT / "templates")
app.static_folder = str(PROJECT_ROOT / "static")

# Database directory creation
db_dir = PROJECT_ROOT / "database"
db_dir.mkdir(parents=True, exist_ok=True)

# App Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_dir / 'interview_portal.db'}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ----------------------------------------------------------------------
# Flask-Mail Configuration (SMTP)
# Make sure to run these 2 commands first in shell for testing:
# export MAIL_USERNAME="hoangdeptrai61@gmail.com"
# export MAIL_PASSWORD="rxnj ferp zrig khha"
# ----------------------------------------------------------------------
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'your_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'your_app_password')
app.config['MAIL_DEFAULT_SENDER'] = (
    os.environ.get('MAIL_SENDER_NAME', 'AI Interview Portal'),
    app.config['MAIL_USERNAME']
)

mail = Mail(app)
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

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
# Email Helper Functions
# ----------------------------------------------------------------------
def send_verification_email(recipient_email, code):
    """Sends a 6-digit OTP code to the recipient's email address."""
    try:
        msg = Message(
            subject="Your AI Interview Portal Verification Code",
            recipients=[recipient_email]
        )
        msg.body = (
            f"Hello,\n\n"
            f"Your 6-digit email verification code is: {code}\n\n"
            f"This code will expire in 10 minutes.\n\n"
            f"If you did not request this, please ignore this email."
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending verification email: {e}")
        return False


def send_password_reset_email(recipient_email, reset_url):
    """Sends a password reset hyperlink to the user's email address."""
    try:
        msg = Message(
            subject="Password Reset Request - AI Interview Portal",
            recipients=[recipient_email]
        )
        msg.body = (
            f"Hello,\n\n"
            f"We received a request to reset your password. Please click the link below to set a new password:\n\n"
            f"{reset_url}\n\n"
            f"This link will expire in 1 hour.\n\n"
            f"If you did not request a password reset, please ignore this email."
        )
        msg.html = (
            f"<p>Hello,</p>"
            f"<p>We received a request to reset your password. Click the link below to set a new password:</p>"
            f"<p><a href='{reset_url}' style='color: #0d9488; font-weight: bold;'>Reset Your Password</a></p>"
            f"<p>This link will expire in 1 hour.</p>"
            f"<p>If you did not request a password reset, please ignore this email.</p>"
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending password reset email: {e}")
        return False

# ----------------------------------------------------------------------
# Authentication Routes
# ----------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password')

        # Check if user exists by username OR email
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('results_checker'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not username or not email or not password or not confirm_password:
            flash('Please fill out all fields.', 'danger')
            return render_template('signup.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html')

        if User.query.filter_by(username=username).first():
            flash('Username is already taken.', 'danger')
            return render_template('signup.html')

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return render_template('signup.html')

        # Generate 6-digit OTP code (valid for 10 minutes)
        verification_code = f"{random.randint(100000, 999999)}"
        session['pending_user'] = {
            'username': username,
            'email': email,
            'password': password,
            'code': verification_code,
            'expires_at': time.time() + 600  # 10 minutes
        }

        # Send actual email
        sent = send_verification_email(email, verification_code)
        if sent:
            flash(f'Verification code sent to {email}!', 'success')
        else:
            flash(f'Verification code could not be sent. Please check SMTP settings.', 'danger')

        return redirect(url_for('verify_email'))

    return render_template('signup.html')

@app.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    pending_user = session.get('pending_user')
    if not pending_user:
        flash('No pending registration found. Please sign up again.', 'warning')
        return redirect(url_for('signup'))

    if request.method == 'POST':
        code_input = request.form.get('code', '').strip()

        if time.time() > pending_user.get('expires_at', 0):
            session.pop('pending_user', None)
            flash('Verification code expired. Please sign up again.', 'danger')
            return redirect(url_for('signup'))

        if code_input == pending_user.get('code'):
            new_user = User(
                username=pending_user['username'],
                email=pending_user['email'],
                role='candidate'
            )
            new_user.set_password(pending_user['password'])
            db.session.add(new_user)
            db.session.commit()

            session.pop('pending_user', None)
            flash('Email verified! Account created successfully. Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid verification code. Please try again.', 'danger')

    return render_template('verify_email.html', email=pending_user.get('email'))

@app.route('/resend_code', methods=['POST'])
def resend_code():
    pending_user = session.get('pending_user')
    if not pending_user:
        flash('No active registration session. Please sign up again.', 'warning')
        return redirect(url_for('signup'))

    new_code = f"{random.randint(100000, 999999)}"
    pending_user['code'] = new_code
    pending_user['expires_at'] = time.time() + 600
    session['pending_user'] = pending_user

    sent = send_verification_email(pending_user['email'], new_code)
    if sent:
        flash(f'A new verification code has been sent to {pending_user["email"]}!', 'info')
    else:
        flash('Failed to resend code. Please verify server SMTP configuration.', 'danger')

    return redirect(url_for('verify_email'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()

        if user:
            token = serializer.dumps(user.email, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            sent = send_password_reset_email(user.email, reset_url)
            
            if sent:
                flash(f'A password reset link has been sent to {email}.', 'info')
            else:
                flash('Could not send reset email. Please try again later or check SMTP settings.', 'danger')
        else:
            # Protect user privacy by returning generic success message
            flash('If an account exists with that email, a password reset link has been sent.', 'info')

        return redirect(url_for('login'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception:
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first_or_404()

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        user.set_password(password)
        db.session.commit()

        flash('Your password has been updated! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)

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
    return render_template("home.html")

@app.route("/interview_portal")
def interview_portal():
    return render_template("index.html")

@app.route("/mic_test")
def mic_test():
    candidate = request.args.get("candidate", None)
    language = request.args.get("lang", "English")
    return render_template("mic_test.html", candidate=candidate, language=language)

@app.route("/results_checker")
@login_required
def results_checker():
    if current_user.is_admin:
        results = InterviewResult.query.order_by(InterviewResult.created_at.desc()).all()
    else:
        results = InterviewResult.query.filter_by(user_id=current_user.id).order_by(InterviewResult.created_at.desc()).all()

    return render_template("checker.html", results=results, is_admin=current_user.is_admin)

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