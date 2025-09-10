"""Nœud de mise à jour Monday - met à jour le ticket avec les résultats."""

from datetime import datetime
from typing import Dict, Any
from models.schemas import WorkflowStatus, WorkflowState
from tools.monday_tool import MondayTool
from utils.logger import get_logger

logger = get_logger(__name__)


async def update_monday(state: WorkflowState) -> Dict[str, Any]:
    if not state.task:
        logger.error("❌ Aucune tâche dans l'état du workflow")
        return {"success": False, "error": "Aucune tâche définie"}
        
    logger.info(f"📋 Mise à jour Monday pour: {state.task.title}")
    
    try:
        monday_tool = MondayTool()
        
        task = state.task
        
        final_status, success_level = _determine_final_status(state)
        
        completion_comment = await _generate_completion_comment(state, success_level)
        
        pr_url = None
        if state.results and "pr_info" in state.results:
            pr_info = state.results["pr_info"]
            pr_url = pr_info.get("pr_url") if isinstance(pr_info, dict) else getattr(pr_info, "pr_url", None)
        
        logger.info(f"📝 Mise à jour statut: {final_status}, PR: {pr_url or 'N/A'}")
        
        if success_level == "success":
            update_result = await monday_tool._arun(
                action="complete_task",
                item_id=task.task_id,
                pr_url=pr_url,
                completion_comment=completion_comment
            )
        else:
            status_result = await monday_tool._arun(
                action="update_item_status",
                item_id=task.task_id,
                status=final_status
            )
            
            comment_result = await monday_tool._arun(
                action="add_comment",
                item_id=task.task_id,
                comment=completion_comment
            )
            
            update_result = {
                "success": status_result.get("success", False) and comment_result.get("success", False),
                "operations": [("status", status_result), ("comment", comment_result)]
            }
        
        if update_result.get("success", False):
            logger.info("✅ Monday.com mis à jour avec succès")
            
            state.status = WorkflowStatus.COMPLETED
            state.completed_at = datetime.now()
            
            return {
                "success": True,
                "message": "Monday.com mis à jour avec succès",
                "final_status": final_status,
                "pr_url": pr_url,
                "comment_added": True
            }
        else:
            error_msg = update_result.get("error", "Erreur inconnue lors de la mise à jour Monday")
            logger.error(f"❌ Échec mise à jour Monday.com: {error_msg}")
            
            state.status = WorkflowStatus.FAILED
            state.error = f"Échec mise à jour Monday: {error_msg}"
            
            return {
                "success": False,
                "error": error_msg,
                "final_status": "Échec mise à jour",
                "comment_added": False
            }
            
    except Exception as e:
        error_msg = f"Exception lors de la mise à jour Monday: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        state.status = WorkflowStatus.FAILED
        state.error = error_msg
        
        return {
            "success": False, 
            "error": error_msg,
            "final_status": "Erreur technique",
            "comment_added": False
        }


def _determine_final_status(state: WorkflowState) -> tuple[str, str]:

    current_status = state.status
    
    if current_status == WorkflowStatus.COMPLETED:
        if state.results and "pr_info" in state.results:
            return "Terminé", "success"
        else:
            return "En attente", "partial"
    elif current_status == WorkflowStatus.FAILED:
        if state.error and any(keyword in state.error.lower() for keyword in ["git", "clone", "repository"]):
            return "Bloqué - Repository", "failed"
        elif state.error and any(keyword in state.error.lower() for keyword in ["test", "tests"]):
            return "Échec Tests", "failed"
        else:
            return "Bloqué", "failed"
    else:
        return "En cours", "partial"


async def _generate_completion_comment(state: WorkflowState, success_level: str) -> str:
    task = state.task
    
    if success_level == "success":
        header = "✅ **Tâche Complétée avec Succès**\n\n"
    elif success_level == "partial":
        header = "⚠️ **Tâche Partiellement Complétée**\n\n"
    else:
        header = "❌ **Tâche Échouée**\n\n"
    
    basic_info = f"**Tâche**: {task.title}\n"
    basic_info += f"**Type**: {task.task_type}\n"
    basic_info += f"**Priorité**: {task.priority}\n\n"
    
    results_section = "## 📊 Résultats\n\n"
    
    if state.completed_at and state.started_at:
        duration = (state.completed_at - state.started_at).total_seconds()
        results_section += f"- **Durée**: {duration:.1f} secondes\n"
    
    results_section += f"- **Statut Final**: {state.status}\n"
    
    if state.completed_nodes:
        results_section += f"- **Étapes Complétées**: {', '.join(state.completed_nodes)}\n"
    
    pr_section = ""
    if state.results and "pr_info" in state.results:
        pr_info = state.results["pr_info"]
        pr_section = "\n## 🔗 Pull Request\n\n"
        if isinstance(pr_info, dict):
            pr_section += f"- **URL**: {pr_info.get('pr_url', 'N/A')}\n"
            pr_section += f"- **Branche**: {pr_info.get('branch', 'N/A')}\n"
    
    error_section = ""
    if state.error:
        error_section = f"\n## ❌ Erreurs\n\n```\n{state.error}\n```\n"
    
    metrics_section = "\n## 📈 Métriques\n\n"
    if state.results:
        for key, value in state.results.items():
            if key not in ["pr_info"] and isinstance(value, (str, int, float)):
                metrics_section += f"- **{key.replace('_', ' ').title()}**: {value}\n"
    
    comment = header + basic_info + results_section + pr_section + error_section + metrics_section
    
    comment += f"\n---\n*Mis à jour automatiquement par AI-Agent le {datetime.now().strftime('%d/%m/%Y à %H:%M')}*"
    
    return comment 