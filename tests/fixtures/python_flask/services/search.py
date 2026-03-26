"""Search service."""


def search_service(query: str, limit: int = 10) -> list:
    """Execute a search query."""
    results = run_db_query(query, limit)
    return rank_results(results)


def run_db_query(query: str, limit: int) -> list:
    """Run the database query."""
    return [{"id": 1, "text": f"result for {query}"}]


def rank_results(results: list) -> list:
    """Rank search results by relevance."""
    return sorted(results, key=lambda x: x.get("id", 0))
