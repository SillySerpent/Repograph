"""Simple models module."""

class User:
    """A user entity."""
    def __init__(self, user_id: int, name: str, email: str):
        self.user_id = user_id
        self.name = name
        self.email = email

    def display(self) -> str:
        return f"{self.name} <{self.email}>"


class Product:
    """A product entity."""
    def __init__(self, product_id: int, name: str, price: float):
        self.product_id = product_id
        self.name = name
        self.price = price
