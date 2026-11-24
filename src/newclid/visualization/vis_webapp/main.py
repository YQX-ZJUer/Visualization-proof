"""几何证明可视化 Web 应用 - FastAPI 后端

功能：
- GET /                        前端页面
- GET /api/problem/{row_idx}   返回第 row_idx 道题目的 JSONL 原始行
- GET /api/svg/{row_idx}       生成该题的证明推导 SVG 图（Graphviz）
- GET /api/graph/{row_idx}     生成该题的节点-边 JSON 数据（供 D3.js 渲染）

复用 src/newclid/visualization/vis_proof.py 中的解析逻辑。

说明：本文件可以放在任意目录层级（如仓库根目录 viz_webapp/ 或
src/newclid/visualization/vis_webapp/），相关路径会自动向上查找定位。
"""
import json
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from graphviz import Digraph

# ================= 路径自适应查找 =================
_BASE = os.path.dirname(os.path.abspath(__file__))


def _search_up(start, is_target):
    """从 start 目录开始逐级向上，返回第一个满足 is_target 的目录（或 None）"""
    d = os.path.abspath(start)
    while True:
        if is_target(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# 1) vis_proof.py 所在目录（用于 import）
VIS_DIR = _search_up(_BASE, lambda d: os.path.isfile(os.path.join(d, "vis_proof.py")))
if VIS_DIR:
    sys.path.insert(0, VIS_DIR)
import vis_proof as vp  # noqa: E402

# 2) 数据集 JSONL 路径（从 main.py 向上，依次尝试常见相对结构）
_DATASET_NAME = "geometry_clauses15_samples10k.jsonl"


def _find_dataset(start):
    d = os.path.abspath(start)
    while True:
        for rel in (
            os.path.join("src", "newclid", "generation", "dataset", _DATASET_NAME),
            os.path.join("generation", "dataset", _DATASET_NAME),
            _DATASET_NAME,
        ):
            cand = os.path.join(d, rel)
            if os.path.isfile(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


DATA_PATH = _find_dataset(_BASE)

# 3) 静态资源目录（包含 index.html 的 static 目录）
def _find_static(start):
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, "static")
        if os.path.isfile(os.path.join(cand, "index.html")):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


STATIC_DIR = _find_static(_BASE) or os.path.join(_BASE, "static")

app = FastAPI(title="几何证明可视化 Web 应用")

# 静态资源目录（前端页面）
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---- rule_mining 路由（可选：复用统计 + 频繁子图挖掘） ----
try:
    sys.path.insert(0, os.path.dirname(_BASE))  # visualization 目录
    from rule_mining.api import router as _mining_router

    if _mining_router is not None:
        app.include_router(_mining_router)
except Exception as _e:  # 环境缺依赖等，不影响主功能
    print("rule_mining 路由加载失败（忽略）:", _e)

# ---- 数据加载与解析 ----
_lines_cache = None


def load_lines():
    """读取全部 JSONL 行（首次调用后缓存）"""
    global _lines_cache
    if _lines_cache is None:
        if not os.path.exists(DATA_PATH):
            raise HTTPException(status_code=500, detail=f"数据集不存在: {DATA_PATH}")
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            _lines_cache = [line.rstrip("\n") for line in f if line.strip()]
    return _lines_cache


def parse_row(row_idx: int):
    """读取并解析指定行，返回 (原始dict, 节点图数据)"""
    lines = load_lines()
    if not 0 <= row_idx < len(lines):
        raise HTTPException(status_code=404, detail=f"行号 {row_idx} 越界，有效范围 0 ~ {len(lines) - 1}")
    try:
        data = json.loads(lines[row_idx])
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"第 {row_idx} 行 JSON 解析失败: {e}")

    llm_input = data.get("llm_input_renamed", "")
    llm_output = data.get("llm_output_renamed", "")

    problem_facts = vp.parse_problem_facts(llm_input)
    numerical_facts = vp.parse_numerical_check_facts(llm_output)
    all_facts = {**problem_facts, **numerical_facts}

    result = vp.parse_proof_relations(llm_output, all_facts)
    if not result or result[0] is None:
        raise HTTPException(status_code=422, detail=f"第 {row_idx} 行无法解析出 <proof> 推导关系")
    stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes = result
    node_layer = vp.adjust_node_layers(rule_nodes, edges, node_layer)
    return data, (stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes)


