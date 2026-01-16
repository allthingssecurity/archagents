"""
MCP-Enabled Architecture Agent

This agent generates architecture diagrams by:
1. Using LLM to analyze requirements and design architecture
2. Calling Draw.io MCP server to build the diagram live

This approach differs from the original agent.py which:
- Generated Draw.io XML locally
- Required export API to render

With MCP, the diagram is built in real-time in an open Draw.io browser tab.
"""

import os
import json
import time
from typing import Dict, List, Optional, Any, Generator

from openai import OpenAI
from dotenv import load_dotenv

from mcp_client import DrawioMCPClient, ArchitectureDiagramBuilder, MCPResponse


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

ARCHITECT_PERSONA = """You are a world-class enterprise solution architect with 20+ years of experience designing mission-critical systems. You think systematically about:

1. **Layered Architecture**: Clear separation of concerns across presentation, business logic, integration, data, and infrastructure layers
2. **Integration Patterns**: Event-driven, API-first, message queues, service mesh
3. **Security by Design**: Zero-trust, identity management, encryption at rest/transit
4. **Scalability**: Horizontal scaling, caching strategies, database sharding
5. **Resilience**: Circuit breakers, retry policies, graceful degradation

When designing architectures, you:
- Start with business requirements and work down to technical implementation
- Consider both functional and non-functional requirements
- Design for change - systems evolve over time
- Balance complexity with maintainability
- Document key decisions and trade-offs"""

PLAN_FORMAT_MCP = """
## Output Format (JSON only for MCP diagram building)

Return ONLY a JSON object with this structure:
```json
{
  "reasoning": "Brief explanation of key architectural decisions",
  "lanes": ["Experience", "Application", "Integration", "Data", "Platform & Security"],
  "nodes": [
    {
      "id": "unique_id",
      "name": "Display Name",
      "lane": "Layer Name",
      "type": "app|service|integration|data|security|external",
      "description": "Brief description of this component"
    }
  ],
  "edges": [
    {
      "from": "source_node_id",
      "to": "target_node_id",
      "label": "Connection description (e.g., REST API, Events, SQL)"
    }
  ]
}
```

## Node Types
- `app`: Core application (rounded rectangle)
- `service`: Microservice/function (rectangle)
- `integration`: Integration component (rounded)
- `data`: Database/storage (cylinder)
- `security`: Security component (shield)
- `external`: External/third-party system (dashed)

## Best Practices
- Use 5-15 nodes for clarity
- Ensure every node has at least one connection
- Use descriptive edge labels (protocol, pattern, security)
- Group related components in the same lane
"""


def get_openai_client() -> OpenAI:
    """Initialize OpenAI client with API key from environment."""
    load_dotenv()
    key = os.getenv("ARCHGEN_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY or ARCHGEN_OPENAI_API_KEY in environment")
    os.environ["OPENAI_API_KEY"] = key
    return OpenAI()


def call_model(client: OpenAI, messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    """Call the OpenAI model with given messages."""
    chosen_model = model or os.getenv("ARCHGEN_OPENAI_MODEL") or "gpt-4o-mini"
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def parse_plan_json(raw: str) -> Dict[str, Any]:
    """Parse JSON plan with resilience to common LLM formatting issues."""
    import re
    
    s = raw.strip()
    
    # Remove code fences
    if s.startswith("```"):
        lines = s.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        s = "\n".join(lines)
    
    # Try direct parse
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    
    # Extract JSON object
    try:
        start = s.find('{')
        end = s.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end+1])
    except json.JSONDecodeError:
        pass
    
    # Apply fixes
    s2 = s.replace("'", '"')
    s2 = re.sub(r',\s*}', '}', s2)
    s2 = re.sub(r',\s*]', ']', s2)
    
    start = s2.find('{')
    end = s2.rfind('}')
    if start != -1 and end != -1 and end > start:
        return json.loads(s2[start:end+1])
    
    raise ValueError("Could not parse PLAN JSON from LLM output")


# =============================================================================
# MCP AGENT
# =============================================================================

# =============================================================================
# MULTI-AGENT PROMPTS
# =============================================================================

ARCHITECT_ALPHA = """You are Architect Alpha, specializing in **Cloud-Native & Scalability**.
Your designs prioritize:
- Microservices and serverless functions
- Auto-scaling and high availability
- Event-driven patterns and asynchronous messaging
- Cutting-edge cloud services (AWS/Azure/GCP)
"""

ARCHITECT_BETA = """You are Architect Beta, specializing in **Security & Enterprise Integration**.
Your designs prioritize:
- Zero-trust security and IAM
- Compliance and governance
- Robust API management and gateways
- Secure data handling and encryption
"""

ARCHITECT_GAMMA = """You are Architect Gamma, specializing in **Pragmatism & Operational Simplicity**.
Your designs prioritize:
- Maintainability and ease of operations
- Proven technologies over hype
- Monolithic or modular monolith approaches where appropriate
- Cost-efficiency and rapid development
"""

