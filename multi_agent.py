"""
Multi-Agent Architecture Design System

A team of AI architects collaborates to produce the best architecture:
- Chief Architect: Sets criteria, reviews, scores, makes final decision
- Architect Alpha, Beta, Gamma: Each produces independent designs
- Peer Review: Architects critique each other's work
- Scoring: Designs ranked on multiple criteria
- Selection: Best design refined and presented
"""

import os
import json
import time
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from dotenv import load_dotenv

from plan_to_drawio import plan_to_mxgraph
from validate import validate_xml


# =============================================================================
# AGENT PERSONAS
# =============================================================================

CHIEF_ARCHITECT_PERSONA = """You are the Chief Solution Architect with 25+ years of experience leading enterprise architecture teams at Fortune 500 companies. You are known for:

- Setting clear architectural standards and evaluation criteria
- Mentoring junior architects while maintaining high standards
- Making decisive technology choices backed by deep experience
- Balancing innovation with pragmatism and risk management

Your role is to:
1. Define clear evaluation criteria for architecture proposals
2. Review and score each proposal objectively
3. Provide constructive feedback for improvement
4. Select the best approach and guide refinement"""

ARCHITECT_PERSONAS = {
    "Alpha": """You are Architect Alpha - a cloud-native specialist with deep AWS/Azure expertise. You favor:
- Microservices and containerization (EKS, ECS, Kubernetes)
- Event-driven architectures with managed services
- Infrastructure as Code and GitOps practices
- Cost optimization through serverless where appropriate
Your designs emphasize scalability and cloud-native patterns.""",

    "Beta": """You are Architect Beta - an enterprise integration expert with strong security focus. You favor:
- API-first design with strong governance
- Zero-trust security architecture
- Robust identity and access management
- Compliance-ready designs (SOC2, GDPR, HIPAA)
Your designs emphasize security, compliance, and integration patterns.""",

    "Gamma": """You are Architect Gamma - a pragmatic full-stack architect focused on developer experience. You favor:
- Simple, maintainable architectures
- Proven technologies over bleeding edge
- Strong observability and debugging capabilities
- Fast time-to-market without sacrificing quality
Your designs emphasize simplicity, maintainability, and operational excellence."""
}


@dataclass
class ArchitectureProposal:
    architect_id: str
    architect_name: str
    plan: Dict[str, Any]
    rationale: str
    xml: str
    scores: Dict[str, float] = None
    peer_reviews: List[Dict[str, str]] = None
    total_score: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class PeerReview:
    reviewer_id: str
    target_id: str
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    score: float


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_openai_client() -> OpenAI:
    load_dotenv()
    key = os.getenv("ARCHGEN_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = key
    return OpenAI()


def call_model(client: OpenAI, messages: List[Dict], model: Optional[str] = None, temperature: float = 0.4) -> str:
    chosen_model = model or os.getenv("ARCHGEN_OPENAI_MODEL") or "gpt-4o-mini"
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def parse_json_response(text: str) -> Dict:
    """Extract JSON from LLM response."""
    import re
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Find JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except:
            pass

    # Try fixing common issues
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])

    raise ValueError("Could not parse JSON")


# =============================================================================
# AGENT FUNCTIONS
# =============================================================================

def chief_define_criteria(client: OpenAI, goal: str, context: Optional[str], model: Optional[str] = None) -> Dict:
    """Chief Architect defines evaluation criteria."""
    msgs = [
        {"role": "system", "content": CHIEF_ARCHITECT_PERSONA},
        {"role": "user", "content": f"""Define evaluation criteria for this architecture project:

Goal: {goal}
{f"Context: {context}" if context else ""}

Return JSON with:
{{
    "key_requirements": ["list of must-have requirements"],
    "evaluation_criteria": [
        {{"name": "criterion name", "weight": 0.0-1.0, "description": "what to evaluate"}}
    ],
    "constraints": ["any constraints or boundaries"],
    "guidance": "brief guidance for the architect team"
}}

Ensure weights sum to 1.0. Include criteria like: scalability, security, maintainability, cost-efficiency, innovation."""}
    ]

    response = call_model(client, msgs, model, temperature=0.3)
    return parse_json_response(response)


