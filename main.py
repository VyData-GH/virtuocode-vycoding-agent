import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional

from models.schemas import TaskRequest
from services.webhook_service import WebhookService
from graph.workflow_graph import run_workflow
from config.settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" Démarrage de l'Agent d'Automatisation IA")
    yield
    logger.info(" Arrêt de l'Agent d'Automatisation IA")


app = FastAPI(
    title="Agent d'Automatisation IA",
    description="Système intelligent d'automatisation du développement logiciel",
    version="1.0.0",
    lifespan=lifespan
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(",") if settings.allowed_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

webhook_service = WebhookService()


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ai-automation-agent",
        "version": "1.0.0"
    }


@app.get("/webhook/monday")
async def validate_monday_webhook(request: Request):
    challenge = request.query_params.get("challenge")
    
    if challenge:
        logger.info(f"✅ Challenge webhook reçu: {challenge}")

        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        logger.info("✅ Validation webhook Monday.com (GET)")
        return JSONResponse(
            content={
                "status": "webhook_ready", 
                "message": "Monday.com webhook endpoint is ready",
                "methods": ["GET", "POST"]
            },
            status_code=200
        )


@app.post("/webhook/monday")
async def receive_monday_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):

    try:
        payload = await request.json()
        
        if "challenge" in payload and not payload.get("event"):
            challenge = payload["challenge"]
            logger.info(f"✅ Challenge webhook reçu via POST: {challenge}")
            return JSONResponse(content={"challenge": challenge}, status_code=200)
        
        signature = request.headers.get("X-Monday-Signature")
        
        background_tasks.add_task(
            process_webhook_background,
            payload,
            signature
        )
        
        return JSONResponse(
            content={"message": "Webhook reçu et en cours de traitement"},
            status_code=202
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la réception du webhook: {e}")
        raise HTTPException(status_code=400, detail="Erreur dans le payload du webhook")


async def process_webhook_background(payload: Dict[str, Any], signature: Optional[str] = None):
    try:
        result = await webhook_service.process_webhook(payload, signature)
        logger.info(f"Webhook traité: {result}")
    except Exception as e:
        logger.error(f"Erreur lors du traitement du webhook en arrière-plan: {e}")


@app.post("/workflow/run")
async def run_manual_workflow(task_request: TaskRequest):

    try:
        logger.info(f"🚀 Lancement manuel du workflow pour: {task_request.title}")
        
        result = await run_workflow(task_request)
        
        return {
            "success": True,
            "task_id": task_request.task_id,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du workflow manuel: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur workflow: {str(e)}")


@app.get("/workflow/status/{task_id}")
async def get_workflow_status(task_id: str):
    # TODO: Implémenter le suivi des statuts avec une base de données
    return {
        "task_id": task_id,
        "status": "unknown",
        "message": "Suivi des statuts non encore implémenté"
    }


@app.post("/tools/test")
async def test_tools():
    test_results = {}
    
    try:
        test_results["settings"] = {
            "status": "ok",
            "anthropic_key": bool(settings.anthropic_api_key),
            "github_token": bool(settings.github_token),
            "monday_key": bool(settings.monday_api_key)
        }
        
        test_results["claude"] = {"status": "not_tested", "message": "Test à implémenter"}
        test_results["github"] = {"status": "not_tested", "message": "Test à implémenter"}
        test_results["monday"] = {"status": "not_tested", "message": "Test à implémenter"}
        
        return {
            "success": True,
            "tests": test_results
        }
        
    except Exception as e:
        logger.error(f"Erreur lors des tests d'outils: {e}")
        return {
            "success": False,
            "error": str(e),
            "tests": test_results
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Désactiver pour éviter les rechargements constants
        log_level="info"
    ) 