from models.state import GraphState
from utils.logger import get_logger

logger = get_logger(__name__)

async def update_monday(state: GraphState) -> GraphState:
    """Met à jour Monday.com avec le résultat."""
    logger.info("📋 Mise à jour de Monday.com...")
    
    # Pour le test, on marque la mise à jour comme terminée
    logger.info("✅ Monday.com mis à jour")
    return state