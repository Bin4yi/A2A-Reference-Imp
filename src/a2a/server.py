"""
A2A Server - FastAPI-based A2A agent server.
Implements the full A2A protocol with Agent Card and JSON-RPC.
"""

import structlog
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from src.a2a.types import (
    AgentCard,
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcError,
    TaskSendParams,
    Task,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
    INTERNAL_ERROR,
    UNAUTHORIZED,
    TASK_NOT_FOUND
)
from src.a2a.executor import TaskExecutor
from src.auth.jwt_validator import get_jwt_validator, TokenClaims

logger = structlog.get_logger()


class A2AServer:
    """
    A2A Protocol Server.
    
    Implements:
    - GET /.well-known/agent.json - Agent Card discovery
    - POST / - JSON-RPC endpoint for tasks/send, tasks/get, etc.
    """
    
    def __init__(self, agent_card: AgentCard, executor: TaskExecutor):
        self.agent_card = agent_card
        self.executor = executor
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Set up A2A protocol routes."""
        
        @self.router.get("/.well-known/agent.json")
        async def get_agent_card():
            """
            Agent Card endpoint (A2A discovery).
            Returns the agent's capabilities and authentication requirements.
            """
            return JSONResponse(content=self.agent_card.to_dict())
        
        # Also support the older path
        @self.router.get("/.well-known/agent-card.json")
        async def get_agent_card_legacy():
            """Legacy Agent Card endpoint."""
            return JSONResponse(content=self.agent_card.to_dict())
        
        @self.router.post("/")
        async def handle_jsonrpc(request: Request):
            """
            JSON-RPC endpoint for A2A protocol.
            
            Supported methods:
            - tasks/send: Send a message to create/continue a task
            - tasks/get: Get task status and history
            - tasks/cancel: Cancel a running task
            """
            return await self._handle_rpc(request)
    
    async def _handle_rpc(self, request: Request) -> JSONResponse:
        """Process JSON-RPC request."""
        request_id = "unknown"
        
        try:
            # Parse request body
            try:
                body = await request.json()
            except Exception as e:
                return self._error_response(
                    "unknown",
                    JsonRpcError(code=PARSE_ERROR, message=f"Invalid JSON: {str(e)}")
                )
            
            rpc_request = JsonRpcRequest.from_dict(body)
            request_id = rpc_request.id
            
            logger.info(
                "a2a_rpc_received",
                agent=self.agent_card.name,
                method=rpc_request.method,
                request_id=request_id
            )
            
            # Validate token
            token = await self._validate_token(request)
            if isinstance(token, JsonRpcError):
                return self._error_response(request_id, token)
            
            # Route to method handler
            if rpc_request.method == "tasks/send":
                return await self._handle_tasks_send(request_id, rpc_request.params, token)
            elif rpc_request.method == "tasks/get":
                return await self._handle_tasks_get(request_id, rpc_request.params, token)
            elif rpc_request.method == "tasks/cancel":
                return await self._handle_tasks_cancel(request_id, rpc_request.params, token)
            else:
                return self._error_response(
                    request_id,
                    JsonRpcError(code=METHOD_NOT_FOUND, message=f"Unknown method: {rpc_request.method}")
                )
                
        except Exception as e:
            logger.error("a2a_rpc_error", request_id=request_id, error=str(e))
            return self._error_response(
                request_id,
                JsonRpcError(code=INTERNAL_ERROR, message=str(e))
            )
    
    async def _validate_token(self, request: Request) -> TokenClaims | JsonRpcError:
        """Validate the Authorization header."""
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            return JsonRpcError(
                code=UNAUTHORIZED,
                message="Missing or invalid Authorization header"
            )
        
        token_str = auth_header[7:]  # Remove "Bearer "
        
        try:
            validator = get_jwt_validator()
            return await validator.validate(token_str)
        except Exception as e:
            return JsonRpcError(
                code=UNAUTHORIZED,
                message=f"Token validation failed: {str(e)}"
            )
    
    async def _handle_tasks_send(
        self,
        request_id: str,
        params: dict,
        token: TokenClaims
    ) -> JSONResponse:
        """Handle tasks/send method."""
        try:
            task_params = TaskSendParams.from_dict(params)
        except Exception as e:
            return self._error_response(
                request_id,
                JsonRpcError(code=PARSE_ERROR, message=f"Invalid params: {str(e)}")
            )
        
        # Execute task
        task = await self.executor.handle_task_send(task_params, token)
        
        return self._success_response(request_id, task.to_dict())
    
    async def _handle_tasks_get(
        self,
        request_id: str,
        params: dict,
        token: TokenClaims
    ) -> JSONResponse:
        """Handle tasks/get method."""
        task_id = params.get("id")
        if not task_id:
            return self._error_response(
                request_id,
                JsonRpcError(code=PARSE_ERROR, message="Missing task id")
            )
        
        task = self.executor.get_task(task_id)
        if not task:
            return self._error_response(
                request_id,
                JsonRpcError(code=TASK_NOT_FOUND, message=f"Task not found: {task_id}")
            )
        
        return self._success_response(request_id, task.to_dict())
    
    async def _handle_tasks_cancel(
        self,
        request_id: str,
        params: dict,
        token: TokenClaims
    ) -> JSONResponse:
        """Handle tasks/cancel method."""
        task_id = params.get("id")
        if not task_id:
            return self._error_response(
                request_id,
                JsonRpcError(code=PARSE_ERROR, message="Missing task id")
            )
        
        task = self.executor.cancel_task(task_id)
        if not task:
            return self._error_response(
                request_id,
                JsonRpcError(code=TASK_NOT_FOUND, message=f"Task not found: {task_id}")
            )
        
        return self._success_response(request_id, task.to_dict())
    
    def _success_response(self, request_id: str, result: dict) -> JSONResponse:
        """Build success response."""
        response = JsonRpcResponse(id=request_id, result=result)
        return JSONResponse(content=response.to_dict())
    
    def _error_response(self, request_id: str, error: JsonRpcError) -> JSONResponse:
        """Build error response."""
        response = JsonRpcResponse(id=request_id, error=error)
        # 200 status for JSON-RPC errors (per spec)
        return JSONResponse(content=response.to_dict())