def mcp_multi_agent_stream(
    user_goal: str,
    context_data: Optional[str] = None,
    model: Optional[str] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Generate 3 distinct architecture proposals and build them side-by-side in Draw.io.
    """
    
    # Check MCP
    yield {"type": "phase", "phase": "init", "message": "Checking MCP server connection..."}
    mcp_client = DrawioMCPClient()
    
    if not mcp_client.is_healthy():
        yield {
            "type": "connection_check", 
            "healthy": False, 
            "message": "MCP server offline. Cannot build diagrams."
        }
        return

    yield {"type": "connection_check", "healthy": True, "message": "MCP server connected!"}
    
    # Initialize LLM
    try:
        llm_client = get_openai_client()
    except Exception as e:
        yield {"type": "error", "message": f"LLM Error: {e}"}
        return

    # Phase 1: Analyze
    yield {"type": "phase", "phase": "analyze", "message": "Analyzing requirements..."}
    
    analysis_prompt = f"Analyze requirements for: {user_goal}\nContext: {context_data or 'None'}"
    messages = [{"role": "system", "content": ARCHITECT_PERSONA}, {"role": "user", "content": analysis_prompt}]
    
    try:
        analysis = call_model(llm_client, messages, model)
        yield {"type": "reasoning", "content": analysis}
    except Exception as e:
        yield {"type": "error", "message": str(e)}
        return

    # Phase 2: Design (3 Variants)
    architects = [
        ("Alpha", ARCHITECT_ALPHA, "Option 1: Cloud-Native & Scalable"),
        ("Beta", ARCHITECT_BETA, "Option 2: Security & Integration"),
        ("Gamma", ARCHITECT_GAMMA, "Option 3: Pragmatic & Simple")
    ]
    
    plans = []
    
    for name, persona, title in architects:
        yield {"type": "phase", "phase": "design", "message": f"Architect {name} is designing..."}
        
        design_prompt = f"""
        Design an architecture for: {user_goal}
        Context: {context_data}
        Analysis: {analysis}
        
        Adopt your PERSONA strictly.
        {persona}
        
        {PLAN_FORMAT_MCP}
        """
        
        messages = [{"role": "system", "content": ARCHITECT_PERSONA}, {"role": "user", "content": design_prompt}]
        
        try:
            raw = call_model(llm_client, messages, model)
            plan = parse_plan_json(raw)
            plan["_title"] = title
            plans.append(plan)
            
            yield {
                "type": "plan", 
                "architect": name,
                "nodes_count": len(plan.get("nodes", [])),
                "data": plan
            }
        except Exception as e:
            yield {"type": "error", "message": f"Architect {name} failed: {e}"}

    # Phase 3: Build All 3 Side-by-Side
    yield {"type": "phase", "phase": "build", "message": "Building 3 diagrams in Draw.io..."}
    
    # Check if we should clear first? Maybe not, user might want to keep things.
    # But for a fresh "recommend 3", we might want a clean slate or at least clear labeling.
    # Let's just build them spaced out.
    
    builder = ArchitectureDiagramBuilder(mcp_client)
    
    # Layout configuration
    DIAGRAM_WIDTH = 1200 # Approximation from mcp_client.py logic
    SPACING = 200
    
    for i, plan in enumerate(plans):
        offset_x = i * (DIAGRAM_WIDTH + SPACING)
        title = plan.get("_title", f"Option {i+1}")
        
        yield {"type": "phase", "phase": "build", "message": f"Building {title}..."}
        
        try:
            for event in builder.build_from_plan(plan, offset_x=offset_x, header_text=title):
                yield event
        except Exception as e:
             yield {"type": "error", "message": f"Failed to build {title}: {e}"}

    yield {
        "type": "complete",
        "message": "Generated 3 architecture options in Draw.io!",
        "plans": plans
    }


def check_mcp_status() -> Dict[str, Any]:
    """
    Check MCP server status and capabilities.
    
    Returns detailed status for debugging.
    """
    client = DrawioMCPClient()
    
    status = {
        "healthy": False,
        "url": client.base_url,
        "tools": [],
        "error": None
    }
    
    try:
        status["healthy"] = client.is_healthy()
        
        if status["healthy"]:
            tools_resp = client.list_tools()
            if tools_resp.success:
                status["tools"] = tools_resp.result
            else:
                status["error"] = tools_resp.error
    except Exception as e:
        status["error"] = str(e)
    
    return status


def hybrid_generate_stream(
    user_goal: str,
    context_data: Optional[str] = None,
    use_mcp: bool = False,
    model: Optional[str] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Generate architecture with option to use MCP or local XML.
    
    If use_mcp=True and MCP is available, runs the Multi-Agent MCP flow.
    Otherwise, falls back to original agent.
    """
    
    if use_mcp:
        client = DrawioMCPClient()
        if client.is_healthy():
            # Use the new multi-agent MCP flow by default for "recommend 3 diagrams" experience
            yield from mcp_multi_agent_stream(user_goal, context_data, model)
            return
        else:
            yield {
                "type": "warning",
                "message": "MCP server not available, falling back to local XML generation"
            }
    
    # Fallback: Import and use original agent
    from agent import agentic_generate_stream
    yield from agentic_generate_stream(user_goal, context_data, model=model)


# Alias for backward compatibility
mcp_generate_stream = mcp_multi_agent_stream



if __name__ == "__main__":
    # Test MCP status
    status = check_mcp_status()
    print(f"MCP Status: {json.dumps(status, indent=2)}")
    
    # Demo generation (if MCP is ready)
    if status["healthy"]:
        print("\nGenerating test architecture...")
        for event in mcp_generate_stream("Simple 3-tier web application"):
            print(f"  {event['type']}: {event.get('message', event)}")
