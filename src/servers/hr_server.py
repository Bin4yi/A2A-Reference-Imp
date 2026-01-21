"""
HR Agent Server - Runs on port 8001
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.apis.hr_api import router as hr_router

app = FastAPI(title="HR Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HR API
app.include_router(hr_router, prefix="/api/hr", tags=["HR"])

@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "hr"}

@app.get("/.well-known/agent.json")
async def agent_card():
    return {
        "name": "HR Agent",
        "description": "Manages employee profiles and HR operations",
        "url": "http://localhost:8001",
        "skills": [{"id": "create_employee", "name": "Create Employee"}]
    }

if __name__ == "__main__":
    uvicorn.run("src.servers.hr_server:app", host="127.0.0.1", port=8001, reload=True)
