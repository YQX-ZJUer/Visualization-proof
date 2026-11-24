"""规则节点复用统计。

两个层次：
- 证明内（单行）：同一条规则被应用几次（实例后缀 _1/_2/…），事实节点被几条
  规则当作前提（fan-out），以及同一事实是否被多条规则重复推出（冗余推导）。
- 数据集级（多行）：规则在多少道证明中出现、总应用次数、平均每次证明的应用数。

同时提供 ``add_reuse_fields``，为每个节点补 ``reuse_count`` / ``reuse_group``，
供前端"点击查看复用详情"直接使用（对应开题报告 4.1.3 细节查询功能）。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .graph_builder import (
    RULE_TYPE,
    build_directed_graph,
    normalize_node_label,
    rule_name_of,
)


@dataclass
class RuleUsage:
    name: str
    instances: int = 0
    conclusions: List[str] = field(default_factory=list)  # 推出的结论谓词

    @property
    def reused(self) -> bool:
        return self.instances >= 2


@dataclass
class ReuseReport:
    rules: Dict[str, RuleUsage] = field(default_factory=dict)
    fact_fanout: Dict[str, int] = field(default_factory=dict)  # 事实 id -> 前提使用次数
    redundant_facts: List[str] = field(default_factory=list)   # 被多条规则重复推出的事实 id

    @property
    def reused_rule_count(self) -> int:
        return sum(1 for r in self.rules.values() if r.reused)

    @property
    def distinct_rule_count(self) -> int:
        return len(self.rules)

    def summary(self) -> Dict[str, Any]:
        return {
            "distinct_rules": self.distinct_rule_count,
            "rule_instances": sum(r.instances for r in self.rules.values()),
            "reused_rules": self.reused_rule_count,
            "reused_rule_names": sorted(
                r.name for r in self.rules.values() if r.reused
            ),
            "redundant_facts": len(self.redundant_facts),
            "max_fact_fanout": max(self.fact_fanout.values(), default=0),
        }


def compute_reuse_stats(row: Dict[str, Any]) -> ReuseReport:
    """统计单个证明行的规则复用情况。"""
    report = ReuseReport()
    Gd = build_directed_graph(row)
    node_of = {n["id"]: n for n in row.get("nodes", [])}

    for n in row.get("nodes", []):
        nid = n["id"]
        if n.get("type") == RULE_TYPE:
            name = rule_name_of(n.get("label") or n.get("id") or "?")
            usage = report.rules.setdefault(name, RuleUsage(name=name))
            usage.instances += 1
            # 该规则实例推出的结论谓词
            for _u, v in Gd.out_edges(nid):
                lbl = normalize_node_label(node_of.get(v, {}))
                pred = lbl.split(":", 1)[1] if ":" in lbl else lbl
                if pred not in usage.conclusions:
                    usage.conclusions.append(pred)
        else:
            fanout = Gd.out_degree(nid)
            indeg = Gd.in_degree(nid)
            if fanout:
                report.fact_fanout[nid] = fanout
            if indeg >= 2:
                report.redundant_facts.append(nid)

    report.redundant_facts.sort()
    return report


def add_reuse_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """返回副本，节点上追加 reuse_count / reuse_group。

    - rule 节点: 复用组 = 规则名，reuse_count = 该规则在本证明的应用次数
    - 事实节点: reuse_group = 谓词名，reuse_count = 被多少条规则用作前提
    """
    out = copy.deepcopy(row)
    stats = compute_reuse_stats(out)

    rule_count = {name: r.instances for name, r in stats.rules.items()}
    for n in out.get("nodes", []):
        if n.get("type") == RULE_TYPE:
            name = rule_name_of(n.get("label") or n.get("id") or "?")
            n["reuse_group"] = name
            n["reuse_count"] = rule_count.get(name, 1)
        else:
            pred = (n.get("label") or "?").split()[0] if (n.get("label") or "").split() else "?"
            n["reuse_group"] = pred
            n["reuse_count"] = stats.fact_fanout.get(n["id"], 0)
    return out


@dataclass
class DatasetRuleUsage:
    name: str
    proofs: int = 0           # 出现该规则的证明数
    instances: int = 0        # 总应用次数
    conclusions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "proofs": self.proofs,
            "instances": self.instances,
            "avg_per_proof": round(self.instances / self.proofs, 2) if self.proofs else 0.0,
            "conclusions": self.conclusions,
        }


def compute_dataset_reuse(rows: Sequence[Dict[str, Any]]) -> List[DatasetRuleUsage]:
    """数据集级规则复用：按 proofs 数降序返回。"""
    agg: Dict[str, DatasetRuleUsage] = {}
    for row in rows:
        stats = compute_reuse_stats(row)
        for name, usage in stats.rules.items():
            d = agg.setdefault(name, DatasetRuleUsage(name=name))
            d.proofs += 1
            d.instances += usage.instances
            for c in usage.conclusions:
                if c not in d.conclusions:
                    d.conclusions.append(c)
    return sorted(agg.values(), key=lambda d: (-d.proofs, -d.instances, d.name))
