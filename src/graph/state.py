"""
LangGraph state definition for the onboarding workflow.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, TypedDict, Optional
from operator import add


class ParsedRequest(TypedDict):
    """Parsed onboarding request from natural language."""
    employee_name: str
    employee_email: str
    role: str
    team: str
    manager_email: str
    start_date: str
    access_requirements: list[str]  # ["vpn", "github", "aws", "jira"]
    github_repos: list[str]
    hardware_needs: list[str]  # ["laptop"]
    delivery_location: Optional[str]


class RiskAssessment(TypedDict):
    """Risk assessment from policy engine."""
    risk_level: str  # "STANDARD", "ELEVATED", "HIGH"
    risk_factors: list[str]
    required_approvals: list[dict]  # [{"type": "...", "policy": "..."}]
    compliance_flags: list[str]


class AuditEntry(TypedDict):
    """Audit log entry."""
    timestamp: str
    agent: str
    action: str
    details: dict
    token_info: Optional[dict]


class OnboardingState(TypedDict):
    """
    Shared state for the onboarding workflow.
    Passed between all agents in the LangGraph.
    """
    # Request info
    request_id: str
    raw_request: str
    parsed_request: Optional[ParsedRequest]
    
    # User context (from OAuth)
    user_sub: str
    actor_sub: str
    composite_token: str
    
    # Risk assessment
    risk_assessment: Optional[RiskAssessment]
    
    # Workflow progress
    employee_id: Optional[str]
    approval_requests: list[str]  # Approval request IDs
    approvals_received: list[str]  # Approved request IDs
    provisioned_services: list[dict]  # [{service, provision_id}]
    scheduled_tasks: list[dict]  # [{task_id, type}]
    scheduled_deliveries: list[dict]  # [{delivery_id, tracking}]
    
    # Agent coordination
    current_phase: str  # "intake", "risk", "hr", "approvals", "it", "booking", "complete"
    pending_actions: list[str]
    completed_actions: list[str]
    blocking_approvals: list[str]  # Approvals blocking IT provisioning
    
    # Audit trail
    audit_log: Annotated[list[AuditEntry], add]
    
    # Status
    status: str  # "in_progress", "waiting_approval", "completed", "failed"
    error: Optional[str]
    final_report: Optional[dict]


def create_initial_state(
    request_id: str,
    raw_request: str,
    user_sub: str,
    actor_sub: str,
    composite_token: str
) -> OnboardingState:
    """Create initial state for a new onboarding request."""
    return OnboardingState(
        request_id=request_id,
        raw_request=raw_request,
        parsed_request=None,
        user_sub=user_sub,
        actor_sub=actor_sub,
        composite_token=composite_token,
        risk_assessment=None,
        employee_id=None,
        approval_requests=[],
        approvals_received=[],
        provisioned_services=[],
        scheduled_tasks=[],
        scheduled_deliveries=[],
        current_phase="intake",
        pending_actions=[],
        completed_actions=[],
        blocking_approvals=[],
        audit_log=[],
        status="in_progress",
        error=None,
        final_report=None
    )


def add_audit_entry(
    state: OnboardingState,
    agent: str,
    action: str,
    details: dict,
    token_info: dict = None
) -> AuditEntry:
    """Create an audit entry for the state."""
    return AuditEntry(
        timestamp=datetime.utcnow().isoformat(),
        agent=agent,
        action=action,
        details=details,
        token_info=token_info
    )
