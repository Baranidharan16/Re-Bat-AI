"""Standalone runner: the solar twin API + dashboard, without the rest of RE-BAT AI.

    pip install fastapi uvicorn
    python solar_demo_server.py            → open http://localhost:8000
                                             (API docs at http://localhost:8000/docs)
"""
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.solar_routes import router as solar_router

DASHBOARD = Path(__file__).resolve().parent.parent / "frontend" / "solar_twin_dashboard.html"

app = FastAPI(title="RE-BAT AI · Solar twin")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(solar_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def dashboard():
    return FileResponse(DASHBOARD)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
