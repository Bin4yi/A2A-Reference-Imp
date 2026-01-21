"""
Token Flow Demonstration Script
Shows all tokens with identifiable names during the A2A onboarding flow.
"""

import asyncio
import sys
import httpx
import json
from datetime import datetime

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Disable SSL warnings for localhost
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration (from .env)
BASE_URL = "https://localhost:9443/t/carbon.super"
TOKEN_URL = f"{BASE_URL}/oauth2/token"

# Credentials
ORCHESTRATOR_CLIENT_ID = "cPfSkWoOf2wS_lJDoaDFWOHqec4a"
ORCHESTRATOR_CLIENT_SECRET = "8gDepfRDQQDpzFIR4uuOUwsakvhwJ400C28KGlCH1sMa"
ORCHESTRATOR_AGENT_ID = "ab7fb3d1-c6ba-4375-80d3-ce6e4c9bb285"

TOKEN_EXCHANGER_CLIENT_ID = "Mb8Nth8ZMb04Z_2iwSb3lLdwnzMa"
TOKEN_EXCHANGER_CLIENT_SECRET = "zbCQvcxSwsCcvISok6eo9gTKxoMFeVn8HeHo6lUFUEMa"

AGENTS = {
    "HR_AGENT": "da390d57-e67a-4ab1-abbb-143e8d17ef0b",
    "IT_AGENT": "f86be2cd-3f15-4353-bf62-f3d0011e4656",
    "APPROVAL_AGENT": "ae11ad1b-d45a-4d56-aff9-047c0e32730f",
    "BOOKING_AGENT": "9f625d17-4600-4327-b345-fae411ed1caf",
}

def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_token(name: str, token: str, description: str = ""):
    print(f"\n[TOKEN] {name}")
    if description:
        print(f"   Description: {description}")
    if len(token) > 80:
        print(f"   Value: {token[:80]}...")
    else:
        print(f"   Value: {token}")

def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (for display only)."""
    import base64
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            # Add padding
            payload += "=" * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
    except:
        pass
    return {}

async def get_client_credentials_token(client: httpx.AsyncClient) -> str:
    """Step 1: Get Orchestrator's client credentials token."""
    data = {
        "grant_type": "client_credentials",
        "client_id": ORCHESTRATOR_CLIENT_ID,
        "client_secret": ORCHESTRATOR_CLIENT_SECRET,
        "scope": "openid"
    }
    
    response = await client.post(TOKEN_URL, data=data)
    response.raise_for_status()
    result = response.json()
    return result["access_token"]

async def exchange_token(
    client: httpx.AsyncClient,
    subject_token: str,
    actor_token: str,
    target_audience: str,
    target_scopes: list[str]
) -> str:
    """Perform RFC 8693 Token Exchange."""
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": actor_token,
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "client_id": TOKEN_EXCHANGER_CLIENT_ID,
        "client_secret": TOKEN_EXCHANGER_CLIENT_SECRET,
        "audience": target_audience,
        "scope": " ".join(target_scopes)
    }
    
    response = await client.post(TOKEN_URL, data=data)
    response.raise_for_status()
    result = response.json()
    return result["access_token"]

