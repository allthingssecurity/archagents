import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import json
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import uvicorn

from .agent import agentic_generate, propose_clarifying_questions, agentic_generate_stream
from .multi_agent import multi_agent_generate_stream
from .render import drawio_xml_to_svg


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
