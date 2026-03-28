from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app

from app import db, login_manager

# User loader moved to __init__.py

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Email verification
    email_confirmed = db.Column(db.Boolean, default=False)
    email_confirmation_token_created_at = db.Column(db.DateTime)
    password_reset_token_created_at = db.Column(db.DateTime)
    
    # Profile fields
    first_name = db.Column(db.String(64), nullable=True)
    last_name = db.Column(db.String(64), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(128), nullable=True)
    fitness_goals = db.Column(db.String(128), nullable=True)
    fitness_level = db.Column(db.String(32), nullable=True)
    
    surveys = db.relationship('Survey', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_email_confirmation_token(self):
        """Generate a token for email confirmation"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        self.email_confirmation_token_created_at = datetime.utcnow()
        db.session.commit()
        return s.dumps(self.email, salt='email-confirmation')
    
    def confirm_email(self, token, expiration=3600):
        """Verify the email confirmation token"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            email = s.loads(token, salt='email-confirmation', max_age=expiration)
        except (SignatureExpired, BadSignature):
            return False
        
        if email != self.email:
            return False
            
        self.email_confirmed = True
        db.session.commit()
        return True
    
    def generate_password_reset_token(self):
        """Generate a token for password reset"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        self.password_reset_token_created_at = datetime.utcnow()
        db.session.commit()
        return s.dumps(self.email, salt='password-reset')
    
    def verify_password_reset_token(self, token, expiration=3600):
        """Verify the password reset token"""
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            email = s.loads(token, salt='password-reset', max_age=expiration)
        except (SignatureExpired, BadSignature):
            return None
        
        if email != self.email:
            return None
            
        return self
    
    def __repr__(self):
        return f'<User {self.username}>'

class NewsletterSubscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=True)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<NewsletterSubscriber {self.email}>'

class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    email = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    current_supplements = db.Column(db.Text, nullable=True)
    interest_level = db.Column(db.Integer, nullable=False)
    price_preference = db.Column(db.String(64), nullable=True)
    heard_from = db.Column(db.String(64), nullable=True)
    
    # Enhanced survey fields
    effectiveness_rating = db.Column(db.Integer, nullable=True)
    value_rating = db.Column(db.Integer, nullable=True)
    convenience_rating = db.Column(db.Integer, nullable=True)
    specific_needs = db.Column(db.Text, nullable=True)
    pain_points = db.Column(db.Text, nullable=True)
    expected_benefits = db.Column(db.Text, nullable=True)
    purchase_likelihood = db.Column(db.Integer, nullable=True)
    
    additional_comments = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Survey {self.id} by {self.email}>' 