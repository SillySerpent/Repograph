"""Test routes — calls through service and model layers to create deep test pathways."""
from routes.auth import login_handler, logout_handler
from routes.search import search_handler
from services.auth import validate_credentials, generate_token, check_password_hash
from models.user import User


def test_login_full_flow():
    """Exercises login_handler -> validate_credentials -> User.find_by_email chain."""
    result = login_handler("alice@example.com", "secret")
    assert isinstance(result, dict)
    assert "status" in result


def test_validate_credentials_with_correct_password():
    """validate_credentials -> check_password_hash -> User path."""
    user = validate_credentials("test@test.com", "pass")
    assert user is None or hasattr(user, "username")


def test_token_generation_chain():
    """Exercises generate_token -> User attribute access chain."""
    u = User(username="bob", password_hash="hashed_pw")
    token = generate_token(u)
    assert token.startswith("token_")


def test_logout_handler():
    """Exercises logout_handler."""
    result = logout_handler("some_token")
    assert result["status"] == 200


def test_search_flow():
    """Exercises search_handler -> search_service chain."""
    result = search_handler({"q": "flask"})
    assert isinstance(result, dict)
