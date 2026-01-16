"""
SVG Renderer for Draw.io mxGraphModel XML
Renders mxGraphModel XML to standalone SVG for preview display.
"""

from __future__ import annotations
import html
import re
from typing import Dict, List, Callable
from xml.etree import ElementTree as ET


def _strip_code_fences(s: str) -> str:
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
    txt = _strip_code_fences(xml_text)
    m = re.match(r"\s*<mxGraphModel\s+([^>]*)>([\s\S]*)</mxGraphModel>\s*\Z", txt)
    if not m:
        return txt
    attrs_str, inner = m.group(1), m.group(2)
    pairs = re.findall(r'([A-Za-z_:][\w:.-]*)\s*=\s*("[^"]*"|\'[^\']*\')', attrs_str)
    seen = {}
    for k, v in pairs:
        seen[k] = v
    order = ["dx", "dy", "grid", "gridSize", "guides", "tooltips", "connect",
             "arrows", "fold", "page", "pageScale", "pageWidth", "pageHeight"]
    items = [f"{k}={seen.pop(k)}" for k in order if k in seen]
    items += [f"{k}={v}" for k, v in seen.items()]
    return f"<mxGraphModel {' '.join(items)}>{inner}</mxGraphModel>"


def _parse_style(style: str) -> Dict[str, str]:
    out = {}
    if not style:
        return out
    for p in style.split(";"):
        p = p.strip()
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        elif p:
            out[p] = "1"
    return out


def _normalize_color(v: str, default: str = "#000000") -> str:
    if not v:
        return default
    v = v.strip()
    if v.startswith("#"):
        return v
    if re.match(r"^[0-9a-fA-F]{6}$", v):
        return f"#{v}"
    colors = {"white": "#ffffff", "black": "#000000", "none": "none"}
    return colors.get(v.lower(), default)


def _is_dark(c: str) -> bool:
    if not c or c == "none" or not c.startswith("#") or len(c) != 7:
        return False
    try:
        r, g, b = int(c[1:3], 16)/255, int(c[3:5], 16)/255, int(c[5:7], 16)/255
        return 0.2126*r + 0.7152*g + 0.0722*b < 0.5
    except:
        return False


