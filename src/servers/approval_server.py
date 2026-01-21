"""
Approval Agent Server - Runs on port 8003
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.apis.approval_api import router as approval_router

app = FastAPI(title="Approval Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(approval_router, prefix="/api/approval", tags=["Approval"])

@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "approval"}

@app.get("/.well-known/agent.json")
async def agent_card():
    return {
        "name": "Approval Agent",
        "description": "Handles approval workflows",
        "url": "http://localhost:8003",
        "skills": [{"id": "request_approval", "name": "Request Approval"}]
    }

if __name__ == "__main__":
    uvicorn.run("src.servers.approval_server:app", host="127.0.0.1", port=8003, reload=True)