def architect_design(client: OpenAI, architect_id: str, goal: str, context: Optional[str],
                     criteria: Dict, model: Optional[str] = None) -> ArchitectureProposal:
    """Individual architect creates a design."""
    persona = ARCHITECT_PERSONAS.get(architect_id, ARCHITECT_PERSONAS["Alpha"])

    msgs = [
        {"role": "system", "content": persona + """

When designing, output a JSON architecture plan:
{
    "rationale": "2-3 sentence explanation of your approach",
    "lanes": ["Experience", "Application", "Integration", "Data", "Platform & Security"],
    "groups": [{"id": "...", "name": "...", "lane": "...", "style": "dashed"}],
    "nodes": [{"id": "...", "name": "...", "lane": "...", "type": "app|service|integration|data|security|external", "group": "optional"}],
    "edges": [{"from": "...", "to": "...", "label": "..."}],
    "legend": true
}"""},
        {"role": "user", "content": f"""Design an architecture for:

Goal: {goal}
{f"Context: {context}" if context else ""}

Chief Architect's Guidance:
{criteria.get('guidance', 'Create a comprehensive, well-structured architecture.')}

Key Requirements:
{json.dumps(criteria.get('key_requirements', []), indent=2)}

Evaluation Criteria:
{json.dumps(criteria.get('evaluation_criteria', []), indent=2)}

Create your best architecture proposal. Return JSON only."""}
    ]

    response = call_model(client, msgs, model, temperature=0.5)
    plan = parse_json_response(response)
    rationale = plan.pop("rationale", "")

    # Generate XML
    xml = plan_to_mxgraph(plan)

    return ArchitectureProposal(
        architect_id=architect_id,
        architect_name=f"Architect {architect_id}",
        plan=plan,
        rationale=rationale,
        xml=xml,
        peer_reviews=[]
    )


def peer_review(client: OpenAI, reviewer_id: str, target: ArchitectureProposal,
                goal: str, model: Optional[str] = None) -> PeerReview:
    """One architect reviews another's work."""
    persona = ARCHITECT_PERSONAS.get(reviewer_id, ARCHITECT_PERSONAS["Alpha"])

    msgs = [
        {"role": "system", "content": persona + "\n\nYou are conducting a peer review. Be constructive but thorough."},
        {"role": "user", "content": f"""Review this architecture proposal:

Original Goal: {goal}

Architect {target.architect_id}'s Proposal:
Rationale: {target.rationale}
Plan: {json.dumps(target.plan, indent=2)}

Provide a peer review as JSON:
{{
    "strengths": ["specific strength 1", "specific strength 2"],
    "weaknesses": ["specific weakness 1", "specific weakness 2"],
    "suggestions": ["actionable suggestion 1", "actionable suggestion 2"],
    "score": 7.5  // Score 1-10
}}"""}
    ]

    response = call_model(client, msgs, model, temperature=0.4)
    review_data = parse_json_response(response)

    return PeerReview(
        reviewer_id=reviewer_id,
        target_id=target.architect_id,
        strengths=review_data.get("strengths", []),
        weaknesses=review_data.get("weaknesses", []),
        suggestions=review_data.get("suggestions", []),
        score=float(review_data.get("score", 5.0))
    )


