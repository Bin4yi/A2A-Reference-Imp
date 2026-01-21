"""
Worker Agents - HR, IT, Approval, and Booking agents.
Updated to perform Token Exchange before API calls.
"""

import structlog

from src.graph.state import OnboardingState, add_audit_entry
from src.tools import hr_tools, it_tools, approval_tools, booking_tools
from src.auth.token_broker import get_token_broker

logger = structlog.get_logger()


async def hr_agent(state: OnboardingState) -> OnboardingState:
    """HR Agent - Creates employee profile."""
    parsed = state["parsed_request"]
    if not parsed:
        return state
        
    token = state["composite_token"]
    broker = get_token_broker()
    
    try:
        # Exchange token for HR API specific access (using HR Agent Identity)
        hr_token = await broker.exchange_token_for_agent(
            source_token=token,
            agent_key="hr_agent",
            target_audience="onboarding-api",
            target_scopes=["hr:write"]  # Minimum privilege
        )
        
        input_data = hr_tools.CreateEmployeeInput(
            name=parsed["employee_name"],
            email=parsed["employee_email"],
            role=parsed["role"],
            team=parsed["team"],
            manager_email=parsed["manager_email"],
            start_date=parsed["start_date"]
        )
        
        # Use exchanged token
        result = await hr_tools.create_employee(input_data, hr_token)
        employee_id = result["employee_id"]
        
        audit = add_audit_entry(
            state, "hr-agent", "employee_created",
            {"employee_id": employee_id},
            {"service": "onboarding-api", "scopes": ["hr:write"]}
        )
        
        return {
            **state,
            "employee_id": employee_id,
            "completed_actions": state["completed_actions"] + ["create_employee"],
            "audit_log": [audit]
        }
    except Exception as e:
        logger.error("hr_agent_error", error=str(e))
        return {**state, "status": "failed", "error": f"HR agent failed: {e}"}


async def it_agent(state: OnboardingState) -> OnboardingState:
    """IT Agent - Provisions VPN, GitHub, AWS."""
    parsed = state["parsed_request"]
    employee_id = state["employee_id"]
    if not parsed or not employee_id or state["blocking_approvals"]:
        return state
        
    token = state["composite_token"]
    broker = get_token_broker()
    provisioned = []
    
    try:
        # Exchange token for IT API (using IT Agent Identity)
        it_token = await broker.exchange_token_for_agent(
            source_token=token,
            agent_key="it_agent",
            target_audience="onboarding-api",
            target_scopes=["it:write"]
        )
        
        access = [a.lower() for a in parsed["access_requirements"]]
        
        if "vpn" in access:
            res = await it_tools.provision_vpn(
                it_tools.ProvisionVPNInput(employee_id=employee_id),
                it_token
            )
            provisioned.append({"service": "vpn", "id": res["provision_id"]})
            
        if "github" in access:
            res = await it_tools.provision_github(
                it_tools.ProvisionGitHubInput(
                    employee_id=employee_id,
                    organization="NebulaSoft",
                    repositories=parsed["github_repos"] or ["general"]
                ),
                it_token
            )
            provisioned.append({"service": "github", "id": res["provision_id"]})
            
        if "aws" in access:
            res = await it_tools.provision_aws(
                it_tools.ProvisionAWSInput(employee_id=employee_id, account="dev"),
                it_token
            )
            provisioned.append({"service": "aws", "id": res["provision_id"]})
            
        audit = add_audit_entry(
            state, "it-agent", "accounts_provisioned",
            {"provisioned": provisioned},
            {"service": "onboarding-api", "scopes": ["it:write"]}
        )
        
        return {
            **state,
            "provisioned_services": state["provisioned_services"] + provisioned,
            "completed_actions": state["completed_actions"] + ["provision_it"],
            "audit_log": [audit]
        }
    except Exception as e:
        logger.error("it_agent_error", error=str(e))
        return {**state, "status": "failed", "error": f"IT agent failed: {e}"}


