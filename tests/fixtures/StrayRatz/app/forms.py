from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, TextAreaField, SelectField, RadioField, SelectMultipleField, widgets
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Regexp
from app.models import User
import re

class MultipleCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()

class PasswordComplexityValidator:
    def __init__(self, message=None):
        if message is None:
            self.message = ('Password must be at least 8 characters long and contain at least '
                          'one uppercase letter, one lowercase letter, and one number.')
        else:
            self.message = message
            
    def __call__(self, form, field):
        password = field.data
        
        # Check length
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters long.')
            
        # Check for at least one uppercase letter
        if not re.search(r'[A-Z]', password):
            raise ValidationError('Password must contain at least one uppercase letter.')
            
        # Check for at least one lowercase letter
        if not re.search(r'[a-z]', password):
            raise ValidationError('Password must contain at least one lowercase letter.')
            
        # Check for at least one digit
        if not re.search(r'\d', password):
            raise ValidationError('Password must contain at least one number.')
            
        # Removed special character requirement
        #if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        #    raise ValidationError('Password must contain at least one special character (!@#$%^&*(),.?":{}|<>).')


class RegistrationForm(FlaskForm):
    username = StringField('Username', 
                          validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email',
                       validators=[DataRequired(), Email()])
    password = PasswordField('Password', 
                            validators=[DataRequired(), PasswordComplexityValidator()])
    confirm_password = PasswordField('Confirm Password',
                                    validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')
    
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is taken. Please choose a different one.')
            
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is taken. Please choose a different one.')

class LoginForm(FlaskForm):
    email = StringField('Email',
                       validators=[DataRequired(), Email()])
    password = PasswordField('Password', 
                            validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

class RequestPasswordResetForm(FlaskForm):
    email = StringField('Email', 
                      validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')
    
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is None:
            raise ValidationError('There is no account with that email. You must register first.')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', 
                           validators=[DataRequired(), PasswordComplexityValidator()])
    confirm_password = PasswordField('Confirm New Password',
                                   validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')

class ResendConfirmationForm(FlaskForm):
    email = StringField('Email', 
                      validators=[DataRequired(), Email()])
    submit = SubmitField('Resend Confirmation Email')
    
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is None:
            raise ValidationError('There is no account with that email. You must register first.')

class ProfileForm(FlaskForm):
    first_name = StringField('First Name', validators=[Length(max=64)])
    last_name = StringField('Last Name', validators=[Length(max=64)])
    bio = TextAreaField('About Me', validators=[Length(max=500)])
    location = StringField('Location', validators=[Length(max=128)])
    fitness_goals = StringField('Fitness Goals', validators=[Length(max=128)])
    fitness_level = SelectField('Fitness Level', 
                              choices=[
                                  ('beginner', 'Beginner'),
                                  ('intermediate', 'Intermediate'),
                                  ('advanced', 'Advanced'),
                                  ('professional', 'Professional/Athlete')
                              ])
    submit = SubmitField('Update Profile')

class NewsletterForm(FlaskForm):
    name = StringField('Name (Optional)', validators=[Length(max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Subscribe')

class SurveyForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    
    current_supplements = MultipleCheckboxField('What supplements do you currently use? (Select all that apply)',
                                    choices=[
                                        ('none', 'None'),
                                        ('preworkout', 'Pre-workout'),
                                        ('protein', 'Protein'),
                                        ('bcaa', 'BCAAs'),
                                        ('creatine', 'Creatine'),
                                        ('vitamins', 'Vitamins'),
                                        ('fish_oil', 'Fish Oil/Omega-3'),
                                        ('mass_gainer', 'Mass Gainer'),
                                        ('fat_burners', 'Fat Burners'),
                                        ('other', 'Other')
                                    ])
    
    interest_level = RadioField('How interested are you in an all-in-one supplement solution?',
                              choices=[
                                  ('1', 'Not interested'),
                                  ('2', 'Slightly'),
                                  ('3', 'Moderate'),
                                  ('4', 'Very'),
                                  ('5', 'Extremely')
                              ], validators=[DataRequired()])
    
    # Enhanced rating fields
    effectiveness_rating = RadioField('How important is effectiveness to you when choosing supplements?',
                                   choices=[
                                       ('1', 'Not'),
                                       ('2', 'Slightly'),
                                       ('3', 'Moderate'),
                                       ('4', 'Very'),
                                       ('5', 'Extremely')
                                   ], validators=[DataRequired()])
    
    value_rating = RadioField('How important is value for money when choosing supplements?',
                           choices=[
                               ('1', 'Not'),
                               ('2', 'Slightly'),
                               ('3', 'Moderate'),
                               ('4', 'Very'),
                               ('5', 'Extremely')
                           ], validators=[DataRequired()])
    
    convenience_rating = RadioField('How important is convenience when choosing supplements?',
                                 choices=[
                                     ('1', 'Not'),
                                     ('2', 'Slightly'),
                                     ('3', 'Moderate'),
                                     ('4', 'Very'),
                                     ('5', 'Extremely')
                                 ], validators=[DataRequired()])
    
    price_preference = SelectField('What price range would you consider reasonable for our all-in-one supplement?',
                                 choices=[
                                     ('50to60', '$50-$60'),
                                     ('60to70', '$60-$70'),
                                     ('70to80', '$70-$80'),
                                     ('80to90', '$80-$90'),
                                     ('over90', 'Over $90')
                                 ])
    
    specific_needs = TextAreaField('What specific needs are you looking to address with supplements?',
                                validators=[Length(max=500)])
                                
    pain_points = TextAreaField('What frustrates you most about current supplement options?',
                             validators=[Length(max=500)])
                             
    expected_benefits = TextAreaField('What benefits would you expect from an all-in-one supplement?',
                                   validators=[Length(max=500)])
    
    purchase_likelihood = RadioField('How likely would you be to purchase our all-in-one supplement?',
                                  choices=[
                                      ('1', 'Very unlikely'),
                                      ('2', 'Unlikely'),
                                      ('3', 'Neutral'),
                                      ('4', 'Likely'),
                                      ('5', 'Very likely')
                                  ], validators=[DataRequired()])
    
    heard_from = RadioField('How did you hear about Hydra Fuel?',
                          choices=[
                              ('social', 'Social Media'),
                              ('friend', 'Friend or Family'),
                              ('search', 'Search Engine'),
                              ('ad', 'Online Advertisement'),
                              ('other', 'Other')
                          ])
    
    additional_comments = TextAreaField('Additional Comments')
    
    submit = SubmitField('Submit Survey') 