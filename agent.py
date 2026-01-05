"""
ArchGen Agent - Professional Architecture Generation with Visible Reasoning

This module implements an AI architect agent that generates compelling Draw.io
architecture diagrams. The agent exposes its thinking process at each phase:
1. ANALYZE - Understanding requirements and constraints
2. DESIGN - Planning architecture layers, components, relationships
3. SYNTHESIZE - Converting plan to Draw.io XML
4. VALIDATE - Checking completeness and correctness
5. REFINE - Improving based on feedback
"""

import os
import re
import time
from typing import Dict, List, Optional, Tuple, Any, Generator

from openai import OpenAI
from dotenv import load_dotenv
import json

from .plan_to_drawio import plan_to_mxgraph
from .validate import validate_xml


# =============================================================================
# SYSTEM PROMPTS - Enhanced for compelling architecture diagrams
# =============================================================================

ARCHITECT_PERSONA = """You are a world-class enterprise solution architect with 20+ years of experience designing mission-critical systems. You think systematically about:

1. **Layered Architecture**: Clear separation of concerns across presentation, business logic, integration, data, and infrastructure layers
2. **Integration Patterns**: Event-driven, API-first, message queues, service mesh
3. **Security by Design**: Zero-trust, identity management, encryption at rest/transit
4. **Scalability**: Horizontal scaling, caching strategies, database sharding
5. **Resilience**: Circuit breakers, retry policies, graceful degradation
6. **Observability**: Logging, metrics, tracing, alerting

When designing architectures, you:
- Start with business requirements and work down to technical implementation
- Consider both functional and non-functional requirements
- Design for change - systems evolve over time
- Balance complexity with maintainability
- Document key decisions and trade-offs"""

SAP_ARCHITECTURE_GUIDE = """
## Architecture Layer Convention

| Layer | Purpose | Color | Components |
|-------|---------|-------|------------|
| Experience | User interfaces, portals, mobile apps | #0a6ed1 (Blue) | Fiori, Mobile, Portal, External UIs |
| Application | Business logic, core applications | #1a9898 (Teal) | S/4HANA, ECC, SuccessFactors, Ariba |
| Integration | APIs, events, orchestration | #f39c12 (Orange) | Integration Suite, API Mgmt, Event Mesh |
| Data | Storage, analytics, lakes | #6c5ce7 (Purple) | HANA, Data Lake, BW/4HANA, Analytics |
| Platform & Security | Infrastructure, identity, security | #2c3e50 (Dark) | BTP, IAS, XSUAA, Cloud Connector |
| External | Third-party systems | #95a5a6 (Gray) | CRM, Legacy, Partner Systems |

## Diagram Best Practices
- Group related components (e.g., "BTP Subaccount", "On-Premise", "Partner Zone")
- Show data flow direction with labeled arrows
- Use consistent spacing and alignment
- Include security boundaries where relevant
- Add a legend for complex diagrams
"""

PLAN_FORMAT = """
## Output Format (JSON only)

Return ONLY a JSON object with this structure:
```json
{
  "lanes": ["Experience", "Application", "Integration", "Data", "Platform & Security"],
  "groups": [
    {"id": "BTP", "name": "SAP BTP", "lane": "Platform & Security", "style": "dashed"},
    {"id": "OnPrem", "name": "On-Premise", "lane": "Application", "style": "solid"}
  ],
  "nodes": [
    {"id": "S4HANA", "name": "SAP S/4HANA", "lane": "Application", "type": "app", "group": "OnPrem"},
    {"id": "IntSuite", "name": "Integration Suite", "lane": "Integration", "type": "integration", "group": "BTP"},
    {"id": "CRM", "name": "External CRM", "lane": "Experience", "type": "external", "scope": "external"}
  ],
  "edges": [
    {"from": "S4HANA", "to": "IntSuite", "label": "OData/REST"},
    {"from": "IntSuite", "to": "CRM", "label": "Events"}
  ],
  "legend": true
}
```

## Node Types
- `app`: Core application (rounded rectangle)
- `service`: Microservice/function (rectangle)
- `integration`: Integration component (rounded)
- `data`: Database/storage (cylinder)
- `security`: Security component (shield-like)
- `external`: External/third-party system (gray)

## Edge Labels (use descriptive labels)
- Protocol: "REST API", "OData", "SOAP", "GraphQL"
- Pattern: "Events", "Message Queue", "Sync/Async"
- Security: "OAuth2/JWT", "mTLS", "API Key"
- Data: "ETL", "CDC", "Replication"
"""


