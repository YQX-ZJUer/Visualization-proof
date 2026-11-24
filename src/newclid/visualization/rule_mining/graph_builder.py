"""把证明行 JSON（nodes/links）转换成点无关的标注图。

设计要点（对应开题报告 4.1.4 的"算法适配"章节）：

1. 点无关标签化（point-agnostic labeling）：
   事实节点标注为 ``<type>:<predicate>``，例如 ``derived:eqangle``，
   丢弃点名字母（a b c d …）。同一几何推导结构在不同题目/不同点命名下
   因此可以被识别为同一模式 —— 这是频繁子图挖掘能跨题发现"复合规则"
   的前提。

2. 规则实例归并：
   规则节点 id 形如 ``r_a01_1``、标签形如 ``a01_1``，末尾 ``_<n>`` 是
   同一条规则在同一次证明中的第 n 次应用。挖掘时归并为规则名 ``a01``，
   否则每次应用都会成为孤立的"新模式"。

3. 方向语义保留：
   links 中 ``事实 -> 规则`` 是前提使用、``规则 -> 事实`` 是结论推导。
   复用分析使用有向图；挖掘使用无向图（经典 gSpan 的输入），但方向
   语义编码进边标签：``premise`` / ``conclusion``，不丢失信息。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import networkx as nx

FACT_TYPES = {"initial_fact", "derived_fact", "final_fact"}
RULE_TYPE = "rule"

_INSTANCE_SUFFIX = re.compile(r"^(.*)_(\d+)$")


def predicate_of(label: str) -> str:
    """取事实标签的第一个词作为谓词名，如 ``eqangle a d b c … [004]`` -> ``eqangle``。"""
    label = (label or "").strip()
    return label.split()[0] if label else "?"


def rule_name_of(label_or_id: str) -> str:
    """规则实例名 -> 规则名：``a01_1`` / ``r_a01_1`` -> ``a01``。

    约定（vis_proof.py 的导出格式）：规则节点 label 是规则名 + 实例后缀
    ``_<n>``，id 再带 ``r_`` 前缀。实例后缀指最后一个 ``_数字`` 段。
    仅当去掉 ``r_`` 前缀后仍符合"名字_数字"形状时才剥前缀，
    避免误伤真正以 r_ 开头的规则名。
    """
    s = (label_or_id or "").strip()
    if s.startswith("r_"):
        body = s[2:]
        if _INSTANCE_SUFFIX.match(body):
            s = body
    m = _INSTANCE_SUFFIX.match(s)
    if m and m.group(1):
        return m.group(1)
    return s


def normalize_node_label(node: Dict[str, Any], *, strip_rule_index: bool = True) -> str:
    """节点 -> 语义标签。rule 节点带 ``rule:`` 前缀，事实节点带类型前缀。"""
    ntype = node.get("type", "?")
    label = node.get("label") or node.get("id") or "?"
    if ntype == RULE_TYPE:
        name = rule_name_of(label) if strip_rule_index else str(label)
        return f"rule:{name}"
    return f"{ntype}:{predicate_of(str(label))}"


# ------------------------------------------------------------------ 加载

def load_row_file(path) -> Dict[str, Any]:
    """加载单个导出行 JSON（proof_row*.json）。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_rows(
    data_path,
    row_indices: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """加载导出行 JSON。

    data_path 可以是单个文件，也可以是目录（json_output/）。
    目录模式只取 ``proof_row<N>.json``；给出 row_indices 时按 <N> 过滤。
    """
    p = Path(data_path)
    if p.is_dir():
        files = sorted(p.glob("proof_row*.json"))
        if row_indices is not None:
            wanted = {f"proof_row{i}.json" for i in row_indices}
            files = [f for f in files if f.name in wanted]
        return [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if p.is_file():
        return [json.loads(p.read_text(encoding="utf-8"))]
    raise FileNotFoundError(f"数据路径不存在: {data_path}")


# ------------------------------------------------------------------ 建图

def build_directed_graph(
    row: Dict[str, Any], *, strip_rule_index: bool = True
) -> nx.DiGraph:
    """保留原方向的证明依赖图。

    节点属性: ``label`` = 语义标签, ``raw`` = 原始节点 dict。
    边属性:   ``type``  = 原始 link type（derivation）。
    边的方向: 事实 -> 规则（前提），规则 -> 事实（结论）。
    """
    nodes = row.get("nodes", [])
    links = row.get("links", [])
    G = nx.DiGraph()
    for n in nodes:
        nid = n.get("id", "?")
        G.add_node(
            nid,
            label=normalize_node_label(n, strip_rule_index=strip_rule_index),
            raw=n,
        )
    for l in links:
        s, t = l.get("source"), l.get("target")
        if s not in G or t not in G:
            continue
        G.add_edge(s, t, type=l.get("type", "derivation"))
    return G


def _edge_semantics(Gd: nx.DiGraph, u, v) -> str:
    """把有向边翻译成语义标签：premise / conclusion / other。"""
    lu = Gd.nodes[u].get("label", "")
    lv = Gd.nodes[v].get("label", "")
    u_rule = lu.startswith("rule:")
    v_rule = lv.startswith("rule:")
    if u_rule and not v_rule:
        return "conclusion"
    if v_rule and not u_rule:
        return "premise"
    return "other"


def build_mining_graph(
    row: Dict[str, Any], *, strip_rule_index: bool = True
) -> nx.Graph:
    """无向挖掘图：方向语义编码进边标签，并行边合并（多语义用 ``|`` 连接）。"""
    Gd = build_directed_graph(row, strip_rule_index=strip_rule_index)
    G = nx.Graph()
    for u, data in Gd.nodes(data=True):
        G.add_node(u, label=data["label"], raw=data["raw"])
    for u, v in Gd.edges():
        sem = _edge_semantics(Gd, u, v)
        if G.has_edge(u, v):
            old = str(G[u][v]["label"])
            if sem not in old:
                G[u][v]["label"] = "|".join(sorted([old, sem]))
        else:
            G.add_edge(u, v, label=sem)
    return G


def build_database(
    rows: Sequence[Dict[str, Any]], *, strip_rule_index: bool = True
) -> List[nx.Graph]:
    """多行 -> 挖掘图数据库。"""
    return [
        build_mining_graph(r, strip_rule_index=strip_rule_index) for r in rows
    ]
