import networkx as nx

from rule_mining.graph_builder import (
    build_directed_graph,
    build_mining_graph,
    normalize_node_label,
    predicate_of,
    rule_name_of,
)

ROW = {
    "nodes": [
        {"id": "004", "type": "derived_fact", "label": "eqangle a d b c c d c d [004]", "layer": 3},
        {"id": "000", "type": "initial_fact", "label": "para a c b d [000]", "layer": 1},
        {"id": "005", "type": "final_fact", "label": "simtri a c d b d c [005]", "layer": 5},
        {"id": "r_a01_1", "type": "rule", "label": "a01_1", "layer": 2},
        {"id": "r_r34_1", "type": "rule", "label": "r34_1", "layer": 4},
    ],
    "links": [
        {"source": "000", "target": "r_a01_1", "type": "derivation"},
        {"source": "r_a01_1", "target": "004", "type": "derivation"},
        {"source": "004", "target": "r_r34_1", "type": "derivation"},
        {"source": "r_r34_1", "target": "005", "type": "derivation"},
    ],
}


def test_predicate_of():
    assert predicate_of("eqangle a d b c c d c d [004]") == "eqangle"
    assert predicate_of("para a c b d [000]") == "para"
    assert predicate_of("") == "?"


def test_rule_name_of():
    assert rule_name_of("a01_1") == "a01"
    assert rule_name_of("r_a01_1") == "a01"
    assert rule_name_of("r_r34_1") == "r34"
    assert rule_name_of("r34") == "r34"
    # 按仓库约定，label "r_5" 解读为规则 r 的第 5 次应用
    assert rule_name_of("r_5") == "r"


def test_normalize_node_label():
    assert normalize_node_label(ROW["nodes"][0]) == "derived_fact:eqangle"
    assert normalize_node_label(ROW["nodes"][3]) == "rule:a01"
    assert normalize_node_label(ROW["nodes"][3], strip_rule_index=False) == "rule:a01_1"


def test_directed_graph_direction():
    G = build_directed_graph(ROW)
    assert G.number_of_nodes() == 5
    assert G.number_of_edges() == 4
    # 前提方向：事实 -> 规则
    assert G.has_edge("000", "r_a01_1")
    # 结论方向：规则 -> 事实
    assert G.has_edge("r_r34_1", "005")
    assert G.nodes["r_a01_1"]["label"] == "rule:a01"


def test_mining_graph_semantics():
    G = build_mining_graph(ROW)
    assert G.number_of_nodes() == 5
    assert G.number_of_edges() == 4
    assert G["000"]["r_a01_1"]["label"] == "premise"
    assert G["r_r34_1"]["005"]["label"] == "conclusion"
    # 点无关标签：para 在两个事实节点上归一相同
    assert G.nodes["000"]["label"] == "initial_fact:para"


def test_mining_graph_parallel_edge_merge():
    row = {
        "nodes": [
            {"id": "f", "type": "initial_fact", "label": "cong a b c d [1]", "layer": 1},
            {"id": "r", "type": "rule", "label": "r1_1", "layer": 2},
        ],
        "links": [
            {"source": "f", "target": "r", "type": "derivation"},
            {"source": "r", "target": "f", "type": "derivation"},
        ],
    }
    G = build_mining_graph(row)
    assert G.number_of_edges() == 1
    assert G["f"]["r"]["label"] == "conclusion|premise"