async def approval_agent(state: OnboardingState) -> OnboardingState:
    """Approval Agent - Creates approval requests."""
    risk = state["risk_assessment"]
    parsed = state["parsed_request"]
    if not risk or not parsed:
        return state
        
    token = state["composite_token"]
    broker = get_token_broker()
    ids = []
    
    try:
        # Exchange token for Approval API (using Approval Agent Identity)
        app_token = await broker.exchange_token_for_agent(
            source_token=token,
            agent_key="approval_agent",
            target_audience="onboarding-api",
            target_scopes=["approval:write"]
        )
        
        approver_map = {"technical_lead": parsed["manager_email"]}
        
        for approval in risk["required_approvals"]:
            res = await approval_tools.request_approval(
                approval_tools.CreateApprovalInput(
                    request_type=approval["type"],
                    target_user=parsed["employee_email"],
                    approver_email=approver_map.get(approval["type"], "admin@ns.com"),
                    reason=approval["reason"]
                ),
                app_token
            )
            ids.append(res["request_id"])
            
        audit = add_audit_entry(
            state, "approval-agent", "approvals_requested",
            {"ids": ids},
            {"service": "onboarding-api", "scopes": ["approval:write"]}
        )
        
        return {
            **state,
            "approval_requests": ids,
            "blocking_approvals": ids.copy(),
            "completed_actions": state["completed_actions"] + ["request_approvals"],
            "audit_log": [audit]
        }
    except Exception as e:
        logger.error("approval_agent_error", error=str(e))
        return {**state, "status": "failed", "error": f"Approval failed: {e}"}


async def check_approvals_agent(state: OnboardingState) -> OnboardingState:
    """Check approval status."""
    if not state["approval_requests"]:
        return state
        
    token = state["composite_token"]
    broker = get_token_broker()
    
    try:
        # Use existing approval token logic or exchange again (using Approval Agent Identity)
        app_token = await broker.exchange_token_for_agent(
            source_token=token,
            agent_key="approval_agent",
            target_audience="onboarding-api",
            target_scopes=["approval:read", "approval:write"]
        )
        
        statuses = await approval_tools.check_approval_status(
            state["approval_requests"], app_token
        )
        # Demo: auto-approve
        pending = [rid for rid, s in statuses.items() if s == "pending"]
        for rid in pending:
            await approval_tools.approve_request(rid, app_token)
            
        return {
            **state,
            "approvals_received": state["approval_requests"], # Assuming all approved
            "blocking_approvals": [],
            "status": "waiting_approval" if pending else state["status"]
        }
    except Exception as e:
        return {**state, "status": "failed", "error": f"Check approvals failed: {e}"}


async def booking_agent(state: OnboardingState) -> OnboardingState:
    """Booking Agent - Schedules tasks."""
    parsed = state["parsed_request"]
    employee_id = state["employee_id"]
    if not parsed or not employee_id:
        return state
        
    token = state["composite_token"]
    broker = get_token_broker()
    tasks = []
    
    try:
        # Exchange for Booking API (using Booking Agent Identity)
        book_token = await broker.exchange_token_for_agent(
            source_token=token,
            agent_key="booking_agent",
            target_audience="onboarding-api",
            target_scopes=["booking:write"]
        )
        
        res = await booking_tools.create_task(
            booking_tools.CreateTaskInput(
                employee_id=employee_id,
                task_type="orientation",
                title="Orientation",
                scheduled_date=parsed["start_date"]
            ),
            book_token
        )
        tasks.append({"id": res["task_id"]})
        
        audit = add_audit_entry(
            state, "booking-agent", "tasks_scheduled",
            {"tasks": tasks},
            {"service": "onboarding-api", "scopes": ["booking:write"]}
        )
        
        return {
            **state,
            "scheduled_tasks": tasks,
            "completed_actions": state["completed_actions"] + ["schedule_tasks"],
            "audit_log": [audit]
        }
    except Exception as e:
        logger.error("booking_agent_error", error=str(e))
        return {**state, "status": "failed", "error": f"Booking failed: {e}"}
