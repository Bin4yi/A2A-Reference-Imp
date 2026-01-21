"""
HR Tools - Functions for HR operations.
Used by LangGraph agents to interact with the HR API.
"""

from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# API base URL
HR_API_URL = "http://localhost:8000/api/hr"


class CreateEmployeeInput(BaseModel):
    """Input for create_employee function."""
    name: str = Field(description="Full name of the employee")
    email: str = Field(description="Employee email address")
    role: str = Field(description="Job title/role")
    team: str = Field(description="Team name")
    manager_email: str = Field(description="Manager's email address")
    start_date: str = Field(description="Start date in YYYY-MM-DD format")


async def create_employee(
    input_data: CreateEmployeeInput,
    token: str
) -> dict:
    """
    Create a new employee in the HR system.
    
    Args:
        input_data: Employee details
        token: Delegated access token
        
    Returns:
        Created employee record with employee_id
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{HR_API_URL}/employees",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": input_data.name,
                "email": input_data.email,
                "role": input_data.role,
                "team": input_data.team,
                "manager_email": input_data.manager_email,
                "start_date": input_data.start_date
            }
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "hr_tool_create_employee",
        employee_id=result.get("employee_id"),
        team=input_data.team
    )
    
    return result


async def get_employee(
    employee_id: str,
    token: str
) -> dict:
    """
    Get employee details.
    
    Args:
        employee_id: Employee ID to fetch
        token: Delegated access token
        
    Returns:
        Employee record
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{HR_API_URL}/employees/{employee_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()


async def update_employee_status(
    employee_id: str,
    status: str,
    token: str
) -> dict:
    """
    Update employee status.
    
    Args:
        employee_id: Employee ID
        status: New status
        token: Delegated access token
        
    Returns:
        Updated status
    """
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{HR_API_URL}/employees/{employee_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            params={"status": status}
        )
        response.raise_for_status()
        return response.json()
