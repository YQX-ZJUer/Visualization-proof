"""面向大数据集（如 geometry_clauses15_samples10k.jsonl）的批量统计。

一条命令完成：
1. 解析全部证明行（dataset_parser）；
2. 规则复用统计（数据集级：每条规则出现多少道证明、应用多少次）；
3. 频繁子图挖掘（gSpan）：宿主图按规范码去重、以证明数加权支持度、
   种子/扩展只用数据中观测到的标签组合（避免组合爆炸）；
4. 输出 JSON 结果 + matplotlib 统计图（规则复用 TopN、频繁子图 TopN）。

输出目录约定：``rule_mining/results/``
- ``mining_results.json``        合并结果（前端 /api/mining/results 直接读）
- ``rule_usage.json``            规则复用明细
- ``frequent_patterns.json``     频繁子图明细（含命名与复用数量）
- ``chart_rule_reuse.png``       规则复用统计图
- ``chart_frequent_subgraphs.png`` 频繁子图统计图
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .dataset_parser import parse_dataset
from .gspan import gspan
from .graph_builder import build_mining_graph
from .patterns import pattern_display_name, pattern_to_dict, pattern_to_rule_text
from .reuse_stats import compute_dataset_reuse

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _observed_index(
    graphs: Sequence[Any],
) -> Tuple[List[Tuple[str, str, str]], Dict[str, List[Tuple[str, str]]]]:
    """收集观测到的 (节点标签, 边标签, 节点标签) 组合及其按节点标签的索引。"""
    observed: set = set()
    by_label: Dict[str, set] = {}
    for g in graphs:
        for u, v in g.edges():
            lu = g.nodes[u].get("label", "")
            le = g[u][v].get("label", "")
            lv = g.nodes[v].get("label", "")
            observed.add((lu, le, lv))
            observed.add((lv, le, lu))
            by_label.setdefault(lu, set()).add((le, lv))
            by_label.setdefault(lv, set()).add((le, lu))
    by_label_sorted = {k: sorted(v) for k, v in by_label.items()}
    return sorted(observed), by_label_sorted


def _graph_features(g: Any) -> tuple:
    """同构不变的特征键（用于分桶；不同构的图也可能同桶，属安全误报）。"""
    node_labels = sorted(d.get("label", "") for _v, d in g.nodes(data=True))
    edge_labels = sorted(d.get("label", "") for _u, _v, d in g.edges(data=True))
    degs = sorted(
        (g.degree(v), d.get("label", "")) for v, d in g.nodes(data=True)
    )
    return (tuple(node_labels), tuple(edge_labels), tuple(degs))


def _wl_histogram(g: Any, rounds: int = 2) -> tuple:
    """Weisfeiler-Lehman 颜色细化直方图（同构不变，用于细分桶）。

    无全局重命名的迭代细化：每轮颜色 = (自身颜色, 排序后的
    (边标签, 邻居颜色) 多重集)；直方图 = 全部节点颜色的多重集。
    同构图的直方图必然相同；1-2 轮即可区分绝大多数非同构图，
    把桶内"相似但不同构"的图分开，避免成对同构判定的指数级开销。
    """
    colors = {v: str(d.get("label", "")) for v, d in g.nodes(data=True)}
    for _ in range(rounds):
        nxt = {}
        for v in g.nodes:
            sig = (
                colors[v],
                tuple(
                    sorted(
                        (g[v][w].get("label", ""), colors[w]) for w in g[v]
                    )
                ),
            )
            nxt[v] = str(sig)
        colors = nxt
    return tuple(sorted(colors.values()))


def _group_by_isomorphism(graphs: Sequence[Any]) -> Tuple[List[Any], List[int]]:
    """按同构精确分组，返回 (代表图列表, 权重列表)。

    大图上计算规范码成本高，改用：特征分桶 + WL 细化直方图分桶
    （两者均为同构不变，同构图必然同桶）+ 桶内与已有代表两两同构
    判定。桶内图"要么同构、要么 WL 两轮后仍不可分"，规模很小，
    判定安全且快。
    """
    from .gspan import isomorphic

    buckets: Dict[tuple, List[int]] = {}
    for i, g in enumerate(graphs):
        key = (_graph_features(g), _wl_histogram(g))
        buckets.setdefault(key, []).append(i)

    reps: List[Any] = []
    weights: List[int] = []
    for idxs in buckets.values():
        groups: List[int] = []  # 展开存储: [代表下标, 权重, 代表下标, 权重, ...]
        for i in idxs:
            g = graphs[i]
            matched = False
            for k in range(0, len(groups), 2):
                if isomorphic(graphs[groups[k]], g):
                    groups[k + 1] += 1
                    matched = True
                    break
            if not matched:
                groups.extend([i, 1])
        for k in range(0, len(groups), 2):
            reps.append(graphs[groups[k]])
            weights.append(groups[k + 1])
    return reps, weights


def mine_dataset(
    jsonl_path,
    min_support: int = 2,
    max_edges: int = 3,
    top_k: int = 100,
    occurrence_limit: int = 5,
    out_dir=None,
    max_rows: Optional[int] = None,
    make_charts: bool = True,
    verbose: bool = True,
) -> Dict[str, Any]:
    """解析数据集并完成复用统计与频繁子图挖掘。

    :param jsonl_path: JSONL 数据集路径
    :param min_support: 频繁子图最小支持度（出现该子图的证明数）
    :param max_edges: 子图最大边数
    :param top_k: 结果中保留的频繁子图数量（按支持度降序）
    :param out_dir: 结果目录，默认 rule_mining/results/
    :return: 合并结果 dict（与 mining_results.json 相同结构）
    """
    t0 = time.time()
    if verbose:
        print(f"[mine_dataset] 解析数据集 {jsonl_path} ...")
    rows, report = parse_dataset(jsonl_path, limit=max_rows)
    if verbose:
        print(f"[mine_dataset] 解析完成: {report} ({time.time() - t0:.1f}s)")
    if not rows:
        raise ValueError("数据集解析后为空")

    # 1) 规则复用（数据集级）
    reuse = compute_dataset_reuse(rows)
    if verbose:
        print(
            f"[mine_dataset] 规则复用统计完成: {len(reuse)} 条规则 "
            f"({time.time() - t0:.1f}s)"
        )

    # 2) 宿主图 + 加权去重（特征分桶 + 桶内同构判定，规避大图规范码开销）
    graphs = [build_mining_graph(r) for r in rows]
    db, weights = _group_by_isomorphism(graphs)
    if verbose:
        print(
            f"[mine_dataset] 宿主图 {len(rows)} 个，同构去重后 {len(db)} 个 "
            f"（最大权重 {max(weights)}）({time.time() - t0:.1f}s)"
        )

    observed_edges, obs_by_label = _observed_index(db)
    if verbose:
        print(
            f"[mine_dataset] 观测组合: 边三元组 {len(observed_edges)}，"
            f"按标签索引 {len(obs_by_label)} 组"
        )

    # 3) 频繁子图挖掘（加权支持度 + 观测剪枝 + occurrence-list 支持度计数）
    patterns = gspan(
        db,
        min_support=min_support,
        max_edges=max_edges,
        weights=weights,
        observed_edges=observed_edges,
        obs_by_label=obs_by_label,
        collect_occurrences=False,
    )
    if verbose:
        print(
            f"[mine_dataset] 频繁子图挖掘完成: {len(patterns)} 个模式 "
            f"(min_support={min_support}, max_edges={max_edges}) "
            f"({time.time() - t0:.1f}s)"
        )

    # TopN 补收集嵌入信息（只在各自宿主集合内扫描）
    from .gspan import occurrences_in

    top_patterns = patterns[:top_k]
    for p in top_patterns:
        p.occurrences = [
            (i, m)
            for i in p.host_set
            for m in occurrences_in(db[i], p.graph, limit=occurrence_limit)
        ]

    # 4) 汇总结果
    host_id_of = {i: f"distinct#{i}" for i in range(len(db))}
    all_pattern_dicts = []
    for p in patterns:
        d = pattern_to_dict(p, host_id_of=host_id_of, host_weights=weights)
        d["name"] = pattern_display_name(p)
        d["support"] = p.support
        d["n_edges"] = p.n_edges
        d["n_nodes"] = p.n_nodes
        d["rule_text"] = pattern_to_rule_text(p)
        all_pattern_dicts.append(d)

    results: Dict[str, Any] = {
        "meta": {
            "dataset": str(jsonl_path),
            "total_lines": report["total_lines"],
            "parsed_rows": report["parsed"],
            "json_errors": report["json_errors"],
            "no_proof": report["no_proof"],
            "distinct_graphs": len(db),
            "min_support": min_support,
            "max_edges": max_edges,
            "elapsed_seconds": round(time.time() - t0, 1),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "rule_usage": [d.to_dict() for d in reuse],
        "frequent_patterns": all_pattern_dicts[:top_k],  # 前端用 TopN
        "frequent_pattern_total": len(patterns),
    }

    out_dir = Path(out_dir) if out_dir else DEFAULT_RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mining_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "rule_usage.json").write_text(
        json.dumps(results["rule_usage"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "frequent_patterns.json").write_text(
        json.dumps(all_pattern_dicts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if make_charts:
        chart_paths = _make_charts(results, out_dir)
        results["meta"]["charts"] = chart_paths
        (out_dir / "mining_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if verbose:
        print(f"[mine_dataset] 结果已写入 {out_dir} ({time.time() - t0:.1f}s)")
    return results


def _make_charts(results: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    """matplotlib 统计图（Agg 后端，无中文依赖，英文标签）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    charts: Dict[str, str] = {}

    # 图 1：规则复用 Top30（按总应用次数）
    rules = results["rule_usage"][:30][::-1]
    names = [f"{r['name']}  (×{r['proofs']} proofs)" for r in rules]
    instances = [r["instances"] for r in rules]
    fig, ax = plt.subplots(figsize=(10, 9))
    ax.barh(names, instances, color="#4c78a8")
    ax.set_xlabel("Total rule applications (instances)")
    ax.set_title(
        f"Rule reuse across dataset (top {len(rules)}, "
        f"{results['meta']['parsed_rows']} proofs)"
    )
    for i, v in enumerate(instances):
        ax.text(v, i, f" {v}", va="center", fontsize=8)
    ax.margins(x=0.08)
    fig.tight_layout()
    chart1 = out_dir / "chart_rule_reuse.png"
    fig.savefig(chart1, dpi=150)
    plt.close(fig)
    charts["rule_reuse"] = chart1.name

    # 图 2：频繁子图 Top30（按支持度 = 复用数量）
    pats = results["frequent_patterns"][:30][::-1]
    labels = [
        f"{p['name'][:60]}  [{p['n_edges']}e]" for p in pats
    ]
    supports = [p["support"] for p in pats]
    fig, ax = plt.subplots(figsize=(11, 10))
    ax.barh(labels, supports, color="#e45756")
    ax.set_xlabel("Reuse count (proofs containing the subgraph)")
    ax.set_title(
        f"Frequent subgraphs (min_support={results['meta']['min_support']}, "
        f"max_edges={results['meta']['max_edges']}; top {len(pats)})"
    )
    for i, v in enumerate(supports):
        ax.text(v, i, f" {v}", va="center", fontsize=8)
    ax.margins(x=0.08)
    fig.tight_layout()
    chart2 = out_dir / "chart_frequent_subgraphs.png"
    fig.savefig(chart2, dpi=150)
    plt.close(fig)
    charts["frequent_subgraphs"] = chart2.name

    return charts
