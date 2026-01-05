"""
Draw.io XML Generator - Creates professional architecture diagrams

This module converts architecture plans (JSON) to Draw.io mxGraphModel XML.
Features:
- Intelligent layout with proper spacing
- Layer-based coloring and styling
- Group containers with dashed/solid borders
- Labeled edges with proper routing
- Professional typography and contrast
"""

from __future__ import annotations

import html
from typing import Dict, List, Any, Tuple
import re
import math


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_LANES = [
    "Experience",
    "Application",
    "Integration",
    "Data",
    "Platform & Security",
]

# Professional color palette for architecture layers
LANE_COLORS = {
    "Experience": {
        "fill": "#0a6ed1",
        "stroke": "#0858a8",
        "bg": "#e8f4fd",
        "text": "#ffffff"
    },
    "Application": {
        "fill": "#1a9898",
        "stroke": "#147a7a",
        "bg": "#e6f5f5",
        "text": "#ffffff"
    },
    "Integration": {
        "fill": "#f39c12",
        "stroke": "#c77d0e",
        "bg": "#fef5e6",
        "text": "#ffffff"
    },
    "Data": {
        "fill": "#6c5ce7",
        "stroke": "#5649b9",
        "bg": "#f0eef9",
        "text": "#ffffff"
    },
    "Platform & Security": {
        "fill": "#2c3e50",
        "stroke": "#1a252f",
        "bg": "#ebeff2",
        "text": "#ffffff"
    },
    "External": {
        "fill": "#95a5a6",
        "stroke": "#7f8c8d",
        "bg": "#f4f6f6",
        "text": "#ffffff"
    }
}

# Layout constants
LANE_HEIGHT = 130
LANE_PADDING = 20
NODE_WIDTH = 160
NODE_HEIGHT = 60
NODE_SPACING_X = 200
NODE_SPACING_Y = 20
GROUP_PADDING = 30
DIAGRAM_MARGIN = 40


def _get_lane_colors(lane: str) -> Dict[str, str]:
    """Get color scheme for a lane."""
    return LANE_COLORS.get(lane, LANE_COLORS["External"])


def _is_dark(hex_color: str) -> bool:
    """Check if a color is dark (for text contrast)."""
    c = hex_color or "#000000"
    if not c.startswith('#'):
        c = f'#{c}'
    if not re.match(r'^#[0-9a-fA-F]{6}$', c):
        return False
    r = int(c[1:3], 16) / 255.0
    g = int(c[3:5], 16) / 255.0
    b = int(c[5:7], 16) / 255.0
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return lum < 0.5


def _node_style(node: Dict[str, Any]) -> str:
    """Generate mxCell style for a node."""
    lane = node.get("lane", "Application")
    colors = _get_lane_colors(lane)
    fill = colors["fill"]
    stroke = colors["stroke"]

    node_type = node.get("type", "app")
    scope = (node.get("scope") or "").lower()

    # External nodes get gray styling
    if node_type == "external" or scope == "external":
        ext_colors = LANE_COLORS["External"]
        fill = ext_colors["fill"]
        stroke = ext_colors["stroke"]

    # Shape based on type
    if node_type == "data":
        shape = "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15"
    elif node_type == "security":
        shape = "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;size=20"
    else:
        shape = "rounded=1;whiteSpace=wrap;html=1;arcSize=20"

    font_color = "#ffffff" if _is_dark(fill) else "#1a1a1a"

    return f"{shape};fillColor={fill};strokeColor={stroke};strokeWidth=2;fontColor={font_color};fontSize=12;fontStyle=1;shadow=1;"


def _lane_positions(lanes: List[str]) -> Dict[str, int]:
    """Calculate Y positions for each lane."""
    positions = {}
    y = DIAGRAM_MARGIN + 40  # Leave space for title
    for lane in lanes:
        positions[lane] = y
        y += LANE_HEIGHT + LANE_PADDING
    return positions


def _layout_nodes_in_lanes(plan: Dict[str, Any], lane_y: Dict[str, int]) -> Dict[str, Tuple[float, float]]:
    """Calculate node positions with intelligent layout."""
    positions: Dict[str, Tuple[float, float]] = {}
    nodes_by_lane: Dict[str, List[Dict[str, Any]]] = {}

    # Group nodes by lane
    for node in plan.get("nodes", []):
        lane = node.get("lane", "Application")
        nodes_by_lane.setdefault(lane, []).append(node)

    # Position nodes in each lane
    for lane, nodes in nodes_by_lane.items():
        y = lane_y.get(lane, 120) + 35  # Center vertically in lane

        # Sort by group to cluster related nodes
        nodes.sort(key=lambda n: (n.get("group") or "zzz", n.get("id", "")))

        x = DIAGRAM_MARGIN + 180  # Start after lane label
        for node in nodes:
            positions[node["id"]] = (x, y)
            x += NODE_SPACING_X

    return positions


