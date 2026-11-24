"""CLI 演示/报告入口。

用法（在仓库根目录、装了 networkx 的环境下）::

    python3 -m newclid.visualization.rule_mining \
        --data-dir src/newclid/visualization/json_output \
        --min-support 1 --max-edges 5 --top-k 20 --out mining_report.json

默认数据目录为 ``visualization/json_output``。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "json_output"


def _require_deps() -> None:
    try:
        import networkx  # noqa: F401
    except ImportError as e:
        print("缺少依赖 networkx（远程环境用 apt 安装：apt-get install python3-networkx）", file=sys.stderr)
        raise SystemExit(2) from e


def build_report(
    data_path: str,
    min_support: int,
    max_edges: int,
    top_k: int,
) -> Dict[str, Any]:
    from .graph_builder import build_database, load_rows
    from .gspan import gspan
    from .patterns import patterns_to_json
    from .reuse_stats import compute_dataset_reuse, compute_reuse_stats

    rows = load_rows(data_path)
    if not rows:
        raise ValueError(f"未加载到任何证明行: {data_path}")

    dataset_reuse = compute_dataset_reuse(rows)
    database = build_database(rows)
    patterns = gspan(database, min_support=min_support, max_edges=max_edges)
    host_id_of = {
        i: f"proof_row{i}.json" for i in range(len(rows))
    }  # 行名统一用导出文件名约定

    return {
        "data_path": str(data_path),
        "rows": len(rows),
        "reuse_dataset": [d.to_dict() for d in dataset_reuse],
        "reuse_summary": [
            compute_reuse_stats(r).summary() for r in rows
        ],
        "mining_params": {"min_support": min_support, "max_edges": max_edges},
        "frequent_patterns": patterns_to_json(
            patterns, host_id_of=host_id_of, top_k=top_k
        ),
    }


def _print_report(report: Dict[str, Any]) -> None:
    print(f"== 数据: {report['data_path']}，证明行数 {report['rows']} ==")
    print()
    print("== 规则复用（数据集级，按出现证明数降序）==")
    for d in report["reuse_dataset"][:15]:
        print(
            f"  {d['name']:<12} proofs={d['proofs']:<3} instances={d['instances']:<4}"
            f" avg={d['avg_per_proof']:<5} conclusions={d['conclusions']}"
        )
    print()
    print("== 各行复用摘要 ==")
    for i, s in enumerate(report["reuse_summary"]):
        print(
            f"  row{i}: distinct={s['distinct_rules']} instances={s['rule_instances']} "
            f"reused={s['reused_rules']} {s['reused_rule_names']} "
            f"redundant_facts={s['redundant_facts']}"
        )
    print()
    print("== 频繁模式（复合规则候选）==")
    if not report["frequent_patterns"]:
        print("  （无）")
    for p in report["frequent_patterns"]:
        print(f"  sup={p['support']:<3} [{p['n_edges']} 边] {p['signature']}")
        if p.get("rule_text"):
            for line in p["rule_text"].splitlines():
                print("        " + line)
        occs = ", ".join(f"{o['host']}×{o['count_in_host']}" for o in p["occurrences"])
        print(f"        出现于: {occs}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="规则复用统计与频繁子图挖掘")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(_DEFAULT_DATA_DIR),
        help="导出行 JSON 目录（默认 visualization/json_output）",
    )
    parser.add_argument("--data", type=str, default=None, help="单个导出行 JSON 文件")
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="JSONL 数据集路径（如 generation/dataset/geometry_clauses15_samples10k.jsonl），"
        "启用批量模式：全量规则复用统计 + 频繁子图挖掘 + 统计图",
    )
    parser.add_argument("--min-support", type=int, default=1)
    parser.add_argument("--max-edges", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--out", type=str, default=None, help="报告 JSON 输出路径")
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="批量模式结果目录（默认 rule_mining/results/）",
    )
    parser.add_argument("--max-rows", type=int, default=None, help="批量模式最多解析行数")
    parser.add_argument(
        "--no-charts", action="store_true", help="批量模式不生成 matplotlib 统计图"
    )
    args = parser.parse_args(argv)

    _require_deps()

    if args.dataset:
        from .dataset_mining import mine_dataset

        mine_dataset(
            args.dataset,
            min_support=args.min_support,
            max_edges=args.max_edges,
            top_k=args.top_k,
            out_dir=args.out_dir,
            max_rows=args.max_rows,
            make_charts=not args.no_charts,
        )
        return 0

    data_path = args.data or args.data_dir
    report = build_report(
        data_path, min_support=args.min_support, max_edges=args.max_edges, top_k=args.top_k
    )
    _print_report(report)
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n报告已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
