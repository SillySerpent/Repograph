"""Search routes."""
from services.search import search_service


def search_endpoint(query: str, limit: int = 10) -> dict:
    """Handle GET /search."""
    results = search_service(query, limit)
    return {"results": results, "count": len(results)}
