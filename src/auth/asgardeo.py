"""
WSO2 IS Client - Authentication & Token Exchange.
Implements 3-step actor token flow and RFC 8693 Token Exchange.
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import structlog

from src.config import get_settings
from src.auth.utils import generate_pkce, PKCEChallenge

logger = structlog.get_logger()


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    scope: str = ""
    token_type: str = "Bearer"
    expires_in: int = 3600
    expires_at: datetime = None

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = datetime.utcnow() + timedelta(seconds=self.expires_in)


@dataclass
class ActorToken:
    token: str
    actor_id: str
    expires_at: datetime


class AsgardeoClient:
    """
    Client for interacting with WSO2 Identity Server.
    Handles:
    - User Authentication (Authorization Code Flow)
    - Actor Token Acquisition (3-Step Flow)
    - Token Exchange (RFC 8693) for delegation and downscoping
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._actor_token: Optional[ActorToken] = None
    
    def _create_fresh_client(self) -> httpx.AsyncClient:
        """Create a fresh HTTP client with no cookies (for each auth flow)."""
        return httpx.AsyncClient(
            timeout=30.0, 
            verify=False,
            follow_redirects=False
        )

    # ─────────────────────────────────────────────────────────────────
    # 1. User Authorization (Orchestrator App)
    # ─────────────────────────────────────────────────────────────────

    def build_user_authorize_url(
        self,
        scopes: list[str],
        state: str,
        pkce: PKCEChallenge
    ) -> str:
        """
        Build the authorization URL for user consent.
        Includes requested_actor to bind the orchestrator agent to the resulting token.
        """
        from urllib.parse import urlencode
        
        all_scopes = scopes + ["openid", "profile"]
        
        params = {
            "response_type": "code",
            "client_id": self.settings.orchestrator_client_id,
            "scope": " ".join(all_scopes),
            "redirect_uri": self.settings.app_callback_url,
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            "requested_actor": self.settings.orchestrator_agent_id
        }
        
        # Properly URL-encode all parameters
        query = urlencode(params)
        auth_url = f"{self.settings.asgardeo_authorize_url}?{query}"
        
        print(f"\n[BUILD AUTH URL]")
        print(f"  Requested Scopes: {all_scopes}")
        print(f"  URL: {auth_url}")
        
        return auth_url


    async def exchange_code_for_delegated_token(
        self,
        code: str,
        code_verifier: str,
        actor_token: str
    ) -> TokenResponse:
        """
        Exchange auth code for a delegated access token.
        Requires actor_token to prove the agent's identity.
        """
        async with self._create_fresh_client() as client:
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.app_callback_url,
                "client_id": self.settings.orchestrator_client_id,
                "client_secret": self.settings.orchestrator_client_secret,
                "code_verifier": code_verifier,
                "actor_token": actor_token,
                "actor_token_type": "urn:ietf:params:oauth:token-type:access_token"
            }
            
            print(f"\n{'='*80}")
            print(f"[EXCHANGE CODE FOR DELEGATED TOKEN]")
            print(f"{'='*80}")
            print(f"  Token URL: {self.settings.asgardeo_token_url}")
            print(f"  Grant Type: authorization_code")
            print(f"  Code: {code}")
            print(f"  Redirect URI: {self.settings.app_callback_url}")
            print(f"  Client ID: {self.settings.orchestrator_client_id}")
            print(f"  Code Verifier: {code_verifier}")
            print(f"  Actor Token: {actor_token[:50]}...")
            print(f"{'='*80}")
            
            response = await client.post(
                self.settings.asgardeo_token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            print(f"\n[RESPONSE]")
            print(f"  Status: {response.status_code}")
            print(f"  Body: {response.text}")

            
            response.raise_for_status()
            
            result = response.json()
            
            print(f"  Access Token: {result.get('access_token', '')[:50]}...")
            print(f"  Scope: {result.get('scope', '')}")
            
            logger.info("delegated_token_received", scope=result.get("scope"))
            
            return TokenResponse(**result)


    # ─────────────────────────────────────────────────────────────────
    # 2. Agent Actor Token (3-Step Flow)
    # ─────────────────────────────────────────────────────────────────

    async def get_actor_token(self) -> ActorToken:
        """Get an actor token for the orchestrator agent."""
        if self._actor_token and self._actor_token.expires_at > datetime.utcnow():
            return self._actor_token
            
        token = await self._fetch_agent_actor_token(
            client_id=self.settings.orchestrator_client_id,
            client_secret=self.settings.orchestrator_client_secret,
            agent_id=self.settings.orchestrator_agent_id
        )
        
        self._actor_token = token
        logger.info("actor_token_obtained", agent_id=self.settings.orchestrator_agent_id)
        return token

    async def _fetch_agent_actor_token(self, client_id: str, client_secret: str, agent_id: str) -> ActorToken:
        """
        Get an actor token for an agent using the 3-step flow.
        Uses a fresh HTTP client each time (clears cookies).
        
        Step 1: POST /oauth2/authorize -> Get flowId
        Step 2: POST /oauth2/authn with agent credentials -> Get auth code
        Step 3: POST /oauth2/token -> Get actor token
        """
        pkce = generate_pkce()
        
        print(f"\n{'='*80}")
        print(f"[3-STEP ACTOR TOKEN FLOW]")
        print(f"  Agent ID: {agent_id}")
        print(f"{'='*80}")
        
        # Use fresh client for each flow (clears cookies)
        async with self._create_fresh_client() as client:
            # Step 1: Initiate Auth Flow - Get flowId
            flow_id = await self._initiate_auth_flow(client, client_id, pkce)
            print(f"\n[STEP 1] Flow ID:")
            print(f"  {flow_id}")
            
            # Step 2: Authenticate Agent
            auth_code = await self._authenticate_agent(client, flow_id, agent_id)
            print(f"\n[STEP 2] Auth Code:")
            print(f"  {auth_code}")
            
            # Step 3: Exchange for Actor Token
            actor_token = await self._exchange_code_for_actor_token(
                client, client_id, client_secret, auth_code, pkce.verifier, agent_id
            )
            print(f"\n[STEP 3] ACTOR_TOKEN:")
            print(f"  {actor_token.token}")
            print(f"{'='*80}\n")
            
            return actor_token

    async def _initiate_auth_flow(self, client: httpx.AsyncClient, client_id: str, pkce: PKCEChallenge) -> str:
        """
        Step 1: Initiate authorization flow.
        POST /oauth2/authorize -> Returns flowId in JSON response
        """
        data = {
            "response_type": "code",
            "client_id": client_id,
            "scope": "openid",
            "redirect_uri": self.settings.app_callback_url,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256"
        }
        
        print(f"\n  [Step 1] Calling: POST {self.settings.asgardeo_authorize_url}")
        
        response = await client.post(
            self.settings.asgardeo_authorize_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        print(f"  [Step 1] Response status: {response.status_code}")
        
        # Handle 302 redirect - extract flowId from redirect URL
        if response.status_code == 302:
            location = response.headers.get("location", "")
            print(f"  [Step 1] Redirect to: {location[:100]}...")
            
            parsed = urlparse(location)
            query_params = parse_qs(parsed.query)
            
            # Try different parameter names
            flow_id = (
                query_params.get("flowId", [None])[0] or
                query_params.get("sessionDataKey", [None])[0]
            )
            if flow_id:
                return flow_id
            else:
                raise ValueError(f"flowId not found in redirect: {location}")
        else:
            # JSON response
            result = response.json()
            print(f"  [Step 1] Response: {result}")
            return result.get("flowId") or result.get("flow_id")

    async def _authenticate_agent(self, client: httpx.AsyncClient, flow_id: str, agent_id: str) -> str:
        """
        Step 2: Authenticate agent with flowId to get auth code.
        POST /oauth2/authn with proper payload structure
        """
        # Get agent secret from config
        from src.config_loader import load_yaml_config
        config = load_yaml_config()
        
        # Find agent secret
        agent_secret = None
        agents = config.get("agents", {})
        for key, agent_config in agents.items():
            if agent_config.get("agent_id") == agent_id:
                agent_secret = agent_config.get("agent_secret")
                break
        
        # Fallback: check if this is the orchestrator agent
        if not agent_secret and agent_id == self.settings.orchestrator_agent_id:
            agent_secret = self.settings.orchestrator_agent_secret
        
        authn_url = f"{self.settings.asgardeo_base_url}/oauth2/authn"
        
        print(f"\n  [Step 2] Calling: POST {authn_url}")
        print(f"  [Step 2] Agent ID: {agent_id}")
        
        # Proper WSO2 IS authn payload structure
        payload = {
            "flowId": flow_id,
            "selectedAuthenticator": {
                "authenticatorId": "QmFzaWNBdXRoZW50aWNhdG9yOkxPQ0FM",  # Base64 of "BasicAuthenticator:LOCAL"
                "params": {
                    "username": agent_id,
                    "password": agent_secret
                }
            }
        }
        
        print(f"  [Step 2] Payload: flowId={flow_id}, username={agent_id}")
        
        response = await client.post(
            authn_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"  [Step 2] Response status: {response.status_code}")
        
        # Handle different response types
        if response.status_code == 302:
            # Redirect contains the auth code
            location = response.headers.get("location", "")
            print(f"  [Step 2] Redirect: {location[:100]}...")
            
            parsed = urlparse(location)
            query_params = parse_qs(parsed.query)
            
            auth_code = query_params.get("code", [None])[0]
            if auth_code:
                return auth_code
            else:
                raise ValueError(f"Auth code not found in redirect: {location}")
        elif response.status_code == 200:
            result = response.json()
            print(f"  [Step 2] Response: {result}")
            
            # Check if we got the code directly or need to follow a redirect
            if "code" in result:
                return result["code"]
            elif "authorizationCode" in result:
                return result["authorizationCode"]
            elif "redirectUrl" in result:
                # Parse code from redirectUrl
                parsed = urlparse(result["redirectUrl"])
                query_params = parse_qs(parsed.query)
                auth_code = query_params.get("code", [None])[0]
                if auth_code:
                    return auth_code
            
            raise ValueError(f"Auth code not found in response: {result}")
        else:
            error_text = response.text
            print(f"  [Step 2] Error: {error_text}")
            raise ValueError(f"Authentication failed: {response.status_code} - {error_text}")

    async def _exchange_code_for_actor_token(
        self, 
        client: httpx.AsyncClient,
        client_id: str, 
        client_secret: str, 
        code: str, 
        verifier: str,
        agent_id: str
    ) -> ActorToken:
        """Step 3: Exchange authorization code for actor token."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.app_callback_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier
        }
        
        print(f"\n  [Step 3] Calling: POST {self.settings.asgardeo_token_url}")
        
        response = await client.post(
            self.settings.asgardeo_token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        print(f"  [Step 3] Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"  [Step 3] Error: {response.text}")
        
        response.raise_for_status()
        
        result = response.json()
        expires_in = result.get("expires_in", 3600)
        
        return ActorToken(
            token=result["access_token"],
            actor_id=agent_id,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in)
        )

    # ─────────────────────────────────────────────────────────────────
    # 3. Token Exchange (RFC 8693)
    # ─────────────────────────────────────────────────────────────────

    async def perform_token_exchange(
        self,
        subject_token: str,
        client_id: str,
        client_secret: str,
        actor_token: Optional[str] = None,
        target_audience: Optional[str] = None,
        target_scopes: Optional[list[str]] = None
    ) -> str:
        """
        Exchange a token for a new one (RFC 8693).
        """
        async with self._create_fresh_client() as client:
            data = {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "client_id": client_id,
                "client_secret": client_secret,
            }
            
            if actor_token:
                data["actor_token"] = actor_token
                data["actor_token_type"] = "urn:ietf:params:oauth:token-type:access_token"
            
            if target_audience:
                data["audience"] = target_audience
                
            if target_scopes:
                data["scope"] = " ".join(target_scopes)
            
            print(f"\n{'='*80}")
            print(f"[TOKEN EXCHANGE]")
            print(f"  Client: {client_id}")
            print(f"  Audience: {target_audience}")
            print(f"  Scopes: {target_scopes}")
            print(f"{'='*80}")
            print(f"\n[SUBJECT_TOKEN]:")
            print(f"  {subject_token}")
            if actor_token:
                print(f"\n[ACTOR_TOKEN]:")
                print(f"  {actor_token}")

                
            response = await client.post(
                self.settings.asgardeo_token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            
            result = response.json()
            exchanged_token = result["access_token"]
            
            print(f"\n[EXCHANGED_TOKEN]:")
            print(f"  {exchanged_token}")
            print(f"{'='*80}\n")
            
            return exchanged_token


# Singleton
_asgardeo_client: Optional[AsgardeoClient] = None

def get_asgardeo_client() -> AsgardeoClient:
    global _asgardeo_client
    if _asgardeo_client is None:
        _asgardeo_client = AsgardeoClient()
    return _asgardeo_client
