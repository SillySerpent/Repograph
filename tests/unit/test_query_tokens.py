"""Search query tokenization."""
from repograph.search.query_tokens import tokenize_search_query


def test_multi_word_query():
    assert tokenize_search_query("ChampionBot on_tick") == ["ChampionBot", "on_tick"]


def test_dedup_case_insensitive():
    assert tokenize_search_query("foo Foo") == ["foo"]


def test_empty():
    assert tokenize_search_query("  ") == []
