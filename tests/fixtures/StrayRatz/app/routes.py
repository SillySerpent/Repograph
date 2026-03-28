from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app, session
from flask_login import login_user, current_user, logout_user, login_required
from werkzeug.security import generate_password_hash
import json

from app import db
from app.models import User, NewsletterSubscriber, Survey
from app.forms import (RegistrationForm, LoginForm, NewsletterForm, SurveyForm, ProfileForm,
                      RequestPasswordResetForm, ResetPasswordForm, ResendConfirmationForm)
from app.email import send_password_reset_email, send_email_confirmation
from app import limiter
from config import Config

main = Blueprint('main', __name__)

@main.route('/')
@main.route('/home')
def index():
    from datetime import datetime
    newsletter_form = NewsletterForm()
    now = datetime.now()
    return render_template('index.html', title='Hydra Fuel - All-In-One Supplement', form=newsletter_form, now=now)

@main.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per minute, 10 per hour, 20 per day")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            email_confirmed=True  # Temporarily auto-confirm all emails
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        
        # Email verification is disabled
        flash('Your account has been created! You can now log in.', 'success')
            
        return redirect(url_for('main.login'))
    return render_template('register.html', title='Register', form=form)

@main.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute, 15 per hour, 30 per day")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # Clear flash messages if this is a verification redirect
    if request.args.get('verified') == 'True' and request.method == 'GET':
        session.pop('_flashes', None)
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            # Email verification check disabled
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            if user.is_admin:
                return redirect(next_page or url_for('admin.dashboard'))
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html', title='Login', form=form)

@main.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@main.route('/reset-password-request', methods=['GET', 'POST'])
@limiter.limit("3 per minute, 10 per hour")
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = RequestPasswordResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            send_password_reset_email(user)
        flash('If your email is registered with us, we\'ve sent instructions to reset your password.', 'info')
        return redirect(url_for('main.login'))
    
    return render_template('reset_password_request.html', title='Reset Password', form=form)

