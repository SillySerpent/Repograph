"""Main entry point."""
from services import find_user, get_user_display

def run(user_id: int) -> None:
    """Run the application."""
    display = get_user_display(user_id)
    print(display)

def _unused_helper() -> str:
    """This function is never called."""
    return "dead code"

if __name__ == "__main__":
    run(1)
