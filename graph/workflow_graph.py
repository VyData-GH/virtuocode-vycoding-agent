from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from models.state import GraphState
from models.schemas import TaskRequest, TaskStatus
from nodes import (
    prepare_environment,
    implement_task,
    run_tests,
    debug_code,
    finalize_pr,
    update_monday
)
from utils.logger import get_logger

logger = get_logger(__name__)


def create_workflow_graph() -> StateGraph:

    logger.info("🔧 Création du graphe de workflow...")
    
    workflow = StateGraph(GraphState)
    
    workflow.add_node("prepare", prepare_environment)
    workflow.add_node("implement", implement_task)
    workflow.add_node("test", run_tests)
    workflow.add_node("debug", debug_code)
    workflow.add_node("finalize", finalize_pr)
    workflow.add_node("update", update_monday)
    
    workflow.set_entry_point("prepare")
    
    
    workflow.add_edge("prepare", "implement")
    
    workflow.add_edge("implement", "test")
    
    workflow.add_conditional_edges(
        "test",
        should_debug_or_finalize,
        {
            "debug": "debug",
            "finalize": "finalize"
        }
    )
    
    workflow.add_edge("debug", "test")
    
    workflow.add_edge("finalize", "update")
    
    workflow.add_edge("update", END)
    
    logger.info("✅ Graphe de workflow créé avec succès")
    return workflow


def should_debug_or_finalize(state: GraphState) -> str:
    if not state.get("test_results"):
        logger.warning("Aucun résultat de test - Passage à la finalisation")
        return "finalize"
    
    latest_test = state["test_results"][-1]
    
    if latest_test.success:
        logger.info("✅ Tests réussis - Passage à la finalisation")
        return "finalize"
    
    debug_attempts = state.get("debug_attempts", 0)
    max_debug_attempts = state.get("max_debug_attempts", 3)
    
    if debug_attempts < max_debug_attempts:
        logger.info(f"🔧 Tests échoués - Passage au debug (tentative {debug_attempts + 1}/{max_debug_attempts})")
        return "debug"
    else:
        logger.warning(f"❌ Limite de debug atteinte ({max_debug_attempts}) - Passage à la finalisation")
        return "finalize"


async def run_workflow(task_request: TaskRequest) -> Dict[str, Any]:

    logger.info(f"🚀 Lancement du workflow pour la tâche: {task_request.title}")
    
    try:
        workflow = create_workflow_graph()
        
        memory = MemorySaver()
        compiled_workflow = workflow.compile(checkpointer=memory)
        
        initial_state = _create_initial_state(task_request)
        
        config = {
            "configurable": {
                "thread_id": f"task_{task_request.task_id}",
                "checkpoint_ns": "ai_automation"
            }
        }
        
        logger.info(f"📋 État initial créé pour la tâche {task_request.task_id}")
        
        final_state = None
        step_count = 0
        max_steps = 20
        
        async for state in compiled_workflow.astream(initial_state, config):
            step_count += 1
            
            current_state = list(state.values())[0] if state else {}
            
            current_status = current_state.get("current_status", "unknown")
            last_operation = current_state.get("last_operation_result", "")
            
            logger.info(f"📊 Étape {step_count}: {current_status} - {last_operation}")
            
            if not current_state.get("should_continue", True):
                logger.info("🛑 Arrêt demandé par le workflow")
                break
            
            if step_count >= max_steps:
                logger.error(f"❌ Limite d'étapes atteinte ({max_steps}) - Arrêt forcé")
                break
            
            final_state = current_state
        
        if final_state:
            result = _process_final_result(final_state, task_request)
            logger.info(f"✅ Workflow terminé avec succès - Statut: {result['status']}")
        else:
            result = _create_error_result(task_request, "Workflow interrompu ou échoué")
            logger.error("❌ Workflow échoué - Aucun état final")
        
        return result
        
    except Exception as e:
        error_msg = f"Exception lors de l'exécution du workflow: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return _create_error_result(task_request, error_msg)


def _create_initial_state(task_request: TaskRequest) -> GraphState:

    return {
        "task": task_request,
        "current_status": TaskStatus.PENDING,
        
        # Résultats et historique
        "git_result": None,
        "test_results": [],
        "error_logs": [],
        "code_changes": {},
        "pr_info": None,
        
        # Compteurs et limites
        "debug_attempts": 0,
        "max_debug_attempts": 3,
        
        # Messages et contexte
        "ai_messages": [f"Initialisation du workflow pour: {task_request.title}"],
        "working_directory": None,
        "modified_files": [],
        "last_operation_result": "Workflow initialisé",
        
        # Contrôle de flux
        "should_continue": True
    }


def _process_final_result(final_state: GraphState, task_request: TaskRequest) -> Dict[str, Any]:
    current_status = final_state.get("current_status", TaskStatus.FAILED)
    
    success = current_status in [TaskStatus.COMPLETED]
    
    pr_info = final_state.get("pr_info")
    test_results = final_state.get("test_results", [])
    error_logs = final_state.get("error_logs", [])
    modified_files = final_state.get("modified_files", [])
    
    total_errors = len(error_logs)
    tests_passed = len([t for t in test_results if t.success])
    total_tests = len(test_results)
    debug_attempts = final_state.get("debug_attempts", 0)
    
    result = {
        "success": success,
        "status": current_status,
        "task_id": task_request.task_id,
        "task_title": task_request.title,
        
        "pr_url": pr_info.pr_url if pr_info else None,
        "pr_number": pr_info.pr_number if pr_info else None,
        "modified_files": modified_files,
        
        "metrics": {
            "files_modified": len(modified_files),
            "tests_executed": total_tests,
            "tests_passed": tests_passed,
            "debug_attempts": debug_attempts,
            "errors_encountered": total_errors,
            "duration": _calculate_workflow_duration(final_state)
        },
        
        "test_results": [
            {
                "command": t.test_command,
                "success": t.success,
                "duration": t.duration,
                "exit_code": t.exit_code
            } for t in test_results
        ],
        "error_summary": error_logs[-5:] if error_logs else [],
        "ai_messages": final_state.get("ai_messages", [])[-10:],
        
        "started_at": task_request.created_at.isoformat(),
        "completed_at": final_state.get("completed_at", task_request.created_at).isoformat() if final_state.get("completed_at") else None
    }
    
    return result


def _create_error_result(task_request: TaskRequest, error_message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "status": TaskStatus.FAILED,
        "task_id": task_request.task_id,
        "task_title": task_request.title,
        "error": error_message,
        
        "pr_url": None,
        "pr_number": None,
        "modified_files": [],
        
        "metrics": {
            "files_modified": 0,
            "tests_executed": 0,
            "tests_passed": 0,
            "debug_attempts": 0,
            "errors_encountered": 1,
            "duration": "N/A"
        },
        
        "test_results": [],
        "error_summary": [error_message],
        "ai_messages": [f"Erreur fatale: {error_message}"],
        
        "started_at": task_request.created_at.isoformat(),
        "completed_at": None
    }


def _calculate_workflow_duration(final_state: GraphState) -> str:
    
    try:
        started_at = final_state["task"].created_at
        completed_at = final_state.get("completed_at")
        
        if not completed_at:
            return "N/A"
        
        duration = completed_at - started_at
        total_seconds = int(duration.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
            
    except Exception:
        return "N/A" 