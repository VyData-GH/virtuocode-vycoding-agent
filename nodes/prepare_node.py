from models.state import GraphState
from utils.logger import get_logger

logger = get_logger(__name__)

async def prepare_environment(state: GraphState) -> GraphState:
    """Prépare l'environnement pour l'exécution de la tâche."""
    logger.info("🔧 Préparation de l'environnement...")
    
    # Pour le test, on marque simplement l'étape comme terminée
    state["current_status"] = "in_progress"
    
    logger.info("✅ Environnement préparé")
    return state