"""Service layer."""
from models import User, Product

def find_user(user_id: int) -> User | None:
    """Find a user by ID."""
    if user_id == 1:
        return User(1, "Alice", "alice@example.com")
    return None

def find_product(product_id: int) -> Product | None:
    """Find a product by ID."""
    if product_id == 1:
        return Product(1, "Widget", 9.99)
    return None

def get_user_display(user_id: int) -> str:
    """Get formatted display for a user."""
    user = find_user(user_id)
    if user is None:
        return "Unknown user"
    return user.display()
