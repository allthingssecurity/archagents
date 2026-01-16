"""
MCP Client for Draw.io MCP Server Integration

This module provides a Python client to communicate with the drawio-mcp-server
via its HTTP transport (streamable HTTP). It enables agentic systems to:
- Create and modify Draw.io diagrams programmatically
- Add shapes, edges, and connections
- Inspect diagram structure
- Query available shapes and categories

The MCP server must be running with HTTP transport enabled:
    npx -y drawio-mcp-server --transport http --http-port 3000

And the browser extension must be connected to a Draw.io session.
"""

import os
import json
import uuid
import time
from typing import Any, Dict, List, Optional, Generator
from dataclasses import dataclass, asdict

import requests
from dotenv import load_dotenv


# =============================================================================
# Configuration
# =============================================================================

load_dotenv()

MCP_SERVER_URL = os.getenv("DRAWIO_MCP_URL", "http://localhost:3000")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"
HEALTH_ENDPOINT = f"{MCP_SERVER_URL}/health"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MCPToolCall:
    """Represents an MCP tool invocation."""
    name: str
    arguments: Dict[str, Any]


@dataclass
class MCPResponse:
    """Represents an MCP response."""
    success: bool
    result: Any = None
    error: Optional[str] = None


# =============================================================================
# MCP Client
# =============================================================================

