"""
SVG Renderer for Draw.io mxGraphModel XML

Renders mxGraphModel XML to standalone SVG for preview display.
Features:
- Proper shape rendering (rectangles, cylinders, hexagons)
- Color-aware text contrast
- Layer backgrounds
- Edge arrows with labels
"""

from __future__ import annotations

import html
import re
from typing import Dict, Tuple, List, Optional
from xml.etree import ElementTree as ET


def _strip_code_fences(s: str) -> str:
    """Remove markdown code fences."""
    t = s.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _sanitize_mxgraphmodel(xml_text: str) -> str:
    """Clean up mxGraphModel XML for parsing."""
    txt = _strip_code_fences(xml_text)

    # Deduplicate attributes on the root tag
    m = re.match(r"\s*<mxGraphModel\s+([^>]*)>([\s\S]*)</mxGraphModel>\s*\Z", txt)
    if not m:
        return txt

    attrs_str, inner = m.group(1), m.group(2)
    pairs = re.findall(r'([A-Za-z_:][\w:.-]*)\s*=\s*("[^"]*"|\'[^\']*\')', attrs_str)
    seen: Dict[str, str] = {}
    for k, v in pairs:
        seen[k] = v

    # Stable attribute order
    order = ["dx", "dy", "grid", "gridSize", "guides", "tooltips", "connect",
             "arrows", "fold", "page", "pageScale", "pageWidth", "pageHeight",
             "math", "shadow", "background", "version"]
    items = []
    for k in order:
        if k in seen:
            items.append(f"{k}={seen[k]}")
            seen.pop(k)
    for k, v in seen.items():
        items.append(f"{k}={v}")

    return f"<mxGraphModel {' '.join(items)}>{inner}</mxGraphModel>"


def _parse_style(style: str) -> Dict[str, str]:
    """Parse mxCell style string to dict."""
    out: Dict[str, str] = {}
    if not style:
        return out
    for p in style.split(";"):
        p = p.strip()
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[p] = "1"
    return out


def _normalize_color(v: str, default: str = "#000000") -> str:
    """Normalize color value to hex."""
    if not v:
        return default
    v = v.strip()
    if v.startswith("#"):
        return v
    if re.match(r"^[0-9a-fA-F]{6}$", v):
        return f"#{v}"
    # Named colors
    color_map = {
        "white": "#ffffff", "black": "#000000", "red": "#ff0000",
        "green": "#00ff00", "blue": "#0000ff", "gray": "#888888",
        "none": "none"
    }
    return color_map.get(v.lower(), default)


def _is_dark(hex_color: str) -> bool:
    """Check if color is dark for text contrast."""
    c = hex_color
    if not c or c == "none" or not c.startswith("#"):
        return False
    if len(c) != 7:
        return False
    try:
        r = int(c[1:3], 16) / 255.0
        g = int(c[3:5], 16) / 255.0
        b = int(c[5:7], 16) / 255.0
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return lum < 0.5
    except ValueError:
        return False


def _text_color_for_bg(bg_color: str) -> str:
    """Get appropriate text color for background."""
    return "#ffffff" if _is_dark(bg_color) else "#1a1a1a"


