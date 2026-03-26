"""Auth routes."""
from services.auth import validate_credentials, generate_token


def login_handler(email: str, password: str) -> dict:
    """Handle POST /auth/login."""
    user = validate_credentials(email, password)
    if user is None:
        return {"error": "Invalid credentials", "status": 401}
    token = generate_token(user)
    return {"token": token, "status": 200}


def logout_handler(token: str) -> dict:
    """Handle POST /auth/logout."""
    return {"status": 200}
