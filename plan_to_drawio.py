"""
Draw.io XML Generator - Simple Flowchart Style

Simple vertical flowchart with:
- Clean top-to-bottom layout
- Pastel colors
- Proper arrows
- Optional grouping
"""

from __future__ import annotations
import html
from typing import Dict, List, Any
import math


# =============================================================================
# PASTEL COLORS (clean, professional)
# =============================================================================

NODE_COLORS = {
    "input": {"fill": "#FFE4C4", "stroke": "#DEB887"},      # Peach
    "process": {"fill": "#E6E6FA", "stroke": "#B8B8DC"},    # Lavender
    "compute": {"fill": "#FFE4C4", "stroke": "#DEB887"},    # Orange/Peach
    "model": {"fill": "#87CEEB", "stroke": "#6BB3D9"},      # Sky blue
    "database": {"fill": "#DDA0DD", "stroke": "#C18BC1"},   # Plum
    "data": {"fill": "#DDA0DD", "stroke": "#C18BC1"},       # Plum
    "storage": {"fill": "#98FB98", "stroke": "#7CCD7C"},    # Mint
    "network": {"fill": "#B0E0E6", "stroke": "#96C8CE"},    # Powder blue
    "security": {"fill": "#FFB6C1", "stroke": "#DB9BA5"},   # Pink
    "output": {"fill": "#98FB98", "stroke": "#7CCD7C"},     # Mint
    "external": {"fill": "#F0E68C", "stroke": "#D4CA7A"},   # Khaki
    "default": {"fill": "#E0E0E0", "stroke": "#BDBDBD"},    # Gray
}

# Layout constants
NODE_WIDTH = 140
NODE_HEIGHT = 45
VERTICAL_SPACING = 70
HORIZONTAL_SPACING = 160
MARGIN = 50


def _escape(text: str) -> str:
    return html.escape(str(text))


def _get_color(node_type: str) -> Dict[str, str]:
    return NODE_COLORS.get(node_type, NODE_COLORS["default"])


def _node_style(node_type: str) -> str:
    colors = _get_color(node_type)
    return (
        f"rounded=1;whiteSpace=wrap;html=1;arcSize=20;"
        f"fillColor={colors['fill']};"
        f"strokeColor={colors['stroke']};"
        f"strokeWidth=1.5;"
        f"fontColor=#333333;"
        f"fontSize=11;"
        f"fontFamily=Arial;"
    )


