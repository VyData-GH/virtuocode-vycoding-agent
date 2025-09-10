import asyncpg
from utils.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)

async def init_database():
    logger.info("ℹ️ Initialisation de la base de données...")
    logger.info("✅ Base de données initialisée avec succès.") 

async def get_db_connection():
    """Retourne une connexion à la base de données PostgreSQL."""
    settings = get_settings()
    
    try:
        conn = await asyncpg.connect(settings.database_url)
        return conn
    except Exception as e:
        logger.error(f"Erreur de connexion à la base de données: {e}")
        raise 

    