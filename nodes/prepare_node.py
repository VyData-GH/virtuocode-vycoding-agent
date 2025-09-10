from typing import Dict, Any

from models.schemas import GitOperationResult, WorkflowStatus
from tools.claude_code_tool import ClaudeCodeTool
from utils.logger import get_logger

logger = get_logger(__name__)

async def prepare_environment(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"🔧 Préparation de l'environnement pour la tâche: {state.task.title}")
    if 'ai_messages' not in state.results:
        state.results['ai_messages'] = []
    state.results["current_status"] = "IN_PROGRESS".lower()
    state.results["ai_messages"].append("Début de la préparation de l'environnement...")
    
    try:
        claude_tool = ClaudeCodeTool()        
        repo_url = state.task.repository_url
        if not repo_url:
            from config.settings import get_settings
            settings = get_settings()
            repo_url = settings.default_repo_url
        
        branch_name = state.task.branch_name        
        logger.info(f"Configuration de l'environnement - Repo: {repo_url}, Branche: {branch_name}")        
        setup_result = await claude_tool._arun(
            action="setup_environment",
            repo_url=repo_url,
            branch=branch_name
        )        
        if setup_result["success"]:
            git_result = GitOperationResult(
                success=True,
                operation="setup_environment",
                message="Environnement configuré avec succès",
                branch_name=branch_name
            )
            state.results["git_result"] = git_result
            state.results["working_directory"] = setup_result["working_directory"]
            state.results["ai_messages"].append(f"✅ Environnement configuré: {branch_name}")
            state.results["last_operation_result"] = "Préparation réussie"
            
            logger.info(f"✅ Environnement préparé avec succès - Répertoire: {setup_result['working_directory']}")
            
        else:
            error_msg = setup_result.get("error", "Erreur inconnue lors de la préparation")            
            git_result = GitOperationResult(
                success=False,
                operation="setup_environment",
                message=error_msg,
                branch_name=branch_name
            )
            
            state.results["git_result"] = git_result
            state.results["error_logs"].append(f"Erreur préparation: {error_msg}")
            state.results["ai_messages"].append(f"❌ Échec préparation: {error_msg}")
            state.results["last_operation_result"] = f"Échec préparation: {error_msg}"
            
            logger.error(f"❌ Échec de la préparation: {error_msg}")        
        state.results["should_continue"] = True
        
    except Exception as e:
        error_msg = f"Exception lors de la préparation: {str(e)}"
        logger.error(error_msg, exc_info=True)        
        git_result = GitOperationResult(
            success=False,
            operation="setup_environment",
            message=error_msg,
            branch_name=state.task.branch_name
        )
        
        state.results["git_result"] = git_result
        state.results["error_logs"].append(error_msg)
        state.results["ai_messages"].append(f"❌ Exception: {error_msg}")
        state.results["last_operation_result"] = error_msg
        state.results["should_continue"] = True
    
    logger.info(f"🏁 Préparation terminée - Statut: {'✅' if (state.results.get('git_result').success if state.results.get('git_result') else False) else '❌'}")
    return state 