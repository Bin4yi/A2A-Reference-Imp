"""
Booking Agent Server - Runs on port 8004
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.apis.booking_api import router as booking_router

app = FastAPI(title="Booking Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(booking_router, prefix="/api/booking", tags=["Booking"])

@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "booking"}

@app.get("/.well-known/agent.json")
async def agent_card():
    return {
        "name": "Booking Agent",
        "description": "Schedules tasks and deliveries",
        "url": "http://localhost:8004",
        "skills": [{"id": "create_task", "name": "Create Task"}]
    }

if __name__ == "__main__":
    uvicorn.run("src.servers.booking_server:app", host="127.0.0.1", port=8004, reload=True)
