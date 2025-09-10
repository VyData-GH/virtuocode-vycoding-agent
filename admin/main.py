from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from contextlib import asynccontextmanager
import uvicorn

from config.settings import get_settings
from admin.backend.database import init_database
from admin.backend.routes.auth_router import auth_router
from admin.backend.routes.dashboard_router import dashboard_router
from admin.backend.routes.workflows_router import workflows_router
from admin.backend.routes.configuration_router import configuration_router
from admin.backend.routes.monitoring_router import monitoring_router
from admin.backend.routes.projects_router import projects_router
from admin.backend.routes.users_router import users_router
from admin.backend.middleware import setup_middleware
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Démarrage du backend d'administration...")
    
    await init_database()
    
    logger.info("✅ Backend d'administration démarré avec succès")
    yield
    
    logger.info("🛑 Arrêt du backend d'administration...")


app = FastAPI(
    title="AI-Agent Admin Backend",
    description="Interface d'administration pour l'agent d'automatisation IA",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.admin_frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_middleware(app)

app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(workflows_router, prefix="/api/workflows", tags=["Workflows"])
app.include_router(configuration_router, prefix="/api/config", tags=["Configuration"])
app.include_router(monitoring_router, prefix="/api/monitoring", tags=["Monitoring"])
app.include_router(projects_router, prefix="/api/projects", tags=["Projects"])
app.include_router(users_router, prefix="/api/users", tags=["Users"])


@app.get("/", response_model=dict)
async def root():
    return {
        "message": "AI-Agent Admin Backend",
        "version": "1.0.0",
        "status": "running",
        "docs": "/api/docs"
    }


@app.get("/api/health", response_model=dict)
async def health_check():
    from admin.backend.database import get_database_status
    from admin.backend.services.monitoring_service import get_system_health
    
    try:
        db_status = await get_database_status()
        system_health = await get_system_health()
        
        return {
            "status": "healthy",
            "timestamp": system_health["timestamp"],
            "database": db_status,
            "system": system_health,
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Erreur lors du health check: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service indisponible"
        )


@app.get("/api/status", response_model=dict)
async def status():
    from admin.backend.services.monitoring_service import get_detailed_status
    
    try:
        detailed_status = await get_detailed_status()
        return detailed_status
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur interne du serveur"
        )


if __name__ == "__main__":
    uvicorn.run(
        "admin.backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    ) 