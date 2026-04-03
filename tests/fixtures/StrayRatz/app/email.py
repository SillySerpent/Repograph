from flask import current_app, render_template
from flask_mail import Message
from threading import Thread
import logging

def send_async_email(app, msg):
    """Send email asynchronously"""
    try:
        with app.app_context():
            from app import mail
            mail.send(msg)
    except Exception as e:
        # Log the error but don't crash
        logging.error(f"Failed to send email: {str(e)}")
        print(f"Email error: {str(e)}")

def send_email(subject, recipients, html_body, text_body=None):
    """Send an email with both HTML and plain text versions"""
    # Skip sending emails if verification is disabled
    if not current_app.config.get('EMAIL_VERIFICATION_REQUIRED', True):
        print(f"Email sending skipped: Email verification disabled")
        logging.info(f"Would have sent email: Subject: {subject}, To: {recipients}")
        return
    
    try:
        # Temporarily disabled actual email sending
        print(f"Email sending temporarily disabled: Subject: {subject}, To: {recipients}")
        logging.info(f"Email content (text): {text_body}")

        # Uncomment to re-enable email sending:
        # app = current_app._get_current_object()
        # msg = Message(subject, recipients=recipients)
        # msg.html = html_body
        # if text_body:
        #     msg.body = text_body
        # Thread(target=send_async_email, args=(app, msg)).start()
        
    except Exception as e:
        logging.error(f"Error preparing email: {str(e)}")
        print(f"Email preparation error: {str(e)}")

def send_password_reset_email(user):
    """Send password reset email to user"""
    token = user.generate_password_reset_token()
    reset_url = f"{current_app.config.get('SITE_URL', 'http://127.0.0.1:5001')}/reset-password/{token}"
    html = render_template('email/reset_password.html', user=user, reset_url=reset_url)
    text = f"Hello {user.username},\n\nTo reset your password, visit the following link:\n\n{reset_url}\n\nIf you did not request a password reset, please ignore this message.\n\nThank you,"
    
    send_email('Reset Your Password', [user.email], html, text)

def send_email_confirmation(user):
    """Send confirmation email to user"""
    token = user.generate_email_confirmation_token()
    confirm_url = f"{current_app.config.get('SITE_URL', 'http://127.0.0.1:5001')}/simple-verify/{token}"
    html = render_template('email/confirmation.html', user=user, confirm_url=confirm_url)
    text = f"Hello {user.username},\n\nPlease confirm your email by clicking on the following link:\n\n{confirm_url}\n\nThank you,"
    
    send_email('Confirm Your Email', [user.email], html, text) 