class DrawioMCPClient:
    """
    Client for the Draw.io MCP Server.
    
    Communicates via HTTP transport to control Draw.io diagrams.
    """
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or MCP_SERVER_URL
        self.mcp_endpoint = f"{self.base_url}/mcp"
        self.health_endpoint = f"{self.base_url}/health"
        self.session_id = str(uuid.uuid4())
        
    def is_healthy(self) -> bool:
        """Check if MCP server is running and healthy."""
        try:
            resp = requests.get(self.health_endpoint, timeout=5)
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except Exception:
            return False
    
    def _call_mcp(self, method: str, params: Dict[str, Any]) -> MCPResponse:
        """
        Make an MCP JSON-RPC call.
        
        The MCP protocol uses JSON-RPC 2.0 over HTTP.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params
        }
        
        try:
            resp = requests.post(
                self.mcp_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            
            if "error" in data:
                return MCPResponse(
                    success=False, 
                    error=data["error"].get("message", str(data["error"]))
                )
            
            return MCPResponse(success=True, result=data.get("result"))
            
        except requests.exceptions.RequestException as e:
            return MCPResponse(success=False, error=f"Connection error: {e}")
        except json.JSONDecodeError as e:
            return MCPResponse(success=False, error=f"Invalid JSON response: {e}")
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPResponse:
        """Call an MCP tool with the given arguments."""
        return self._call_mcp("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
    
    def list_tools(self) -> MCPResponse:
        """List all available MCP tools."""
        return self._call_mcp("tools/list", {})
    
    # =========================================================================
    # Diagram Inspection Tools
    # =========================================================================
    
    def get_selected_cell(self) -> MCPResponse:
        """Get the currently selected cell in Draw.io."""
        return self.call_tool("get-selected-cell", {})
    
    def get_shape_categories(self) -> MCPResponse:
        """Get available shape categories from the diagram's library."""
        return self.call_tool("get-shape-categories", {})
    
    def get_shapes_in_category(self, category_id: str) -> MCPResponse:
        """Get all shapes in a specified category."""
        return self.call_tool("get-shapes-in-category", {"category_id": category_id})
    
    def get_shape_by_name(self, shape_name: str) -> MCPResponse:
        """Get a specific shape by its name."""
        return self.call_tool("get-shape-by-name", {"shape_name": shape_name})
    
    def list_paged_model(self, page: int = 0, page_size: int = 50) -> MCPResponse:
        """Get a paginated view of all cells in the diagram."""
        return self.call_tool("list-paged-model", {
            "page": page,
            "pageSize": page_size
        })
    
    # =========================================================================
    # Diagram Modification Tools
    # =========================================================================
    
    def add_rectangle(
        self, 
        x: int, 
        y: int, 
        width: int, 
        height: int, 
        text: str = "",
        style: Optional[str] = None
    ) -> MCPResponse:
        """
        Add a rectangle shape to the diagram.
        
        Args:
            x, y: Position coordinates
            width, height: Dimensions
            text: Content text
            style: Draw.io style string (e.g., "rounded=1;fillColor=#dae8fc;")
        """
        args = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "text": text
        }
        if style:
            args["style"] = style
        return self.call_tool("add-rectangle", args)
    
    def add_edge(
        self, 
        source_id: str, 
        target_id: str, 
        text: str = "",
        style: Optional[str] = None
    ) -> MCPResponse:
        """
        Create a connection between two cells.
        
        Args:
            source_id: ID of the source cell
            target_id: ID of the target cell
            text: Optional label for the edge
            style: Optional style properties
        """
        args = {
            "source_id": source_id,
            "target_id": target_id
        }
        if text:
            args["text"] = text
        if style:
            args["style"] = style
        return self.call_tool("add-edge", args)
    
    def add_cell_of_shape(
        self,
        shape_name: str,
        x: Optional[int] = None,
        y: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        text: str = "",
        style: Optional[str] = None
    ) -> MCPResponse:
        """
        Add a cell of a specific shape type from the library.
        
        Args:
            shape_name: Name of the shape to create
            x, y: Position coordinates (optional)
            width, height: Dimensions (optional)
            text: Content text
            style: Additional style properties
        """
        args = {"shape_name": shape_name}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        if width is not None:
            args["width"] = width
        if height is not None:
            args["height"] = height
        if text:
            args["text"] = text
        if style:
            args["style"] = style
        return self.call_tool("add-cell-of-shape", args)
    
    def delete_cell_by_id(self, cell_id: str) -> MCPResponse:
        """Delete a cell from the diagram."""
        return self.call_tool("delete-cell-by-id", {"cell_id": cell_id})
    
    def edit_cell(
        self,
        cell_id: str,
        text: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        style: Optional[str] = None
    ) -> MCPResponse:
        """
        Update properties of an existing cell.
        
        Only specified properties will be changed.
        """
        args = {"cell_id": cell_id}
        if text is not None:
            args["text"] = text
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        if width is not None:
            args["width"] = width
        if height is not None:
            args["height"] = height
        if style is not None:
            args["style"] = style
        return self.call_tool("edit-cell", args)
    
    def edit_edge(
        self,
        cell_id: str,
        text: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        style: Optional[str] = None
    ) -> MCPResponse:
        """Update an existing edge connection."""
        args = {"cell_id": cell_id}
        if text is not None:
            args["text"] = text
        if source_id is not None:
            args["source_id"] = source_id
        if target_id is not None:
            args["target_id"] = target_id
        if style is not None:
            args["style"] = style
        return self.call_tool("edit-edge", args)
    
    def set_cell_shape(self, cell_id: str, shape_name: str) -> MCPResponse:
        """Apply a library shape's style to an existing cell."""
        return self.call_tool("set-cell-shape", {
            "cell_id": cell_id,
            "shape_name": shape_name
        })
    
    def set_cell_data(self, cell_id: str, key: str, value: str) -> MCPResponse:
        """Store a custom attribute on a cell."""
        return self.call_tool("set-cell-data", {
            "cell_id": cell_id,
            "key": key,
            "value": value
        })


# =============================================================================
# Architecture Builder - High-level API
# =============================================================================

# =============================================================================
# Style Definitions - Professional "Technical Paper" Aesthetic
# =============================================================================

