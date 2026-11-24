"""从 JSONL 数据集行解析证明图（复刻 vis_proof.py 的解析逻辑，自包含）。

数据集行格式（generation/dataset/*.jsonl）：::

    {"llm_input_renamed": "<problem> … </problem>",
     "llm_output_renamed": "<numerical_check> … </numerical_check> <proof> … </proof>",
     ...}

输出：与 vis_proof.export_to_json 相同形状的行 dict（nodes/links），
可直接交给 rule_mining 的 graph_builder / reuse_stats / gspan。

不依赖 newclid / graphviz，最小环境（仅标准库）即可解析。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_PROBLEM = re.compile(r"<problem>(.*?)</problem>", re.DOTALL)
_NUMERICAL = re.compile(r"<numerical_check>(.*?)</numerical_check>", re.DOTALL)
_PROOF = re.compile(r"<proof>(.*?)</proof>", re.DOTALL)
_LABEL = re.compile(r"\[(\d{3})\]")
_FACT = re.compile(r"([^\[\]]+?\[\d{3}\])")


def extract_facts_from_tag(content: str, tag_pattern) -> Dict[str, str]:
    """复刻 vis_proof.extract_facts_from_tag：编号 -> 事实语句。"""
    match = tag_pattern.search(content)
    if not match:
        return {}
    stmt_map: Dict[str, str] = {}
    tag_content = match.group(1).strip()
    for segment in [s.strip() for s in tag_content.split(";") if s.strip()]:
        parts = [p.strip() for p in segment.split(":") if p.strip()]
        if len(parts) < 2:
            facts = _FACT.findall(segment)
        else:
            value = ":".join(parts[1:])
            facts = _FACT.findall(value)
        for fact in facts:
            m = _LABEL.search(fact)
            if m:
                stmt_map[m.group(1)] = fact.strip()
    return stmt_map


def parse_problem_facts(llm_input: str) -> Dict[str, str]:
    return extract_facts_from_tag(llm_input, _PROBLEM)


def parse_numerical_check_facts(llm_output: str) -> Dict[str, str]:
    return extract_facts_from_tag(llm_output, _NUMERICAL)


def adjust_node_layers(rule_nodes, edges, node_layer) -> Dict[str, int]:
    """复刻 vis_proof.adjust_node_layers：偶数层规则的前提对齐到同一层。"""
    for rule_node in rule_nodes:
        premises = [u for u, v in edges if v == rule_node]
        if not premises:
            continue
        rule_layer = node_layer.get(rule_node, 0)
        if rule_layer % 2 == 0:
            target = rule_layer - 1
            for p in premises:
                node_layer[p] = target
    return node_layer


def parse_proof_relations(
    llm_output: str, initial_stmt_map: Dict[str, str]
) -> Optional[Tuple[Dict[str, str], set, set, List[Tuple[str, str]], Dict[str, int], set]]:
    """复刻 vis_proof.parse_proof_relations。"""
    proof_match = _PROOF.search(llm_output)
    if not proof_match:
        return None
    proof_lines = [
        line.strip()
        for line in proof_match.group(1).strip().split(";")
        if line.strip()
    ]
    stmt_map = dict(initial_stmt_map)
    initial_fact_nodes = set(initial_stmt_map)
    fact_nodes = set(initial_fact_nodes)
    rule_nodes: set = set()
    edges: List[Tuple[str, str]] = []
    node_layer = {label: 1 for label in fact_nodes}

    for line in proof_lines:
        concl_match = re.search(r"(.*?\[\d{3}\])", line)
        if not concl_match:
            continue
        concl_part = concl_match.group(1).strip()
        rule_prem_part = line.replace(concl_part, "", 1).strip()
        concl_label_match = _LABEL.search(concl_part)
        if not concl_label_match:
            continue
        concl_label = concl_label_match.group(1)
        stmt_map[concl_label] = concl_part
        fact_nodes.add(concl_label)
        node_layer.setdefault(concl_label, 1)

        rule_match = re.search(r"^(\w+)", rule_prem_part)
        if not rule_match:
            continue
        rule_name = rule_match.group(1)
        n_same = len([rn for rn in rule_nodes if rn.startswith(f"r_{rule_name}")])
        rule_node = f"r_{rule_name}_{n_same + 1}"
        rule_nodes.add(rule_node)

        premise_labels = re.findall(r"(\d{3})", rule_prem_part)
        valid_premises = [p for p in premise_labels if p in stmt_map]
        if not valid_premises:
            continue

        prem_layers = [node_layer[p] for p in valid_premises]
        rule_layer = max(prem_layers) + 1
        concl_layer = rule_layer + 1
        node_layer[rule_node] = rule_layer
        node_layer[concl_label] = concl_layer

        for p in valid_premises:
            edges.append((p, rule_node))
        edges.append((rule_node, concl_label))

    return stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes


def parse_data_row(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """一行 JSONL -> nodes/links 行 dict（同 export_to_json 结构）。

    优先 llm_input_renamed / llm_output_renamed，缺失时回退未改名字段。
    无法解析 <proof> 时返回 None。
    """
    llm_input = data.get("llm_input_renamed") or data.get("llm_input") or ""
    llm_output = (
        data.get("llm_output_renamed") or data.get("llm_output") or ""
    )

    problem_facts = parse_problem_facts(llm_input)
    numerical_facts = parse_numerical_check_facts(llm_output)
    all_facts = {**problem_facts, **numerical_facts}

    result = parse_proof_relations(llm_output, all_facts)
    if not result or result[0] is None:
        return None
    stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes = result
    node_layer = adjust_node_layers(rule_nodes, edges, node_layer)

    fact_layers = {n: node_layer[n] for n in fact_nodes if n in node_layer}
    max_layer = max(fact_layers.values()) if fact_layers else 0
    final_nodes = {n for n, l in fact_layers.items() if l == max_layer}

    nodes = []
    for label in fact_nodes:
        if label in initial_fact_nodes:
            node_type = "initial_fact"
        elif label in final_nodes:
            node_type = "final_fact"
        else:
            node_type = "derived_fact"
        shape = "ellipse" if node_type == "initial_fact" else "box"
        nodes.append(
            {
                "id": label,
                "type": node_type,
                "label": stmt_map[label],
                "layer": node_layer.get(label, 1),
                "shape": shape,
                "final": label in final_nodes,
            }
        )
    for rule_node in rule_nodes:
        rule_label = "_".join(rule_node.split("_")[1:])
        nodes.append(
            {
                "id": rule_node,
                "type": "rule",
                "label": rule_label,
                "layer": node_layer.get(rule_node, 1),
                "shape": "diamond",
                "final": False,
            }
        )
    links = [{"source": u, "target": v, "type": "derivation"} for u, v in edges]
    return {"nodes": nodes, "links": links}


def parse_dataset(
    jsonl_path, limit: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """解析整个 JSONL 数据集。

    :return: (行列表, 报告)。行 = nodes/links dict；跳过 JSON 错误行与
             无法解析 <proof> 的行。
    """
    rows: List[Dict[str, Any]] = []
    report = {"total_lines": 0, "json_errors": 0, "no_proof": 0, "parsed": 0}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if limit is not None and report["parsed"] >= limit:
                break
            line = line.strip()
            if not line:
                continue
            report["total_lines"] += 1
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                report["json_errors"] += 1
                continue
            row = parse_data_row(data)
            if row is None:
                report["no_proof"] += 1
                continue
            rows.append(row)
            report["parsed"] += 1
    return rows, report
