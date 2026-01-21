"""
Booking Tools - Functions for task and delivery scheduling.
"""

from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

BOOKING_API_URL = "http://localhost:8000/api/booking"


class CreateTaskInput(BaseModel):
    """Input for creating an onboarding task."""
    employee_id: str = Field(description="Employee ID")
    task_type: str = Field(description="Type: hr_orientation, security_training, etc.")
    title: str = Field(description="Task title")
    scheduled_date: str = Field(description="Date in YYYY-MM-DD format")
    duration_hours: float = Field(default=2.0, description="Duration in hours")
    description: Optional[str] = Field(default=None, description="Task description")


class ScheduleDeliveryInput(BaseModel):
    """Input for scheduling a delivery."""
    employee_id: str = Field(description="Employee ID")
    item_type: str = Field(description="Type: laptop, equipment, etc.")
    item_description: str = Field(description="Description of the item")
    delivery_address: str = Field(description="Delivery address")
    delivery_date: str = Field(description="Date in YYYY-MM-DD format")
    approved_by: Optional[str] = Field(default=None, description="Approver email")


async def create_task(
    input_data: CreateTaskInput,
    token: str
) -> dict:
    """Create an onboarding task."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOOKING_API_URL}/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "booking_tool_task_created",
        task_id=result.get("task_id"),
        task_type=input_data.task_type
    )
    
    return result


async def schedule_delivery(
    input_data: ScheduleDeliveryInput,
    token: str
) -> dict:
    """Schedule a delivery (e.g., laptop)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOOKING_API_URL}/deliveries",
            headers={"Authorization": f"Bearer {token}"},
            json=input_data.model_dump()
        )
        response.raise_for_status()
        result = response.json()
    
    logger.info(
        "booking_tool_delivery_scheduled",
        delivery_id=result.get("delivery_id"),
        tracking_number=result.get("tracking_number")
    )
    
    return result


async def get_tasks(
    employee_id: str,
    token: str
) -> list[dict]:
    """Get all tasks for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BOOKING_API_URL}/tasks",
            headers={"Authorization": f"Bearer {token}"},
            params={"employee_id": employee_id}
        )
        response.raise_for_status()
        return response.json()


async def get_deliveries(
    employee_id: str,
    token: str
) -> list[dict]:
    """Get all deliveries for an employee."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BOOKING_API_URL}/deliveries",
            headers={"Authorization": f"Bearer {token}"},
            params={"employee_id": employee_id}
        )
        response.raise_for_status()
        return response.json()
