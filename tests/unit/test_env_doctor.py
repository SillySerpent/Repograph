from __future__ import annotations

from repograph.diagnostics.env_doctor import collect_doctor_results


def test_doctor_uninitialized_message_mentions_sync(tmp_path) -> None:
    results = collect_doctor_results(repo_path=str(tmp_path), verbose=False)
    graph_open = next(r for r in results if r.name == "graph_open")
    assert "repograph sync" in graph_open.detail
    assert "init" in graph_open.detail