async def main():
    print_header("A2A TOKEN FLOW DEMONSTRATION")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Identity Server: {BASE_URL}")
    
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        
        # ─────────────────────────────────────────────────────────────
        # STEP 1: Orchestrator gets its own token
        # ─────────────────────────────────────────────────────────────
        print_header("STEP 1: ORCHESTRATOR CLIENT CREDENTIALS TOKEN")
        
        try:
            orchestrator_token = await get_client_credentials_token(client)
            print_token(
                "ORCHESTRATOR_ACCESS_TOKEN",
                orchestrator_token,
                "Client credentials token for the Orchestrator App"
            )
            
            payload = decode_jwt_payload(orchestrator_token)
            print(f"   Subject (sub): {payload.get('sub', 'N/A')}")
            print(f"   Audience (aud): {payload.get('aud', 'N/A')}")
            print(f"   Scopes: {payload.get('scope', 'N/A')}")
            
        except Exception as e:
            print(f"[ERROR] Failed to get orchestrator token: {e}")
            orchestrator_token = None

        # ─────────────────────────────────────────────────────────────
        # STEP 2: Simulate User Delegation (would be auth code flow)
        # ─────────────────────────────────────────────────────────────
        print_header("STEP 2: USER DELEGATED TOKEN (Simulated)")
        print("   [INFO] In production, this comes from Authorization Code flow")
        print("   [INFO] User authenticates, consents, and Orchestrator gets delegated token")
        
        composite_token = orchestrator_token
        if composite_token:
            print_token(
                "USER_DELEGATED_TOKEN (Composite)",
                composite_token,
                "Token representing User + Orchestrator delegation"
            )

        # ─────────────────────────────────────────────────────────────
        # STEP 3: Token Exchange for each Agent
        # ─────────────────────────────────────────────────────────────
        if not composite_token:
            print("\n[ERROR] Cannot proceed without tokens")
            return
            
        agent_configs = [
            ("HR_AGENT", AGENTS["HR_AGENT"], "hr-api", ["hr:read", "hr:write"]),
            ("IT_AGENT", AGENTS["IT_AGENT"], "it-api", ["it:read", "it:write"]),
            ("APPROVAL_AGENT", AGENTS["APPROVAL_AGENT"], "approval-api", ["approval:read", "approval:write"]),
            ("BOOKING_AGENT", AGENTS["BOOKING_AGENT"], "booking-api", ["booking:read", "booking:write"]),
        ]
        
        for agent_name, agent_id, audience, scopes in agent_configs:
            print_header(f"STEP 3: TOKEN EXCHANGE FOR {agent_name}")
            print(f"   Agent ID: {agent_id}")
            print(f"   Target Audience: {audience}")
            print(f"   Requested Scopes: {scopes}")
            
            try:
                actor_token = orchestrator_token
                
                print_token(
                    f"{agent_name}_ACTOR_TOKEN",
                    actor_token,
                    f"Actor token proving {agent_name}'s identity"
                )
                
                # Perform token exchange
                exchanged_token = await exchange_token(
                    client,
                    subject_token=composite_token,
                    actor_token=actor_token,
                    target_audience=audience,
                    target_scopes=scopes
                )
                
                print_token(
                    f"{agent_name}_EXCHANGED_TOKEN",
                    exchanged_token,
                    f"Downscoped token for {audience} with scopes {scopes}"
                )
                
                # Decode and show claims
                payload = decode_jwt_payload(exchanged_token)
                print(f"   Subject (sub): {payload.get('sub', 'N/A')}")
                print(f"   Audience (aud): {payload.get('aud', 'N/A')}")
                print(f"   Scopes: {payload.get('scope', 'N/A')}")
                if "act" in payload:
                    print(f"   Actor (act.sub): {payload['act'].get('sub', 'N/A')}")
                    
            except Exception as e:
                print(f"   [ERROR] Token exchange failed: {e}")

        # ─────────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────────
        print_header("TOKEN FLOW SUMMARY")
        print("""
        1. ORCHESTRATOR_ACCESS_TOKEN
           -> Client credentials token for the Orchestrator App
        
        2. USER_DELEGATED_TOKEN  
           -> (From Auth Code Flow) User's consent + Orchestrator delegation
        
        3. AGENT_ACTOR_TOKENs
           |-- HR_AGENT_ACTOR_TOKEN
           |-- IT_AGENT_ACTOR_TOKEN  
           |-- APPROVAL_AGENT_ACTOR_TOKEN
           |-- BOOKING_AGENT_ACTOR_TOKEN
        
        4. EXCHANGED_TOKENs (via Token Exchanger App)
           |-- HR_AGENT_EXCHANGED_TOKEN (audience: hr-api)
           |-- IT_AGENT_EXCHANGED_TOKEN (audience: it-api)
           |-- APPROVAL_AGENT_EXCHANGED_TOKEN (audience: approval-api)
           |-- BOOKING_AGENT_EXCHANGED_TOKEN (audience: booking-api)
        """)

if __name__ == "__main__":
    asyncio.run(main())