# Clean, muted professional color palette
LAYER_STYLES = {
    "Experience": "fillColor=#F0F7FF;strokeColor=#4A90D9;fontColor=#4A90D9;rounded=0;",
    "Application": "fillColor=#F0FAF6;strokeColor=#5AAA8D;fontColor=#5AAA8D;rounded=0;",
    "Integration": "fillColor=#FFFAF0;strokeColor=#E5A84B;fontColor=#E5A84B;rounded=0;",
    "Data": "fillColor=#F5F3FA;strokeColor=#7B68C8;fontColor=#7B68C8;rounded=0;",
    "Platform & Security": "fillColor=#F4F6F8;strokeColor=#5C6B7A;fontColor=#5C6B7A;rounded=0;",
    "External": "fillColor=#F8FAFB;strokeColor=#8FA3B0;fontColor=#8FA3B0;rounded=0;",
}

NODE_TYPE_STYLES = {
    # App components - Professional blue
    "app": (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        "fillColor=#4A90D9;strokeColor=#3A7AC9;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
    
    # Services - Teal green
    "service": (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        "fillColor=#5AAA8D;strokeColor=#4A9A7D;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
    
    # Integration - Warm amber
    "integration": (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        "fillColor=#E5A84B;strokeColor=#D59A3B;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
    
    # Data - Cylinder shape, soft purple
    "data": (
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"
        "backgroundOutline=1;size=12;"
        "fillColor=#7B68C8;strokeColor=#6B58B8;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
    
    # Security - Hexagon, slate
    "security": (
        "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;"
        "fixedSize=1;size=16;"
        "fillColor=#5C6B7A;strokeColor=#4C5B6A;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
    
    # External - Light slate, dashed
    "external": (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;dashed=1;dashPattern=6 3;"
        "fillColor=#8FA3B0;strokeColor=#7F939F;strokeWidth=1.5;"
        "fontColor=#FFFFFF;fontSize=12;fontStyle=1;"
        "fontFamily=Inter,Helvetica,Arial,sans-serif;"
    ),
}

class ArchitectureDiagramBuilder:
    """
    High-level builder for creating architecture diagrams via MCP.
    
    Translates architecture plans (from your agents) into MCP tool calls.
    """
    
    def __init__(self, client: Optional[DrawioMCPClient] = None):
        self.client = client or DrawioMCPClient()
        self.cell_ids: Dict[str, str] = {}  # node_id -> drawio cell_id
        
    def is_ready(self) -> bool:
        """Check if MCP server is ready."""
        return self.client.is_healthy()
    
    def build_from_plan(
        self, 
        plan: Dict[str, Any], 
        offset_x: int = 0, 
        offset_y: int = 0,
        header_text: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Build a diagram from an architecture plan.
        
        Args:
            plan: The architecture plan JSON
            offset_x: X offset for the entire diagram (for multi-diagram support)
            offset_y: Y offset for the entire diagram
            header_text: Optional title to display above the diagram
            
        Yields progress events for each step.
        """
        lanes = plan.get("lanes", [])
        nodes = plan.get("nodes", [])
        edges = plan.get("edges", [])
        
        # Enhanced Layout Config (Technical Paper Style)
        # Tighter packing, clear labels
        LANE_HEADER_WIDTH = 140
        LANE_HEIGHT = 180 
        NODE_WIDTH = 160   
        NODE_HEIGHT = 60
        MARGIN_X = 40
        MARGIN_Y = 30
        MAX_NODES_PER_ROW = 5 
        
        total_width = LANE_HEADER_WIDTH + (NODE_WIDTH + MARGIN_X) * MAX_NODES_PER_ROW + MARGIN_X
        
        # 0. Create Diagram Header (Proposal Name)
        if header_text:
            self.client.add_rectangle(
                x=offset_x, y=offset_y,
                width=400, height=40,
                text=header_text,
                style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;fontSize=16;fontStyle=1;fontFamily=Helvetica"
            )
            # Push diagram down
            start_y = offset_y + 60
        else:
            start_y = offset_y
        
        # 1. Create lane headers (as container boxes)
        yield {"type": "phase", "message": "Creating architecture layers..."}
        
        for i, lane in enumerate(lanes):
            y_pos = start_y + (i * LANE_HEIGHT)
            style = LAYER_STYLES.get(lane, LAYER_STYLES.get("Application", ""))
            
            # Use specific style for the lane header/container background?
            # Actually, let's make the lane header text separate and clean
            # We'll just put the text label on the left, clear background
            
            resp = self.client.add_rectangle(
                x=offset_x, y=y_pos,
                width=LANE_HEADER_WIDTH, height=LANE_HEIGHT - 10,
                text=lane,
                style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1;fontSize=12;fontFamily=Helvetica;fontColor=#333333;"
                # Original style was a big colored box. Let's keep it minimal text.
            )
            
            if resp.success:
                yield {"type": "lane_created", "lane": lane, "index": i}
            else:
                yield {"type": "error", "message": f"Failed to create lane {lane}: {resp.error}"}
        
        # 2. Create nodes
        yield {"type": "phase", "message": "Adding architecture components..."}
        
        # Group nodes by lane
        lane_nodes: Dict[str, List[Dict]] = {lane: [] for lane in lanes}
        for node in nodes:
            node_lane = node.get("lane", "Application")
            if node_lane not in lane_nodes and lanes:
                # Fuzzy match or fallback
                found = False
                for l in lanes:
                    if l.lower() in node_lane.lower() or node_lane.lower() in l.lower():
                        lane_nodes[l].append(node)
                        found = True
                        break
                if not found:
                    lane_nodes[lanes[0]].append(node)
            elif node_lane in lane_nodes:
                lane_nodes[node_lane].append(node)
        
        # Position and create nodes
        for lane_idx, lane in enumerate(lanes):
            nodes_in_lane = lane_nodes.get(lane, [])
            base_y = start_y + (lane_idx * LANE_HEIGHT)
            
            # Add a subtle background container for the whole lane contents?
            # Calculate lane width based on nodes
            # real_lane_width = max(len(nodes_in_lane) * (NODE_WIDTH + MARGIN_X), 600)
            # self.client.add_rectangle(
            #     x=offset_x + LANE_HEADER_WIDTH, y=base_y,
            #     width=real_lane_width, height=LANE_HEIGHT - 10,
            #     text="",
            #     style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f9f9f9;strokeColor=#eeeeee;dashed=1;"
            # )

            # Smart Grid Layout within Lane
            for node_idx, node in enumerate(nodes_in_lane):
                # Calculate grid position
                row = node_idx // MAX_NODES_PER_ROW
                col = node_idx % MAX_NODES_PER_ROW
                
                # Calculate coordinates
                # Start X after lane header
                node_x = offset_x + LANE_HEADER_WIDTH + MARGIN_X + (col * (NODE_WIDTH + MARGIN_X))
                
                # Centered vertically in lane, or stacked if multiple rows
                if len(nodes_in_lane) <= MAX_NODES_PER_ROW:
                    # Single row - center vertically
                    node_y = base_y + (LANE_HEIGHT - NODE_HEIGHT) // 2
                else:
                    # Multiple rows
                    # effective height for rows
                    rows_needed = (len(nodes_in_lane) + MAX_NODES_PER_ROW - 1) // MAX_NODES_PER_ROW
                    total_rows_h = rows_needed * NODE_HEIGHT + (rows_needed - 1) * MARGIN_Y if rows_needed > 1 else NODE_HEIGHT
                    start_row_y = base_y + (LANE_HEIGHT - total_rows_h) // 2
                    node_y = start_row_y + row * (NODE_HEIGHT + MARGIN_Y)

                node_type = node.get("type", "app")
                
                # Get base style for node type - ignore lane style mixing for now to keep it clean
                style = NODE_TYPE_STYLES.get(node_type, NODE_TYPE_STYLES["app"])
                
                resp = self.client.add_rectangle(
                    x=node_x, y=node_y,
                    width=NODE_WIDTH, height=NODE_HEIGHT,
                    text=node.get("name", node.get("id", "")),
                    style=style
                )
                
                if resp.success:
                    result = resp.result
                    # Handle varying response formats from MCP server
                    cid = result.get("id") if isinstance(result, dict) else result
                    self.cell_ids[node["id"]] = cid
                    
                    yield {
                        "type": "node_created",
                        "node_id": node["id"],
                        "name": node.get("name"),
                        "lane": lane
                    }
        
        # 3. Create edges
        yield {"type": "phase", "message": "Connecting components..."}
        
        for edge in edges:
            source_id = edge.get("from")
            target_id = edge.get("to")
            label = edge.get("label", "")
            
            source_cell = self.cell_ids.get(source_id)
            target_cell = self.cell_ids.get(target_id)
            
            if source_cell and target_cell:
                # Professional edge style - clean, muted colors
                edge_style = (
                    "edgeStyle=orthogonalEdgeStyle;"
                    "rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
                    "strokeColor=#64748B;strokeWidth=1.5;"
                    "endArrow=blockThin;endFill=1;endSize=6;"
                    "fontFamily=Inter,Helvetica,Arial,sans-serif;"
                )
                resp = self.client.add_edge(
                    source_id=source_cell,
                    target_id=target_cell,
                    text=label,
                    style=edge_style
                )
                
                if resp.success:
                    yield {
                        "type": "edge_created",
                        "from": source_id,
                        "to": target_id,
                        "label": label
                    }
    
    def clear_diagram(self) -> MCPResponse:
        """Clear all cells from the current diagram."""
        # Get all cells and delete them
        model_resp = self.client.list_paged_model()
        if not model_resp.success:
            return model_resp
        
        cells = model_resp.result if isinstance(model_resp.result, list) else []
        
        for cell in cells:
            if isinstance(cell, dict) and "id" in cell:
                self.client.delete_cell_by_id(cell["id"])
        
        self.cell_ids.clear()
        return MCPResponse(success=True, result="Diagram cleared")


# =============================================================================
# Utility Functions
# =============================================================================

def check_mcp_server() -> Dict[str, Any]:
    """Check the status of the MCP server."""
    client = DrawioMCPClient()
    
    result = {
        "healthy": client.is_healthy(),
        "url": client.base_url,
        "tools": []
    }
    
    if result["healthy"]:
        tools_resp = client.list_tools()
        if tools_resp.success:
            result["tools"] = tools_resp.result
    
    return result


def demo_create_simple_diagram():
    """Demo: Create a simple 3-tier architecture."""
    client = DrawioMCPClient()
    
    if not client.is_healthy():
        print("❌ MCP server not running. Start it with:")
        print("   npx -y drawio-mcp-server --transport http --http-port 3000")
        return
    
    print("✅ MCP server is healthy")
    
    # Create layers
    layers = [
        ("Frontend", 0, "#0a6ed1"),
        ("Backend", 150, "#1a9898"),
        ("Database", 300, "#6c5ce7"),
    ]
    
    cell_ids = {}
    
    for name, y, color in layers:
        resp = client.add_rectangle(
            x=100, y=y, width=200, height=100, text=name,
            style=f"fillColor={color};strokeColor=#333333;fontColor=#ffffff;rounded=1;"
        )
        print(f"Created {name}: {resp}")
        if resp.success and resp.result:
            cell_ids[name] = resp.result.get("id") if isinstance(resp.result, dict) else resp.result
    
    # Create edges
    if "Frontend" in cell_ids and "Backend" in cell_ids:
        client.add_edge(cell_ids["Frontend"], cell_ids["Backend"], "REST API")
    if "Backend" in cell_ids and "Database" in cell_ids:
        client.add_edge(cell_ids["Backend"], cell_ids["Database"], "SQL")
    
    print("✅ Demo diagram created!")


if __name__ == "__main__":
    # Run health check
    status = check_mcp_server()
    print(f"MCP Server Status: {json.dumps(status, indent=2)}")
