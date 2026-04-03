#!/usr/bin/env python3
"""Extract Obsidian vault into graph JSON for 3D visualization."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from vault_io import read_note

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
OUTPUT = Path(__file__).parent / "data" / "vault_graph.json"

# Wiki-link pattern: [[target]] or [[target|display]]
WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

# Color groups (hex) matching Obsidian graph.json
COLOR_MAP = {
    "0. INPUT/People": "#FF6B6B",      # red
    "0. INPUT/Meeting": "#FFA94D",      # orange
    "0. INPUT/COLLECT": "#FFD43B",      # yellow
    "0. INPUT": "#FF8787",              # light red (other INPUT)
    "1. THINK/매일": "#51CF66",         # green
    "1. THINK/Projects": "#339AF0",     # blue
    "1. THINK": "#6BB5FF",             # light blue (other THINK)
    "2. OUTPUT": "#CC5DE8",             # purple
}

# Category labels
CATEGORY_MAP = {
    "0. INPUT/People": "인물",
    "0. INPUT/Meeting": "미팅",
    "0. INPUT/COLLECT/00. Inbox": "인박스",
    "0. INPUT/COLLECT": "수집",
    "0. INPUT": "인풋",
    "1. THINK/매일": "데일리",
    "1. THINK/Projects": "프로젝트",
    "1. THINK": "생각",
    "2. OUTPUT": "아웃풋",
}


def get_color(rel_path: str) -> str:
    for prefix, color in COLOR_MAP.items():
        if rel_path.startswith(prefix):
            return color
    return "#868E96"  # gray


def get_category(rel_path: str) -> str:
    for prefix, cat in CATEGORY_MAP.items():
        if rel_path.startswith(prefix):
            return cat
    return "기타"


def extract_links(text: str) -> list[str]:
    """Extract wiki-link targets from markdown text."""
    return WIKILINK_RE.findall(text)


def main():
    print(f"Scanning vault: {VAULT_ROOT}")

    # Build stem→path index for link resolution
    stem_index: dict[str, Path] = {}
    all_md_files = list(VAULT_ROOT.rglob("*.md"))

    # Skip .obsidian and .trash
    all_md_files = [
        f for f in all_md_files
        if not any(p.startswith('.') for p in f.relative_to(VAULT_ROOT).parts)
    ]

    for f in all_md_files:
        stem_index[f.stem] = f

    print(f"Found {len(all_md_files)} markdown files")

    nodes = []
    edges = []
    node_ids = {}  # stem → node_id

    # Pass 1: Create nodes
    for i, fpath in enumerate(sorted(all_md_files)):
        rel = str(fpath.relative_to(VAULT_ROOT))
        stem = fpath.stem
        node_id = str(i)
        node_ids[stem] = node_id

        # Try to read frontmatter
        fm = {}
        try:
            fm, body = read_note(fpath)
        except Exception:
            try:
                body = fpath.read_text(encoding='utf-8')
            except Exception:
                body = ""

        # Extract metadata
        note_type = fm.get('type', '')
        if isinstance(note_type, list):
            note_type = note_type[0] if note_type else ''
        created = fm.get('created', '')
        tags = fm.get('tags', [])
        if isinstance(tags, str):
            tags = [tags]

        # Count outgoing links
        links = extract_links(body) if body else []

        node = {
            "id": node_id,
            "name": stem,
            "path": rel,
            "folder": str(fpath.parent.relative_to(VAULT_ROOT)),
            "color": get_color(rel),
            "category": get_category(rel),
            "type": note_type,
            "created": str(created)[:10] if created else "",
            "tags": tags if tags else [],
            "linkCount": len(links),
            "size": 1,  # will be updated based on degree
        }
        nodes.append(node)

    # Pass 2: Create edges
    edge_set = set()
    for fpath in sorted(all_md_files):
        stem = fpath.stem
        source_id = node_ids.get(stem)
        if not source_id:
            continue

        try:
            _, body = read_note(fpath)
        except Exception:
            try:
                body = fpath.read_text(encoding='utf-8')
            except Exception:
                continue

        links = extract_links(body) if body else []
        for target_stem in links:
            target_id = node_ids.get(target_stem)
            if target_id and target_id != source_id:
                edge_key = tuple(sorted([source_id, target_id]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        "source": edge_key[0],
                        "target": edge_key[1],
                    })

    # Update node sizes based on degree (connections)
    degree = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1

    for node in nodes:
        d = degree.get(node["id"], 0)
        # Size: min 1, max 8, log scale
        import math
        node["size"] = min(8, max(1, 1 + math.log2(d + 1)))
        node["degree"] = d

    # Category summary
    categories = {}
    for n in nodes:
        cat = n["category"]
        categories[cat] = categories.get(cat, 0) + 1

    graph = {
        "nodes": nodes,
        "edges": edges,
        "categories": categories,
        "totalNodes": len(nodes),
        "totalEdges": len(edges),
        "generated": datetime.now().isoformat(),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2))
    print(f"Output: {OUTPUT}")
    print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
