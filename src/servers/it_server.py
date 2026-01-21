"""
IT Agent Server - Runs on port 8002
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.apis.it_api import router as it_router

app = FastAPI(title="IT Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(it_router, prefix="/api/it", tags=["IT"])

@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "it"}

@app.get("/.well-known/agent.json")
async def agent_card():
    return {
        "name": "IT Agent",
        "description": "Provisions IT accounts and access",
        "url": "http://localhost:8002",
        "skills": [{"id": "provision_vpn", "name": "Provision VPN"}]
    }

if __name__ == "__main__":
    uvicorn.run("src.servers.it_server:app", host="127.0.0.1", port=8002, reload=True)
