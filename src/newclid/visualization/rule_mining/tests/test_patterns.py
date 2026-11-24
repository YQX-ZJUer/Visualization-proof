import json

import networkx as nx

from rule_mining.gspan import gspan
from rule_mining.patterns import (
    describe_pattern,
    pattern_signature,
    pattern_to_dict,
    pattern_to_rule_text,
)


def _star_host():
    G = nx.Graph()
    G.add_node("f1", label="initial_fact:eqangle")
    G.add_node("f2", label="initial_fact:eqangle")
    G.add_node("f3", label="initial_fact:sameclock")
    G.add_node("f4", label="final_fact:simtri")
    G.add_node("r", label="rule:r34")
    G.add_edge("f1", "r", label="premise")
    G.add_edge("f2", "r", label="premise")
    G.add_edge("f3", "r", label="premise")
    G.add_edge("r", "f4", label="conclusion")
    return G


def test_rule_star_mining_and_text():
    h1, h2 = _star_host(), _star_host()
    patterns = gspan([h1, h2], min_support=2, max_edges=4)
    # 找到 4 边星型模式（支持 2）
    stars = [p for p in patterns if p.n_edges == 4]
    assert stars, "应挖到 4 边的规则星型模式"
    text = pattern_to_rule_text(stars[0])
    assert text is not None
    assert "r34" in text
    assert "eqangle" in text and "sameclock" in text and "simtri" in text
    assert "=>" in text


def test_signature_and_describe():
    G = _star_host()
    sig = pattern_signature(G)
    assert "premise" in sig and "conclusion" in sig and "rule:r34" in sig
    fp = gspan([G], min_support=1, max_edges=1)[0]
    desc = describe_pattern(fp)
    assert "支持度 1" in desc


def test_serializable():
    G = _star_host()
    patterns = gspan([G, G], min_support=2, max_edges=4)
    for p in patterns:
        d = pattern_to_dict(p, host_id_of={0: "proof_row0.json", 1: "proof_row1.json"})
        json.dumps(d, ensure_ascii=False)  # 必须可 JSON 序列化
        assert d["support"] == 2


def test_non_star_returns_none():
    G = nx.Graph()
    G.add_node(0, label="initial_fact:cong")
    G.add_node(1, label="derived_fact:cong")
    G.add_edge(0, 1, label="other")
    fp = gspan([G], min_support=1, max_edges=1)[0]
    assert pattern_to_rule_text(fp) is None
