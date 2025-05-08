#!/usr/bin/env python3
"""
view_flame.py

Read FlameGraph‐style folded stacks from stdin and
render an aggregated, collapsible tree in your terminal
using Rich, with human-friendly time units.
"""

import sys
from rich import print
from rich.tree import Tree


def format_time(us: int) -> str:
    """Convert microseconds to a human-friendly string."""
    if us >= 1_000_000:
        return f"{us / 1_000_000:.2f}s"
    elif us >= 1_000:
        return f"{us / 1_000:.2f}ms"
    else:
        return f"{us}μs"


def build_tree(folded_lines):
    # Nested dict: node → { '_time': total_us, 'children': {} }
    root = {"_time": 0, "children": {}}
    for line in folded_lines:
        line = line.strip()
        if not line or " " not in line:
            continue
        stack_part, us_part = line.rsplit(" ", 1)
        try:
            dur = int(us_part)
        except ValueError:
            continue
        frames = stack_part.split(";")
        node = root
        node["_time"] += dur
        for frame in frames:
            children = node["children"]
            if frame not in children:
                children[frame] = {"_time": 0, "children": {}}
            node = children[frame]
            node["_time"] += dur
    return root


def build_tree_from_spans(spans: dict, build_path_func) -> dict:
    """Build a nested tree with aggregated durations and earliest start times per node."""
    root = {"_time": 0, "_start": float("inf"), "children": {}}
    for span_id, info in spans.items():
        start_us = info.get("start", 0)
        dur = info.get("end", 0) - start_us
        path = build_path_func(span_id, spans)
        node = root
        node["_time"] += dur
        if start_us < node.get("_start", float("inf")):
            node["_start"] = start_us
        for frame in path:
            children = node["children"]
            if frame not in children:
                children[frame] = {"_time": 0, "_start": float("inf"), "children": {}}
            node = children[frame]
            node["_time"] += dur
            if start_us < node.get("_start", float("inf")):
                node["_start"] = start_us
    return root


def render(node, tree: Tree, total_time: int):
    """
    Recursively render the flame-graph tree as a nested tree view in the terminal.
    """
    # Render each child as its own branch, sorted by earliest start time
    children = node.get("children", {})
    for name, child in sorted(children.items(), key=lambda kv: kv[1].get("_start", 0)):
        dur = child["_time"]
        pct = (dur / total_time * 100) if total_time else 0
        human = format_time(dur)
        branch = tree.add(f"[bold]{name}[/] • {human} ({pct:.1f}%)")
        render(child, branch, total_time)


def main():
    folded = sys.stdin.readlines()
    root = build_tree(folded)
    total = root["_time"]
    human_total = format_time(total)
    console_tree = Tree(f"[b]root[/] • {human_total} (100%)")
    render(root, console_tree, total)
    print(console_tree)


if __name__ == "__main__":
    main()
