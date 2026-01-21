"""
Token Broker for centralized token management.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import structlog

from src.auth.asgardeo import (
    AsgardeoClient,
    TokenResponse,
    ActorToken,
    PKCEChallenge,
    generate_pkce,
    get_asgardeo_client
)
from src.config_loader import load_yaml_config
from src.config import get_settings

logger = structlog.get_logger()

@dataclass
class UserSession:
    """User session with OAuth state."""
    session_id: str
    user_sub: Optional[str] = None
    pkce: Optional[PKCEChallenge] = None
    delegated_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class AuditEntry:
    timestamp: datetime
    operation: str
    user_sub: Optional[str]
    actor_sub: str
    target_service: str
    scopes: list[str]
    success: bool = True
    error: Optional[str] = None

class TokenBroker:
    """
    Centralized token broker.
    """
    
    def __init__(self, asgardeo: AsgardeoClient = None):
        self.settings = get_settings()
        self.asgardeo = asgardeo or get_asgardeo_client()
        self._actor_token: Optional[ActorToken] = None
        self._sessions: dict[str, UserSession] = {}
        self._audit_log: list[AuditEntry] = []
        
        # Load agent configs for identity lookup
        self.app_config = load_yaml_config()
        self.agents_config = self.app_config.get("agents", {})

    async def initialize(self):
        """Initialize the token broker by getting the orchestrator's actor token."""
        try:
            print(f"\n[TOKEN BROKER] Initializing orchestrator actor token...")
            self._actor_token = await self.asgardeo.get_actor_token()
            print(f"[TOKEN BROKER] Actor token obtained: {self._actor_token.token[:50]}...")
            logger.info("token_broker_initialized", actor_id=self._actor_token.actor_id)
        except Exception as e:
            logger.error("broker_init_error", error=str(e))
            print(f"[TOKEN BROKER ERROR] Failed to initialize: {e}")
            raise  # Re-raise so caller knows initialization failed

    def create_session(self) -> UserSession:
        session_id = str(uuid.uuid4())
        pkce = generate_pkce()
        session = UserSession(session_id=session_id, pkce=pkce)
        self._sessions[session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[UserSession]:
        return self._sessions.get(session_id)
        
    def get_authorization_url(self, session_id: str, scopes: list[str]) -> str:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return self.asgardeo.build_user_authorize_url(scopes, session_id, session.pkce)

    async def handle_callback(self, code: str, state: str) -> UserSession:
        """
        Handle OAuth callback - exchange code for delegated token.
        Requires actor token to prove the orchestrator agent's identity.
        """
        session = self._sessions.get(state)
        if not session:
            raise ValueError(f"Session not found: {state}")
        
        print(f"\n[HANDLE CALLBACK]")
        print(f"  Code: {code[:30]}...")
        print(f"  State: {state}")

        # First, get the orchestrator's actor token (using 3-step flow)
        if not self._actor_token:
            print(f"\n[GETTING ORCHESTRATOR ACTOR TOKEN...]")
            await self.initialize()
        
        if not self._actor_token:
            raise ValueError("Failed to obtain orchestrator actor token")
        
        print(f"\n[ORCHESTRATOR_ACTOR_TOKEN]:")
        print(f"  {self._actor_token.token}")

        # Exchange code for delegated token (with actor token)
        token_response = await self.asgardeo.exchange_code_for_delegated_token(
            code, session.pkce.verifier, self._actor_token.token
        )
        
        print(f"\n[USER_DELEGATED_TOKEN]:")
        print(f"  {token_response.access_token}")
        print(f"  Scope: {token_response.scope}")

        
        session.delegated_token = token_response.access_token
        session.token_expires_at = token_response.expires_at
        
        self._log_audit(
            operation="delegated_token_obtained",
            user_sub="user",
            target_service="orchestrator",
            scopes=token_response.scope.split()
        )
        return session

    def get_delegated_token(self, session_id: str) -> Optional[str]:
        session = self._sessions.get(session_id)
        if not session or not session.delegated_token:
            return None
        return session.delegated_token
        
    def get_demo_token(self) -> str:
        """
        Get a delegated token for demo purposes.
        Uses the most recent session's delegated token if available.
        """
        # Try to get token from most recent session
        for session in reversed(list(self._sessions.values())):
            if session.delegated_token:
                print(f"\n[DEMO] Using delegated token from session: {session.session_id}")
                return session.delegated_token
        
        # If no session, log warning
        print(f"\n[DEMO WARNING] No user session found! Please login first at /auth/login")
        raise ValueError("No user session found. Please login at /auth/login first to get a delegated token.")

    # ─────────────────────────────────────────────────────────────────
    # Token Exchange (Single App, Per-Agent Identity)
    # ─────────────────────────────────────────────────────────────────

    async def exchange_token_for_agent(
        self,
        source_token: str,
        agent_key: str,  # e.g. "hr_agent"
        target_audience: str,
        target_scopes: list[str]
    ) -> str:
        """
        Exchange source token for a downstream agent.
        Uses Token Exchanger App credentials + Agent's actor token.
        """
        agent_config = self.agents_config.get(agent_key)
        if not agent_config:
            raise ValueError(f"Unknown agent: {agent_key}")
            
        agent_id = agent_config.get("agent_id")
        agent_secret = agent_config.get("agent_secret")
        
        if not agent_id:
            raise ValueError(f"Missing agent_id for agent {agent_key}")

        print(f"\n{'#'*80}")
        print(f"# TOKEN EXCHANGE FOR: {agent_key.upper()}")
        print(f"{'#'*80}")
        print(f"Agent ID: {agent_id}")
        print(f"Target Audience: {target_audience}")
        print(f"Target Scopes: {target_scopes}")
        
        print(f"\n[SOURCE_TOKEN (Composite/Delegated)]:")
        print(f"{source_token}")

        try:
            # 1. Get Agent's Actor Token (using Orchestrator App + Agent credentials)
            agent_actor_token = await self.asgardeo._fetch_agent_actor_token(
                client_id=self.settings.orchestrator_client_id,
                client_secret=self.settings.orchestrator_client_secret,
                agent_id=agent_id
            )
            
            print(f"\n[{agent_key.upper()}_ACTOR_TOKEN]:")
            print(f"{agent_actor_token.token}")
            
            # 2. Perform Exchange using TOKEN EXCHANGER App + Agent's Actor Token
            if not self.settings.token_exchanger_client_id or not self.settings.token_exchanger_client_secret:
                raise ValueError("TOKEN_EXCHANGER_CLIENT_ID and TOKEN_EXCHANGER_CLIENT_SECRET are required")
            
            print(f"\nUsing Token Exchanger App: {self.settings.token_exchanger_client_id}")
            
            new_token = await self.asgardeo.perform_token_exchange(
                subject_token=source_token,
                client_id=self.settings.token_exchanger_client_id,
                client_secret=self.settings.token_exchanger_client_secret,
                actor_token=agent_actor_token.token,
                target_audience=target_audience,
                target_scopes=target_scopes
            )
            
            print(f"\n[{agent_key.upper()}_EXCHANGED_TOKEN for {target_audience}]:")
            print(f"{new_token}")
            print(f"{'#'*80}\n")


            
            self._log_audit(
                operation="token_exchange",
                user_sub="unknown",
                target_service=target_audience,
                scopes=target_scopes
            )
            
            return new_token
            
        except Exception as e:
            self._log_audit(
                operation="token_exchange_failed",
                user_sub="unknown",
                target_service=target_audience,
                scopes=target_scopes,
                success=False,
                error=str(e)
            )
            raise


    def _log_audit(self, operation, user_sub, target_service, scopes, success=True, error=None):
        entry = AuditEntry(
            timestamp=datetime.utcnow(),
            operation=operation,
            user_sub=user_sub,
            actor_sub=self.settings.orchestrator_agent_id,
            target_service=target_service,
            scopes=scopes,
            success=success,
            error=error
        )
        self._audit_log.append(entry)

_token_broker: Optional[TokenBroker] = None

def get_token_broker() -> TokenBroker:
    global _token_broker
    if _token_broker is None:
        _token_broker = TokenBroker()
    return _token_broker
