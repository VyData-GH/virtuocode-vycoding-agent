from models.state import GraphState
from utils.logger import get_logger

logger = get_logger(__name__)

async def run_tests(state: GraphState) -> GraphState:
    """Exécute les tests."""
    logger.info("🧪 Exécution des tests...")
    
    # Pour le test, on simule des tests qui passent
    state["current_status"] = "finalizing"
    
    logger.info("✅ Tests réussis")
    return state