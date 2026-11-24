# Rule Mining —— 规则节点复用分析与频繁子图（gSpan）挖掘

面向开题报告 **4.1.4「频繁子图挖掘算法的适配与集成应用」** 与
**创新点 4.2.2「融合规则复用挖掘的交互式展示模式」** 的独立子项目。

本包不依赖 `newclid` 内部模块，只依赖 `networkx`（`api.py` 可选依赖 `fastapi`）。
输入是 `visualization/json_output/` 里已导出的证明行 JSON（`nodes`/`links`），
因此可以先于 Web 集成独立开发、测试与演示。

## 目录结构

```
rule_mining/
├── graph_builder.py     证明行 JSON -> 点无关标注图（有向/无向）
├── reuse_stats.py       规则复用统计（证明内 + 数据集级）+ 节点复用字段
├── gspan.py             频繁子图挖掘（gSpan 家族：逐边增长 + 规范码去重）
├── patterns.py          模式签名/命名/复合规则回写骨架
├── dataset_parser.py    JSONL 数据集行解析（复刻 vis_proof 逻辑，自包含）
├── dataset_mining.py    批量统计：全量复用 + 加权去重 + 剪枝挖掘 + 统计图
├── api.py               FastAPI 路由（/api/mining/*，可集成进 vis_webapp）
├── __main__.py          CLI：导出行报告 / --dataset 批量模式
├── static/mining.html   前端页面（规则复用条形图 + 频繁子图统计 + 子图渲染）
├── results/             输出：mining_results.json、rule_usage.json、
│                        frequent_patterns.json、chart_*.png
└── tests/               pytest 用例（gSpan 与暴力枚举对照、规范码交叉验证等）
```

## 数据集级批量统计（10000 行）

```bash
PYTHONPATH=src/newclid/visualization python3 -m rule_mining \
    --dataset src/newclid/generation/dataset/geometry_clauses15_samples10k.jsonl \
    --min-support 2 --max-edges 3 --top-k 100
```

流程与关键设计（论文 4.1.4 / 创新点 4.2.2 的实证材料）：

1. **解析**：全部行 → 证明图（节点/边语义同 `vis_proof.export_to_json`）；
2. **规则复用（数据集级）**：每条规则出现多少道证明、总应用次数、平均每证明
   应用数、推出的结论谓词；
3. **宿主图加权去重**：同构图合并、以证明数加权。大图上规范码计算昂贵，
   改用"特征分桶 + 桶内同构判定"（结果与规范码去重等价）；
4. **频繁子图挖掘**：种子/扩展只用数据中观测到的标签组合（避免 10²×2 级
   组合爆炸），支持度 = 包含该子图的证明数（加权）；
5. **统计图**（matplotlib，英文标签避免服务器缺中文字体）：
   `chart_rule_reuse.png`（规则复用 Top30）、
   `chart_frequent_subgraphs.png`（频繁子图 Top30，含子图命名与复用数量）。

前端：启动 `vis_webapp/main.py` 后访问 `/mining`（页面已在
`vis_webapp/static/mining.html`，数据来自 `GET /api/mining/results`），
左侧为规则复用统计（点击查看详情），右侧为频繁子图统计（点击渲染子图
结构），下方为 Top50 明细表。

## 对几何证明图的三个适配点（论文"算法适配"素材）

1. **点无关标签化**：事实节点标注为 `<类型>:<谓词>`（如 `derived:eqangle`），
   丢弃点名字母。同一推导结构在不同题目、不同点命名下因此可被识别为同一模式。
2. **规则实例归并**：规则节点标签 `a01_1` / id `r_a01_1` 中的末尾 `_<n>` 是
   同一条规则在第 n 次应用的实例后缀，挖掘前归并为规则名 `a01`。
3. **方向语义保留**：`事实 -> 规则` = 前提（premise），`规则 -> 事实` = 结论
   （conclusion）。复用分析用有向图；挖掘用无向图，但方向语义编码进边标签。

## 复用统计

- **证明内**：每条规则的应用次数（实例计数）、复用判定（≥2 次）、
  事实节点的前提扇出（fan-out）、被多条规则重复推出的冗余事实；
- **数据集级**：规则在多少道证明中出现、总应用次数、平均每次证明应用数；
- `add_reuse_fields(row)` 给每个节点补 `reuse_group` / `reuse_count`，
  可直接喂给前端"点击查看复用详情"。

## 频繁子图挖掘（gSpan）

- 支持度 = **包含该模式的证明图个数**（per-proof support），语义即
  "有多少道证明用到了这个复合结构"；
- canonical 形式 = min-DFS-code（该图全部 DFS 遍历码在固定全序下的最小者），
  同构 ⟺ 同码；实现采用"逐边增长 + 规范码去重 + 支持度剪枝"，
  与标准 gSpan 的 rightmost-path 扩展生成相同的模式空间（见 `gspan.py`
  模块 docstring 的等价性说明）；
- 正确性由 `tests/test_gspan.py` 保证：随机小图上与暴力枚举全部连通子图
  的频繁集逐一对照，另验证规范码的同构不变性。

## 使用

CLI（在仓库根、装好 networkx 的环境）：

```bash
python3 -m newclid.visualization.rule_mining \
    --data-dir src/newclid/visualization/json_output \
    --min-support 1 --max-edges 5 --top-k 20 --out mining_report.json
```

Web 集成（两行，不改动本模块）：

```python
from newclid.visualization.rule_mining.api import router as mining_router
app.include_router(mining_router)
```

测试（最小环境：只需 networkx + pytest，测试经 conftest 以顶层包导入，
不触发 newclid 重依赖）：

```bash
# 仓库根目录
python3 -m pytest src/newclid/visualization/rule_mining/tests -v
```

独立 CLI（同样不触发 newclid）：

```bash
PYTHONPATH=src/newclid/visualization python3 -m rule_mining \
    --data-dir src/newclid/visualization/json_output \
    --min-support 1 --max-edges 5 --top-k 20
```

## 已知边界与下一步

- `pattern_to_rule_text` 输出的是**点无关骨架**：前提/结论谓词中的点变量
  尚未统一（需要按出现频次与几何约束做变量对齐），这是"复合规则回注
  rules.txt"研究点的核心剩余步骤；
- 挖掘未利用节点的 `layer` 属性（层级约束挖掘是候选优化点）；
- 支持度计数用自研回溯匹配器（节点/边标签精确匹配，带标签索引与邻居
  剪枝；不依赖 networkx GraphMatcher——旧版 networkx 的该实现存在误判）；
  大规模数据集（数百证明）可进一步换 occurrence-list 计数或并行化；
- 前端叠加视图与交互（点击查看复用详情、复用链路高亮）待接入
  `vis_webapp/static/index.html`。