@main.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # Try to find user by token
    try:
        from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        email = s.loads(token, salt='password-reset', max_age=3600)  # 1 hour
        user = User.query.filter_by(email=email).first()
        
        if user is None:
            flash('Invalid user.', 'danger')
            return redirect(url_for('main.reset_request'))
    except SignatureExpired:
        flash('The password reset link has expired.', 'danger')
        return redirect(url_for('main.reset_request'))
    except BadSignature:
        flash('The password reset link is invalid.', 'danger')
        return redirect(url_for('main.reset_request'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset! You can now log in with your new password.', 'success')
        return redirect(url_for('main.login'))
    
    return render_template('reset_password.html', title='Reset Password', form=form)

@main.route('/resend-confirmation', methods=['GET', 'POST'])
@limiter.limit("3 per minute, 10 per hour")
def resend_confirmation():
    if current_user.is_authenticated and current_user.email_confirmed:
        return redirect(url_for('main.index'))
    
    form = ResendConfirmationForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and not user.email_confirmed:
            send_email_confirmation(user)
            flash('A new confirmation email has been sent. Please check your inbox.', 'success')
            return redirect(url_for('main.login'))
        elif user and user.email_confirmed:
            flash('Your email is already confirmed. Please login.', 'info')
            return redirect(url_for('main.login'))
    
    return render_template('resend_confirmation.html', title='Resend Confirmation Email', form=form)

@main.route('/confirm-email/<token>')
def confirm_email(token):
    if current_user.is_authenticated and current_user.email_confirmed:
        return redirect(url_for('main.index'))
    
    form = ResendConfirmationForm()
    
    # Try to find user by email in token
    try:
        from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        email = s.loads(token, salt='email-confirmation', max_age=86400)  # 24 hours
        user = User.query.filter_by(email=email).first()
        
        if user is None:
            flash('Invalid user.', 'danger')
            return render_template('confirm_email.html', title='Confirm Email', confirmed=False, form=form)
        
        if user.email_confirmed:
            flash('Email already confirmed. Please login.', 'info')
            return redirect(url_for('main.login'))
        
        user.email_confirmed = True
        db.session.commit()
        flash('Your email has been confirmed! You can now log in.', 'success')
        return render_template('confirm_email.html', title='Confirm Email', confirmed=True)
        
    except SignatureExpired:
        flash('The confirmation link has expired.', 'danger')
    except BadSignature:
        flash('The confirmation link is invalid.', 'danger')
    
    return render_template('confirm_email.html', title='Confirm Email', confirmed=False, form=form)

@main.route('/profile')
@login_required
def profile():
    return render_template('profile.html', title=f"{current_user.username}'s Profile")

@main.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.first_name = form.first_name.data
        current_user.last_name = form.last_name.data
        current_user.bio = form.bio.data
        current_user.location = form.location.data
        current_user.fitness_goals = form.fitness_goals.data
        current_user.fitness_level = form.fitness_level.data
        db.session.commit()
        flash('Your profile has been updated!', 'success')
        return redirect(url_for('main.profile'))
    elif request.method == 'GET':
        form.first_name.data = current_user.first_name
        form.last_name.data = current_user.last_name
        form.bio.data = current_user.bio
        form.location.data = current_user.location
        form.fitness_goals.data = current_user.fitness_goals
        form.fitness_level.data = current_user.fitness_level
    return render_template('edit_profile.html', title='Edit Profile', form=form)

@main.route('/my-surveys')
@login_required
def my_surveys():
    surveys = Survey.query.filter_by(user_id=current_user.id).order_by(Survey.submitted_at.desc()).all()
    return render_template('my_surveys.html', title='My Surveys', surveys=surveys)

@main.route('/shop')
def shop():
    newsletter_form = NewsletterForm()
    return render_template('shop.html', title='Shop - Coming Soon', form=newsletter_form)

@main.route('/survey', methods=['GET', 'POST'])
def survey():
    if current_user.is_authenticated and not current_user.is_admin:
        existing_survey = Survey.query.filter_by(user_id=current_user.id).first()
        if existing_survey:
            flash('You have already completed the survey. Thank you for your feedback!', 'info')
            return redirect(url_for('main.profile'))
    
    form = SurveyForm()
    
    # Autofill form with user data if authenticated
    if current_user.is_authenticated and request.method == 'GET':
        # Use username if first_name/last_name not available
        if current_user.first_name:
            form.name.data = f"{current_user.first_name} {current_user.last_name or ''}".strip()
        else:
            form.name.data = current_user.username
        form.email.data = current_user.email
        
    if form.validate_on_submit():
        supplements_json = json.dumps(form.current_supplements.data)
        
        survey = Survey(
            email=form.email.data,
            name=form.name.data,
            current_supplements=supplements_json,
            interest_level=int(form.interest_level.data),
            price_preference=form.price_preference.data,
            heard_from=form.heard_from.data,
            additional_comments=form.additional_comments.data,
            effectiveness_rating=int(form.effectiveness_rating.data),
            value_rating=int(form.value_rating.data),
            convenience_rating=int(form.convenience_rating.data),
            specific_needs=form.specific_needs.data,
            pain_points=form.pain_points.data,
            expected_benefits=form.expected_benefits.data,
            purchase_likelihood=int(form.purchase_likelihood.data)
        )
        if current_user.is_authenticated:
            survey.user_id = current_user.id
            
        db.session.add(survey)
        db.session.commit()
        flash('Thank you for completing our survey!', 'success')
        return redirect(url_for('main.thank_you'))
    return render_template('survey.html', title='Product Survey', form=form)

@main.route('/thank-you')
def thank_you():
    return render_template('thank_you.html', title='Thank You')

@main.route('/api/subscribe', methods=['POST'])
def newsletter_subscribe():
    form = NewsletterForm()
    print("Newsletter subscription attempt:", request.form)
    
    if form.validate_on_submit():
        existing = NewsletterSubscriber.query.filter_by(email=form.email.data).first()
        if existing:
            return jsonify({'success': False, 'message': 'Email already subscribed'})
            
        subscriber = NewsletterSubscriber(
            email=form.email.data,
            name=form.name.data if form.name.data else None
        )
        db.session.add(subscriber)
        db.session.commit()
        print("Successfully subscribed:", form.email.data)
        return jsonify({'success': True, 'message': 'Successfully subscribed to newsletter'})
    
    print("Form validation errors:", form.errors)
    return jsonify({'success': False, 'message': 'Invalid form data. Please check your email format.'})

@main.route('/privacy-policy')
def privacy_policy():
    from datetime import datetime
    now = datetime.now()
    return render_template('privacy_policy.html', title='Privacy Policy', config=Config, now=now)

@main.route('/terms-of-service')
def terms_of_service():
    from datetime import datetime
    now = datetime.now()
    return render_template('terms_of_service.html', title='Terms of Service', config=Config, now=now)

@main.route('/about')
def about():
    from datetime import datetime
    now = datetime.now()
    return render_template('about.html', title='About Hydra Fuel', now=now)

@main.route('/verify/<token>')
def verify_email(token):
    """Alternative email verification endpoint that should work even with CSRF protection"""
    try:
        from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        email = s.loads(token, salt='email-confirmation', max_age=86400)  # 24 hours
        user = User.query.filter_by(email=email).first()
        
        if user is None:
            return "Invalid user. Please contact support."
        
        if user.email_confirmed:
            return "Email already confirmed. You can now <a href='/login'>log in</a>."
        
        user.email_confirmed = True
        db.session.commit()
        return "Your email has been successfully confirmed! You can now <a href='/login'>log in</a>."
        
    except SignatureExpired:
        return "The confirmation link has expired. Please request a new confirmation email."
    except BadSignature:
        return "Invalid confirmation link. Please request a new confirmation email."
        
@main.route('/simple-verify/<token>')
def simple_verify(token):
    """Ultra-simple verification endpoint with minimal Flask dependencies"""
    try:
        # Manual database connection to avoid potential middleware issues
        from app import db
        from app.models import User
        from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
        
        # Manually get the secret key to avoid potential issues with current_app
        from flask import current_app
        secret_key = current_app.config.get('SECRET_KEY', 'fallback-key')
        
        # Deserialize the token
        s = URLSafeTimedSerializer(secret_key)
        email = s.loads(token, salt='email-confirmation', max_age=86400)  # 24 hours
        
        # Find the user
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash('User not found. Please contact support.', 'danger')
            return redirect(url_for('main.login'))
            
        # Update user and commit
        user.email_confirmed = True
        db.session.commit()
        
        # Redirect to login page with success parameter
        return redirect(url_for('main.login', verified=True))
        
    except SignatureExpired:
        flash('The email verification link has expired. Please request a new one.', 'warning')
        return redirect(url_for('main.resend_confirmation'))
    except BadSignature:
        flash('Invalid verification link. Please request a new one.', 'danger')
        return redirect(url_for('main.resend_confirmation'))
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('main.login'))

@main.route('/test-access')
def test_access():
    """Simple route to test if the server is accessible without CSRF issues"""
    return """
    <html>
        <head><title>Server Access Test</title></head>
        <body>
            <h1>Server Access Successful</h1>
            <p>If you can see this page, the server is accessible and not blocking your requests.</p>
        </body>
    </html>
    """

@main.route('/health')
def health_check():
    """Health check endpoint for Railway.com monitoring"""
    return jsonify({"status": "healthy"}) 