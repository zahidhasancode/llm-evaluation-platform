"""
FastAPI entrypoint for LLM Evaluation Platform.
"""

import sys
from pathlib import Path

# Ensure src is on path so api, core, storage imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI

from api.logs import router as logs_router
from api.metrics import router as metrics_router

app = FastAPI(title="LLM Evaluation Platform")

app.include_router(logs_router)
app.include_router(metrics_router)
