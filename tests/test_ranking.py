"""Unit tests for ranking with N/A handling."""

from podcast_benchmark.ranking import rank_by


def _show(name, value):
    return {"name": name, "metrics": {"x": value}}


def test_rank_excludes_none_and_sorts_desc():
    shows = [
        _show("A", 10),
        _show("B", None),
        _show("C", 30),
        _show("D", 20),
    ]
    result = rank_by(shows, lambda s: s["metrics"]["x"])
    assert result["ranked"] == [("C", 30), ("D", 20), ("A", 10)]
    assert result["excluded"] == ["B"]


def test_rank_ascending():
    shows = [_show("A", 10), _show("B", 5), _show("C", 20)]
    result = rank_by(shows, lambda s: s["metrics"]["x"], higher_is_better=False)
    assert result["ranked"] == [("B", 5), ("A", 10), ("C", 20)]
    assert result["excluded"] == []


def test_all_none_yields_empty_ranking():
    shows = [_show("A", None), _show("B", None)]
    result = rank_by(shows, lambda s: s["metrics"]["x"])
    assert result["ranked"] == []
    assert result["excluded"] == ["A", "B"]