def get_openai_client() -> OpenAI:
    """Initialize OpenAI client with API key from environment."""
    load_dotenv()
    key = os.getenv("ARCHGEN_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY or ARCHGEN_OPENAI_API_KEY in environment")
    os.environ["OPENAI_API_KEY"] = key
    return OpenAI()


def system_prompt() -> str:
    """Build the full system prompt for the architect agent."""
    return f"""{ARCHITECT_PERSONA}

{SAP_ARCHITECTURE_GUIDE}

{PLAN_FORMAT}

---
CRITICAL: Return ONLY valid JSON. No explanations, no markdown outside the JSON, no preamble.
"""


def analyze_requirements_prompt(user_goal: str, context_data: Optional[str]) -> str:
    """Generate prompt for requirements analysis phase."""
    return f"""Analyze these architecture requirements and identify:
1. Key business capabilities needed
2. Integration points and data flows
3. Security and compliance requirements
4. Scalability and performance considerations
5. Potential risks or challenges

**Goal**: {user_goal}
{f"**Context**: {context_data}" if context_data else ""}

Provide a brief analysis (3-5 sentences) focusing on the most critical architectural decisions."""


def design_architecture_prompt(user_goal: str, context_data: Optional[str], analysis: str) -> str:
    """Generate prompt for architecture design phase."""
    return f"""Based on this analysis, design a comprehensive architecture:

**Goal**: {user_goal}
{f"**Context**: {context_data}" if context_data else ""}

**Analysis**: {analysis}

Return ONLY a JSON plan with lanes, groups, nodes, and edges. Ensure:
- All major components are represented
- Integration paths are clearly defined
- Security boundaries are shown
- The architecture is practical and implementable"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    t = text.strip()
    if t.startswith("```"):
        # Remove opening fence with optional language tag
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _fix_ampersands(xml_text: str) -> str:
    """Fix unescaped ampersands in XML."""
    return re.sub(r"&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", xml_text)


def sanitize_llm_xml(text: str) -> str:
    """Clean up XML output from LLM."""
    t = _strip_code_fences(text)
    t = _fix_ampersands(t)
    return t


def parse_plan_json(raw: str) -> Dict[str, Any]:
    """Parse JSON plan with resilience to common LLM formatting issues."""
    s = _strip_code_fences(raw).strip()

    # Remove common prefixes
    for prefix in ("PLAN:", "Here is the plan:", "Plan:", "Here's the plan:"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):].strip()

    # Try direct parse
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Extract JSON object substring
    try:
        start = s.find('{')
        end = s.rfind('}')
        if start != -1 and end != -1 and end > start:
            sub = s[start:end+1]
            return json.loads(sub)
    except json.JSONDecodeError:
        pass

    # Apply heuristic fixes
    s2 = s.replace("'", '"')
    s2 = re.sub(r',\s*}', '}', s2)  # Remove trailing commas in objects
    s2 = re.sub(r',\s*]', ']', s2)  # Remove trailing commas in arrays

    try:
        start = s2.find('{')
        end = s2.rfind('}')
        if start != -1 and end != -1 and end > start:
            sub = s2[start:end+1]
            return json.loads(sub)
    except json.JSONDecodeError:
        pass

    raise ValueError("Could not parse PLAN JSON from LLM output")


def normalize_plan(user_goal: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and enhance the architecture plan with best practices."""
    g = plan.copy()
    goal_lower = user_goal.lower()

    # Ensure standard lanes
    default_lanes = ["Experience", "Application", "Integration", "Data", "Platform & Security"]
    g["lanes"] = g.get("lanes") or default_lanes

    # Normalize groups
    groups = {grp.get("id"): grp for grp in (g.get("groups") or []) if grp.get("id")}

    def ensure_group(gid: str, name: str, lane: str, style: str = "dashed"):
        if gid not in groups:
            groups[gid] = {"id": gid, "name": name, "lane": lane, "style": style}

    # Add contextual groups based on goal
    ensure_group("BTP", "SAP BTP", "Platform & Security")
    if any(kw in goal_lower for kw in ["hybrid", "on-prem", "on premise"]):
        ensure_group("OnPrem", "On-Premise", "Application", "solid")
    if any(kw in goal_lower for kw in ["security", "secure", "zero trust"]):
        ensure_group("SecurityZone", "Security Boundary", "Platform & Security")
    if any(kw in goal_lower for kw in ["partner", "third party", "external"]):
        ensure_group("PartnerZone", "Partner Integration Zone", "Integration")

    g["groups"] = list(groups.values())

    # Normalize nodes
    nodes = {n.get("id"): n for n in (g.get("nodes") or []) if n.get("id")}

    def ensure_node(nid: str, name: str, lane: str, ntype: str, group: Optional[str] = None, scope: Optional[str] = None):
        if nid not in nodes:
            n = {"id": nid, "name": name, "lane": lane, "type": ntype}
            if group:
                n["group"] = group
            if scope:
                n["scope"] = scope
            nodes[nid] = n

    # Add contextual components
    if any(kw in goal_lower for kw in ["event", "async", "message"]):
        ensure_node("EventMesh", "Event Mesh", "Integration", "integration", group="BTP")
    if any(kw in goal_lower for kw in ["api", "rest", "gateway"]):
        ensure_node("APIM", "API Management", "Integration", "integration", group="BTP")
    if "monitor" in goal_lower:
        ensure_node("Monitoring", "Cloud ALM", "Platform & Security", "service", group="BTP")

    # Correct lane assignments for known components
    lane_corrections = {
        "IntegrationSuite": ("Integration", "BTP"),
        "Integration Suite": ("Integration", "BTP"),
        "IAS": ("Platform & Security", "BTP"),
        "XSUAA": ("Platform & Security", "BTP"),
        "CloudConnector": ("Platform & Security", "BTP"),
    }

    for nid, (lane, group) in lane_corrections.items():
        if nodes.get(nid):
            nodes[nid]["lane"] = lane
            nodes[nid]["group"] = nodes[nid].get("group") or group

    g["nodes"] = list(nodes.values())

    # Normalize edges
    edges = list(g.get("edges") or [])
    edge_set = {(e.get("from"), e.get("to"), e.get("label", "")) for e in edges}

    def add_edge(src: str, tgt: str, label: str):
        if (src, tgt, label) not in edge_set and src in nodes and tgt in nodes:
            edges.append({"from": src, "to": tgt, "label": label})
            edge_set.add((src, tgt, label))

    # Add common integration patterns
    if nodes.get("IAS"):
        for nid in nodes:
            if nodes[nid].get("type") in ("app", "service") and nid != "IAS":
                add_edge("IAS", nid, "OAuth2/SAML")
                break  # Only add one example

    g["edges"] = edges
    g["legend"] = g.get("legend", True)

    return g


