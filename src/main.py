"""
FastAPI application entry point.
Implements the Employee Onboarding Orchestrator with A2A protocol support.
"""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.config import get_settings
from src.apis import hr_api, it_api, approval_api, booking_api
from src.auth.token_broker import get_token_broker
from src.a2a.types import Skill
from src.a2a.server import A2AServer

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("application_starting")
    
    # Initialize token broker (get actor token)
    broker = get_token_broker()
    try:
        await broker.initialize()
    except Exception as e:
        logger.warning("broker_init_skipped", error=str(e))
        
    # Initialize A2A Client Discovery
    client = get_a2a_client()
    discovery_urls = orch_config.get("discovery", {}).get("agent_urls", [])
    if discovery_urls:
         await client.start_background_discovery(discovery_urls)
    
    yield
    
    # Shutdown
    logger.info("application_shutting_down")
    await client.close()


app = FastAPI(
    title="Employee Onboarding Orchestrator",
    description="AI-Powered A2A Reference Implementation",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from src.config_loader import load_yaml_config
from src.a2a.orchestrator import OrchestratorExecutor
from src.a2a.client import get_a2a_client
from src.a2a.types import AgentCard, Skill, Capabilities, AuthenticationInfo

# ─────────────────────────────────────────────────────────────────
# A2A Protocol Setup (Agent Card & Server)
# ─────────────────────────────────────────────────────────────────

# Load configuration
config = load_yaml_config()
orch_config = config.get("orchestrator", {})

# Create Executor
executor = OrchestratorExecutor()

# Create Agent Card
skills = [
    Skill(
        id="onboard_employee",
        name="Onboard Employee",
        description="Process complete employee onboarding from natural language request"
    ),
    Skill(
        id="check_onboarding_status",
        name="Check Onboarding Status",
        description="Check the status of an onboarding request"
    )
]

agent_card = AgentCard(
    name=orch_config.get("name", "Employee Onboarding Orchestrator"),
    description=orch_config.get("description", "AI-powered orchestrator"),
    url=orch_config.get("url", f"http://localhost:{settings.app_port}"),
    skills=skills,
    capabilities=Capabilities(streaming=False),
    authentication=AuthenticationInfo(
        schemes=["bearer"],
        required_scopes=["orchestrator:call"] # Example scope
    )
)

# Initialize A2A Server
a2a_server = A2AServer(agent_card=agent_card, executor=executor)

# Include A2A routes
app.include_router(a2a_server.router)

# Include API routers
app.include_router(hr_api.router, prefix="/api/hr", tags=["HR"])
app.include_router(it_api.router, prefix="/api/it", tags=["IT"])
app.include_router(approval_api.router, prefix="/api/approval", tags=["Approval"])
app.include_router(booking_api.router, prefix="/api/booking", tags=["Booking"])


# ─────────────────────────────────────────────────────────────────
# Health & OAuth Endpoints
# ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/auth/login")
async def start_login():
    """
    Start the OAuth login flow.
    Creates a session and redirects to Asgardeo.
    """
    broker = get_token_broker()
    session = broker.create_session()
    
    # Request all scopes needed for onboarding
    scopes = [
        "hr:read", "hr:write",
        "it:read", "it:write",
        "approval:read", "approval:write",
        "booking:read", "booking:write"
    ]
    
    auth_url = broker.get_authorization_url(
        session_id=session.session_id,
        scopes=scopes
    )
    
    logger.info("login_started", session_id=session.session_id)
    
    return RedirectResponse(url=auth_url)


@app.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...)
):
    """
    OAuth2 callback endpoint.
    Exchanges the authorization code for a delegated token.
    """
    broker = get_token_broker()
    
    try:
        session = await broker.handle_callback(code=code, state=state)
        
        logger.info(
            "oauth_callback_success",
            session_id=session.session_id
        )
        
        return {
            "status": "success",
            "session_id": session.session_id,
            "message": "Authorization successful. You can now use the onboarding API."
        }
        
    except Exception as e:
        logger.error("oauth_callback_failed", error=str(e))
        raise HTTPException(400, f"Authorization failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────
# Onboarding Endpoints
# ─────────────────────────────────────────────────────────────────

class OnboardingRequest(BaseModel):
    """Request to start an onboarding workflow."""
    request: str  # Natural language request
    session_id: str = None  # Session with delegated token


class OnboardingResponse(BaseModel):
    """Response from onboarding workflow."""
    request_id: str
    status: str
    employee_id: str | None = None
    message: str
    audit_log: list[dict] = []


@app.post("/api/onboard", response_model=OnboardingResponse)
async def start_onboarding(request: OnboardingRequest):
    """
    Start an employee onboarding workflow.
    
    For demo purposes, this works without OAuth.
    In production, use session_id from /auth/login flow.
    """
    from src.graph.state import create_initial_state
    from src.graph.workflow import get_onboarding_graph
    
    request_id = f"ONB-{uuid.uuid4().hex[:8].upper()}"
    
    logger.info(
        "onboarding_started",
        request_id=request_id,
        request_length=len(request.request)
    )
    
    # Get delegated token from session or use demo token
    broker = get_token_broker()
    if request.session_id:
        token = broker.get_delegated_token(request.session_id)
        if not token:
            raise HTTPException(401, "Invalid or expired session")
        user_sub = broker.get_session(request.session_id).user_sub or "unknown"
    else:
        # Demo mode
        token = broker.get_demo_token()
        user_sub = "demo-user@nebulasoft.com"
    
    try:
        # Create initial state
        initial_state = create_initial_state(
            request_id=request_id,
            raw_request=request.request,
            user_sub=user_sub,
            actor_sub=settings.orchestrator_agent_id,
            composite_token=token
        )
        
        # Get the workflow graph
        graph = get_onboarding_graph()
        
        # Run the workflow
        final_state = await graph.ainvoke(initial_state)
        
        logger.info(
            "onboarding_completed",
            request_id=request_id,
            status=final_state.get("status"),
            employee_id=final_state.get("employee_id")
        )
        
        return OnboardingResponse(
            request_id=request_id,
            status=final_state.get("status", "unknown"),
            employee_id=final_state.get("employee_id"),
            message=_build_status_message(final_state),
            audit_log=final_state.get("audit_log", [])
        )
        
    except Exception as e:
        logger.error("onboarding_failed", request_id=request_id, error=str(e))
        raise HTTPException(500, f"Onboarding failed: {str(e)}")


def _build_status_message(state: dict) -> str:
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


@app.get("/api/demo")
async def run_demo():
    """
    Run the demo scenario: Onboard Nimal Perera.
    Works without OAuth authentication.
    """
    demo_request = OnboardingRequest(
        request="""Onboard Nimal Perera (nimal.perera@nebulasoft.com) as Senior Software Engineer 
        in Platform Engineering team, reporting to Rajith Vitharana. Start date February 1st 2026. 
        He needs laptop delivery to Colombo, VPN access, GitHub Enterprise access to 
        identity-server-core repo, and AWS dev environment access."""
    )
    
    return await start_onboarding(demo_request)


# ─────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True
    )
