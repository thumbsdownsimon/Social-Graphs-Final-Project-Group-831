"""Draw the challenge network for one government window.

    python -m archetypes.plot_network [--window "2022 M+S+V"] [--min-weight 3] [--labels 10]

Run archetypes.run_network first: party, government status and roles come from
data/archetypes/member_window.parquet.

What the picture shows
    node        one member who made or received a challenge in the window
    node size   challenges received (in_w); bigger = challenged more
    node color  the member's bloc: red, blue, centre (M), North Atlantic, or independent/other.
                Blocs rather than parties, because there are too many parties to tell apart by color;
                the party is in the hover text and the labels.
    dark ring   the member's party was in government in this window
    line        two members who challenged each other at least --min-weight times, either way.
                Direction is not drawn: with thousands of pairs, arrows only add clutter.
    position    spring layout: members who challenge each other a lot are pulled together, so
                tight clusters are groups that mostly argue among themselves.

Writes data/archetypes/figures/network_<window>.png (static, for the report) and
network_<window>.html (interactive: hover a node for name, party, counts and roles).
"""
import argparse
import re

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import networkx as nx
import pandas as pd
import plotly.graph_objects as go

from .config import BLOC, INDEPENDENT, OUT, SEED
from .data import load_all
from .graphs import graphs_by_window

# Bloc colors from the dataviz reference palette, validated for color-blind separation.
BLOC_STYLE = {
    "red": ("Red bloc", "#e34948"),
    "blue": ("Blue bloc", "#2a78d6"),
    "centre": ("Centre (M)", "#6250d6"),
    "north_atlantic": ("North Atlantic", "#1baf7a"),
    "other": ("Independent / other", "#9a9893"),
}
RING = "#0b0b0b"
EDGE = "#b8b6af"
SURFACE = "#fcfcfb"


def node_table(graph, window):
    """Party, government status, counts and roles for each node, from member_window.parquet."""
    t = pd.read_parquet(OUT / "member_window.parquet")
    t = t[t["window"] == window].set_index("person")
    t = t.reindex(list(graph.nodes))
    t["bloc"] = t["party"].map(BLOC).fillna("other")
    t.loc[t["party"] == INDEPENDENT, "bloc"] = "other"
    t["in_government"] = t["in_government"].fillna(False).astype(bool)
    t["roles"] = t["roles"].fillna("")
    t["in_w"] = t["in_w"].fillna(0)
    return t


def undirected(graph, min_weight):
    """Merge both directions into one weighted line per pair; keep pairs with >= min_weight."""
    g = nx.Graph()
    g.add_nodes_from(graph.nodes)
    for a, b, d in graph.edges(data=True):
        w = d["weight"] + (g[a][b]["weight"] if g.has_edge(a, b) else 0)
        g.add_edge(a, b, weight=w)
    weak = [(a, b) for a, b, d in g.edges(data=True) if d["weight"] < min_weight]
    g.remove_edges_from(weak)
    return g


def sizes(in_w, small, large):
    """Node area grows with challenges received, scaled into [small, large]."""
    top = max(float(in_w.max()), 1.0)
    return small + (large - small) * (in_w / top) ** 0.5


