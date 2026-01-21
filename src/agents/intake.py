"""
Intake Agent - Parses natural language onboarding requests.
"""

import json
import structlog
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.config import get_settings
from src.graph.state import OnboardingState, ParsedRequest, add_audit_entry

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are an intelligent HR intake assistant for NebulaSoft.
Your job is to parse natural language onboarding requests and extract structured data.

Extract the following information:
- employee_name: Full name of the new employee
- employee_email: Email address
- role: Job title/role
- team: Team name
- manager_email: Manager's email (derive from name if only name given, use format: firstname.lastname@nebulasoft.com)
- start_date: Start date in YYYY-MM-DD format
- access_requirements: List of access needs (vpn, github, aws, jira, etc.)
- github_repos: List of specific GitHub repositories mentioned
- hardware_needs: List of hardware needs (laptop, monitor, etc.)
- delivery_location: Delivery address/city if mentioned

Return ONLY valid JSON, no markdown or explanation. Example:
{
  "employee_name": "John Doe",
  "employee_email": "john.doe@company.com",
  "role": "Software Engineer",
  "team": "Platform Engineering",
  "manager_email": "jane.smith@company.com",
  "start_date": "2026-02-01",
  "access_requirements": ["vpn", "github", "aws"],
  "github_repos": ["identity-server-core"],
  "hardware_needs": ["laptop"],
  "delivery_location": "Colombo"
}
"""


async def intake_agent(state: OnboardingState) -> OnboardingState:
    """
    Parse the natural language onboarding request.
    
    This agent uses GPT-4 to extract structured data from
    the conversational input.
    """
    settings = get_settings()
    
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0,
        api_key=settings.openai_api_key
    )
    
    logger.info(
        "intake_agent_processing",
        request_id=state["request_id"],
        raw_request_length=len(state["raw_request"])
    )
    
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=state["raw_request"])
    ]
    
    # Requires valid OPENAI_API_KEY
    response = await llm.ainvoke(messages)

    
    try:
        # Parse the JSON response
        parsed = json.loads(response.content)
        
        parsed_request = ParsedRequest(
            employee_name=parsed.get("employee_name", ""),
            employee_email=parsed.get("employee_email", ""),
            role=parsed.get("role", ""),
            team=parsed.get("team", ""),
            manager_email=parsed.get("manager_email", ""),
            start_date=parsed.get("start_date", ""),
            access_requirements=parsed.get("access_requirements", []),
            github_repos=parsed.get("github_repos", []),
            hardware_needs=parsed.get("hardware_needs", []),
            delivery_location=parsed.get("delivery_location")
        )
        
        logger.info(
            "intake_agent_parsed",
            employee_name=parsed_request["employee_name"],
            team=parsed_request["team"],
            access_requirements=parsed_request["access_requirements"]
        )
        
        # Create audit entry
        audit = add_audit_entry(
            state,
            agent="intake-agent",
            action="request_parsed",
            details={
                "employee_name": parsed_request["employee_name"],
                "team": parsed_request["team"],
                "access_count": len(parsed_request["access_requirements"])
            }
        )
        
        return {
            **state,
            "parsed_request": parsed_request,
            "current_phase": "risk",
            "audit_log": [audit]
        }
        
    except json.JSONDecodeError as e:
        logger.error("intake_agent_parse_error", error=str(e))
        return {
            **state,
            "status": "failed",
            "error": f"Failed to parse request: {str(e)}"
        }
