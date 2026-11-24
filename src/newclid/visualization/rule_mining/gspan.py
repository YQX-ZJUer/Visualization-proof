"""频繁子图挖掘（gSpan 家族，枚举-剪枝变体）。

输入：由 :mod:`graph_builder` 构造的无向标注图数据库
（节点属性 ``label``、边属性 ``label``，均为字符串）。

与 Yan & Han (2002) 标准 gSpan 的关系（论文"算法适配"章节的素材）：

* 标准 gSpan 沿 rightmost-path 用"最小边优先"扩展，其 DFS 字典序保证每个
  模式只被生成一次（canonical）；
* 本实现采用**逐边增长 + 规范编码去重**：增长空间与标准 gSpan 完全一致
  （全体连通子图），唯一性由 :func:`canonical_code` 保证 —— 图的 canonical
  形式取"该图所有 DFS 遍历码在固定全序下的最小者"（min-DFS-code）。两个
  标注图同构当且仅当 canonical 形式相同；
* 与原文的 DFS 字典序不同，这里使用简单元组字典序作为全序。canonicity
  只需要全序即可成立，因此不影响正确性（见模块内注释）；
* 支持度定义：**数据库中包含该模式的证明图个数**（per-proof support），
  即"有多少道证明用到了这个复合结构"——这正是"规则复用"的业务语义；
* ``max_edges`` 限制模式规模；canonical 形式用"每步取最小可行元素的贪心
  DFS 码"计算（完整码等长 → 贪心即最小，无需全枚举）。

对几何证明图的适配点（graph_builder 完成）：点无关标签、规则实例归并、
前提/结论语义保留。这三条让挖掘结果可以直接读作"复合推导规则"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

import networkx as nx

Edge = Tuple[Any, Any]
Code = Tuple[Tuple[int, int, str, str, str], ...]


# ------------------------------------------------------------ DFS 码与规范形式

def _greedy_suffix(G: nx.Graph, disc: Tuple[Tuple[Any, int], ...], recorded: FrozenSet) -> Optional[Code]:
    """从状态 (disc, recorded) 出发的最小后缀码（贪心 + 隐式回溯）。

    状态 = DFS 栈（发现序）+ 已记录边集。当前栈顶的可行元素是：
    - 回边：指向已发现邻居 w 的未记录边，元素 (i_tip, j_w, l_tip, l_e, l_w)；
    - 前向边：指向未发现邻居 w 的未记录边，元素 (i_tip, j_new, …)，并推进栈；
    - 无可行元素时隐式回溯到父节点（不产生元素）。

    贪心正确性：从同一状态出发的所有完整码长度相等
    （= 剩余边数），字典序最小者必然以最小的可行首元素开头。
    图连通时任何状态都能走完（DFS 栈上的节点覆盖全部未记录边）。
    """
    n_edges = G.number_of_edges()
    if len(recorded) == n_edges:
        return ()
    u, ui = disc[-1]
    idx_of = {d: i for d, i in disc}
    lu = G.nodes[u].get("label", "")
    options = []  # (element, new_disc, new_recorded)
    for w in G[u]:
        ek = frozenset((u, w))
        if ek in recorded:
            continue
        le = G[u][w].get("label", "")
        lw = G.nodes[w].get("label", "")
        if w in idx_of:
            options.append(((ui, idx_of[w], lu, le, lw), disc, recorded | {ek}))
        else:
            wj = len(disc)
            options.append(
                ((ui, wj, lu, le, lw), disc + ((w, wj),), recorded | {ek})
            )
    if not options:
        if len(disc) == 1:
            return None  # 根耗尽且仍有未记录边：图不连通（候选模式总是连通的）
        return _greedy_suffix(G, disc[:-1], recorded)
    min_elem = min(elem for elem, _nd, _nr in options)
    best: Optional[Code] = None
    for elem, nd, nr in options:
        if elem != min_elem:
            continue
        rest = _greedy_suffix(G, nd, nr)
        if rest is None:
            continue
        cand = (elem,) + rest
        if best is None or cand < best:
            best = cand
    return best


def canonical_code(G: nx.Graph) -> Code:
    """min-DFS-code：min over 起点 of 贪心最小 DFS 码。

    五元组 (i, j, l_i, l_ij, l_j) 逐元素比较，序列再逐元素比较。
    任何固定全序都满足 canonicity：同构图产生同一集合的码，最小者相同。
    """
    if G.number_of_edges() == 0:
        return ()
    best: Optional[Code] = None
    starts = sorted(G.nodes, key=lambda v: (G.nodes[v].get("label", ""), str(v)))
    for s in starts:
        code = _greedy_suffix(G, ((s, 0),), frozenset())
        if code is not None and (best is None or code < best):
            best = code
    if best is None:
        raise RuntimeError("canonical_code 无法枚举（图不连通？）")
    return best


def relabel_graph(G: nx.Graph) -> nx.Graph:
    """节点 id 换成确定性小整数（按标签排序），便于序列化与跨图比较。"""
    H = nx.Graph()
    order = sorted(G.nodes, key=lambda v: (G.nodes[v].get("label", ""), str(v)))
    mapping = {old: i for i, old in enumerate(order)}
    for old in order:
        H.add_node(mapping[old], label=G.nodes[old].get("label", ""))
    for u, v in G.edges():
        H.add_edge(mapping[u], mapping[v], label=G[u][v].get("label", ""))
    return H


# ------------------------------------------------------------ 支持度
#
# 子图同构判定用自研回溯匹配器（节点/边标签精确匹配），
# 不依赖 networkx 的 GraphMatcher：旧版（如 2.4）对"宿主图含闭合边 +
# 边标签匹配"的组合存在误判（已实测复现），且小图回溯带标签索引与
# 邻居剪枝，比通用 VF2 更快。

def _subgraph_match(host: nx.Graph, pattern: nx.Graph, limit: int = 1) -> List[Dict[Any, Any]]:
    """pattern 嵌入 host 的全部同构映射（最多 limit 个）。limit=1 时尽早返回。"""
    if pattern.number_of_nodes() == 0:
        return [{}]
    if pattern.number_of_nodes() > host.number_of_nodes():
        return []
    host_by_label: Dict[str, List[Any]] = {}
    for v, d in host.nodes(data=True):
        host_by_label.setdefault(d.get("label", ""), []).append(v)
    pat_nodes = sorted(pattern.nodes, key=lambda v: -pattern.degree(v))
    results: List[Dict[Any, Any]] = []
    assignment: Dict[Any, Any] = {}

    def backtrack(idx: int) -> None:
        if len(results) >= limit:
            return
        if idx == len(pat_nodes):
            # 全部边校验
            for u, v in pattern.edges():
                hu, hv = assignment[u], assignment[v]
                if not host.has_edge(hu, hv):
                    return
                if host[hu][hv].get("label") != pattern[u][v].get("label"):
                    return
            results.append(dict(assignment))
            return
        p = pat_nodes[idx]
        plabel = pattern.nodes[p].get("label", "")
        for h in host_by_label.get(plabel, ()):
            if h in assignment.values():
                continue
            ok = True
            for q in pattern.neighbors(p):
                if q in assignment:
                    hq = assignment[q]
                    if not host.has_edge(h, hq):
                        ok = False
                        break
                    if host[h][hq].get("label") != pattern[p][q].get("label"):
                        ok = False
                        break
            if not ok:
                continue
            assignment[p] = h
            backtrack(idx + 1)
            if len(results) >= limit:
                return
            del assignment[p]

    backtrack(0)
    return results


def subgraph_is_present(host: nx.Graph, pattern: nx.Graph) -> bool:
    """pattern 是否同构嵌入 host（节点/边标签精确匹配）。"""
    return bool(_subgraph_match(host, pattern, limit=1))


def occurrences_in(
    host: nx.Graph, pattern: nx.Graph, limit: int = 8
) -> List[Dict[Any, Any]]:
    """pattern 在 host 中的嵌入（pattern 节点 -> host 节点），最多 limit 个。"""
    return _subgraph_match(host, pattern, limit=limit)


def isomorphic(G: nx.Graph, H: nx.Graph) -> bool:
    """两个标注图是否同构（节点/边标签精确匹配）。"""
    if G.number_of_nodes() != H.number_of_nodes():
        return False
    if G.number_of_edges() != H.number_of_edges():
        return False
    return bool(_subgraph_match(G, H, limit=1))


def support_of(
    database: Sequence[nx.Graph],
    pattern: nx.Graph,
    weights: Optional[Sequence[int]] = None,
) -> int:
    """加权支持度：包含 pattern 的宿主图权重之和（权重 = 该图代表的证明数）。"""
    if weights is None:
        return sum(1 for g in database if subgraph_is_present(g, pattern))
    return sum(
        w for g, w in zip(database, weights) if subgraph_is_present(g, pattern)
    )


# ------------------------------------------------------------ 模式增长与 gSpan

@dataclass
class FrequentPattern:
    graph: nx.Graph
    code: Code
    support: int
    host_set: List[int] = field(default_factory=list)  # 包含该模式的宿主下标（occurrence-list）
    occurrences: List[Tuple[int, Dict[Any, Any]]] = field(default_factory=list)

    @property
    def n_edges(self) -> int:
        return self.graph.number_of_edges()

    @property
    def n_nodes(self) -> int:
        return self.graph.number_of_nodes()


def _label_universe(database: Sequence[nx.Graph]) -> Tuple[List[str], List[str]]:
    node_labels, edge_labels = set(), set()
    for g in database:
        for _v, d in g.nodes(data=True):
            node_labels.add(d.get("label", ""))
        for _u, _v, d in g.edges(data=True):
            edge_labels.add(d.get("label", ""))
    return sorted(node_labels), sorted(edge_labels)


def _single_edge_patterns(
    database: Sequence[nx.Graph],
    node_labels: List[str],
    edge_labels: List[str],
    occurrence_limit: int = 8,
    weights: Optional[Sequence[int]] = None,
    observed_edges: Optional[Sequence[Tuple[str, str, str]]] = None,
) -> List[FrequentPattern]:
    """1 条边的种子模式。

    observed_edges 给出时只枚举数据中真实出现的 (节点标签, 边标签, 节点标签)
    组合（大数据集下从 100²×2 降到数百级）；否则枚举全标签组合。
    """
    combos = (
        [(nl1, el, nl2) for nl1, el, nl2 in observed_edges]
        if observed_edges is not None
        else [(nl1, el, nl2) for nl1 in node_labels for el in edge_labels for nl2 in node_labels]
    )
    seen = set()
    seeds = []
    for nl1, el, nl2 in combos:
        p = nx.Graph()
        p.add_node(0, label=nl1)
        p.add_node(1, label=nl2)
        p.add_edge(0, 1, label=el)
        code = canonical_code(p)
        if code in seen:
            continue
        seen.add(code)
        host_set = [i for i, g in enumerate(database) if subgraph_is_present(g, p)]
        sup = (
            sum(weights[i] for i in host_set)
            if weights is not None
            else len(host_set)
        )
        if sup:
            seeds.append(
                FrequentPattern(p, code, sup, host_set=host_set)
            )
    return seeds


def _extend_once(
    pattern: nx.Graph,
    node_labels: List[str],
    edge_labels: List[str],
    obs_by_label: Optional[Dict[str, List[Tuple[str, str]]]] = None,
) -> Iterable[nx.Graph]:
    """加一条边（新节点或连接既有节点），保持连通。

    obs_by_label: 节点标签 -> 观测到的 (边标签, 邻居标签) 组合。
    给出时前向扩展只使用数据中真实出现过的组合，避免组合爆炸。
    """
    next_id = pattern.number_of_nodes()
    # (a) 前向扩展：连一个新节点
    for u in pattern.nodes:
        u_label = pattern.nodes[u].get("label", "")
        combos = (
            obs_by_label.get(u_label, [])
            if obs_by_label is not None
            else [(el, nl) for el in edge_labels for nl in node_labels]
        )
        for el, nl in combos:
            p = pattern.copy()
            p.add_node(next_id, label=nl)
            p.add_edge(u, next_id, label=el)
            yield p
    # (b) 后向扩展：连接两个既有的不相邻节点
    pairs = [
        (u, v)
        for u in pattern.nodes
        for v in pattern.nodes
        if u < v and not pattern.has_edge(u, v)
    ]
    for u, v in pairs:
        for el in edge_labels:
            p = pattern.copy()
            p.add_edge(u, v, label=el)
            yield p


def gspan(
    database: Sequence[nx.Graph],
    min_support: int = 2,
    max_edges: int = 6,
    occurrence_limit: int = 8,
    verbose: bool = False,
    weights: Optional[Sequence[int]] = None,
    observed_edges: Optional[Sequence[Tuple[str, str, str]]] = None,
    obs_by_label: Optional[Dict[str, List[Tuple[str, str]]]] = None,
    collect_occurrences: bool = False,
) -> List[FrequentPattern]:
    """频繁子图挖掘（逐边增长 + 规范码去重 + 支持度剪枝）。

    支持度计数使用 occurrence-list 剪枝：候选 = 父模式 + 一条边，
    其宿主集合必然是父模式宿主集合的子集，因此只在父模式的宿主
    集合内计数（经典 gSpan 优化，大数据集下比全库扫描快一到两个
    数量级）。

    :param database: 无向标注图列表（节点/边须有字符串 ``label`` 属性）
    :param min_support: 绝对支持度阈值（加权：包含该模式的证明数）
    :param max_edges: 模式最大边数（复杂度上限）
    :param weights: 每个宿主图的权重（如去重后的证明数），默认全 1
    :param observed_edges / obs_by_label: 大数据集剪枝（见 _single_edge_patterns /
        _extend_once）；默认枚举全标签组合
    :param collect_occurrences: 是否收集每个模式的具体嵌入（大数据集建议
        False，之后对 TopN 单独收集）
    :return: 按 (支持度降序, 边数升序, 规范码) 排序的频繁模式
    """
    if not database:
        return []
    for g in database:
        if g.is_multigraph():
            raise ValueError("database 图必须是简单图（build_mining_graph 已合并并行边）")
    if weights is not None and len(weights) != len(database):
        raise ValueError("weights 长度必须与 database 一致")

    node_labels, edge_labels = _label_universe(database)
    if observed_edges is not None:
        # 边标签收窄为数据中出现过的（后向扩展用）
        used_el = sorted({el for _a, el, _b in observed_edges})
        if used_el:
            edge_labels = used_el
    level: List[FrequentPattern] = [
        p
        for p in _single_edge_patterns(
            database,
            node_labels,
            edge_labels,
            occurrence_limit=occurrence_limit,
            weights=weights,
            observed_edges=observed_edges,
        )
        if p.support >= min_support
    ]

    result: List[FrequentPattern] = []
    seen_codes = set()

    while level and level[0].n_edges <= max_edges:
        result.extend(level)
        seen_codes.update(p.code for p in level)
        next_level: List[FrequentPattern] = []
        for p in level:
            if p.n_edges >= max_edges:
                continue
            for cand in _extend_once(
                p.graph, node_labels, edge_labels, obs_by_label=obs_by_label
            ):
                code = canonical_code(cand)
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                # occurrence-list 剪枝：只在父模式的宿主集合内计数
                host_set = [
                    i
                    for i in p.host_set
                    if subgraph_is_present(database[i], cand)
                ]
                sup = (
                    sum(weights[i] for i in host_set)
                    if weights is not None
                    else len(host_set)
                )
                if sup < min_support:
                    continue
                fp = FrequentPattern(cand, code, sup, host_set=host_set)
                if collect_occurrences:
                    for gi in host_set:
                        for m in occurrences_in(
                            database[gi], cand, limit=occurrence_limit
                        ):
                            fp.occurrences.append((gi, m))
                next_level.append(fp)
                if verbose:
                    print(
                        f"  [gspan] support={sup} edges={cand.number_of_edges()} "
                        f"nodes={cand.number_of_nodes()}"
                    )
        level = next_level

    result.sort(key=lambda p: (-p.support, p.n_edges, p.code))
    return result
