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

from plan_to_drawio import plan_to_mxgraph, plans_to_mxgraph
from validate import validate_xml

# =============================================================================
# SYSTEM PROMPTS - Simple and focused
# =============================================================================

ARCHITECT_PERSONA = """You are an expert at creating SIMPLE, CLEAN architecture diagrams.

CRITICAL RULES:
- Maximum 6 nodes (components)
- Short names (under 15 characters)
- Clear top-to-bottom data flow
- Edge labels: 1-2 words only
- Focus on MAIN components only"""

ARCHITECTURE_GUIDE = """
## Simple Architecture Format

Just create nodes and edges. Keep it SIMPLE.

Node Types:
- process: Services, apps, functions
- data: Databases, storage, caches  
- network: Load balancers, API gateways
- security: IAM, auth, firewalls
- external: Third-party systems

Example (max 6 nodes):
```json
{
  "title": "Simple Web App",
  "nodes": [
    {"id": "lb", "name": "Load Balancer", "type": "network"},
    {"id": "app", "name": "App Server", "type": "process"},
    {"id": "cache", "name": "Redis Cache", "type": "data"},
    {"id": "db", "name": "Database", "type": "data"}
  ],
  "edges": [
    {"from": "lb", "to": "app", "label": "HTTP"},
    {"from": "app", "to": "cache", "label": "cache"},
    {"from": "app", "to": "db", "label": "SQL"}
  ]
}
```
"""