def call_model(client: OpenAI, messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    """Call the OpenAI model with given messages."""
    chosen_model = model or os.getenv("ARCHGEN_OPENAI_MODEL") or "gpt-4o-mini"
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def is_drawio_xml(txt: str) -> bool:
    """Check if text is valid Draw.io XML."""
    t = txt.strip()
    if t.startswith("<?xml"):
        return "mxGraphModel" in t or "mxfile" in t
    return t.startswith("<mxGraphModel") or t.startswith("<mxfile")


def self_check(client: OpenAI, user_goal: str, xml_text: str, model: Optional[str] = None) -> Tuple[bool, str]:
    """Validate the generated diagram against the original goal."""
    msgs = [
        {"role": "system", "content": "You are a strict architecture reviewer. Evaluate the diagram against requirements. Be concise. Output format: 'OK' if compliant, or list specific issues."},
        {"role": "user", "content": f"Goal: {user_goal}"},
        {"role": "user", "content": f"Diagram XML (excerpt):\n{xml_text[:3000]}"},
    ]
    verdict = call_model(client, msgs, model=model)
    ok = verdict.strip().upper().startswith("OK") or ("compliant" in verdict.lower() and "not" not in verdict.lower())
    return ok, verdict


def propose_plan_fixes(user_goal: str, issues: str, current_plan: Dict[str, Any], client: OpenAI, model: Optional[str] = None) -> List[Dict[str, str]]:
    """Generate specific fixes for identified issues."""
    msgs = [
        {"role": "system", "content": 'Return JSON only: {"fixes": [{"reason": "...", "change": "..."}]}'},
        {"role": "user", "content": f"Goal: {user_goal}\nIssues: {issues}\nCurrent plan: {json.dumps(current_plan, indent=2)}"},
    ]
    out = call_model(client, msgs, model=model)
    try:
        data = json.loads(_strip_code_fences(out))
        return data.get("fixes", [])
    except Exception:
        return []


def propose_clarifying_questions(user_goal: str, context_data: Optional[str] = None, max_q: int = 6, model: Optional[str] = None) -> List[str]:
    """Generate clarifying questions for ambiguous requirements."""
    client = get_openai_client()
    msgs = [
        {"role": "system", "content": "You are a senior architect. Ask 3-6 clarifying questions to design a precise architecture. Return numbered questions or 'NONE' if requirements are clear."},
        {"role": "user", "content": f"Goal: {user_goal}"},
    ]
    if context_data:
        msgs.append({"role": "user", "content": f"Context: {context_data}"})

    out = call_model(client, msgs, model=model)
    lines = [l.strip() for l in out.splitlines() if l.strip()]

    if len(lines) == 1 and "NONE" in lines[0].upper():
        return []

    questions = []
    for line in lines:
        # Clean up numbering and bullets
        cleaned = re.sub(r'^[\d\.\)\-\*\s]+', '', line).strip()
        if cleaned and len(cleaned) > 10:
            questions.append(cleaned)
        if len(questions) >= max_q:
            break

    return questions


# =============================================================================
# MAIN AGENT FUNCTIONS
# =============================================================================

def agentic_generate(user_goal: str, context_data: Optional[str] = None, max_iters: int = 3, model: Optional[str] = None) -> Dict:
    """
    Synchronous architecture generation.

    Returns: {"xml": str, "trace": List[Dict]}
    """
    client = get_openai_client()
    trace: List[Dict] = []
    xml: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None

    for i in range(max_iters):
        start = time.time()

        # Build messages for plan generation
        msgs = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"Design an architecture for: {user_goal}"},
        ]
        if context_data:
            msgs.append({"role": "user", "content": f"Context: {context_data}"})
        if plan:
            msgs.append({"role": "user", "content": f"Previous plan (refine if needed): {json.dumps(plan)}"})

        # Generate plan
        raw_plan = call_model(client, msgs, model=model)
        try:
            plan = parse_plan_json(raw_plan)
            plan = normalize_plan(user_goal, plan)
        except Exception as e:
            trace.append({"iteration": i + 1, "error": f"Plan parsing failed: {e}"})
            continue

        # Convert to XML
        draft_xml = plan_to_mxgraph(plan)
        ok_fmt = is_drawio_xml(draft_xml)

        # Validate
        ok_sem, check = (False, "") if not ok_fmt else self_check(client, user_goal, draft_xml, model=model)
        local = validate_xml(draft_xml, user_goal) if ok_fmt else {"ok": False, "issues": ["Invalid XML"]}

        trace.append({
            "iteration": i + 1,
            "plan": plan,
            "format_ok": ok_fmt,
            "semantics": check,
            "local_validation": local,
            "duration_sec": round(time.time() - start, 2),
        })

        if ok_fmt and ok_sem and local.get("ok", False):
            xml = draft_xml
            break

    return {"xml": xml or plan_to_mxgraph(plan) if plan else "", "trace": trace}


