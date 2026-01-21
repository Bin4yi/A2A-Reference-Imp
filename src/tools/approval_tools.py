"""
Approval Tools - Functions for approval workflow operations.
"""

from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

APPROVAL_API_URL = "http://localhost:8000/api/approval"


class CreateApprovalInput(BaseModel):
    """Input for creating an approval request."""
    request_type: str = Field(description="Type of approval request")
    target_user: str = Field(description="User the request is for")
    target_resource: Optional[str] = Field(default=None, description="Resource being requested")
    approver_email: str = Field(description="Email of the approver")
    reason: str = Field(description="Reason for the request")
    priority: str = Field(default="normal", description="Priority: normal, high")
    policy_reference: Optional[str] = Field(default=None, description="Policy ID reference")


async def request_approval(
    input_data: CreateApprovalInput,
    token: str
) -> dict:
    """Create an approval request."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{APPROVAL_API_URL}/requests",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "approval_tool_request_created",
        request_id=result.get("request_id"),
        request_type=input_data.request_type,
        approver=input_data.approver_email
    )
    
    return result


async def check_approval_status(
    request_ids: list[str],
    token: str
) -> dict[str, str]:
    """Check status of multiple approval requests."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{APPROVAL_API_URL}/requests/check-status",
            headers={"Authorization": f"Bearer {token}"},
            json=request_ids
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "approval_tool_status_checked",
        request_ids=request_ids,
        statuses=result
    )
    
    return result


async def get_approval_request(
    request_id: str,
    token: str
) -> dict:
    """Get details of an approval request."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{APPROVAL_API_URL}/requests/{request_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()


async def approve_request(
    request_id: str,
    token: str
) -> dict:
    """Approve a pending request."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{APPROVAL_API_URL}/requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info("approval_tool_approved", request_id=request_id)
    
    return result
