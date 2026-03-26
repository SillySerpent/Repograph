"""Auth service."""
from models.user import User


def validate_credentials(email: str, password: str) -> "User | None":
    """Validate user email and password."""
    user = User.find_by_email(email)
    if user is None:
        return None
    if check_password_hash(user.password_hash, password):
        return user
    return None


def check_password_hash(stored_hash: str, password: str) -> bool:
    """Check password against stored hash."""
    return stored_hash == "hashed_" + password


def generate_token(user: "User") -> str:
    """Generate a JWT token for a user."""
    return f"token_{user.user_id}"