PLAN_FORMAT = """
## Output Format (JSON only)

Return ONLY a JSON object with this structure:

```json
{
  "title": "Architecture Name",
  "nodes": [
    {"id": "n1", "name": "Component 1", "type": "process"},
    {"id": "n2", "name": "Component 2", "type": "data"},
    {"id": "n3", "name": "Component 3", "type": "network"}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "label": "calls"},
    {"from": "n2", "to": "n3"}
  ]
}
```

## Node Types
- process: Apps, services, functions (lavender)
- data: Databases, caches, storage (plum)
- network: Load balancers, gateways (blue)
- security: Auth, firewall (pink)
- external: Third-party (yellow)

## RULES
- MAX 6 nodes
- Names under 15 chars
- Labels under 10 chars
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

{ARCHITECTURE_GUIDE}

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
    """
    Normalize and SIMPLIFY the architecture plan.
    Key actions:
    - Limit nodes to MAX 8
    - Convert VPC/Subnet/Cluster nodes to groups
    - Truncate long names
    - Remove duplicate edges
    """
    g = plan.copy()
    
    # Ensure title
    if not g.get("title"):
        g["title"] = user_goal[:50] + ("..." if len(user_goal) > 50 else "")
    
    # Ensure lists exist
    g["nodes"] = g.get("nodes") or []
    g["edges"] = g.get("edges") or []
    g["groups"] = list(g.get("groups") or [])
    
    # Keywords that indicate infrastructure containers (should be groups, not nodes)
    CONTAINER_KEYWORDS = [
        "vpc", "subnet", "cluster", "network", "region", "zone",
        "namespace", "environment", "boundary", "perimeter"
    ]
    
    # Convert container nodes to groups
    nodes_to_remove = []
    for node in g["nodes"]:
        name_lower = node.get("name", "").lower()
        id_lower = node.get("id", "").lower()
        
        # Check if this node should be a group
        is_container = any(kw in name_lower or kw in id_lower for kw in CONTAINER_KEYWORDS)
        
        if is_container:
            # Convert to group
            new_group = {
                "id": node.get("id"),
                "name": node.get("name", node.get("id"))
            }
            # Check if this group already exists
            existing_ids = {grp.get("id") for grp in g["groups"]}
            if new_group["id"] not in existing_ids:
                g["groups"].append(new_group)
            nodes_to_remove.append(node)
    
    # Remove converted nodes
    for node in nodes_to_remove:
        g["nodes"].remove(node)
    
    # Remove edges that reference removed nodes
    node_ids = {n.get("id") for n in g["nodes"]}
    g["edges"] = [
        e for e in g["edges"]
        if e.get("from") in node_ids and e.get("to") in node_ids
    ]
    
    # LIMIT nodes to max 8 (keep first 8 for simplicity)
    MAX_NODES = 8
    if len(g["nodes"]) > MAX_NODES:
        # Keep nodes that have the most connections
        node_connection_count = {}
        for node in g["nodes"]:
            nid = node.get("id")
            count = sum(1 for e in g["edges"] if e.get("from") == nid or e.get("to") == nid)
            node_connection_count[nid] = count
        
        # Sort by connection count (most connected first)
        sorted_nodes = sorted(g["nodes"], key=lambda n: node_connection_count.get(n.get("id"), 0), reverse=True)
        g["nodes"] = sorted_nodes[:MAX_NODES]
        
        # Clean edges again
        node_ids = {n.get("id") for n in g["nodes"]}
        g["edges"] = [
            e for e in g["edges"]
            if e.get("from") in node_ids and e.get("to") in node_ids
        ]
    
    # Truncate long node names
    for node in g["nodes"]:
        name = node.get("name", node.get("id", ""))
        if len(name) > 20:
            node["name"] = name[:17] + "..."
    
    # Remove duplicate edges
    seen_edges = set()
    unique_edges = []
    for e in g["edges"]:
        edge_key = (e.get("from"), e.get("to"))
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            unique_edges.append(e)
    g["edges"] = unique_edges
    
    # Truncate edge labels
    for edge in g["edges"]:
        label = edge.get("label", "")
        if len(label) > 15:
            edge["label"] = label[:12] + "..."
    
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


# =============================================================================
# MULTI-PROPOSAL GENERATION (Recommendation System)
# =============================================================================

PROPOSAL_VARIANTS = [
    {
        "name": "Option 1: Standard",
        "instruction": "Design a balanced, standard enterprise architecture focusing on proven patterns and maintainability.",
        "focus": "balanced"
    },
    {
        "name": "Option 2: Event-Driven",
        "instruction": "Design an event-driven, loosely-coupled architecture emphasizing async communication, event mesh, and real-time data flows.",
        "focus": "event-driven"
    },
    {
        "name": "Option 3: Security-First",
        "instruction": "Design a security-first architecture with zero-trust principles, strong identity management, and defense in depth.",
        "focus": "security"
    }
]


def generate_multi_proposals(
    user_goal: str, 
    context_data: Optional[str] = None, 
    model: Optional[str] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Generate 3 different architecture proposals for recommendation.
    
    Yields events:
    - phase: Current generation phase
    - proposal: Individual proposal data
    - final: Combined XML with all 3 proposals side-by-side
    """
    client = get_openai_client()
    proposals: List[Dict[str, Any]] = []
    
    yield {
        "type": "phase",
        "phase": "multi_proposal",
        "reasoning": f"Generating 3 architecture recommendations for: \"{user_goal[:100]}...\""
    }
    
    # Generate each proposal variant
    for idx, variant in enumerate(PROPOSAL_VARIANTS):
        yield {
            "type": "phase",
            "phase": "generating",
            "reasoning": f"Creating {variant['name']}...",
            "proposal_index": idx
        }
        
        t0 = time.time()
        
        # Build variant-specific prompt
        variant_prompt = f"""Design an architecture for: {user_goal}

{variant['instruction']}

Key focus areas for this variant:
{"- Proven patterns, standard integrations, maintainable design" if variant['focus'] == 'balanced' else ""}
{"- Event Mesh, async messaging, loosely-coupled services, CQRS patterns" if variant['focus'] == 'event-driven' else ""}
{"- Zero-trust, Identity Access, encryption, security boundaries, audit logging" if variant['focus'] == 'security' else ""}

Return ONLY a JSON plan with lanes, groups, nodes, and edges."""
        
        msgs = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": variant_prompt},
        ]
        if context_data:
            msgs.append({"role": "user", "content": f"Context: {context_data}"})
        
        raw_plan = call_model(client, msgs, model=model)
        
        try:
            plan = parse_plan_json(raw_plan)
            plan = normalize_plan(user_goal, plan)
            plan["title"] = variant["name"]
            
            proposals.append(plan)
            
            duration_sec = round(time.time() - t0, 2)
            
            yield {
                "type": "proposal",
                "index": idx,
                "name": variant["name"],
                "plan": plan,
                "node_count": len(plan.get("nodes", [])),
                "edge_count": len(plan.get("edges", [])),
                "duration_sec": duration_sec
            }
            
        except Exception as e:
            yield {
                "type": "proposal_error",
                "index": idx,
                "name": variant["name"],
                "error": str(e)
            }
            # Add empty placeholder
            proposals.append({
                "title": variant["name"],
                "lanes": ["Experience", "Application", "Integration", "Data", "Platform & Security"],
                "nodes": [{"id": "placeholder", "name": "Error generating", "lane": "Application", "type": "app"}],
                "edges": [],
                "groups": []
            })
    
    # Generate combined XML
    yield {
        "type": "phase",
        "phase": "synthesize",
        "reasoning": "Combining 3 proposals into side-by-side comparison layout..."
    }
    
    combined_xml = plans_to_mxgraph(proposals)
    
    yield {
        "type": "phase",
        "phase": "complete",
        "reasoning": f"Generated {len(proposals)} architecture recommendations."
    }
    
    yield {
        "type": "final",
        "xml": combined_xml,
        "proposal_count": len(proposals)
    }


def agentic_generate_recommendations(
    user_goal: str, 
    context_data: Optional[str] = None, 
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synchronous version: Generate 3 architecture recommendations.
    
    Returns: {"xml": str, "proposals": List[Dict]}
    """
    proposals = []
    xml = ""
    
    for event in generate_multi_proposals(user_goal, context_data, model):
        if event.get("type") == "proposal":
            proposals.append(event.get("plan"))
        elif event.get("type") == "final":
            xml = event.get("xml", "")
    
    return {"xml": xml, "proposals": proposals}
