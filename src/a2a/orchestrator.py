"""
Orchestrator Executor - Wraps LangGraph workflow in A2A Task Executor.
"""

import uuid
import structlog

from src.a2a.executor import TaskExecutor
from src.a2a.types import Task, TaskStatus, TaskState, Message, TextPart
from src.auth.jwt_validator import TokenClaims
from src.graph.state import create_initial_state
from src.graph.workflow import get_onboarding_graph
from src.config import get_settings

logger = structlog.get_logger()

class OrchestratorExecutor(TaskExecutor):
    """
    Executes onboarding tasks using the LangGraph workflow.
    """
    
    def __init__(self):
        super().__init__("Onboarding Orchestrator")
        self.settings = get_settings()
        
    async def execute(
        self,
        message: Message,
        token: TokenClaims,
        task_id: str,
        session_id: str
    ) -> Task:
        """
        Execute the onboarding workflow.
        """
        # Extract text request from message
        request_text = ""
        for part in message.parts:
            if isinstance(part, TextPart):
                request_text += part.text
        
        logger.info(
            "orchestrator_executing",
            task_id=task_id,
            request_len=len(request_text)
        )
        
        try:
            # Create initial state
            # Use raw_token from TokenClaims if available, otherwise fallback (shouldn't happen with updated validator)
            composite_token = token.raw_token or "demo-token"
            
            initial_state = create_initial_state(
                request_id=task_id, # Use task_id as request_id
                raw_request=request_text,
                user_sub=token.sub,
                actor_sub=self.settings.orchestrator_agent_id,
                composite_token=composite_token
            )
            
            # Run graph
            graph = get_onboarding_graph()
            final_state = await graph.ainvoke(initial_state)
            
            # Format result
            status_msg = self._build_status_message(final_state)
            
            if final_state.get("status") == "failed":
                 state = TaskState.FAILED
            else:
                 state = TaskState.COMPLETED
                 
            # Create response message
            response_msg = Message(
                role="agent",
                parts=[TextPart(text=status_msg)]
            )
            
            # Convert graph state/artifacts to A2A artifacts if needed
            # For now, just return the text response
            
            return Task(
                id=task_id,
                session_id=session_id,
                status=TaskStatus(
                    state=state,
                    message=response_msg
                ),
                history=[message, response_msg],
                artifacts=[final_state.get("final_report", {})],
                metadata={"employee_id": final_state.get("employee_id")}
            )
            
        except Exception as e:
            logger.error("orchestrator_execution_failed", error=str(e))
            raise e

    def _build_status_message(self, state: dict) -> str:
        """Build a human-readable status message."""
        if state.get("status") == "failed":
            return f"Onboarding failed: {state.get('error', 'Unknown error')}"
        
        parts = []
        if state.get("employee_id"):
            parts.append(f"Employee created: {state['employee_id']}")
        if state.get("provisioned_services"):
            services = [s["service"] for s in state["provisioned_services"]]
            parts.append(f"Provisioned: {', '.join(services)}")
        if state.get("scheduled_tasks"):
            parts.append(f"Scheduled {len(state['scheduled_tasks'])} tasks")
        if state.get("approval_requests"):
            parts.append(f"Created {len(state['approval_requests'])} approval requests")
        
        return " | ".join(parts) if parts else "Processing complete"
