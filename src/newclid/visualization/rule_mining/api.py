"""FastAPI 路由：复用统计与频繁子图挖掘接口。

集成到 vis_webapp 的方式（两步，不改动本模块）：

.. code:: python

    sys.path.insert(0, os.path.dirname(_BASE))   # visualization 目录
    from rule_mining.api import router as mining_router
    app.include_router(mining_router)

接口约定：

- ``POST /api/mining/reuse``
    body: ``{"data_path": str, "row_indices": [int] | null}``
    data_path 可为导出行 JSON/目录，或 .jsonl 数据集（后者做全量统计，结果缓存）。
    返回: 数据集级规则复用表 + 各行复用统计（jsonl 模式不含逐行明细）。
- ``POST /api/mining/frequent``
    body: ``{"data_path": str, "min_support": 2, "max_edges": 6, "top_k": 50}``
    jsonl 模式读取批处理结果缓存（rule_mining/results/mining_results.json，
    由 ``python3 -m rule_mining --dataset ...`` 生成），按参数过滤；
    导出行模式现场挖掘。
- ``GET /api/mining/results``
    返回批处理缓存（前端 mining.html 的数据源）。
- ``GET /api/mining/health``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import APIRouter, HTTPException
except ImportError:  # 环境没有 fastapi 时仍可导入本模块（只是不能建路由）
    APIRouter = None  # type: ignore
    HTTPException = RuntimeError

from .graph_builder import build_database, load_rows
from .gspan import gspan
from .patterns import patterns_to_json
from .reuse_stats import compute_dataset_reuse, compute_reuse_stats

RESULTS_DIR = Path(__file__).resolve().parent / "results"
_results_cache: Dict[str, Dict[str, Any]] = {}


def _load(data_path: str, row_indices: Optional[List[int]]) -> List[Dict[str, Any]]:
    if str(data_path).endswith(".jsonl"):
        from .dataset_parser import parse_dataset

        rows, _report = parse_dataset(data_path)
        if not rows:
            raise ValueError(f"数据集解析后为空: {data_path}")
        return rows
    rows = load_rows(data_path, row_indices=row_indices)
    if not rows:
        raise ValueError(f"未加载到任何证明行: {data_path}")
    return rows


def run_reuse(data_path: str, row_indices: Optional[List[int]] = None) -> Dict[str, Any]:
    is_jsonl = str(data_path).endswith(".jsonl")
    rows = _load(data_path, row_indices)
    dataset = compute_dataset_reuse(rows)
    if is_jsonl:
        _results_cache.setdefault(
            data_path, {"dataset": [d.to_dict() for d in dataset]}
        )
        return {"dataset": [d.to_dict() for d in dataset]}
    return {
        "dataset": [d.to_dict() for d in dataset],
        "rows": [
            {"index": i, "summary": compute_reuse_stats(r).summary()}
            for i, r in enumerate(rows)
        ],
    }


def run_frequent(
    data_path: str,
    row_indices: Optional[List[int]] = None,
    min_support: int = 2,
    max_edges: int = 6,
    top_k: int = 50,
) -> Dict[str, Any]:
    if str(data_path).endswith(".jsonl"):
        # 大数据集：读取批处理缓存（先跑 python3 -m rule_mining --dataset ...）
        cache = RESULTS_DIR / "mining_results.json"
        if not cache.is_file():
            raise HTTPException(
                status_code=501,
                detail=(
                    "尚未生成数据集级挖掘缓存。请先运行: "
                    f"python3 -m rule_mining --dataset {data_path}"
                ),
            )
        results = json.loads(cache.read_text(encoding="utf-8"))
        patterns = [
            p
            for p in results["frequent_patterns"]
            if p["support"] >= min_support and p["n_edges"] <= max_edges
        ][:top_k]
        return {
            "params": {
                "rows": results["meta"]["parsed_rows"],
                "min_support": min_support,
                "max_edges": max_edges,
            },
            "patterns": patterns,
            "meta": results["meta"],
        }
    rows = _load(data_path, row_indices)
    database = build_database(rows)
    names = [
        f"proof_row{i}.json"
        for i in range(len(rows))
    ]
    host_id_of = {i: names[i] for i in range(len(rows))}
    patterns = gspan(database, min_support=min_support, max_edges=max_edges)
    return {
        "params": {"rows": len(rows), "min_support": min_support, "max_edges": max_edges},
        "patterns": patterns_to_json(patterns, host_id_of=host_id_of, top_k=top_k),
    }


def load_results_cache(results_path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(results_path) if results_path else RESULTS_DIR / "mining_results.json"
    if not p.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"挖掘结果缓存不存在: {p}（先运行 python3 -m rule_mining --dataset ...）",
        )
    return json.loads(p.read_text(encoding="utf-8"))


if APIRouter is not None:
    router = APIRouter(prefix="/api/mining", tags=["rule-mining"])
else:
    router = None


if router is not None:

    @router.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "module": "rule_mining"}

    @router.get("/results")
    def results_endpoint(results_path: str = "") -> Dict[str, Any]:
        return load_results_cache(results_path or None)

    @router.post("/reuse")
    def reuse_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
        return run_reuse(str(body["data_path"]), row_indices=body.get("row_indices"))

    @router.post("/frequent")
    def frequent_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
        return run_frequent(
            str(body["data_path"]),
            row_indices=body.get("row_indices"),
            min_support=int(body.get("min_support", 2)),
            max_edges=int(body.get("max_edges", 6)),
            top_k=int(body.get("top_k", 50)),
        )
