"""
IT Tools - Functions for IT provisioning operations.
"""

from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

IT_API_URL = "http://localhost:8000/api/it"


class ProvisionVPNInput(BaseModel):
    """Input for VPN provisioning."""
    employee_id: str = Field(description="Employee ID")
    vpn_profile: str = Field(default="standard", description="VPN profile type")
    approved_by: Optional[str] = Field(default=None, description="Approver email")


class ProvisionGitHubInput(BaseModel):
    """Input for GitHub provisioning."""
    employee_id: str = Field(description="Employee ID")
    organization: str = Field(description="GitHub organization")
    repositories: list[str] = Field(description="List of repository names")
    permission: str = Field(default="write", description="Permission level")
    approved_by: Optional[str] = Field(default=None, description="Approver email")


class ProvisionAWSInput(BaseModel):
    """Input for AWS provisioning."""
    employee_id: str = Field(description="Employee ID")
    account: str = Field(description="AWS account name")
    role: str = Field(default="developer", description="IAM role")
    approved_by: Optional[str] = Field(default=None, description="Approver email")


async def provision_vpn(
    input_data: ProvisionVPNInput,
    token: str
) -> dict:
    """Provision VPN access for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{IT_API_URL}/provision/vpn",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "it_tool_vpn_provisioned",
        provision_id=result.get("provision_id"),
        employee_id=input_data.employee_id
    )
    
    return result


async def provision_github(
    input_data: ProvisionGitHubInput,
    token: str
) -> dict:
    """Provision GitHub Enterprise access for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{IT_API_URL}/provision/github",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "it_tool_github_provisioned",
        provision_id=result.get("provision_id"),
        repositories=input_data.repositories
    )
    
    return result


async def provision_aws(
    input_data: ProvisionAWSInput,
    token: str
) -> dict:
    """Provision AWS environment access for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{IT_API_URL}/provision/aws",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "it_tool_aws_provisioned",
        provision_id=result.get("provision_id"),
        account=input_data.account
    )
    
    return result


async def get_provisions(
    employee_id: str,
    token: str
) -> list[dict]:
    """Get all provisions for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{IT_API_URL}/provisions/{employee_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()