def chief_score_and_select(client: OpenAI, proposals: List[ArchitectureProposal],
                           criteria: Dict, goal: str, model: Optional[str] = None) -> Dict:
    """Chief Architect scores all proposals and selects the best."""
    proposals_summary = []
    for p in proposals:
        avg_peer_score = sum(r.score for r in (p.peer_reviews or [])) / max(len(p.peer_reviews or []), 1)
        proposals_summary.append({
            "architect": p.architect_id,
            "rationale": p.rationale,
            "node_count": len(p.plan.get("nodes", [])),
            "edge_count": len(p.plan.get("edges", [])),
            "peer_avg_score": round(avg_peer_score, 1),
            "peer_feedback": [
                {"reviewer": r.reviewer_id, "strengths": r.strengths[:2], "weaknesses": r.weaknesses[:2]}
                for r in (p.peer_reviews or [])
            ]
        })

    msgs = [
        {"role": "system", "content": CHIEF_ARCHITECT_PERSONA},
        {"role": "user", "content": f"""Score and select the best architecture:

Goal: {goal}

Evaluation Criteria:
{json.dumps(criteria.get('evaluation_criteria', []), indent=2)}

Proposals:
{json.dumps(proposals_summary, indent=2)}

Return JSON:
{{
    "scores": {{
        "Alpha": {{"scalability": 8, "security": 7, ..., "total": 7.5, "reasoning": "brief"}},
        "Beta": {{"scalability": 7, "security": 9, ..., "total": 8.0, "reasoning": "brief"}},
        "Gamma": {{"scalability": 6, "security": 8, ..., "total": 7.0, "reasoning": "brief"}}
    }},
    "winner": "Beta",
    "winner_reasoning": "Why this proposal was selected",
    "refinement_instructions": ["specific improvement 1", "specific improvement 2"]
}}

Score each criterion 1-10, then compute weighted total."""}
    ]

    response = call_model(client, msgs, model, temperature=0.3)
    return parse_json_response(response)