def drawio_xml_to_svg(xml_text: str) -> str:
    """
    Convert Draw.io mxGraphModel XML to SVG.

    Args:
        xml_text: Valid mxGraphModel XML string

    Returns:
        Standalone SVG string
    """
    xml_text = _sanitize_mxgraphmodel(xml_text)
    xml_text = re.sub(r"&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='400' height='100'><text x='20' y='50' fill='red'>XML Parse Error: {html.escape(str(e))}</text></svg>"

    if root.tag != "mxGraphModel":
        if root.tag == "mxfile":
            diag = root.find(".//diagram")
            if diag is not None and diag.text:
                return drawio_xml_to_svg(diag.text)
        raise ValueError("Unsupported XML root tag")

    cells = root.findall(".//mxCell")

    # Parse all cells
    vertices: Dict[str, Dict] = {}
    edges: List[Dict] = []

    for cell in cells:
        cid = cell.get("id") or ""
        style = _parse_style(cell.get("style") or "")
        value = html.unescape(cell.get("value") or "")
        is_vertex = cell.get("vertex") == "1"
        is_edge = cell.get("edge") == "1"
        geom = cell.find("mxGeometry")

        if is_vertex and geom is not None:
            x = float(geom.get("x") or 0)
            y = float(geom.get("y") or 0)
            w = float(geom.get("width") or 120)
            h = float(geom.get("height") or 60)
            vertices[cid] = {
                "id": cid,
                "x": x, "y": y, "w": w, "h": h,
                "value": value,
                "style": style,
                "parent": cell.get("parent", "1")
            }
        elif is_edge:
            edges.append({
                "id": cid,
                "source": cell.get("source"),
                "target": cell.get("target"),
                "style": style,
            })

    # Compute bounding box
    if not vertices:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200'><text x='20' y='100' fill='#666'>No diagram elements</text></svg>"

    min_x = min(v["x"] for v in vertices.values())
    min_y = min(v["y"] for v in vertices.values())
    max_x = max(v["x"] + v["w"] for v in vertices.values())
    max_y = max(v["y"] + v["h"] for v in vertices.values())

    margin = 30
    width = int(max(400, max_x - min_x + 2 * margin))
    height = int(max(300, max_y - min_y + 2 * margin))

    def tx(x: float) -> float:
        return x - min_x + margin

    def ty(y: float) -> float:
        return y - min_y + margin

    def center(v: Dict) -> Tuple[float, float]:
        return (tx(v["x"]) + v["w"] / 2, ty(v["y"]) + v["h"] / 2)

    # Build SVG
    svg_parts: List[str] = []

    # Header with embedded fonts
    svg_parts.append(f"""<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>
  <defs>
    <style>
      .node-text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-weight: 600; }}
      .label-text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 10px; }}
      .lane-text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-weight: 700; }}
    </style>
    <marker id="arrow" markerWidth="12" markerHeight="8" refX="10" refY="4" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L12,4 L0,8 L3,4 Z" fill="#333" />
    </marker>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="2" dy="2" stdDeviation="2" flood-opacity="0.15"/>
    </filter>
  </defs>
  <rect width="{width}" height="{height}" fill="#ffffff"/>""")

    # Sort vertices by z-order (backgrounds first, then groups, then nodes)
    def vertex_order(v: Dict) -> int:
        st = v["style"]
        if st.get("opacity") or st.get("fillOpacity"):
            return 0  # Background lanes
        if st.get("dashed"):
            return 1  # Groups
        if "text" in st or st.get("strokeColor") == "none":
            return 2  # Labels
        return 3  # Nodes

    sorted_vertices = sorted(vertices.values(), key=vertex_order)

    # Render edges first (under everything)
    for e in edges:
        src = vertices.get(e.get("source") or "")
        tgt = vertices.get(e.get("target") or "")
        if not src or not tgt:
            continue

        sx, sy = center(src)
        tx_e, ty_e = center(tgt)

        stroke = _normalize_color(e["style"].get("strokeColor", "#333"), "#333")
        stroke_width = e["style"].get("strokeWidth", "2")

        svg_parts.append(
            f"  <line x1='{sx:.1f}' y1='{sy:.1f}' x2='{tx_e:.1f}' y2='{ty_e:.1f}' "
            f"stroke='{stroke}' stroke-width='{stroke_width}' marker-end='url(#arrow)'/>"
        )

    # Render vertices
    for v in sorted_vertices:
        x = tx(v["x"])
        y = ty(v["y"])
        w = v["w"]
        h = v["h"]
        st = v["style"]
        value = v["value"]

        fill = _normalize_color(st.get("fillColor", "#f5f5f5"), "#f5f5f5")
        stroke = _normalize_color(st.get("strokeColor", "#333"), "#333")
        opacity = st.get("opacity", "100")
        fill_opacity = st.get("fillOpacity", "100")

        # Text-only elements
        if "text" in st or st.get("strokeColor") == "none":
            font_size = st.get("fontSize", "12")
            font_color = _normalize_color(st.get("fontColor", "#333"), "#333")
            font_weight = "700" if st.get("fontStyle") == "1" else "400"

            # Align text
            text_x = x + 4
            text_y = y + float(font_size) + 4

            if value:
                svg_parts.append(
                    f"  <text x='{text_x:.1f}' y='{text_y:.1f}' fill='{font_color}' "
                    f"font-size='{font_size}' font-weight='{font_weight}' class='lane-text'>{html.escape(value)}</text>"
                )
            continue

        # Calculate opacity
        try:
            op = float(opacity) / 100.0
            fill_op = float(fill_opacity) / 100.0
        except (ValueError, TypeError):
            op = 1.0
            fill_op = 1.0

        # Rounded corners
        rounded = st.get("rounded") == "1"
        rx = 8 if rounded else 3

        # Check for special shapes
        shape = st.get("shape", "")

        if "cylinder" in shape:
            # Simple cylinder approximation
            svg_parts.append(
                f"  <rect x='{x:.1f}' y='{y + 10:.1f}' width='{w:.1f}' height='{h - 10:.1f}' "
                f"fill='{fill}' stroke='{stroke}' stroke-width='2' rx='3' "
                f"opacity='{op}' fill-opacity='{fill_op}'/>"
            )
            svg_parts.append(
                f"  <ellipse cx='{x + w/2:.1f}' cy='{y + 12:.1f}' rx='{w/2:.1f}' ry='10' "
                f"fill='{fill}' stroke='{stroke}' stroke-width='2' opacity='{op}' fill-opacity='{fill_op}'/>"
            )
        elif "hexagon" in shape:
            # Hexagon shape
            points = [
                (x + w*0.25, y),
                (x + w*0.75, y),
                (x + w, y + h/2),
                (x + w*0.75, y + h),
                (x + w*0.25, y + h),
                (x, y + h/2)
            ]
            pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            svg_parts.append(
                f"  <polygon points='{pts_str}' fill='{fill}' stroke='{stroke}' "
                f"stroke-width='2' opacity='{op}' fill-opacity='{fill_op}'/>"
            )
        else:
            # Standard rectangle
            dashed = st.get("dashed") == "1"
            dash_array = "8 4" if dashed else ""

            filter_attr = "" if op < 0.8 else "filter='url(#shadow)'"

            svg_parts.append(
                f"  <rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
                f"rx='{rx}' ry='{rx}' fill='{fill}' stroke='{stroke}' stroke-width='2' "
                f"opacity='{op}' fill-opacity='{fill_op}' "
                + (f"stroke-dasharray='{dash_array}' " if dash_array else "")
                + f"{filter_attr}/>"
            )

        # Add text label
        if value and fill_op > 0.3:
            font_color = st.get("fontColor")
            if not font_color:
                font_color = _text_color_for_bg(fill)
            else:
                font_color = _normalize_color(font_color, "#333")

            font_size = st.get("fontSize", "12")
            text_x = x + w / 2
            text_y = y + h / 2 + float(font_size) / 3

            # Truncate long labels
            display_value = value if len(value) <= 25 else value[:22] + "..."

            svg_parts.append(
                f"  <text x='{text_x:.1f}' y='{text_y:.1f}' fill='{font_color}' "
                f"font-size='{font_size}' text-anchor='middle' class='node-text'>{html.escape(display_value)}</text>"
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)
