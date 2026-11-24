from rule_mining.reuse_stats import (
    add_reuse_fields,
    compute_dataset_reuse,
    compute_reuse_stats,
)

ROW = {
    "nodes": [
        {"id": "000", "type": "initial_fact", "label": "para a c b d [000]", "layer": 1},
        {"id": "001", "type": "initial_fact", "label": "para a d b c [001]", "layer": 1},
        {"id": "002", "type": "derived_fact", "label": "eqangle a d b c c d c d [002]", "layer": 2},
        {"id": "003", "type": "derived_fact", "label": "eqangle a c b d c d c d [003]", "layer": 2},
        {"id": "005", "type": "final_fact", "label": "simtri a c d b d c [005]", "layer": 3},
        {"id": "r_a01_1", "type": "rule", "label": "a01_1", "layer": 2},
        {"id": "r_a01_2", "type": "rule", "label": "a01_2", "layer": 2},
        {"id": "r_r34_1", "type": "rule", "label": "r34_1", "layer": 3},
    ],
    "links": [
        {"source": "000", "target": "r_a01_1", "type": "derivation"},
        {"source": "r_a01_1", "target": "003", "type": "derivation"},
        {"source": "001", "target": "r_a01_2", "type": "derivation"},
        {"source": "r_a01_2", "target": "002", "type": "derivation"},
        {"source": "002", "target": "r_r34_1", "type": "derivation"},
        {"source": "003", "target": "r_r34_1", "type": "derivation"},
        {"source": "r_r34_1", "target": "005", "type": "derivation"},
    ],
}


def test_single_row_rule_reuse():
    rep = compute_reuse_stats(ROW)
    assert rep.rules["a01"].instances == 2
    assert rep.rules["a01"].reused
    assert rep.rules["r34"].instances == 1
    assert rep.reused_rule_count == 1
    assert rep.distinct_rule_count == 2


def test_fact_fanout():
    rep = compute_reuse_stats(ROW)
    # 002、003 都各自只被一条规则当一次前提
    assert rep.fact_fanout["002"] == 1
    assert rep.fact_fanout["003"] == 1
    assert "000" not in rep.fact_fanout or rep.fact_fanout["000"] == 1


def test_add_reuse_fields():
    out = add_reuse_fields(ROW)
    by_id = {n["id"]: n for n in out["nodes"]}
    assert by_id["r_a01_1"]["reuse_group"] == "a01"
    assert by_id["r_a01_1"]["reuse_count"] == 2
    assert by_id["r_r34_1"]["reuse_count"] == 1
    assert by_id["002"]["reuse_group"] == "eqangle"
    # 原行不被修改
    assert "reuse_count" not in ROW["nodes"][0]


def test_dataset_reuse():
    rows = [ROW, ROW, ROW]
    dataset = compute_dataset_reuse(rows)
    by_name = {d.name: d for d in dataset}
    assert by_name["a01"].proofs == 3
    assert by_name["a01"].instances == 6
    assert by_name["r34"].instances == 3
    assert dataset[0].name == "a01"  # 按 proofs 降序，a01 与 r34 同 proofs，instances 多者在前
