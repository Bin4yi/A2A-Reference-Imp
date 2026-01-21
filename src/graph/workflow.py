"""
LangGraph Hierarchical Workflow for Employee Onboarding.
"""

import structlog
from langgraph.graph import StateGraph, END

from src.graph.state import OnboardingState, add_audit_entry
from src.agents.intake import intake_agent
from src.agents.policy import policy_engine
from src.agents.workers import (
    hr_agent,
    approval_agent,
    check_approvals_agent,
    it_agent,
    booking_agent
)

logger = structlog.get_logger()


async def director_agent(state: OnboardingState) -> OnboardingState:
    """
    Director Agent - Top level coordination.
    Determines next phase based on current state.
    """
    phase = state["current_phase"]
    
    logger.info(
        "director_agent",
        request_id=state["request_id"],
        current_phase=phase,
        completed=state["completed_actions"]
    )
    
    audit = add_audit_entry(
        state,
        agent="director",
        action=f"routing_from_{phase}",
        details={"completed_actions": state["completed_actions"]}
    )
    
    return {
        **state,
        "audit_log": [audit]
    }


async def compile_report(state: OnboardingState) -> OnboardingState:
    """
    Compile final onboarding report.
    """
    parsed = state["parsed_request"]
    
    report = {
        "request_id": state["request_id"],
        "employee": {
            "id": state["employee_id"],
            "name": parsed["employee_name"] if parsed else "Unknown",
            "email": parsed["employee_email"] if parsed else "Unknown",
            "role": parsed["role"] if parsed else "Unknown",
            "team": parsed["team"] if parsed else "Unknown",
            "start_date": parsed["start_date"] if parsed else "Unknown"
        },
        "risk_assessment": state["risk_assessment"],
        "approvals": {
            "requested": state["approval_requests"],
            "received": state["approvals_received"]
        },
        "provisioned_services": state["provisioned_services"],
        "scheduled_tasks": state["scheduled_tasks"],
        "scheduled_deliveries": state["scheduled_deliveries"],
        "audit_log_count": len(state["audit_log"])
    }
    
    audit = add_audit_entry(
        state,
        agent="director",
        action="onboarding_completed",
        details={"employee_id": state["employee_id"]}
    )
    
    logger.info(
        "onboarding_completed",
        request_id=state["request_id"],
        employee_id=state["employee_id"]
    )
    
    return {
        **state,
        "status": "completed",
        "current_phase": "complete",
        "final_report": report,
        "audit_log": [audit]
    }


def should_continue_after_hr(state: OnboardingState) -> str:
    """Determine next step after HR agent."""
    if state.get("status") == "failed":
        return "end"
    
    # Check if approvals are needed
    risk = state.get("risk_assessment")
    if risk and risk.get("required_approvals"):
        return "approvals"
    
    return "it"


def should_continue_after_approvals(state: OnboardingState) -> str:
    """Determine next step after approval agent."""
    if state.get("status") == "failed":
        return "end"
    
    # If approvals requested, need to wait (in real system, would poll)
    if state.get("blocking_approvals"):
        # For demo, simulate approvals received
        return "check_approvals"
    
    return "it"


def should_continue_after_check(state: OnboardingState) -> str:
    """Determine next step after checking approvals."""
    if state.get("blocking_approvals"):
        # Still waiting - in production would wait/retry
        # For demo, proceed anyway
        return "it"
    return "it"


def should_continue_after_it(state: OnboardingState) -> str:
    """Determine next step after IT agent."""
    if state.get("status") == "failed":
        return "end"
    return "booking"


def should_continue_after_booking(state: OnboardingState) -> str:
    """Determine next step after booking agent."""
    if state.get("status") == "failed":
        return "end"
    return "compile"


def create_onboarding_graph() -> StateGraph:
    """
    Create the LangGraph workflow for employee onboarding.
    
    Flow:
    intake → policy → director → hr → [approvals] → it → booking → compile
    """
    graph = StateGraph(OnboardingState)
    
    # Add nodes
    graph.add_node("intake", intake_agent)
    graph.add_node("policy", policy_engine)
    graph.add_node("director", director_agent)
    graph.add_node("hr", hr_agent)
    graph.add_node("approvals", approval_agent)
    graph.add_node("check_approvals", check_approvals_agent)
    graph.add_node("it", it_agent)
    graph.add_node("booking", booking_agent)
    graph.add_node("compile", compile_report)
    
    # Set entry point
    graph.set_entry_point("intake")
    
    # Add edges
    graph.add_edge("intake", "policy")
    graph.add_edge("policy", "director")
    graph.add_edge("director", "hr")
    
    # Conditional routing after HR
    graph.add_conditional_edges(
        "hr",
        should_continue_after_hr,
        {
            "approvals": "approvals",
            "it": "it",
            "end": END
        }
    )
    
    # After approvals, check status or proceed
    graph.add_conditional_edges(
        "approvals",
        should_continue_after_approvals,
        {
            "check_approvals": "check_approvals",
            "it": "it",
            "end": END
        }
    )
    
    # After checking approvals
    graph.add_conditional_edges(
        "check_approvals",
        should_continue_after_check,
        {
            "it": "it"
        }
    )
    
    # After IT provisioning
    graph.add_conditional_edges(
        "it",
        should_continue_after_it,
        {
            "booking": "booking",
            "end": END
        }
    )
    
    # After booking
    graph.add_conditional_edges(
        "booking",
        should_continue_after_booking,
        {
            "compile": "compile",
            "end": END
        }
    )
    
    # Final node
    graph.add_edge("compile", END)
    
    return graph


# Compiled graph
_compiled_graph = None


def get_onboarding_graph():
    """Get the compiled onboarding graph."""
    global _compiled_graph
    if _compiled_graph is None:
        graph = create_onboarding_graph()
        _compiled_graph = graph.compile()
    return _compiled_graph