def plan_to_mxgraph(plan: Dict[str, Any]) -> str:
    """Convert architecture plan to simple flowchart XML."""
    title = plan.get("title", "Architecture")
    nodes = plan.get("nodes", [])
    edges = plan.get("edges", [])
    groups = plan.get("groups") or plan.get("containers") or []
    
    # Limit nodes
    nodes = nodes[:10]
    
    # Build graph for layout
    outgoing = {n.get("id"): [] for n in nodes}
    incoming = {n.get("id"): [] for n in nodes}
    
    for e in edges:
        src, tgt = e.get("from"), e.get("to")
        if src in outgoing and tgt in incoming:
            outgoing[src].append(tgt)
            incoming[tgt].append(src)
    
    # Find layout layers using BFS
    roots = [n.get("id") for n in nodes if not incoming.get(n.get("id"))]
    if not roots and nodes:
        roots = [nodes[0].get("id")]
    
    layers = {}
    visited = set()
    current = roots[:]
    layer = 0
    
    while current:
        for nid in current:
            if nid not in layers:
                layers[nid] = layer
            visited.add(nid)
        
        next_layer = []
        for nid in current:
            for child in outgoing.get(nid, []):
                if child not in visited:
                    next_layer.append(child)
        
        current = list(set(next_layer))
        layer += 1
    
    # Assign unvisited nodes
    for n in nodes:
        nid = n.get("id")
        if nid not in layers:
            layers[nid] = layer
            layer += 1
    
    # Group by layer
    by_layer = {}
    for nid, ly in layers.items():
        by_layer.setdefault(ly, []).append(nid)
    
    # Calculate positions
    positions = {}
    y = MARGIN + 50  # Space for title
    
    max_width = 0
    for ly in sorted(by_layer.keys()):
        layer_nodes = by_layer[ly]
        total_width = len(layer_nodes) * HORIZONTAL_SPACING
        start_x = max(MARGIN, (600 - total_width) // 2)
        max_width = max(max_width, start_x + total_width)
        
        for i, nid in enumerate(layer_nodes):
            x = start_x + i * HORIZONTAL_SPACING
            positions[nid] = (x, y)
        
        y += VERTICAL_SPACING
    
    # Calculate diagram size
    width = max(600, max_width + MARGIN)
    height = y + MARGIN
    
    # Build XML
    parts = []
    parts.append(
        f'<mxGraphModel dx="{width}" dy="{height}" grid="1" gridSize="10" '
        f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
        f'pageScale="1" pageWidth="{width}" pageHeight="{height}">'
    )
    parts.append("  <root>")
    parts.append('    <mxCell id="0" />')
    parts.append('    <mxCell id="1" parent="0" />')
    
    # Title
    parts.append(
        f'    <mxCell id="title" value="{_escape(title)}" '
        f'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
        f'verticalAlign=middle;fontStyle=1;fontSize=16;fontColor=#333333;" '
        f'vertex="1" parent="1">'
    )
    parts.append(f'      <mxGeometry x="{MARGIN}" y="20" width="{width - MARGIN*2}" height="30" as="geometry" />')
    parts.append('    </mxCell>')
    
    # Groups (dashed containers)
    node_to_group = {n.get("id"): n.get("group") or n.get("container") for n in nodes}
    group_bounds = {}
    
    for group in groups:
        gid = group.get("id")
        gname = group.get("name", gid)
        
        group_nodes = [nid for nid, g in node_to_group.items() if g == gid]
        if not group_nodes or not all(nid in positions for nid in group_nodes):
            continue
        
        xs = [positions[nid][0] for nid in group_nodes]
        ys = [positions[nid][1] for nid in group_nodes]
        
        gx = min(xs) - 15
        gy = min(ys) - 25
        gw = max(xs) - min(xs) + NODE_WIDTH + 30
        gh = max(ys) - min(ys) + NODE_HEIGHT + 35
        
        group_bounds[gid] = (gx, gy, gw, gh)
        
        parts.append(
            f'    <mxCell id="g_{gid}" value="{_escape(gname)}" '
            f'style="rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=5 3;'
            f'fillColor=#FAFAFA;strokeColor=#AAAAAA;strokeWidth=1;'
            f'verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;'
            f'fontSize=10;fontColor=#666666;" '
            f'vertex="1" parent="1">'
        )
        parts.append(f'      <mxGeometry x="{gx}" y="{gy}" width="{gw}" height="{gh}" as="geometry" />')
        parts.append('    </mxCell>')
    
    # Nodes
    node_cells = {}
    for node in nodes:
        nid = node.get("id")
        if nid not in positions:
            continue
        
        x, y = positions[nid]
        ntype = node.get("type", "default")
        name = node.get("name", nid)
        
        # Truncate long names
        if len(name) > 18:
            name = name[:15] + "..."
        
        style = _node_style(ntype)
        node_cells[nid] = f"n_{nid}"
        
        parts.append(
            f'    <mxCell id="n_{nid}" value="{_escape(name)}" '
            f'style="{style}" vertex="1" parent="1">'
        )
        parts.append(f'      <mxGeometry x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" as="geometry" />')
        parts.append('    </mxCell>')
    
    # Edges with orthogonal routing
    for edge in edges:
        src = edge.get("from", "")
        tgt = edge.get("to", "")
        label = edge.get("label", "")
        
        src_cell = node_cells.get(src)
        tgt_cell = node_cells.get(tgt)
        
        if not src_cell or not tgt_cell:
            continue
        
        # Truncate label
        if len(label) > 20:
            label = label[:17] + "..."
        
        edge_style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
            "jettySize=auto;html=1;strokeColor=#666666;strokeWidth=1.5;"
            "endArrow=classic;endFill=1;endSize=6;"
            "fontColor=#666666;fontSize=10;"
        )
        
        parts.append(
            f'    <mxCell id="e_{src}_{tgt}" value="{_escape(label)}" style="{edge_style}" '
            f'edge="1" parent="1" source="{src_cell}" target="{tgt_cell}">'
        )
        parts.append('      <mxGeometry relative="1" as="geometry" />')
        parts.append('    </mxCell>')
    
    parts.append("  </root>")
    parts.append("</mxGraphModel>")
    
    return "\n".join(parts)


def plans_to_mxgraph(plans: List[Dict[str, Any]]) -> str:
    """For multiple plans, use the first one."""
    if not plans:
        return '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'
    return plan_to_mxgraph(plans[0])
