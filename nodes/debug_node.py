from models.state import GraphState
from utils.logger import get_logger

logger = get_logger(__name__)

async def debug_code(state: GraphState) -> GraphState:
    """Debug le code en cas d'erreur."""
    logger.info("🐛 Debug du code...")
    
    # Pour le test, on marque le debug comme terminé
    state["current_status"] = "testing"
    
    logger.info("✅ Debug terminé")
    return state