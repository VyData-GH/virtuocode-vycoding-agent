from fastapi import FastAPI
from utils.logger import get_logger

logger = get_logger(__name__)

def setup_middleware(app: FastAPI):
    """Configure les middlewares pour l'application FastAPI."""
    logger.info("ℹ️ Configuration des middlewares...")
    # Ici, vous ajouteriez la logique réelle de configuration des middlewares
    # Exemple: app.add_middleware(SomeMiddleware)
    logger.info("✅ Middlewares configurés avec succès.") 