def _calculate_diagram_size(positions: Dict[str, Tuple[float, float]], lane_count: int) -> Tuple[int, int]:
    """Calculate total diagram dimensions."""
    if not positions:
        return (1000, 600)

    max_x = max(x for x, y in positions.values()) + NODE_WIDTH + DIAGRAM_MARGIN
    height = DIAGRAM_MARGIN * 2 + 40 + (LANE_HEIGHT + LANE_PADDING) * lane_count

    return (max(1200, int(max_x)), int(height))


def plan_to_mxgraph(plan: Dict[str, Any]) -> str:
    """
    Convert architecture plan to Draw.io mxGraphModel XML.

    Args:
        plan: Dict with lanes, groups, nodes, edges, legend

    Returns:
        Valid mxGraphModel XML string
    """
    lanes: List[str] = plan.get("lanes") or DEFAULT_LANES
    lane_y = _lane_positions(lanes)
    positions = _layout_nodes_in_lanes(plan, lane_y)
    width, height = _calculate_diagram_size(positions, len(lanes))

    parts: List[str] = []

    # XML header
    parts.append(f'<mxGraphModel dx="{width}" dy="{height}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{width}" pageHeight="{height}" math="0" shadow="1">')
    parts.append("  <root>")
    parts.append('    <mxCell id="0" />')
    parts.append('    <mxCell id="1" parent="0" />')

    cell_id = 100

    # =================================================================
    # DIAGRAM TITLE
    # =================================================================
    title = plan.get("title", "Architecture Diagram")
    parts.append(f'    <mxCell id="{cell_id}" value="{html.escape(title)}" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontStyle=1;fontSize=18;fontColor=#1a1a1a;" vertex="1" parent="1">')
    parts.append(f'      <mxGeometry x="{DIAGRAM_MARGIN}" y="{DIAGRAM_MARGIN}" width="400" height="30" as="geometry" />')
    parts.append('    </mxCell>')
    cell_id += 1

    # =================================================================
    # LANE BACKGROUNDS
    # =================================================================
    lane_width = width - DIAGRAM_MARGIN * 2

    for lane in lanes:
        y = lane_y.get(lane, 120) - 10
        colors = _get_lane_colors(lane)

        # Lane background stripe
        parts.append(f'    <mxCell id="{cell_id}" value="" style="rounded=0;whiteSpace=wrap;html=1;strokeColor=#e0e0e0;fillColor={colors["bg"]};opacity=50;" vertex="1" parent="1">')
        parts.append(f'      <mxGeometry x="{DIAGRAM_MARGIN}" y="{y}" width="{lane_width}" height="{LANE_HEIGHT}" as="geometry" />')
        parts.append('    </mxCell>')
        cell_id += 1

        # Lane header label
        parts.append(f'    <mxCell id="{cell_id}" value="{html.escape(lane)}" style="text;html=1;strokeColor=none;fillColor=none;fontStyle=1;fontColor={colors["fill"]};align=left;verticalAlign=top;fontSize=13;spacingLeft=4;" vertex="1" parent="1">')
        parts.append(f'      <mxGeometry x="{DIAGRAM_MARGIN + 8}" y="{y + 6}" width="160" height="24" as="geometry" />')
        parts.append('    </mxCell>')
        cell_id += 1

    # =================================================================
    # GROUPS (Containers)
    # =================================================================
    group_cells: Dict[str, int] = {}
    seen_groups = set()

    for group in plan.get("groups", []) or []:
        gid = group.get("id")
        if not gid or gid in seen_groups:
            continue
        seen_groups.add(gid)

        lane = group.get("lane", "Platform & Security")
        y = lane_y.get(lane, 120) - 5
        style_type = group.get("style", "dashed")

        # Calculate group bounds based on contained nodes
        group_nodes = [n for n in plan.get("nodes", []) if n.get("group") == gid]
        if group_nodes:
            xs = [positions.get(n["id"], (0, 0))[0] for n in group_nodes if n["id"] in positions]
            if xs:
                x = min(xs) - GROUP_PADDING
                w = max(xs) - min(xs) + NODE_WIDTH + GROUP_PADDING * 2
            else:
                x = DIAGRAM_MARGIN + 160
                w = 400
        else:
            x = DIAGRAM_MARGIN + 160
            w = 400

        h = LANE_HEIGHT - 10
        dash = "1" if style_type == "dashed" else "0"

        group_style = f"rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;fillOpacity=60;strokeColor=#666666;strokeWidth=2;dashed={dash};dashPattern=8 4;verticalAlign=top;fontStyle=1;fontSize=11;fontColor=#666666;spacingTop=4;"

        parts.append(f'    <mxCell id="g_{gid}" value="{html.escape(group.get("name", gid))}" style="{group_style}" vertex="1" parent="1">')
        parts.append(f'      <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />')
        parts.append('    </mxCell>')
        group_cells[gid] = cell_id
        cell_id += 1

    # =================================================================
    # NODES
    # =================================================================
    seen_nodes = set()
    node_cells: Dict[str, str] = {}

    for node in plan.get("nodes", []) or []:
        nid = node.get("id")
        if not nid or nid in seen_nodes or nid not in positions:
            continue
        seen_nodes.add(nid)

        x, y = positions[nid]
        style = _node_style(node)
        name = node.get("name", nid)

        # Parent - use group if specified, otherwise root
        parent = "1"
        if node.get("group") and node["group"] in group_cells:
            parent = f'g_{node["group"]}'

        node_cell_id = f"n_{nid}"
        node_cells[nid] = node_cell_id

        parts.append(f'    <mxCell id="{node_cell_id}" value="{html.escape(name)}" style="{style}" vertex="1" parent="{parent}">')
        parts.append(f'      <mxGeometry x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" as="geometry" />')
        parts.append('    </mxCell>')

    # =================================================================
    # EDGES
    # =================================================================
    seen_edges = set()

    for edge in plan.get("edges", []) or []:
        src = edge.get("from", "")
        tgt = edge.get("to", "")
        label = edge.get("label", "")

        if not src or not tgt:
            continue

        edge_key = (src, tgt)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        src_cell = node_cells.get(src, src)
        tgt_cell = node_cells.get(tgt, tgt)

        edge_style = "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#333333;strokeWidth=2;endArrow=blockThin;endFill=1;endSize=8;"

        parts.append(f'    <mxCell id="e_{src}_{tgt}" style="{edge_style}" edge="1" parent="1" source="{src_cell}" target="{tgt_cell}">')
        parts.append('      <mxGeometry relative="1" as="geometry" />')
        parts.append('    </mxCell>')

        # Edge label
        if label:
            # Calculate label position at midpoint
            sx, sy = positions.get(src, (0, 0))
            tx, ty = positions.get(tgt, (0, 0))
            lx = (sx + tx) / 2 + NODE_WIDTH / 2
            ly = (sy + ty) / 2 - 15

            label_escaped = html.escape(label)
            parts.append(f'    <mxCell id="l_{src}_{tgt}" value="{label_escaped}" style="text;html=1;strokeColor=none;fillColor=#ffffff;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=1;fontSize=10;fontColor=#333333;spacing=2;labelBackgroundColor=#ffffff;" vertex="1" parent="1">')
            parts.append(f'      <mxGeometry x="{lx - 50}" y="{ly}" width="100" height="20" as="geometry" />')
            parts.append('    </mxCell>')

    # =================================================================
    # LEGEND
    # =================================================================
    if plan.get("legend", True):
        legend_x = width - 200
        legend_y = DIAGRAM_MARGIN

        parts.append(f'    <mxCell id="legend" value="Legend" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;fontStyle=1;fontSize=11;fontColor=#666666;" vertex="1" parent="1">')
        parts.append(f'      <mxGeometry x="{legend_x}" y="{legend_y}" width="80" height="20" as="geometry" />')
        parts.append('    </mxCell>')

        ly = legend_y + 25
        for lane in lanes[:4]:  # Show first 4 lanes in legend
            colors = _get_lane_colors(lane)
            # Color swatch
            parts.append(f'    <mxCell id="leg_{lane}" value="" style="rounded=1;whiteSpace=wrap;html=1;fillColor={colors["fill"]};strokeColor={colors["stroke"]};" vertex="1" parent="1">')
            parts.append(f'      <mxGeometry x="{legend_x}" y="{ly}" width="16" height="16" as="geometry" />')
            parts.append('    </mxCell>')
            # Label
            parts.append(f'    <mxCell id="legl_{lane}" value="{html.escape(lane)}" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=9;fontColor=#666666;" vertex="1" parent="1">')
            parts.append(f'      <mxGeometry x="{legend_x + 22}" y="{ly}" width="100" height="16" as="geometry" />')
            parts.append('    </mxCell>')
            ly += 22

    # Close XML
    parts.append("  </root>")
    parts.append("</mxGraphModel>")

    return "\n".join(parts)
