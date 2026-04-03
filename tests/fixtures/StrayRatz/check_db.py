from app import create_app, db
from app.models import User, Survey, NewsletterSubscriber
import inspect

app = create_app()

with app.app_context():
    # Print User model fields
    print("User Model Fields:")
    for attr in dir(User):
        if not attr.startswith('_') and not callable(getattr(User, attr)):
            print(f"  - {attr}")

    # Print Survey model fields
    print("\nSurvey Model Fields:")
    for attr in dir(Survey):
        if not attr.startswith('_') and not callable(getattr(Survey, attr)):
            print(f"  - {attr}")
