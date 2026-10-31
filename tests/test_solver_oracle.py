"""Check the independent enumerator on a graph with known edge-path alternatives."""

import networkx as nx

from experiments.validate_solver_oracle import chain_dynamic_program, enumerate_paths


def test_oracle_enumerates_parallel_edges_and_excludes_cycles():
    graph = nx.MultiDiGraph()
    graph.add_edge("s", "a", key="short", length=2)
    graph.add_edge("s", "a", key="long", length=5)
    graph.add_edge("a", "s", key="cycle", length=1)
    graph.add_edge("a", "t", key="finish", length=3)
    graph.add_edge("s", "t", key="direct", length=9)
    paths = enumerate_paths(graph, "s", "t")
    assert {edges: distance for edges, distance in paths} == {
        (("s", "a", "short"), ("a", "t", "finish")): 5,
        (("s", "a", "long"), ("a", "t", "finish")): 8,
        (("s", "t", "direct"),): 9,
    }


def test_integer_chain_reference_retains_minimum_cost_for_each_distance():
    # Four edge combinations produce distances 5, 7, 7, 9; keep the cheaper 7.
    result = chain_dynamic_program([[(2, 10), (4, 2)], [(3, 8), (5, 1)]])
    assert result == {5: 18, 7: 10, 9: 3}
