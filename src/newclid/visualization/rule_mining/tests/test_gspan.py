"""gSpan 实现的正确性测试。

核心验证手段：随机小图上与"暴力枚举全部连通子图"对照 ——
gSpan 输出的模式集合（按 canonical_code）必须与暴力枚举的频繁连通
子图集合一致。另验证规范码的同构不变性。
"""
import itertools
import random

import networkx as nx

from rule_mining.gspan import (
    canonical_code,
    gspan,
    subgraph_is_present,
    support_of,
)


def _rand_graph(n, m, node_labels=("A", "B"), edge_labels=("x", "y"), seed=0):
    rng = random.Random(seed)
    G = nx.Graph()
    for i in range(n):
        G.add_node(i, label=rng.choice(node_labels))
    pairs = list(itertools.combinations(range(n), 2))
    rng.shuffle(pairs)
    for u, v in pairs[:m]:
        G.add_edge(u, v, label=rng.choice(edge_labels))
    return G


def _connected_subgraphs(G, max_edges):
    """枚举 G 的全部连通子图（边数 >= 1 且 <= max_edges）。"""
    edges = list(G.edges())
    for k in range(1, min(max_edges, len(edges)) + 1):
        for subset in itertools.combinations(edges, k):
            nodes = {v for e in subset for v in e}
            H = nx.Graph()
            for v in nodes:
                H.add_node(v, label=G.nodes[v]["label"])
            for u, v in subset:
                H.add_edge(u, v, label=G[u][v]["label"])
            if nx.is_connected(H):
                yield H


def _brute_frequent(database, min_support, max_edges):
    """暴力法：所有 host 图的所有连通子图，按 canonical_code 聚合支持度。"""
    counts = {}
    for G in database:
        seen = set()
        for H in _connected_subgraphs(G, max_edges):
            code = canonical_code(H)
            if code in seen:
                continue
            seen.add(code)
            counts[code] = counts.get(code, 0) + 1
    return {code: sup for code, sup in counts.items() if sup >= min_support}


def test_canonical_invariance_under_relabel():
    rng = random.Random(42)
    for _ in range(10):
        G = _rand_graph(5, 5, seed=rng.randint(0, 10**6))
        if G.number_of_edges() == 0:
            continue
        perm = list(G.nodes)
        rng.shuffle(perm)
        mapping = {old: f"n{new}" for old, new in zip(G.nodes, perm)}
        H = nx.relabel_nodes(G, mapping)
        assert canonical_code(G) == canonical_code(H)


def test_simple_support():
    h1 = nx.Graph()
    h1.add_node(0, label="A"); h1.add_node(1, label="B"); h1.add_edge(0, 1, label="x")
    h2 = nx.Graph()
    h2.add_node(0, label="A"); h2.add_node(1, label="B"); h2.add_edge(0, 1, label="x")
    p = nx.Graph()
    p.add_node(0, label="A"); p.add_node(1, label="B"); p.add_edge(0, 1, label="x")
    assert subgraph_is_present(h1, p)
    assert support_of([h1, h2], p) == 2


def test_known_patterns():
    # h1: A-x-B-y-C 路径；h2: A-x-B。min_support=2 时只有单边模式频繁
    h1 = nx.Graph()
    for i, lab in enumerate(("A", "B", "C")):
        h1.add_node(i, label=lab)
    h1.add_edge(0, 1, label="x")
    h1.add_edge(1, 2, label="y")
    h2 = nx.Graph()
    h2.add_node(0, label="A"); h2.add_node(1, label="B")
    h2.add_edge(0, 1, label="x")
    patterns = gspan([h1, h2], min_support=2, max_edges=2)
    codes = {p.code for p in patterns}
    brute = set(_brute_frequent([h1, h2], 2, 2).keys())
    assert codes == brute
    # 单边 A-x-B 支持 2；A-y-B、B-y-C 不存在；双边的路径只出现在 h1
    assert all(p.support >= 2 for p in patterns)


def test_gspan_matches_bruteforce_random():
    rng = random.Random(7)
    for trial in range(6):
        db = [
            _rand_graph(5, rng.randint(2, 5), seed=rng.randint(0, 10**6))
            for _ in range(3)
        ]
        max_edges, min_support = 3, 2
        got = {p.code for p in gspan(db, min_support=min_support, max_edges=max_edges)}
        want = set(_brute_frequent(db, min_support, max_edges).keys())
        assert got == want, f"trial {trial}: got {len(got)} want {len(want)}"


def test_pruning_antimonotone():
    db = [
        _rand_graph(5, 4, seed=s) for s in (1, 2, 3)
    ]
    for p in gspan(db, min_support=3, max_edges=3):
        assert p.support >= 3


# ---------------------------------------------------------------- 参考实现交叉验证

def _naive_all_codes(G):
    """参考实现：枚举全部 DFS 遍历码（所有起点、所有边序），仅用于小图验证。

    状态机 = (DFS 栈, 已记录边集)：栈顶对每条未记录边分支（回边原地记录 /
    前向边入栈），无未记录边时显式回溯出栈。关键：recorded 随状态传递，
    "回溯到祖先后再记录新边"的遍历不会被丢（这是此前朴素实现不完整的原因）。
    """
    n_edges = G.number_of_edges()
    out = set()

    def rec(disc, recorded, code):
        if len(recorded) == n_edges:
            out.add(code)
            return
        u, ui = disc[-1]
        idx_of = {d: i for d, i in disc}
        lu = G.nodes[u].get("label", "")
        moved = False
        for w in G[u]:
            ek = frozenset((u, w))
            if ek in recorded:
                continue
            moved = True
            le = G[u][w].get("label", "")
            lw = G.nodes[w].get("label", "")
            nr = recorded | {ek}
            if w in idx_of:
                rec(disc, nr, code + ((ui, idx_of[w], lu, le, lw),))
            else:
                rec(
                    disc + ((w, len(disc)),),
                    nr,
                    code + ((ui, len(disc), lu, le, lw),),
                )
        if not moved and len(disc) > 1:
            rec(disc[:-1], recorded, code)

    for s in G.nodes:
        rec(((s, 0),), frozenset(), ())
    return out


def test_greedy_canonical_equals_naive_min():
    """贪心 canonical_code 必须等于朴素全枚举的最小码（随机小图交叉验证）。"""
    rng = random.Random(3)
    checked = 0
    for _ in range(40):
        G = _rand_graph(4, rng.randint(1, 4), seed=rng.randint(0, 10**6))
        if G.number_of_edges() == 0 or not nx.is_connected(G):
            continue
        naive = min(_naive_all_codes(G))
        assert canonical_code(G) == naive, f"图: {list(G.edges(data=True))}"
        checked += 1
    assert checked >= 10
