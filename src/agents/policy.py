"""
Policy Engine - Risk assessment and approval routing.
"""

import structlog
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import get_settings
from src.graph.state import OnboardingState, RiskAssessment, add_audit_entry

logger = structlog.get_logger()

# Security policies
POLICIES = {
    "SP-2025-08": {
        "name": "Core Repository Access",
        "description": "GitHub core repository access requires Technical Lead approval",
        "trigger": "github_core_repo"
    },
    "SP-2025-12": {
        "name": "VPN + AWS Combination",
        "description": "VPN + AWS combination requires Security Team approval",
        "trigger": "vpn_aws_combo"
    },
    "PR-2025-03": {
        "name": "Hardware Procurement",
        "description": "Laptop procurement >$2000 requires Finance approval",
        "trigger": "laptop_procurement"
    }
}


async def policy_engine(state: OnboardingState) -> OnboardingState:
    """
    Analyze the request and determine risk level and required approvals.
    
    This agent evaluates:
    - Risk factors based on access combinations
    - Required approvals based on security policies
    - Compliance flags for audit
    """
    parsed = state["parsed_request"]
    if not parsed:
        return {**state, "status": "failed", "error": "No parsed request"}
    
    access = [a.lower() for a in parsed["access_requirements"]]
    repos = [r.lower() for r in parsed["github_repos"]]
    hardware = [h.lower() for h in parsed["hardware_needs"]]
    
    risk_factors = []
    required_approvals = []
    compliance_flags = []
    
    # Check VPN access
    if "vpn" in access:
        risk_factors.append("VPN access requested")
    
    # Check core repository access
    core_repos = ["identity-server-core", "core-platform", "auth-service"]
    has_core_repo = any(repo in repos for repo in core_repos)
    if has_core_repo or any("core" in r for r in repos):
        risk_factors.append("Core repository access requested")
        required_approvals.append({
            "type": "technical_lead",
            "approver_role": "Tech Lead",
            "reason": "GitHub core repository access per Security Policy SP-2025-08",
            "policy": "SP-2025-08"
        })
    
    # Check VPN + AWS combination
    if "vpn" in access and "aws" in access:
        risk_factors.append("VPN + AWS combination (high risk)")
        required_approvals.append({
            "type": "security_team",
            "approver_role": "Security Team Lead",
            "reason": "VPN + AWS dev environment per Security Policy SP-2025-12",
            "policy": "SP-2025-12"
        })
    
    # Check laptop procurement
    if "laptop" in hardware:
        risk_factors.append("Laptop procurement required")
        required_approvals.append({
            "type": "finance",
            "approver_role": "Finance Manager",
            "reason": "Laptop procurement per Procurement Policy PR-2025-03",
            "policy": "PR-2025-03"
        })
    
    # Check AWS access (without VPN already checked)
    if "aws" in access and "vpn" not in access:
        risk_factors.append("AWS environment access")
    
    # Determine risk level
    if len(risk_factors) >= 3:
        risk_level = "HIGH"
    elif len(risk_factors) >= 2:
        risk_level = "ELEVATED"
    else:
        risk_level = "STANDARD"
    
    # Add compliance flags
    if "aws" in access:
        compliance_flags.append("cloud_access")
    if has_core_repo:
        compliance_flags.append("pci_dss_scope_access")
    
    risk_assessment = RiskAssessment(
        risk_level=risk_level,
        risk_factors=risk_factors,
        required_approvals=required_approvals,
        compliance_flags=compliance_flags
    )
    
    logger.info(
        "policy_engine_assessment",
        request_id=state["request_id"],
        risk_level=risk_level,
        risk_factor_count=len(risk_factors),
        approval_count=len(required_approvals)
    )
    
    audit = add_audit_entry(
        state,
        agent="policy-engine",
        action="risk_assessed",
        details={
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "approvals_required": len(required_approvals)
        }
    )
    
    return {
        **state,
        "risk_assessment": risk_assessment,
        "current_phase": "hr",
        "audit_log": [audit]
    }
