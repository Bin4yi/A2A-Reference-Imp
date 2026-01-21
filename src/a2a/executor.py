"""
A2A Executor - Handles task execution for A2A agents.
Each agent has an executor that processes incoming tasks.
"""

import structlog
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional, Any
from uuid import uuid4

from src.a2a.types import (
    Task, TaskStatus, TaskState,
    Message, TextPart, DataPart,
    TaskSendParams
)
from src.auth.jwt_validator import TokenClaims

logger = structlog.get_logger()


class TaskExecutor(ABC):
    """
    Abstract base class for A2A task executors.
    Each agent implements its own executor.
    """
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._tasks: dict[str, Task] = {}
    
    @abstractmethod
    async def execute(
        self,
        message: Message,
        token: TokenClaims,
        task_id: str,
        session_id: str
    ) -> Task:
        """
        Execute a task based on the incoming message.
        
        Args:
            message: The incoming message with user request
            token: Validated JWT claims
            task_id: Unique task identifier
            session_id: Session for conversation context
            
        Returns:
            Updated Task with result
        """
        pass
    
    async def handle_task_send(
        self,
        params: TaskSendParams,
        token: TokenClaims
    ) -> Task:
        """
        Handle tasks/send RPC method.
        Creates or continues a task.
        """
        # Check if task exists (continuation)
        existing_task = self._tasks.get(params.id)
        
        if existing_task:
            # Add message to history
            existing_task.history.append(params.message)
            existing_task.status = TaskStatus(
                state=TaskState.WORKING,
                message=None
            )
        else:
            # Create new task
            existing_task = Task(
                id=params.id,
                session_id=params.session_id,
                status=TaskStatus(state=TaskState.SUBMITTED),
                history=[params.message]
            )
            self._tasks[params.id] = existing_task
        
        logger.info(
            "task_received",
            agent=self.agent_name,
            task_id=params.id,
            session_id=params.session_id
        )
        
        try:
            # Execute the task
            result_task = await self.execute(
                message=params.message,
                token=token,
                task_id=params.id,
                session_id=params.session_id
            )
            
            # Update stored task
            self._tasks[params.id] = result_task
            
            logger.info(
                "task_completed",
                agent=self.agent_name,
                task_id=params.id,
                state=result_task.status.state.value
            )
            
            return result_task
            
        except Exception as e:
            logger.error(
                "task_failed",
                agent=self.agent_name,
                task_id=params.id,
                error=str(e)
            )
            
            # Update task with error
            existing_task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Error: {str(e)}")]
                )
            )
            self._tasks[params.id] = existing_task
            return existing_task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus(state=TaskState.CANCELED)
        return task


class SimpleExecutor(TaskExecutor):
    """
    Simple executor that routes to handler functions.
    Used for agents that don't need complex execution logic.
    """
    
    def __init__(
        self,
        agent_name: str,
        handler: Callable[[str, TokenClaims], Awaitable[str]]
    ):
        super().__init__(agent_name)
        self._handler = handler
    
    async def execute(
        self,
        message: Message,
        token: TokenClaims,
        task_id: str,
        session_id: str
    ) -> Task:
        """Execute by calling the handler function."""
        # Extract text from message
        text_content = ""
        for part in message.parts:
            if isinstance(part, TextPart):
                text_content += part.text
        
        # Call handler
        result_text = await self._handler(text_content, token)
        
        # Build response message
        response_message = Message(
            role="agent",
            parts=[TextPart(text=result_text)]
        )
        
        # Return completed task
        return Task(
            id=task_id,
            session_id=session_id,
            status=TaskStatus(
                state=TaskState.COMPLETED,
                message=response_message
            ),
            history=[message, response_message]
        )


class DataExecutor(TaskExecutor):
    """
    Executor that handles structured data input/output.
    Used for agents that process JSON data.
    """
    
    def __init__(
        self,
        agent_name: str,
        handler: Callable[[dict, TokenClaims], Awaitable[dict]]
    ):
        super().__init__(agent_name)
        self._handler = handler
    
    async def execute(
        self,
        message: Message,
        token: TokenClaims,
        task_id: str,
        session_id: str
    ) -> Task:
        """Execute by calling the handler with structured data."""
        # Extract data from message
        input_data = {}
        for part in message.parts:
            if isinstance(part, DataPart):
                input_data.update(part.data)
            elif isinstance(part, TextPart):
                input_data["text"] = part.text
        
        # Call handler
        result_data = await self._handler(input_data, token)
        
        # Build response message
        response_message = Message(
            role="agent",
            parts=[DataPart(data=result_data)]
        )
        
        # Return completed task
        return Task(
            id=task_id,
            session_id=session_id,
            status=TaskStatus(
                state=TaskState.COMPLETED,
                message=response_message
            ),
            history=[message, response_message],
            artifacts=[result_data] if result_data else []
        )
