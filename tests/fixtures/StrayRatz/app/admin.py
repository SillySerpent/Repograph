from flask import Blueprint, render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app import db
from app.models import User, NewsletterSubscriber, Survey

admin = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(func):
    """Decorator to require admin access for routes"""
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You must be an admin to access this page.', 'danger')
            return redirect(url_for('main.index'))
        return func(*args, **kwargs)
    decorated_view.__name__ = func.__name__
    return decorated_view

@admin.route('/')
@login_required
@admin_required
def dashboard():
    # Count statistics for dashboard
    user_count = User.query.count()
    subscriber_count = NewsletterSubscriber.query.count()
    survey_count = Survey.query.count()
    
    # Get the 5 most recent surveys
    recent_surveys = Survey.query.order_by(Survey.submitted_at.desc()).limit(5).all()
    
    # Calculate average interest level
    interest_avg = db.session.query(db.func.avg(Survey.interest_level)).scalar() or 0
    interest_avg = round(interest_avg, 1)  # Round to one decimal place
    
    # Get price preference distribution
    price_prefs = db.session.query(
        Survey.price_preference, 
        db.func.count(Survey.price_preference)
    ).group_by(Survey.price_preference).all()
    
    return render_template('admin/dashboard.html', 
                          title='Admin Dashboard',
                          user_count=user_count,
                          subscriber_count=subscriber_count,
                          survey_count=survey_count,
                          recent_surveys=recent_surveys,
                          interest_avg=interest_avg,
                          price_prefs=price_prefs)

@admin.route('/users')
@login_required
@admin_required
def users():
    # Get all users, sort by creation date (newest first)
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', 
                          title='User Management',
                          users=all_users)

@admin.route('/newsletters')
@login_required
@admin_required
def newsletters():
    # Get all newsletter subscribers, sort by subscription date (newest first)
    subscribers = NewsletterSubscriber.query.order_by(NewsletterSubscriber.subscribed_at.desc()).all()
    return render_template('admin/newsletters.html', 
                          title='Newsletter Subscribers',
                          subscribers=subscribers)

@admin.route('/surveys')
@login_required
@admin_required
def surveys():
    # Get all surveys, sort by submission date (newest first)
    all_surveys = Survey.query.order_by(Survey.submitted_at.desc()).all()
    return render_template('admin/surveys.html', 
                          title='Survey Results',
                          surveys=all_surveys)

@admin.route('/debug_surveys')
@login_required
@admin_required
def debug_surveys():
    # Get all surveys for debugging
    all_surveys = Survey.query.order_by(Survey.submitted_at.desc()).all()
    return render_template('admin/debug_surveys.html', 
                          title='Survey Debug',
                          surveys=all_surveys)

@admin.route('/survey/<int:survey_id>')
@login_required
@admin_required
def view_survey(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    return render_template('admin/survey_detail.html',
                          title=f'Survey #{survey.id}',
                          survey=survey)

@admin.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account!', 'danger')
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} has been deleted.', 'success')
    return redirect(url_for('admin.users'))

@admin.route('/delete_subscriber/<int:subscriber_id>', methods=['POST'])
@login_required
@admin_required
def delete_subscriber(subscriber_id):
    subscriber = NewsletterSubscriber.query.get_or_404(subscriber_id)
    db.session.delete(subscriber)
    db.session.commit()
    flash(f'Subscriber {subscriber.email} has been deleted.', 'success')
    return redirect(url_for('admin.newsletters'))