"""Rule Mining 子项目：规则节点复用分析与频繁子图（gSpan）挖掘。

面向开题报告 4.1.4 与创新点 4.2.2。不依赖 newclid 内部模块，
只依赖 networkx（api.py 可选依赖 fastapi，dataset_mining 可选依赖 matplotlib）。

入口：
- :func:`graph_builder.build_mining_graph` / :func:`build_database`
- :func:`reuse_stats.compute_reuse_stats` / :func:`compute_dataset_reuse`
- :func:`gspan.gspan`
- :func:`dataset_parser.parse_dataset`（JSONL 数据集解析）
- :func:`dataset_mining.mine_dataset`（批量统计 + 统计图）
- CLI: ``python3 -m rule_mining --dataset ...``
"""
from .gspan import FrequentPattern, canonical_code, gspan
from .graph_builder import (
    build_database,
    build_directed_graph,
    build_mining_graph,
    load_rows,
    normalize_node_label,
    predicate_of,
    rule_name_of,
)
from .patterns import (
    describe_pattern,
    pattern_display_name,
    pattern_signature,
    pattern_to_dict,
    pattern_to_rule_text,
    patterns_to_json,
)
from .reuse_stats import (
    ReuseReport,
    add_reuse_fields,
    compute_dataset_reuse,
    compute_reuse_stats,
)
from .dataset_parser import parse_data_row, parse_dataset

try:
    from .dataset_mining import mine_dataset
except ImportError:  # matplotlib 缺失等场景下仍可导入其余功能
    mine_dataset = None  # type: ignore

__all__ = [
    "FrequentPattern",
    "ReuseReport",
    "add_reuse_fields",
    "build_database",
    "build_directed_graph",
    "build_mining_graph",
    "canonical_code",
    "compute_dataset_reuse",
    "compute_reuse_stats",
    "describe_pattern",
    "gspan",
    "load_rows",
    "mine_dataset",
    "normalize_node_label",
    "parse_data_row",
    "parse_dataset",
    "pattern_display_name",
    "pattern_signature",
    "pattern_to_dict",
    "pattern_to_rule_text",
    "patterns_to_json",
    "predicate_of",
    "rule_name_of",
]
