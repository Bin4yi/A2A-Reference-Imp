"""
A2A Client - For discovering and communicating with A2A agents.
Implements runtime discovery and task-based communication.
"""

import asyncio
from typing import Optional
from uuid import uuid4

import httpx
import structlog

from src.a2a.types import (
    AgentCard,
    Skill,
    Capabilities,
    AuthenticationInfo,
    JsonRpcRequest,
    JsonRpcResponse,
    Task,
    TaskSendParams,
    Message,
    TextPart,
    DataPart,
    TaskState
)

logger = structlog.get_logger()


class DiscoveredAgent:
    """Represents a discovered A2A agent."""
    
    def __init__(self, agent_card: AgentCard):
        self.card = agent_card
        self.url = agent_card.url
        self.name = agent_card.name
        self.skills = {s.id: s for s in agent_card.skills}
        self.last_seen = None
        self.healthy = True
    
    def has_skill(self, skill_id: str) -> bool:
        """Check if agent has a specific skill."""
        return skill_id in self.skills
    
    def get_skill_names(self) -> list[str]:
        """Get list of skill names."""
        return [s.name for s in self.skills.values()]


class A2AClient:
    """
    A2A Protocol Client.
    
    Features:
    - Runtime agent discovery
    - Task-based communication
    - Automatic retry and health checking
    """
    
    def __init__(self, discovery_urls: list[str] = None):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._discovered_agents: dict[str, DiscoveredAgent] = {}
        self._discovery_urls = discovery_urls or []
        self._discovery_task: Optional[asyncio.Task] = None
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    async def close(self):
        """Close the HTTP client."""
        if self._discovery_task:
            self._discovery_task.cancel()
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    # ─────────────────────────────────────────────────────────────────
    # Discovery
    # ─────────────────────────────────────────────────────────────────
    
    async def discover_agent(self, agent_url: str) -> Optional[DiscoveredAgent]:
        """
        Discover an agent by fetching its Agent Card.
        
        Args:
            agent_url: Base URL of the agent (e.g., http://localhost:8001)
            
        Returns:
            DiscoveredAgent if successful, None otherwise
        """
        # Try both endpoints (new and legacy)
        for endpoint in ["/.well-known/agent.json", "/.well-known/agent-card.json"]:
            try:
                url = f"{agent_url.rstrip('/')}{endpoint}"
                logger.debug("discovering_agent", url=url)
                
                response = await self.http_client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    agent_card = self._parse_agent_card(data, agent_url)
                    discovered = DiscoveredAgent(agent_card)
                    
                    self._discovered_agents[agent_url] = discovered
                    
                    logger.info(
                        "agent_discovered",
                        name=discovered.name,
                        url=agent_url,
                        skills=discovered.get_skill_names()
                    )
                    
                    return discovered
                    
            except Exception as e:
                logger.debug("discovery_failed", url=url, error=str(e))
                continue
        
        logger.warning("agent_not_found", url=agent_url)
        return None
    
    def _parse_agent_card(self, data: dict, fallback_url: str) -> AgentCard:
        """Parse Agent Card from JSON response."""
        skills = [
            Skill(
                id=s.get("id", ""),
                name=s.get("name", ""),
                description=s.get("description", ""),
                input_schema=s.get("inputSchema"),
                output_schema=s.get("outputSchema")
            )
            for s in data.get("skills", [])
        ]
        
        caps = data.get("capabilities", {})
        auth = data.get("authentication", {})
        
        return AgentCard(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            url=data.get("url", fallback_url),
            version=data.get("version", "1.0.0"),
            skills=skills,
            capabilities=Capabilities(
                streaming=caps.get("streaming", False),
                push_notifications=caps.get("pushNotifications", False),
                state_transition_history=caps.get("stateTransitionHistory", False)
            ),
            authentication=AuthenticationInfo(
                schemes=auth.get("schemes", ["bearer"]),
                required_scopes=auth.get("requiredScopes", [])
            )
        )
    
    async def discover_all(self, agent_urls: list[str] = None) -> list[DiscoveredAgent]:
        """
        Discover all agents from the given URLs.
        
        Args:
            agent_urls: List of agent URLs to discover (uses config if not provided)
            
        Returns:
            List of successfully discovered agents
        """
        urls = agent_urls or self._discovery_urls
        discovered = []
        
        for url in urls:
            agent = await self.discover_agent(url)
            if agent:
                discovered.append(agent)
        
        logger.info(
            "discovery_complete",
            total=len(urls),
            successful=len(discovered),
            agents=[a.name for a in discovered]
        )
        
        return discovered
    
    async def start_background_discovery(
        self,
        agent_urls: list[str],
        interval_seconds: int = 30
    ):
        """
        Start background discovery loop.
        Periodically checks for new agents and health of existing ones.
        """
        self._discovery_urls = agent_urls
        
        async def discovery_loop():
            while True:
                try:
                    await self.discover_all(agent_urls)
                except Exception as e:
                    logger.error("background_discovery_error", error=str(e))
                await asyncio.sleep(interval_seconds)
        
        self._discovery_task = asyncio.create_task(discovery_loop())
        logger.info("background_discovery_started", interval=interval_seconds)
    
    # ─────────────────────────────────────────────────────────────────
    # Agent Lookup
    # ─────────────────────────────────────────────────────────────────
    
    def get_agent(self, url: str) -> Optional[DiscoveredAgent]:
        """Get a discovered agent by URL."""
        return self._discovered_agents.get(url)
    
    def get_agent_by_name(self, name: str) -> Optional[DiscoveredAgent]:
        """Get a discovered agent by name."""
        for agent in self._discovered_agents.values():
            if agent.name.lower() == name.lower():
                return agent
        return None
    
    def get_agent_with_skill(self, skill_id: str) -> Optional[DiscoveredAgent]:
        """Find an agent that has a specific skill."""
        for agent in self._discovered_agents.values():
            if agent.has_skill(skill_id):
                return agent
        return None
    
    def list_agents(self) -> list[dict]:
        """Get simplified list of all discovered agents."""
        return [
            {
                "name": agent.name,
                "url": agent.url,
                "description": agent.card.description,
                "skills": agent.get_skill_names(),
                "healthy": agent.healthy
            }
            for agent in self._discovered_agents.values()
        ]
    
    # ─────────────────────────────────────────────────────────────────
    # Task Communication
    # ─────────────────────────────────────────────────────────────────
    
    async def send_task(
        self,
        agent_url: str,
        message: str | dict,
        access_token: str,
        task_id: str = None,
        session_id: str = None
    ) -> Task:
        """
        Send a task to an agent using A2A protocol.
        
        Args:
            agent_url: Base URL of the target agent
            message: Message content (text or structured data)
            access_token: Delegated access token
            task_id: Optional task ID (generated if not provided)
            session_id: Optional session ID (generated if not provided)
            
        Returns:
            Task with execution result
        """
        task_id = task_id or f"task-{uuid4().hex[:8]}"
        session_id = session_id or f"session-{uuid4().hex[:8]}"
        
        # Build message parts
        if isinstance(message, str):
            parts = [TextPart(text=message)]
        else:
            parts = [DataPart(data=message)]
        
        # Build task send params
        params = TaskSendParams(
            id=task_id,
            session_id=session_id,
            message=Message(role="user", parts=parts)
        )
        
        # Build JSON-RPC request
        rpc_request = JsonRpcRequest(
            method="tasks/send",
            params=params.to_dict()
        )
        
        logger.info(
            "sending_task",
            agent_url=agent_url,
            task_id=task_id,
            session_id=session_id
        )
        
        # Send request
        response = await self.http_client.post(
            agent_url,
            json=rpc_request.to_dict(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
        )
        
        result = response.json()
        
        # Check for error
        if "error" in result and result["error"]:
            error = result["error"]
            raise Exception(f"A2A Error [{error.get('code')}]: {error.get('message')}")
        
        # Parse task result
        task_data = result.get("result", {})
        
        logger.info(
            "task_response_received",
            task_id=task_id,
            state=task_data.get("status", {}).get("state")
        )
        
        return self._parse_task(task_data)
    
    def _parse_task(self, data: dict) -> Task:
        """Parse Task from response."""
        from src.a2a.types import TaskStatus, TaskState
        
        status_data = data.get("status", {})
        status_message = None
        
        if status_data.get("message"):
            status_message = Message.from_dict(status_data["message"])
        
        return Task(
            id=data.get("id", ""),
            session_id=data.get("sessionId", ""),
            status=TaskStatus(
                state=TaskState(status_data.get("state", "completed")),
                message=status_message,
                timestamp=status_data.get("timestamp", "")
            ),
            history=[Message.from_dict(m) for m in data.get("history", [])],
            artifacts=data.get("artifacts", []),
            metadata=data.get("metadata", {})
        )
    
    async def get_task_result_text(self, task: Task) -> str:
        """Extract text result from a completed task."""
        if task.status.message:
            for part in task.status.message.parts:
                if isinstance(part, TextPart):
                    return part.text
        return ""
    
    async def get_task_result_data(self, task: Task) -> dict:
        """Extract data result from a completed task."""
        if task.status.message:
            for part in task.status.message.parts:
                if isinstance(part, DataPart):
                    return part.data
        return {}


# Singleton instance
_a2a_client: Optional[A2AClient] = None


def get_a2a_client() -> A2AClient:
    """Get or create the A2A client singleton."""
    global _a2a_client
    if _a2a_client is None:
        _a2a_client = A2AClient()
    return _a2a_client
