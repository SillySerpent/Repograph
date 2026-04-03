from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import json
import sqlalchemy as sa
from werkzeug.security import generate_password_hash

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message_category = 'info'
migrate = Migrate()
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
    strategy="fixed-window"  # More strict rate limiting strategy
)

def create_app(config_class=None):
    app = Flask(__name__)

    if config_class:
        app.config.from_object(config_class)
    else:
        # Fix the config import
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import Config
        app.config.from_object(Config)

    # Ensure the instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    
    # Configure CSRF protection to exclude GET requests
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    app.config['WTF_CSRF_METHODS'] = ['POST', 'PUT', 'PATCH', 'DELETE']
    
    # Define user loader function
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Add security headers middleware
    @app.after_request
    def add_security_headers(response):
        # Content Security Policy - restrict sources of content
        response.headers['Content-Security-Policy'] = "default-src 'self'; " \
                                                     "script-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://unpkg.com; " \
                                                     "style-src 'self' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com 'unsafe-inline'; " \
                                                     "img-src 'self' data: https:; " \
                                                     "font-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.gstatic.com; " \
                                                     "connect-src 'self'; " \
                                                     "form-action 'self'"
        
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # Enable browser XSS filtering
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Control referrer information
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        return response
    
    # Only exempt email confirmation route from CSRF protection
    csrf.exempt('app.routes.confirm_email')  # Email confirmation needs exemption for direct link access
    
    migrate.init_app(app, db)
    
    # Add custom Jinja filters
    @app.template_filter('from_json')
    def from_json(value):
        try:
            return json.loads(value) if value else []
        except:
            return []
    
    @app.template_filter('type')
    def get_type(value):
        return type(value).__name__
    
    # Register blueprints
    from app.routes import main
    from app.admin import admin
    
    app.register_blueprint(main)
    app.register_blueprint(admin, url_prefix='/admin')
    
    # Create database tables
    with app.app_context():
        try:
            # Create tables if they don't exist
            db.create_all()
            
            # Check if columns exist and add them if they don't
            inspector = sa.inspect(db.engine)
            if 'user' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('user')]
                
                # Add columns safely using SQLAlchemy Core for schema modifications
                try:
                    conn = db.engine.connect()
                    
                    # Add email_confirmed column if not exists
                    if 'email_confirmed' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN email_confirmed BOOLEAN DEFAULT FALSE'))
                    
                    # Add email_confirmation_token_created_at column if not exists
                    if 'email_confirmation_token_created_at' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN email_confirmation_token_created_at DATETIME'))
                    
                    # Add password_reset_token_created_at column if not exists
                    if 'password_reset_token_created_at' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN password_reset_token_created_at DATETIME'))
                    
                    # Add profile fields if they don't exist
                    if 'first_name' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN first_name VARCHAR(64)'))
                    
                    if 'last_name' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN last_name VARCHAR(64)'))
                    
                    if 'bio' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN bio TEXT'))
                    
                    if 'location' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN location VARCHAR(128)'))
                    
                    if 'fitness_goals' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN fitness_goals VARCHAR(128)'))
                    
                    if 'fitness_level' not in columns:
                        with conn.begin():
                            conn.execute(sa.text('ALTER TABLE user ADD COLUMN fitness_level VARCHAR(32)'))
                        
                    conn.close()
                except Exception as e:
                    print(f"Error adding columns: {e}")
            
            # Create default admin if no users exist
            admin_user = User.query.filter_by(username=app.config.get('ADMIN_USERNAME')).first()
            if not admin_user:
                admin_user = User(
                    username=app.config.get('ADMIN_USERNAME', 'admin'),
                    email=app.config.get('ADMIN_EMAIL', 'admin@hydrafuel.com'),
                    is_admin=True,
                    email_confirmed=True
                )
                
                # Set default password
                default_password = app.config.get('ADMIN_PASSWORD', 'admin')
                admin_user.password_hash = generate_password_hash(default_password)
                
                db.session.add(admin_user)
                db.session.commit()
                
                print(f"Default admin account created successfully.")
        except Exception as e:
            print(f"Error initializing database: {e}")
    
    return app 