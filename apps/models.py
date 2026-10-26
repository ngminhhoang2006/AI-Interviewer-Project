from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='candidate', nullable=False) # 'candidate' or 'admin'
    
    # Relationship to candidate results
    results = db.relationship('InterviewResult', backref='candidate_user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'


class InterviewResult(db.Model):
    __tablename__ = 'interview_results'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    candidate_name = db.Column(db.String(100), nullable=False)
    language = db.Column(db.String(50), default='English')
    cv_score = db.Column(db.Float, nullable=True)
    interview_score = db.Column(db.Float, nullable=True)
    feedback_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ApplicantProfile(db.Model):
    """CV details of an applicant, linked to the user and to their interview result."""
    __tablename__ = 'applicant_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    interview_result_id = db.Column(db.Integer, db.ForeignKey('interview_results.id'),
                                    nullable=False, unique=True)

    full_name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    address = db.Column(db.String(255))
    age = db.Column(db.Integer)

    # Lists extracted from the CV, stored as JSON text
    education = db.Column(db.Text)
    experience = db.Column(db.Text)
    projects = db.Column(db.Text)
    skills = db.Column(db.Text)
    certifications = db.Column(db.Text)
    awards = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # result.applicant -> this profile (one-to-one); user.applicant_profiles -> list
    result = db.relationship('InterviewResult', backref=db.backref('applicant', uselist=False))
    user = db.relationship('User', backref='applicant_profiles')
