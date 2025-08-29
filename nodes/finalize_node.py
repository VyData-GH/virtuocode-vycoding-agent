from models.state import GraphState
from utils.logger import get_logger

logger = get_logger(__name__)

async def finalize_pr(state: GraphState) -> GraphState:
    logger.info("Finalisation de la Pull Request...")
    state["current_status"] = "completed"    
    logger.info("✅ Pull Request finalisée")
    return state