def draw_png(g, pos, nodes, labels, window, min_weight, path):
    fig, ax = plt.subplots(figsize=(12, 12), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    weights = [d["weight"] for _, _, d in g.edges(data=True)]
    top_w = max(weights, default=1)
    nx.draw_networkx_edges(g, pos, ax=ax, edge_color=EDGE, alpha=0.5,
                           width=[0.3 + 2.0 * w / top_w for w in weights])
    area = sizes(nodes["in_w"], 10, 260)
    for bloc, (name, color) in BLOC_STYLE.items():
        ids = [n for n in g.nodes if nodes.at[n, "bloc"] == bloc]
        if not ids:
            continue
        gov = [nodes.at[n, "in_government"] for n in ids]
        ax.scatter([pos[n][0] for n in ids], [pos[n][1] for n in ids], s=area[ids], c=color, label=name,
                   edgecolors=[RING if x else SURFACE for x in gov], linewidths=[1.4 if x else 0.6 for x in gov],
                   zorder=3)
    for n in labels:
        ax.annotate(f"{nodes.at[n, 'name']} ({nodes.at[n, 'party']})", pos[n], fontsize=7.5, color="#0b0b0b",
                    xytext=(5, 5), textcoords="offset points", zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none", alpha=0.8))
    handles = [Line2D([], [], marker="o", ls="", ms=8, mfc=color, mec=SURFACE, label=name)
               for bloc, (name, color) in BLOC_STYLE.items() if (nodes["bloc"] == bloc).any()]
    handles.append(Line2D([], [], marker="o", ls="", ms=8, mfc=SURFACE, mec=RING, mew=1.4, label="In government (ring)"))
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=9)
    ax.set_title(f"Who challenges whom, {window}", loc="left", fontsize=13, color="#0b0b0b")
    ax.text(0, -0.01, "Node size = challenges received. Lines = pairs who challenged each other at least "
            f"{min_weight} times, in either direction. Named: the most-challenged members.", transform=ax.transAxes, fontsize=8, color="#52514e")
    ax.axis("off")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def draw_html(g, pos, nodes, labels, window, path):
    ex, ey = [], []
    for a, b in g.edges:
        ex += [pos[a][0], pos[b][0], None]
        ey += [pos[a][1], pos[b][1], None]
    traces = [go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.5, color=EDGE), hoverinfo="skip",
                         showlegend=False)]
    area = sizes(nodes["in_w"], 4, 30)
    for bloc, (name, color) in BLOC_STYLE.items():
        ids = [n for n in g.nodes if nodes.at[n, "bloc"] == bloc]
        if not ids:
            continue
        sub = nodes.loc[ids]
        text = [f"<b>{r['name']}</b> ({r['party']}{', government' if r['in_government'] else ''})<br>"
                f"made {int(r['out_w'] or 0)}, received {int(r['in_w'] or 0)} challenges<br>"
                f"roles: {r['roles'] or 'none'}" for _, r in sub.iterrows()]
        traces.append(go.Scatter(
            x=[pos[n][0] for n in ids], y=[pos[n][1] for n in ids], mode="markers", name=name,
            marker=dict(size=area[ids], color=color,
                        line=dict(color=[RING if x else SURFACE for x in sub["in_government"]],
                                  width=[2 if x else 1 for x in sub["in_government"]])),
            text=text, hoverinfo="text"))
    traces.append(go.Scatter(
        x=[pos[n][0] for n in labels], y=[pos[n][1] for n in labels], mode="text",
        text=[nodes.at[n, "name"] for n in labels], textposition="top center",
        textfont=dict(size=10, color="#0b0b0b"), hoverinfo="skip", showlegend=False))
    fig = go.Figure(traces)
    fig.update_layout(
        title=dict(text=f"Who challenges whom, {window}<br><sup>Node size = challenges received; dark ring = "
                        "in government; hover a node for details</sup>", x=0.01),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, height=850, hovermode="closest",
        xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"),
        legend=dict(orientation="h", y=-0.02), margin=dict(l=10, r=10, t=70, b=10))
    fig.write_html(path, include_plotlyjs="cdn")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", default="2022 M+S+V", help='a window name, e.g. "2019 S", or "all"')
    parser.add_argument("--min-weight", type=int, default=3, help="hide pairs with fewer challenges than this")
    parser.add_argument("--labels", type=int, default=10, help="name the N most-challenged members")
    args = parser.parse_args(argv)

    edges, _, _, windows, _ = load_all()
    graphs = graphs_by_window(edges, windows)
    if args.window not in graphs:
        raise SystemExit(f"Unknown window {args.window!r}. Choose from: {', '.join(graphs)}")
    _, graph = graphs[args.window]

    g = undirected(graph, args.min_weight)
    g.remove_nodes_from([n for n in list(g.nodes) if g.degree(n) == 0])
    nodes = node_table(g, args.window)
    pos = nx.spring_layout(g, weight="weight", seed=SEED, iterations=300, k=2.5 / g.number_of_nodes() ** 0.5)
    labels = nodes["in_w"].sort_values(ascending=False).head(args.labels).index.tolist()

    folder = OUT / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    stem = "network_" + re.sub(r"[^A-Za-z0-9]+", "_", args.window).strip("_")
    draw_png(g, pos, nodes, labels, args.window, args.min_weight, folder / f"{stem}.png")
    draw_html(g, pos, nodes, labels, args.window, folder / f"{stem}.html")
    print(f"{g.number_of_nodes()} members, {g.number_of_edges()} pairs with >= {args.min_weight} challenges")
    print(f"Wrote {folder / stem}.png and .html")


if __name__ == "__main__":
    main()