def build_svg(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes, row_idx) -> str:
    """复用 vis_proof.create_visualization 的样式，直接返回 SVG 字符串（不写文件）"""
    dot = Digraph(engine="dot", format="svg", name=f"proof_row{row_idx}")
    dot.attr(rankdir="TB", splines="ortho", fontname="Arial")

    fact_layers = {n: node_layer[n] for n in fact_nodes if n in node_layer}
    max_layer = max(fact_layers.values()) if fact_layers else 0
    final_nodes = {n for n, l in fact_layers.items() if l == max_layer}

    for label in fact_nodes:
        shape = "ellipse" if label in initial_fact_nodes else "box"
        if label in final_nodes:
            color, fillcolor = "green", "lightgreen"
        else:
            color, fillcolor = "blue", "lightblue"
        dot.node(name=label, label=stmt_map[label], shape=shape, color=color,
                 style="filled", fillcolor=fillcolor)

    for rule_node in rule_nodes:
        rule_label = "_".join(rule_node.split("_")[1:])
        dot.node(name=rule_node, label=rule_label, shape="diamond", color="red",
                 style="filled", fillcolor="pink")

    for u, v in edges:
        dot.edge(u, v)

    for layer in sorted(set(node_layer.values())):
        with dot.subgraph() as sub:
            sub.attr(rank="same")
            for node in node_layer:
                if node_layer[node] == layer:
                    sub.node(node)

    return dot.pipe(format="svg").decode("utf-8")


def build_graph_json(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes) -> dict:
    """复用 vis_proof.export_to_json 的格式，直接返回 dict

    最终结论节点（推导深度最大的事实节点）会被标记 final=True，供前端标红显示。
    """
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
        nodes.append({
            "id": label,
            "type": node_type,
            "label": stmt_map[label],
            "layer": node_layer.get(label, 1),
            "shape": shape,
            "final": label in final_nodes,
        })
    for rule_node in rule_nodes:
        rule_label = "_".join(rule_node.split("_")[1:])
        nodes.append({
            "id": rule_node,
            "type": "rule",
            "label": rule_label,
            "layer": node_layer.get(rule_node, 1),
            "shape": "diamond",
            "final": False,
        })
    links = [{"source": u, "target": v, "type": "derivation"} for u, v in edges]
    return {"nodes": nodes, "links": links}


# ---- 路由 ----
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/mining", include_in_schema=False)
def mining_page():
    """规则复用与频繁子图挖掘页面。"""
    return FileResponse(os.path.join(STATIC_DIR, "mining.html"))


def parse_custom(llm_input: str, llm_output: str):
    """解析用户自定义输入的形式化证明文本（与 parse_row 相同的解析逻辑）

    输入格式（与数据集中 llm_input_renamed / llm_output_renamed 一致）：
      llm_input : <problem> 点定义 ; 初始事实 [编号] ? 目标 </problem>
      llm_output: <numerical_check> 补充事实 [编号] ; </numerical_check>
                  <proof> 结论 [编号] 规则名 [前提编号] ... ; </proof>
    """
    if not llm_input or not llm_input.strip():
        raise HTTPException(status_code=422, detail="llm_input 为空，请输入 <problem> 标签内容")
    if not llm_output or not llm_output.strip():
        raise HTTPException(status_code=422, detail="llm_output 为空，请输入 <numerical_check>/<proof> 标签内容")

    problem_facts = vp.parse_problem_facts(llm_input)
    if not problem_facts:
        raise HTTPException(status_code=422, detail="未在 llm_input 中找到有效的 <problem> 初始事实")
    numerical_facts = vp.parse_numerical_check_facts(llm_output)
    all_facts = {**problem_facts, **numerical_facts}

    result = vp.parse_proof_relations(llm_output, all_facts)
    if not result or result[0] is None:
        raise HTTPException(status_code=422, detail="未在 llm_output 中找到有效的 <proof> 推导")
    stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes = result
    node_layer = vp.adjust_node_layers(rule_nodes, edges, node_layer)
    return stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes


@app.post("/api/custom/svg")
def api_custom_svg(payload: dict):
    llm_input = payload.get("llm_input", "")
    llm_output = payload.get("llm_output", "")
    try:
        (stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes) = parse_custom(llm_input, llm_output)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"解析失败: {e}")
    svg = build_svg(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes, "custom")
    return Response(content=svg, media_type="image/svg+xml")


@app.post("/api/custom/graph")
def api_custom_graph(payload: dict):
    llm_input = payload.get("llm_input", "")
    llm_output = payload.get("llm_output", "")
    try:
        (stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes) = parse_custom(llm_input, llm_output)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"解析失败: {e}")
    return build_graph_json(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes)


@app.get("/api/problem/{row_idx}")
def api_problem(row_idx: int):
    lines = load_lines()
    if not 0 <= row_idx < len(lines):
        raise HTTPException(status_code=404, detail=f"行号 {row_idx} 越界，有效范围 0 ~ {len(lines) - 1}")
    return {
        "row_idx": row_idx,
        "total_rows": len(lines),
        "raw_line": lines[row_idx],
        "parsed": json.loads(lines[row_idx]),
    }


@app.get("/api/svg/{row_idx}")
def api_svg(row_idx: int):
    _, (stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes) = parse_row(row_idx)
    svg = build_svg(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes, row_idx)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/graph/{row_idx}")
def api_graph(row_idx: int):
    _, (stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes) = parse_row(row_idx)
    return build_graph_json(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
