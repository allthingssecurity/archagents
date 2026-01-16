import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import json
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import uvicorn

from agent import agentic_generate, propose_clarifying_questions, agentic_generate_stream, generate_multi_proposals
from multi_agent import multi_agent_generate_stream
from render import drawio_xml_to_svg
from mcp_client import DrawioMCPClient, ArchitectureDiagramBuilder, check_mcp_server
from mcp_agent import mcp_generate_stream, check_mcp_status, hybrid_generate_stream


class GenerateRequest(BaseModel):
    prompt: str
    context: Optional[str] = None
    max_iters: int = 3

class ClarifyRequest(BaseModel):
    prompt: str
    context: Optional[str] = None


app = FastAPI(title="Architecture Generator (Draw.io)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/generate")
def generate(req: GenerateRequest) -> Dict[str, Any]:
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")
    try:
        model = os.getenv("ARCHGEN_OPENAI_MODEL", None)
        result = agentic_generate(req.prompt.strip(), req.context, max_iters=max(1, min(req.max_iters, 5)), model=model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate_stream")
def generate_stream(req: GenerateRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")
    def iter_chunks():
        try:
            model = os.getenv("ARCHGEN_OPENAI_MODEL", None)
            for item in agentic_generate_stream(req.prompt.strip(), req.context, max_iters=max(1, min(req.max_iters, 5)), model=model):
                yield ("data: " + json.dumps(item) + "\n\n")
            yield "event: end\n\n"
        except Exception as e:
            yield ("event: error\n" + "data: " + json.dumps({"error": str(e)}) + "\n\n")
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(iter_chunks(), media_type="text/event-stream", headers=headers)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("archgen.server:app", host=host, port=port, reload=False)


@app.post("/api/recommendations")
def generate_recommendations(req: GenerateRequest):
    """
    Generate 3 architecture recommendations side-by-side.
    
    Returns:
    - Option 1: Standard (balanced, maintainable)
    - Option 2: Event-Driven (async, loosely-coupled)
    - Option 3: Security-First (zero-trust, defense in depth)
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")

    def iter_chunks():
        try:
            model = os.getenv("ARCHGEN_OPENAI_MODEL", None)
            for item in generate_multi_proposals(req.prompt.strip(), req.context, model=model):
                yield ("data: " + json.dumps(item) + "\n\n")
            yield "event: end\n\n"
        except Exception as e:
            yield ("event: error\n" + "data: " + json.dumps({"error": str(e)}) + "\n\n")

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(iter_chunks(), media_type="text/event-stream", headers=headers)


@app.post("/api/multi_agent_stream")
def multi_agent_stream(req: GenerateRequest):
    """Multi-agent architecture generation with Chief Architect and team."""
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")

    def iter_chunks():
        try:
            model = os.getenv("ARCHGEN_OPENAI_MODEL", None)
            for item in multi_agent_generate_stream(req.prompt.strip(), req.context, model=model):
                yield ("data: " + json.dumps(item) + "\n\n")
            yield "event: end\n\n"
        except Exception as e:
            yield ("event: error\n" + "data: " + json.dumps({"error": str(e)}) + "\n\n")

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(iter_chunks(), media_type="text/event-stream", headers=headers)


@app.post("/api/clarify")
def clarify(req: ClarifyRequest) -> Dict[str, Any]:
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")
    try:
        qs = propose_clarifying_questions(req.prompt.strip(), req.context)
        return {"questions": qs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExportRequest(BaseModel):
    xml: str
    format: str = "svg"  # svg or png
    scale: float = 1.0


@app.post("/api/export")
def export_diagram(req: ExportRequest) -> Dict[str, Any]:
    if not req.xml or not req.xml.strip():
        raise HTTPException(status_code=400, detail="Missing xml")
    # Try local renderer first (avoids CSP/DNS)
    try:
        svg = drawio_xml_to_svg(req.xml)
        return {"svg": svg}
    except Exception as local_err:
        # Fallback to hosted exporter
        try:
            params = {
                "format": req.format,
                "bg": "white",
                "w": int(1600 * req.scale),
                "h": int(1200 * req.scale),
            }
            resp = requests.post(
                "https://exp.draw.io/ImageExport4/export",
                params=params,
                data=req.xml.encode("utf-8"),
                timeout=30,
            )
            resp.raise_for_status()
            if req.format == "svg":
                return {"svg": resp.text}
            else:
                import base64
                b64 = base64.b64encode(resp.content).decode("ascii")
                return {"png": f"data:image/png;base64,{b64}"}
        except Exception as remote_err:
            raise HTTPException(status_code=500, detail=f"Export failed: {remote_err} | local: {local_err}")


# =============================================================================
# MCP INTEGRATION ENDPOINTS
# =============================================================================

@app.get("/api/mcp/status")
def mcp_status() -> Dict[str, Any]:
    """Check Draw.io MCP server status and available tools."""
    return check_mcp_status()


class MCPGenerateRequest(BaseModel):
    prompt: str
    context: Optional[str] = None
    use_mcp: bool = True  # If False, falls back to local XML generation


@app.post("/api/mcp/generate_stream")
def mcp_generate(req: MCPGenerateRequest):
    """
    Generate architecture using MCP to build diagram live in Draw.io.
    
    Prerequisites:
    1. Start MCP server: npx -y drawio-mcp-server --transport http --http-port 3000
    2. Install & connect Draw.io browser extension
    3. Open draw.io in browser with new diagram
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Missing prompt")

    def iter_chunks():
        try:
            model = os.getenv("ARCHGEN_OPENAI_MODEL", None)
            for item in hybrid_generate_stream(
                req.prompt.strip(), 
                req.context, 
                use_mcp=req.use_mcp, 
                model=model
            ):
                yield ("data: " + json.dumps(item) + "\n\n")
            yield "event: end\n\n"
        except Exception as e:
            yield ("event: error\n" + "data: " + json.dumps({"error": str(e)}) + "\n\n")

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(iter_chunks(), media_type="text/event-stream", headers=headers)


class MCPToolRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = {}


@app.post("/api/mcp/call_tool")
def mcp_call_tool(req: MCPToolRequest) -> Dict[str, Any]:
    """
    Directly invoke an MCP tool.
    
    Available tools:
    - get-selected-cell: Get currently selected cell
    - get-shape-categories: List shape categories
    - add-rectangle: Add a rectangle shape
    - add-edge: Create a connection
    - add-cell-of-shape: Add a shape from the library
    - delete-cell-by-id: Remove a cell
    - edit-cell: Update cell properties
    - edit-edge: Update edge properties
    """
    client = DrawioMCPClient()
    
    if not client.is_healthy():
        raise HTTPException(
            status_code=503, 
            detail="MCP server not available. Start it with: npx -y drawio-mcp-server --transport http --http-port 3000"
        )
    
    resp = client.call_tool(req.tool_name, req.arguments)
    
    if resp.success:
        return {"success": True, "result": resp.result}
    else:
        return {"success": False, "error": resp.error}


class MCPBuildRequest(BaseModel):
    plan: Dict[str, Any]  # Architecture plan with lanes, nodes, edges


@app.post("/api/mcp/build_diagram")
def mcp_build_diagram(req: MCPBuildRequest) -> Dict[str, Any]:
    """
    Build a diagram from an architecture plan using MCP.
    
    Plan structure:
    {
        "lanes": ["Experience", "Application", "Integration", "Data", "Platform & Security"],
        "nodes": [{"id": "...", "name": "...", "lane": "...", "type": "..."}],
        "edges": [{"from": "...", "to": "...", "label": "..."}]
    }
    """
    client = DrawioMCPClient()
    
    if not client.is_healthy():
        raise HTTPException(
            status_code=503,
            detail="MCP server not available"
        )
    
    builder = ArchitectureDiagramBuilder(client)
    events = []
    
    try:
        for event in builder.build_from_plan(req.plan):
            events.append(event)
    except Exception as e:
        return {"success": False, "error": str(e), "events": events}
    
    return {"success": True, "events": events}


@app.get("/api/mcp/tools")
def mcp_list_tools() -> Dict[str, Any]:
    """List all available MCP tools."""
    client = DrawioMCPClient()
    
    if not client.is_healthy():
        return {"available": False, "tools": []}
    
    resp = client.list_tools()
    
    if resp.success:
        return {"available": True, "tools": resp.result}
    else:
        return {"available": False, "error": resp.error, "tools": []}

