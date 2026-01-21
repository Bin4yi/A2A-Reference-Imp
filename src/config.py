"""
Configuration management.
"""

from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App Settings
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_callback_url: str = "http://localhost:8000/callback"
    
    # Asgardeo Settings
    asgardeo_org_name: str
    asgardeo_base_url: Optional[str] = None
    asgardeo_token_url: Optional[str] = None
    asgardeo_authorize_url: Optional[str] = None
    asgardeo_jwks_url: Optional[str] = None
    
    # Orchestrator App & Agent
    orchestrator_client_id: str
    orchestrator_client_secret: str
    orchestrator_agent_id: str
    orchestrator_agent_secret: str
    
    # Agents (Optional, as they are primarily in config.yaml but useful here for validation)
    # Orchestrator is mandatory
    
    # Token Exchanger Application (for RFC 8693 exchange calls)
    token_exchanger_client_id: Optional[str] = None
    token_exchanger_client_secret: Optional[str] = None
    
    # Optional Agent Credentials (loaded via env if needed, but primarily used by TokenBroker via config.yaml)
    # However, if .env contains them, Pydantic might complain if not defined here 
    # OR we set extra='ignore' to allow unknown env vars (e.g. agent specifics)
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Allow extra fields in .env (like HR_AGENT_ID, etc.)

    
    # APIs
    api_audience: str = "onboarding-api"
    
    # OpenAI
    openai_api_key: str
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Auto-compute Asgardeo URLs if not set
        base = f"https://api.asgardeo.io/t/{self.asgardeo_org_name}"
        if not self.asgardeo_base_url:
            self.asgardeo_base_url = base
        if not self.asgardeo_token_url:
            self.asgardeo_token_url = f"{base}/oauth2/token"
        if not self.asgardeo_authorize_url:
            self.asgardeo_authorize_url = f"{base}/oauth2/authorize"
        if not self.asgardeo_jwks_url:
            self.asgardeo_jwks_url = f"{base}/oauth2/jwks"


_settings: Optional[Settings] = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
