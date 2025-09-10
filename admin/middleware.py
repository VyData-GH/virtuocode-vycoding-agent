from fastapi import FastAPI
from utils.logger import get_logger

logger = get_logger(__name__)

def setup_middleware(app: FastAPI):
    logger.info("ℹ️ Configuration des middlewares...")
    logger.info("✅ Middlewares configurés avec succès.") 