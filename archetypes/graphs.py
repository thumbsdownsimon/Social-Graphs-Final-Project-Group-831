"""Weighted directed challenge graphs: challenger -> member holding the floor."""
import networkx as nx


def build_graph(edges):
    """One DiGraph from labeled edges; weight = number of challenges on that ordered pair."""
    graph = nx.DiGraph()
    counts = edges.groupby(["challenger", "floor"]).size()
    graph.add_weighted_edges_from((int(a), int(b), int(w)) for (a, b), w in counts.items())
    return graph


def graphs_by_window(edges, windows, include_all=True):
    """{window name: (edges subset, graph)}, in time order, plus 'all' for the whole period."""
    out = {}
    for w in windows:
        part = edges[edges["window"] == w["name"]]
        if len(part):
            out[w["name"]] = (part, build_graph(part))
    if include_all:
        out["all"] = (edges, build_graph(edges))
    return out


def graph_summary(graph, edges):
    """Whole-graph numbers for one window: size, density, reciprocity, party assortativity."""
    party = {}
    for person, p in zip(edges["challenger"], edges["c_party"]):
        party[int(person)] = p
    for person, p in zip(edges["floor"], edges["f_party"]):
        party.setdefault(int(person), p)
    nx.set_node_attributes(graph, party, "party")
    weights = [d["weight"] for _, _, d in graph.edges(data=True)]
    return {
        "nodes": graph.number_of_nodes(),
        "pairs": graph.number_of_edges(),
        "challenges": int(sum(weights)),
        "density": round(nx.density(graph), 4),
        "reciprocity": round(nx.reciprocity(graph), 3) if graph.number_of_edges() else None,
        "party_assortativity": round(nx.attribute_assortativity_coefficient(graph, "party"), 3),
        "share_cross_side": round(float(edges["cross_side"].mean()), 3),
        "share_same_party": round(float(edges["same_party"].mean()), 4),
    }