def agentic_generate_stream(user_goal: str, context_data: Optional[str] = None, max_iters: int = 3, model: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming architecture generation with detailed phase reporting.

    Yields events:
    - iteration: {type: "iteration", iteration: int}
    - phase: {type: "phase", phase: str, reasoning: str, duration?: str}
    - plan: {type: "plan", data: Dict, duration_sec: float}
    - verify: {type: "verify", ok: bool, format_ok: bool, verdict: str}
    - fixes: {type: "fixes", data: List}
    - final: {type: "final", xml: str}
    """
    client = get_openai_client()
    plan: Optional[Dict[str, Any]] = None

    for i in range(max_iters):
        yield {"type": "iteration", "iteration": i + 1}

        # =================================================================
        # PHASE 1: ANALYZE
        # =================================================================
        t0 = time.time()
        yield {
            "type": "phase",
            "phase": "analyze",
            "reasoning": f"Analyzing architecture requirements for: \"{user_goal[:100]}{'...' if len(user_goal) > 100 else ''}\""
        }

        # Generate analysis
        analysis_msgs = [
            {"role": "system", "content": ARCHITECT_PERSONA},
            {"role": "user", "content": analyze_requirements_prompt(user_goal, context_data)}
        ]
        analysis = call_model(client, analysis_msgs, model=model)

        analyze_duration = f"{round(time.time() - t0, 1)}s"

        # =================================================================
        # PHASE 2: DESIGN
        # =================================================================
        t1 = time.time()
        yield {
            "type": "phase",
            "phase": "design",
            "reasoning": f"Designing architecture based on analysis:\n{analysis[:200]}...",
            "duration": analyze_duration
        }

        # Generate plan
        design_msgs = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"Goal: {user_goal}"},
        ]
        if context_data:
            design_msgs.append({"role": "user", "content": f"Context: {context_data}"})
        if plan:
            design_msgs.append({"role": "user", "content": f"Refine this plan: {json.dumps(plan)}"})
        else:
            design_msgs.append({"role": "user", "content": "Create the architecture plan as JSON."})

        raw_plan = call_model(client, design_msgs, model=model)

        try:
            proposed = parse_plan_json(raw_plan)
            plan = normalize_plan(user_goal, proposed)
        except Exception as e:
            yield {"type": "phase", "phase": "design", "reasoning": f"Plan parsing error: {e}. Retrying..."}
            # Retry with explicit formatting instruction
            design_msgs.append({"role": "user", "content": "Error parsing JSON. Please return ONLY valid JSON with lanes, groups, nodes, edges."})
            raw_plan = call_model(client, design_msgs, model=model)
            try:
                proposed = parse_plan_json(raw_plan)
                plan = normalize_plan(user_goal, proposed)
            except Exception as e2:
                yield {"type": "phase", "phase": "design", "reasoning": f"Plan parsing failed: {e2}"}
                continue

        design_duration = round(time.time() - t1, 2)

        # Report plan
        node_count = len(plan.get("nodes", []))
        edge_count = len(plan.get("edges", []))
        yield {
            "type": "plan",
            "data": plan,
            "duration_sec": design_duration
        }

        yield {
            "type": "reasoning",
            "content": f"Designed architecture with {node_count} components and {edge_count} connections across {len(plan.get('lanes', []))} layers."
        }

        # =================================================================
        # PHASE 3: SYNTHESIZE
        # =================================================================
        t2 = time.time()
        yield {
            "type": "phase",
            "phase": "synthesize",
            "reasoning": f"Converting architecture plan to Draw.io XML format with proper styling and layout..."
        }

        xml_text = plan_to_mxgraph(plan)
        ok_fmt = is_drawio_xml(xml_text)

        synth_duration = f"{round(time.time() - t2, 2)}s"

        if not ok_fmt:
            yield {
                "type": "phase",
                "phase": "synthesize",
                "reasoning": "Generated XML is malformed. Will retry...",
                "duration": synth_duration
            }
            continue

        # =================================================================
        # PHASE 4: VALIDATE
        # =================================================================
        t3 = time.time()
        yield {
            "type": "phase",
            "phase": "validate",
            "reasoning": "Validating architecture against requirements, checking completeness and correctness..."
        }

        ok_sem, verdict = self_check(client, user_goal, xml_text, model=model)
        local = validate_xml(xml_text, user_goal)

        all_ok = ok_fmt and ok_sem and local.get("ok", False)

        yield {
            "type": "verify",
            "format_ok": ok_fmt,
            "ok": all_ok,
            "verdict": verdict,
            "local": local
        }

        if all_ok:
            yield {
                "type": "reasoning",
                "content": f"Architecture validated successfully! The diagram meets all requirements."
            }
            yield {"type": "final", "xml": xml_text}
            return

        # =================================================================
        # PHASE 5: REFINE
        # =================================================================
        yield {
            "type": "phase",
            "phase": "refine",
            "reasoning": f"Validation found issues. Analyzing and planning improvements..."
        }

        # Get specific fixes
        issues = verdict if not ok_sem else "; ".join(local.get("issues", []))
        fixes = propose_plan_fixes(user_goal, issues, plan, client, model=model)

        if fixes:
            yield {"type": "fixes", "data": fixes}
            yield {
                "type": "reasoning",
                "content": f"Identified {len(fixes)} improvements to apply in next iteration."
            }

    # Exhausted iterations - return best effort
    if plan:
        xml_text = plan_to_mxgraph(plan)
        yield {
            "type": "reasoning",
            "content": "Completed maximum iterations. Returning best effort architecture."
        }
        yield {"type": "final", "xml": xml_text}