def refine_winning_design(client: OpenAI, winner: ArchitectureProposal,
                          refinements: List[str], goal: str, model: Optional[str] = None) -> ArchitectureProposal:
    """Refine the winning design based on feedback."""
    persona = ARCHITECT_PERSONAS.get(winner.architect_id, ARCHITECT_PERSONAS["Alpha"])

    msgs = [
        {"role": "system", "content": persona},
        {"role": "user", "content": f"""Refine your architecture based on Chief Architect's feedback:

Original Goal: {goal}

Your Current Plan:
{json.dumps(winner.plan, indent=2)}

Chief Architect's Refinement Instructions:
{json.dumps(refinements, indent=2)}

Peer Feedback to Consider:
{json.dumps([{"from": r.reviewer_id, "suggestions": r.suggestions} for r in (winner.peer_reviews or [])], indent=2)}

Return the refined architecture plan as JSON with the same structure (lanes, groups, nodes, edges, legend).
Add a "refinements_applied" field listing what you changed."""}
    ]

    response = call_model(client, msgs, model, temperature=0.3)
    refined_plan = parse_json_response(response)
    refined_plan.pop("refinements_applied", None)  # Remove meta field

    xml = plan_to_mxgraph(refined_plan)

    return ArchitectureProposal(
        architect_id=winner.architect_id,
        architect_name=f"Architect {winner.architect_id} (Refined)",
        plan=refined_plan,
        rationale=winner.rationale + " [Refined based on team feedback]",
        xml=xml,
        scores=winner.scores,
        peer_reviews=winner.peer_reviews,
        total_score=winner.total_score
    )


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def multi_agent_generate_stream(goal: str, context: Optional[str] = None,
                                model: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
    """
    Orchestrate multi-agent architecture design with streaming updates.
    """
    client = get_openai_client()
    architect_ids = ["Alpha", "Beta", "Gamma"]

    # =================================================================
    # PHASE 1: Chief Architect defines criteria
    # =================================================================
    yield {
        "type": "phase",
        "phase": "chief_planning",
        "agent": "Chief Architect",
        "message": "Analyzing requirements and defining evaluation criteria..."
    }

    t0 = time.time()
    try:
        criteria = chief_define_criteria(client, goal, context, model)
    except Exception as e:
        yield {"type": "error", "message": f"Chief Architect error: {e}"}
        return

    yield {
        "type": "criteria",
        "data": criteria,
        "duration": round(time.time() - t0, 1)
    }

    # =================================================================
    # PHASE 2: Architects design in parallel
    # =================================================================
    yield {
        "type": "phase",
        "phase": "team_design",
        "message": "Architecture team is designing proposals..."
    }

    proposals: List[ArchitectureProposal] = []

    for arch_id in architect_ids:
        yield {
            "type": "architect_start",
            "architect": arch_id,
            "message": f"Architect {arch_id} is designing..."
        }

        t1 = time.time()
        try:
            proposal = architect_design(client, arch_id, goal, context, criteria, model)
            proposals.append(proposal)

            yield {
                "type": "architect_done",
                "architect": arch_id,
                "proposal": {
                    "rationale": proposal.rationale,
                    "nodes": len(proposal.plan.get("nodes", [])),
                    "edges": len(proposal.plan.get("edges", [])),
                    "layers": proposal.plan.get("lanes", [])
                },
                "duration": round(time.time() - t1, 1)
            }
        except Exception as e:
            yield {"type": "architect_error", "architect": arch_id, "error": str(e)}

    if not proposals:
        yield {"type": "error", "message": "No proposals generated"}
        return

    # =================================================================
    # PHASE 3: Peer Review
    # =================================================================
    yield {
        "type": "phase",
        "phase": "peer_review",
        "message": "Architects are reviewing each other's work..."
    }

    for proposal in proposals:
        reviewers = [a for a in architect_ids if a != proposal.architect_id]
        proposal.peer_reviews = []

        for reviewer_id in reviewers:
            yield {
                "type": "review_start",
                "reviewer": reviewer_id,
                "target": proposal.architect_id
            }

            try:
                review = peer_review(client, reviewer_id, proposal, goal, model)
                proposal.peer_reviews.append(review)

                yield {
                    "type": "review_done",
                    "reviewer": reviewer_id,
                    "target": proposal.architect_id,
                    "score": review.score,
                    "strengths": review.strengths[:2],
                    "weaknesses": review.weaknesses[:2]
                }
            except Exception as e:
                yield {"type": "review_error", "reviewer": reviewer_id, "error": str(e)}

    # =================================================================
    # PHASE 4: Chief Architect Scoring & Selection
    # =================================================================
    yield {
        "type": "phase",
        "phase": "chief_scoring",
        "agent": "Chief Architect",
        "message": "Evaluating all proposals and selecting the best..."
    }

    t2 = time.time()
    try:
        selection = chief_score_and_select(client, proposals, criteria, goal, model)
    except Exception as e:
        yield {"type": "error", "message": f"Scoring error: {e}"}
        # Fallback: pick first
        selection = {"winner": proposals[0].architect_id, "scores": {}, "refinement_instructions": []}

    # Apply scores
    for proposal in proposals:
        if proposal.architect_id in selection.get("scores", {}):
            score_data = selection["scores"][proposal.architect_id]
            proposal.total_score = score_data.get("total", 0)
            proposal.scores = score_data

    yield {
        "type": "scores",
        "data": selection.get("scores", {}),
        "winner": selection.get("winner"),
        "reasoning": selection.get("winner_reasoning", ""),
        "duration": round(time.time() - t2, 1)
    }

    # Find winner
    winner_id = selection.get("winner", proposals[0].architect_id)
    winner = next((p for p in proposals if p.architect_id == winner_id), proposals[0])

    # =================================================================
    # PHASE 5: Refinement
    # =================================================================
    refinements = selection.get("refinement_instructions", [])
    if refinements:
        yield {
            "type": "phase",
            "phase": "refinement",
            "agent": f"Architect {winner.architect_id}",
            "message": f"Refining the winning design based on feedback..."
        }

        t3 = time.time()
        try:
            winner = refine_winning_design(client, winner, refinements, goal, model)
            yield {
                "type": "refinement_done",
                "changes": refinements,
                "duration": round(time.time() - t3, 1)
            }
        except Exception as e:
            yield {"type": "refinement_error", "error": str(e)}

    # =================================================================
    # FINAL: Present winning architecture
    # =================================================================
    yield {
        "type": "phase",
        "phase": "complete",
        "message": "Architecture design complete!"
    }

    yield {
        "type": "final",
        "winner": winner.architect_id,
        "xml": winner.xml,
        "plan": winner.plan,
        "scores": {p.architect_id: p.total_score for p in proposals},
        "all_proposals": [
            {
                "architect": p.architect_id,
                "rationale": p.rationale,
                "score": p.total_score,
                "xml": p.xml
            }
            for p in sorted(proposals, key=lambda x: x.total_score, reverse=True)
        ]
    }
