"""频繁模式的结构化表达、可读描述与"复合规则"回写骨架。

挖掘出的 FrequentPattern 在这里被翻译成两类输出：
1. 人类可读的描述 / 签名（前端展示、论文报告用）；
2. 复合规则文本（rules.txt 风格）—— 当前是**点无关骨架**：变量统一
   （把前提与结论中的点对应起来）属于下一步研究内容，骨架里以占位符
   标注，见 :func:`pattern_to_rule_text` 的 docstring。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import networkx as nx

from .gspan import FrequentPattern, relabel_graph


def _label_of(G: nx.Graph, node: Any) -> str:
    return G.nodes[node].get("label", "?")


def _predicate_of(label: str) -> str:
    """``derived:eqangle`` -> ``eqangle``；``rule:a01`` -> ``a01``。"""
    return label.split(":", 1)[1] if ":" in label else label


def pattern_signature(pattern: nx.Graph) -> str:
    """紧凑签名：边三元组（节点标签, 边标签, 节点标签）排序拼接。"""
    triples = sorted(
        (
            _label_of(pattern, u),
            pattern[u][v].get("label", "?"),
            _label_of(pattern, v),
        )
        for u, v in pattern.edges()
    )
    return " ; ".join(f"{a} --{e}-> {b}" for a, e, b in triples)


def pattern_display_name(fp: FrequentPattern) -> str:
    """人类可读的子图命名（图表/前端列表用）。

    单规则星型：``r34: { eqangle, sameclock } => simtri``；
    一般模式：回退为三元组签名。
    """
    star = _single_rule_star(fp)
    if star:
        rule_node, premises, conclusions = star
        rule = _predicate_of(_label_of(fp.graph, rule_node))
        return f"{rule}: {{ {', '.join(premises)} }} => {', '.join(conclusions)}"
    return pattern_signature(fp.graph)


def describe_pattern(fp: FrequentPattern) -> str:
    """一段可读描述。"""
    return (
        f"支持度 {fp.support} / {fp.n_nodes} 节点 {fp.n_edges} 边："
        f"{pattern_signature(fp.graph)}"
    )


def _single_rule_star(fp: FrequentPattern) -> Optional[Tuple[Any, List[str], List[str]]]:
    """若模式是"单个规则节点 + 事实节点星型"，返回 (规则节点, 前提谓词, 结论谓词)。"""
    G = fp.graph
    rules = [v for v in G.nodes if _label_of(G, v).startswith("rule:")]
    if len(rules) != 1:
        return None
    r = rules[0]
    premises, conclusions = [], []
    for u, v in G.edges(r):
        el = G[u][v].get("label", "")
        other = v if u == r else u
        pred = _predicate_of(_label_of(G, other))
        if "conclusion" in el:
            conclusions.append(pred)
        elif "premise" in el:
            premises.append(pred)
        else:
            # 语义不明的边 -> 无法可靠判定角色
            return None
    if not premises or not conclusions:
        return None
    return r, sorted(premises), sorted(conclusions)


def pattern_to_rule_text(fp: FrequentPattern, name: Optional[str] = None) -> Optional[str]:
    """把"单规则星型"模式写成 rules.txt 风格复合规则文本。

    语法对照 default_configs/rules.txt：::

        <规则名> <描述>
        <前提谓词1>, <前提谓词2>, ... => <结论谓词1>, ...

    **当前输出是点无关骨架**：谓词里的点变量（a b c …）尚未统一 ——
    例如前提 eqangle 与结论 simtri 中的点如何一一对应，需要从出现频次
    与几何约束推理（下一步研究）。骨架会以大写占位符 A B C … 表示
    待统一的点，并加注释行说明。无法表达的一般模式返回 None。
    """
    star = _single_rule_star(fp)
    if star is None:
        return None
    rule_node, premises, conclusions = star
    rule_name = _predicate_of(_label_of(fp.graph, rule_node))
    name = name or f"mined_{rule_name}_sup{fp.support}"
    lines = [
        f"{name} mined composite rule (skeleton, point-unification TODO)",
        ", ".join(premises) + " => " + ", ".join(conclusions),
    ]
    return "\n".join(lines)


def pattern_to_dict(
    fp: FrequentPattern,
    host_id_of: Optional[Dict[int, str]] = None,
    host_weights: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """序列化（API / CLI 输出用）。host_id_of 把宿主下标映射成可读名，
    host_weights 记录每个宿主代表多少道证明（去重加权挖掘时使用）。"""
    G = relabel_graph(fp.graph)
    return {
        "support": fp.support,
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "signature": pattern_signature(fp.graph),
        "nodes": [
            {"id": n, "label": d.get("label", "")} for n, d in G.nodes(data=True)
        ],
        "edges": [
            {"source": u, "target": v, "label": G[u][v].get("label", "")}
            for u, v in G.edges()
        ],
        "rule_text": pattern_to_rule_text(fp),
        "occurrences": [
            {
                "host": host_id_of.get(gi, gi) if host_id_of else gi,
                "host_weight": host_weights[gi] if host_weights else None,
                "count_in_host": sum(1 for g, _m in fp.occurrences if g == gi),
            }
            for gi in sorted({g for g, _m in fp.occurrences})
        ],
    }


def patterns_to_json(
    patterns: Sequence[FrequentPattern],
    host_id_of: Optional[Dict[int, str]] = None,
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if top_k is not None:
        patterns = patterns[:top_k]
    return [pattern_to_dict(fp, host_id_of=host_id_of) for fp in patterns]
