from __future__ import annotations

import re
from typing import Dict, List, Tuple
from xml.etree import ElementTree as ET


def _parse_style(style: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (style or '').split(';'):
        if not part:
            continue
        if '=' in part:
            k, v = part.split('=', 1)
            out[k.strip()] = v.strip()
        else:
            out[part.strip()] = '1'
    return out


def _bbox(geom: ET.Element) -> Tuple[float, float, float, float]:
    x = float(geom.get('x') or 0)
    y = float(geom.get('y') or 0)
    w = float(geom.get('width') or 0)
    h = float(geom.get('height') or 0)
    return (x, y, x + w, y + h)


def _overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def validate_xml(xml_text: str, user_goal: str) -> Dict:
    issues: List[str] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        return {"ok": False, "issues": [f"XML parse error: {e}"]}

    if root.tag != 'mxGraphModel':
        issues.append('Root is not mxGraphModel')

    nodes: List[Dict] = []
    texts: List[Dict] = []
    edges: List[Dict] = []

    for cell in root.findall('.//mxCell'):
        style = _parse_style(cell.get('style') or '')
        geom = cell.find('mxGeometry')
        if cell.get('vertex') == '1' and geom is not None:
            bbox = _bbox(geom)
            if style.get('text') or style.get('shape') == 'text' or (cell.get('value') and style.get('strokeColor') == 'none'):
                texts.append({"id": cell.get('id'), "bbox": bbox})
            else:
                nodes.append({"id": cell.get('id'), "bbox": bbox, "style": style, "value": cell.get('value') or ''})
        if cell.get('edge') == '1':
            edges.append({"id": cell.get('id'), "style": style})

    # Basic checks
    if not nodes:
        issues.append('No nodes found')
    if not edges:
        issues.append('No edges found')
    else:
        for e in edges:
            if e['style'].get('endArrow') not in ('block', 'classic', 'open'):
                issues.append(f"Edge {e['id']} missing endArrow")

    # Overlaps between nodes
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if _overlap(nodes[i]['bbox'], nodes[j]['bbox']):
                issues.append(f"Overlap: {nodes[i]['id']} with {nodes[j]['id']}")

    # Colors present
    for n in nodes:
        st = n['style']
        if 'fillColor' not in st:
            issues.append(f"Node {n['id']} missing fillColor")
        # Ensure good contrast: if dark fill, require light font; if light fill, require dark font
        fc = st.get('fillColor', '#ffffff')
        font = st.get('fontColor', '#111111')
        def _is_dark(c: str) -> bool:
            import re
            if not c.startswith('#'):
                c = f'#{c}'
            if not re.match(r'^#[0-9a-fA-F]{6}$', c):
                return False
            r = int(c[1:3], 16) / 255.0
            g = int(c[3:5], 16) / 255.0
            b = int(c[5:7], 16) / 255.0
            return (0.2126*r + 0.7152*g + 0.0722*b) < 0.45
        if _is_dark(fc) and (not font or font.lower() in ('#000', '#000000', '#333', '#222')):
            issues.append(f"Low contrast text on {n['id']} (dark fill + dark font)")
        if not _is_dark(fc) and font.lower() in ('#fff', '#ffffff'):
            issues.append(f"Low contrast text on {n['id']} (light fill + light font)")

    # Goal-aligned labels
    goal = user_goal.lower()
    if 'event' in goal:
        # expect a label cell with Events
        if not any((n.get('value') or '').lower().find('event') >= 0 for n in nodes + texts):
            issues.append('Missing Events label or node')
    if 'api' in goal:
        if not any('api' in (n.get('value') or '').lower() for n in nodes + texts):
            issues.append('Missing API label or node')
    if 'monitor' in goal:
        if not any('monitor' in (n.get('value') or '').lower() for n in nodes + texts):
            issues.append('Missing Monitoring node/label')
    if 'security' in goal:
        if not any('secur' in (n.get('value') or '').lower() for n in nodes + texts):
            issues.append('Missing Security boundary/label')

    return {"ok": len(issues) == 0, "issues": issues}