def drawio_xml_to_svg(xml_text: str) -> str:
    """Convert Draw.io mxGraphModel XML to SVG."""
    xml_text = _sanitize_mxgraphmodel(xml_text)
    xml_text = re.sub(r"&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='400' height='100'><text x='20' y='50' fill='red'>Error: {html.escape(str(e))}</text></svg>"

    if root.tag != "mxGraphModel":
        if root.tag == "mxfile":
            diag = root.find(".//diagram")
            if diag is not None and diag.text:
                return drawio_xml_to_svg(diag.text)
        return "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='100'><text x='20' y='50'>Unsupported format</text></svg>"

    cells = root.findall(".//mxCell")
    vertices: Dict[str, Dict] = {}
    edges: List[Dict] = []

    for cell in cells:
        cid = cell.get("id") or ""
        style = _parse_style(cell.get("style") or "")
        value = html.unescape(cell.get("value") or "")
        geom = cell.find("mxGeometry")

        if cell.get("vertex") == "1" and geom is not None:
            vertices[cid] = {
                "id": cid,
                "x": float(geom.get("x") or 0),
                "y": float(geom.get("y") or 0),
                "w": float(geom.get("width") or 100),
                "h": float(geom.get("height") or 50),
                "value": value, "style": style
            }
        elif cell.get("edge") == "1":
            edges.append({
                "source": cell.get("source"),
                "target": cell.get("target"),
                "value": value, "style": style
            })

    if not vertices:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='100'><text x='20' y='50'>No elements</text></svg>"

    # Bounding box
    min_x = min(v["x"] for v in vertices.values())
    min_y = min(v["y"] for v in vertices.values())
    max_x = max(v["x"] + v["w"] for v in vertices.values())
    max_y = max(v["y"] + v["h"] for v in vertices.values())

    margin = 40
    width = int(max(800, max_x - min_x + 2 * margin))
    height = int(max(400, max_y - min_y + 2 * margin))

    tx = lambda x: x - min_x + margin
    ty = lambda y: y - min_y + margin

    svg = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
    <polygon points="0 0, 10 3.5, 0 7" fill="#475569"/>
  </marker>
</defs>
<rect width="{width}" height="{height}" fill="#fafafc"/>''']

    # Classify vertices for proper layering
    def z_order(v):
        st = v["style"]
        fill = _normalize_color(st.get("fillColor", ""), "#fff")
        value = v.get("value", "")
        w = v.get("w", 0)
        h = v.get("h", 0)
        
        # Check opacity
        op_str = st.get("opacity", "100")
        try:
            op = float(op_str) if op_str.replace(".", "").isdigit() else 100
        except:
            op = 100
        
        # Layer 0: Low opacity backgrounds (lane backgrounds)
        if op < 80:
            return 0
        
        # Layer 1: Dashed containers
        if st.get("dashed"):
            return 1
        
        # Layer 2: White/large containers (proposal boxes) - no text value, large size
        if not value and w > 400:
            return 2
        if fill.lower() in ["#ffffff", "#fff", "white"] and not value and w > 300:
            return 2
            
        # Layer 5: Text-only elements (labels)
        if "text" in st or st.get("strokeColor") == "none":
            return 5
        
        # Layer 3: Regular nodes
        return 3

    # LAYER 1 & 2: Backgrounds and containers (render BEFORE edges)
    for v in sorted(vertices.values(), key=z_order):
        if z_order(v) > 2:  # Only layers 0, 1, 2
            continue
        x, y, w, h = tx(v["x"]), ty(v["y"]), v["w"], v["h"]
        st = v["style"]
        fill = _normalize_color(st.get("fillColor"), "#f8fafc")
        stroke = _normalize_color(st.get("strokeColor"), "#e2e8f0")
        op = float(st.get("opacity", "100")) / 100 if st.get("opacity", "").replace(".", "").isdigit() else 1
        dashed = 'stroke-dasharray="6 3"' if st.get("dashed") else ""
        svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5" opacity="{op}" {dashed}/>')

    # LAYER 2: Edges (connections)
    for e in edges:
        src = vertices.get(e["source"] or "")
        tgt = vertices.get(e["target"] or "")
        if not src or not tgt:
            continue

        # Calculate connection points (bottom of src to top of tgt, or side-to-side)
        sx, sy, sw, sh = tx(src["x"]), ty(src["y"]), src["w"], src["h"]
        ex, ey, ew, eh = tx(tgt["x"]), ty(tgt["y"]), tgt["w"], tgt["h"]
        
        src_cx, src_cy = sx + sw/2, sy + sh/2
        tgt_cx, tgt_cy = ex + ew/2, ey + eh/2
        dx, dy = tgt_cx - src_cx, tgt_cy - src_cy

        # Pick connection direction
        if abs(dx) > abs(dy):
            # Horizontal
            x1, y1 = (sx + sw, src_cy) if dx > 0 else (sx, src_cy)
            x2, y2 = (ex, tgt_cy) if dx > 0 else (ex + ew, tgt_cy)
        else:
            # Vertical
            x1, y1 = (src_cx, sy + sh) if dy > 0 else (src_cx, sy)
            x2, y2 = (tgt_cx, ey) if dy > 0 else (tgt_cx, ey + eh)

        svg.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>')
        
        # Label
        if e["value"]:
            lx, ly = (x1 + x2) / 2 + 12, (y1 + y2) / 2
            svg.append(f'<text x="{lx:.0f}" y="{ly:.0f}" fill="#475569" font-size="11" font-family="system-ui">{html.escape(e["value"])}</text>')

    # LAYER 3+: Regular nodes (not backgrounds or containers)
    for v in sorted(vertices.values(), key=z_order):
        if z_order(v) <= 2:
            continue  # Already rendered in layers 0-2
        
        x, y, w, h = tx(v["x"]), ty(v["y"]), v["w"], v["h"]
        st = v["style"]
        fill = _normalize_color(st.get("fillColor"), "#f8fafc")
        stroke = _normalize_color(st.get("strokeColor"), "#e2e8f0")
        value = v["value"]
        
        # Skip text-only elements for now, render them separately
        if "text" in st or st.get("strokeColor") == "none" or stroke == "none":
            if value:
                font_size = st.get("fontSize", "12")
                font_color = _normalize_color(st.get("fontColor"), "#374151")
                anchor = {"left": "start", "right": "end"}.get(st.get("align"), "middle")
                text_x = x + ({"left": 4, "right": w - 4}.get(st.get("align"), w / 2))
                text_y = y + h / 2 + float(font_size) / 3
                weight = "bold" if st.get("fontStyle") == "1" else "normal"
                svg.append(f'<text x="{text_x:.0f}" y="{text_y:.0f}" fill="{font_color}" font-size="{font_size}" font-weight="{weight}" text-anchor="{anchor}" font-family="system-ui">{html.escape(value)}</text>')
            continue

        # Regular node shapes
        shape = st.get("shape", "")
        op = float(st.get("opacity", "100")) / 100 if st.get("opacity", "").replace(".", "").isdigit() else 1
        
        if "cylinder" in shape:
            ellipse_h = 10
            svg.append(f'<rect x="{x:.0f}" y="{y + ellipse_h:.0f}" width="{w:.0f}" height="{h - ellipse_h:.0f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" rx="4"/>')
            svg.append(f'<ellipse cx="{x + w/2:.0f}" cy="{y + ellipse_h:.0f}" rx="{w/2:.0f}" ry="{ellipse_h}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        elif "hexagon" in shape:
            inset = w * 0.15
            pts = f"{x+inset:.0f},{y:.0f} {x+w-inset:.0f},{y:.0f} {x+w:.0f},{y+h/2:.0f} {x+w-inset:.0f},{y+h:.0f} {x+inset:.0f},{y+h:.0f} {x:.0f},{y+h/2:.0f}"
            svg.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        else:
            svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5" opacity="{op}"/>')

        # Node label
        if value and op > 0.3:
            font_color = "#fff" if _is_dark(fill) else "#1f2937"
            font_size = st.get("fontSize", "11")
            max_chars = int(w / 7)
            display = value if len(value) <= max_chars else value[:max_chars-1] + "…"
            svg.append(f'<text x="{x + w/2:.0f}" y="{y + h/2 + float(font_size)/3:.0f}" fill="{font_color}" font-size="{font_size}" text-anchor="middle" font-family="system-ui" font-weight="600">{html.escape(display)}</text>')

    svg.append("</svg>")
    return "\n".join(svg)
