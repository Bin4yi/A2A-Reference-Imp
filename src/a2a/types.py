"""
A2A Protocol Types - Following the official A2A specification.
Includes Agent Card, JSON-RPC, Task, and Executor patterns.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any, Callable, Awaitable
from uuid import uuid4


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class TaskState(str, Enum):
    """Task execution states."""
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class PartKind(str, Enum):
    """Message part types."""
    TEXT = "text"
    DATA = "data"
    FILE = "file"


# ─────────────────────────────────────────────────────────────────
# Agent Card (Discovery)
# ─────────────────────────────────────────────────────────────────

@dataclass
class Skill:
    """A capability that an agent exposes."""
    id: str
    name: str
    description: str
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    
    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description
        }
        if self.input_schema:
            result["inputSchema"] = self.input_schema
        if self.output_schema:
            result["outputSchema"] = self.output_schema
        return result


@dataclass
class AuthenticationInfo:
    """Authentication requirements for an agent."""
    schemes: list[str] = field(default_factory=lambda: ["bearer"])
    required_scopes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "schemes": self.schemes,
            "requiredScopes": self.required_scopes
        }


@dataclass
class Capabilities:
    """Agent capabilities flags."""
    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    
    def to_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "stateTransitionHistory": self.state_transition_history
        }


@dataclass
class AgentCard:
    """
    Agent Card - The digital identity of an A2A agent.
    Hosted at /.well-known/agent.json (per A2A spec)
    """
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    skills: list[Skill] = field(default_factory=list)
    capabilities: Capabilities = field(default_factory=Capabilities)
    authentication: AuthenticationInfo = field(default_factory=AuthenticationInfo)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict (A2A spec format)."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "skills": [s.to_dict() for s in self.skills],
            "capabilities": self.capabilities.to_dict(),
            "authentication": self.authentication.to_dict(),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes
        }


# ─────────────────────────────────────────────────────────────────
# Message Parts
# ─────────────────────────────────────────────────────────────────

@dataclass
class TextPart:
    """Text content in a message."""
    text: str
    kind: str = "text"
    
    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text}


@dataclass
class DataPart:
    """Structured data in a message."""
    data: dict
    kind: str = "data"
    
    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": self.data}


@dataclass
class FilePart:
    """File content in a message."""
    file_uri: str
    mime_type: str
    kind: str = "file"
    
    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "fileUri": self.file_uri,
            "mimeType": self.mime_type
        }


Part = TextPart | DataPart | FilePart


# ─────────────────────────────────────────────────────────────────
# Message
# ─────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """A2A Protocol Message."""
    role: str  # "user" or "agent"
    parts: list[Part]
    message_id: str = field(default_factory=lambda: f"msg-{uuid4().hex[:8]}")
    
    def to_dict(self) -> dict:
        return {
            "messageId": self.message_id,
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        parts = []
        for p in data.get("parts", []):
            if p.get("kind") == "text":
                parts.append(TextPart(text=p.get("text", "")))
            elif p.get("kind") == "data":
                parts.append(DataPart(data=p.get("data", {})))
            elif p.get("kind") == "file":
                parts.append(FilePart(
                    file_uri=p.get("fileUri", ""),
                    mime_type=p.get("mimeType", "")
                ))
        return cls(
            message_id=data.get("messageId", f"msg-{uuid4().hex[:8]}"),
            role=data.get("role", "user"),
            parts=parts
        )


# ─────────────────────────────────────────────────────────────────
# Task (Core A2A concept)
# ─────────────────────────────────────────────────────────────────

@dataclass
class TaskStatus:
    """Current status of a task."""
    state: TaskState
    message: Optional[Message] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> dict:
        result = {
            "state": self.state.value,
            "timestamp": self.timestamp
        }
        if self.message:
            result["message"] = self.message.to_dict()
        return result


@dataclass
class Task:
    """
    A2A Task - Represents a unit of work.
    Tasks are created via tasks/send and tracked via tasks/get.
    """
    id: str
    session_id: str
    status: TaskStatus
    history: list[Message] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "status": self.status.to_dict(),
            "history": [m.to_dict() for m in self.history],
            "artifacts": self.artifacts,
            "metadata": self.metadata
        }


@dataclass
class TaskSendParams:
    """Parameters for tasks/send RPC method."""
    id: str
    session_id: str
    message: Message
    accept_modes: list[str] = field(default_factory=lambda: ["text"])
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "message": self.message.to_dict(),
            "acceptModes": self.accept_modes
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskSendParams":
        return cls(
            id=data.get("id", f"task-{uuid4().hex[:8]}"),
            session_id=data.get("sessionId", f"session-{uuid4().hex[:8]}"),
            message=Message.from_dict(data.get("message", {})),
            accept_modes=data.get("acceptModes", ["text"])
        )


# ─────────────────────────────────────────────────────────────────
# JSON-RPC
# ─────────────────────────────────────────────────────────────────

@dataclass
class JsonRpcRequest:
    """JSON-RPC 2.0 Request."""
    method: str
    params: dict
    id: str = field(default_factory=lambda: f"req-{uuid4().hex[:8]}")
    jsonrpc: str = "2.0"
    
    def to_dict(self) -> dict:
        return {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
            "params": self.params
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "JsonRpcRequest":
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id", f"req-{uuid4().hex[:8]}"),
            method=data.get("method", ""),
            params=data.get("params", {})
        )


@dataclass
class JsonRpcError:
    """JSON-RPC 2.0 Error."""
    code: int
    message: str
    data: Optional[Any] = None
    
    def to_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass
class JsonRpcResponse:
    """JSON-RPC 2.0 Response."""
    id: str
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None
    jsonrpc: str = "2.0"
    
    def to_dict(self) -> dict:
        response = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            response["error"] = self.error.to_dict()
        else:
            response["result"] = self.result
        return response


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# A2A-specific error codes
TASK_NOT_FOUND = -32000
UNAUTHORIZED = -32001
SCOPE_INSUFFICIENT = -32002
