import pytest

import rule_mining.api as api
from rule_mining.api import run_frequent, run_reuse


def _write_jsonl(tmp_path, row_data, n_rows=3):
    import json

    p = tmp_path / "d.jsonl"
    lines = [
        json.dumps(
            {
                "llm_input_renamed": row_data["llm_input_renamed"],
                "llm_output_renamed": row_data["llm_output_renamed"],
            },
            ensure_ascii=False,
        )
        for _ in range(n_rows)
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def test_run_reuse_jsonl(tmp_path, row_data):
    path = _write_jsonl(tmp_path, row_data, 3)
    out = run_reuse(path)
    rules = {d["name"]: d for d in out["dataset"]}
    assert rules["a01"]["proofs"] == 3
    assert rules["a01"]["instances"] == 3
    assert rules["r34"]["instances"] == 3
    assert "rows" not in out  # jsonl 模式不含逐行明细


def test_run_frequent_jsonl_needs_cache(tmp_path, row_data):
    path = _write_jsonl(tmp_path, row_data, 3)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    with pytest.raises(Exception):
        run_frequent(path, min_support=1, max_edges=3)
    monkeypatch.undo()


def test_run_frequent_jsonl_cache(tmp_path, row_data):
    import json as _json

    path = _write_jsonl(tmp_path, row_data, 3)
    cache = {
        "meta": {"parsed_rows": 3, "min_support": 2, "max_edges": 3},
        "frequent_patterns": [
            {
                "name": "x",
                "support": 5,
                "n_edges": 1,
                "n_nodes": 2,
                "rule_text": None,
                "signature": "a --x-> b",
                "nodes": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}],
                "edges": [{"source": 0, "target": 1, "label": "x"}],
                "occurrences": [],
            },
            {
                "name": "big",
                "support": 3,
                "n_edges": 5,
                "n_nodes": 6,
                "rule_text": None,
                "signature": "big",
                "nodes": [],
                "edges": [],
                "occurrences": [],
            },
        ],
    }
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    (tmp_path / "mining_results.json").write_text(
        _json.dumps(cache, ensure_ascii=False), encoding="utf-8"
    )
    out = run_frequent(path, min_support=4, max_edges=3)
    assert len(out["patterns"]) == 1
    assert out["patterns"][0]["name"] == "x"
    monkeypatch.undo()
