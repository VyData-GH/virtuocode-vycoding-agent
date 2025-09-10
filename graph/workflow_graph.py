from typing import Dict, Any
from datetime import datetime
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from models.schemas import TaskRequest, WorkflowStatus, WorkflowState

from nodes import (
    prepare_environment,
    analyze_requirements,
    implement_task,
    run_tests,
    debug_code,
    quality_assurance_automation,
    finalize_pr,
    update_monday
)
from utils.logger import get_logger

logger = get_logger(__name__)


def create_workflow_graph() -> StateGraph:
    workflow = StateGraph(WorkflowState)
    
    workflow.add_node("prepare_environment", prepare_environment)
    workflow.add_node("analyze_requirements", analyze_requirements)
    workflow.add_node("implement_task", implement_task) 
    workflow.add_node("run_tests", run_tests)
    workflow.add_node("debug_code", debug_code)
    workflow.add_node("quality_assurance_automation", quality_assurance_automation)
    workflow.add_node("finalize_pr", finalize_pr)
    workflow.add_node("update_monday", update_monday)
    
    workflow.set_entry_point("prepare_environment")
    
    workflow.add_edge("prepare_environment", "analyze_requirements")
    workflow.add_edge("analyze_requirements", "implement_task")
    workflow.add_edge("implement_task", "run_tests")
    
    workflow.add_conditional_edges(
        "run_tests",
        _should_debug,
        {
            "debug": "debug_code",
            "continue": "quality_assurance_automation",
            "end": END
        }
    )
    
    workflow.add_edge("debug_code", "run_tests")
    
    workflow.add_edge("quality_assurance_automation", "finalize_pr")
    workflow.add_edge("finalize_pr", "update_monday")
    workflow.add_edge("update_monday", END)    
    logger.info("✅ Graphe de workflow créé et configuré pour RabbitMQ avec nouveaux nœuds")
    return workflow


def _should_debug(state: WorkflowState) -> str:
    if not state.results or "test_results" not in state.results:
        logger.warning("⚠️ Aucun résultat de test trouvé")
        return "end"
    
    test_results = state.results["test_results"]    
    if not test_results:
        logger.info("📝 Aucun test exécuté - passage à l'assurance qualité")
        return "continue"
    
    if isinstance(test_results, dict):
        tests_passed = test_results.get("success", False)
        failed_count = len(test_results.get("failed_tests", []))
    elif isinstance(test_results, list):
        tests_passed = all(test.get("passed", False) for test in test_results)
        failed_count = len([test for test in test_results if not test.get("passed", False)])
    else:
        tests_passed = bool(test_results)
        failed_count = 0 if tests_passed else 1
    
    debug_attempts = len([node for node in state.completed_nodes if node == "debug_code"])
    max_debug_attempts = 3    
    if tests_passed:
        logger.info(f"✅ Tests réussis - passage à l'assurance qualité")
        return "continue"
    elif debug_attempts >= max_debug_attempts:
        logger.warning(f"⚠️ Limite de debug atteinte ({debug_attempts}/{max_debug_attempts}) - passage forcé à QA")
        state.error = f"Tests échoués après {debug_attempts} tentatives de debug"
        return "continue"
    else:
        logger.info(f"🔧 Tests échoués ({failed_count} échecs) - tentative debug {debug_attempts + 1}/{max_debug_attempts}")
        return "debug"


async def run_workflow(task_request: TaskRequest) -> Dict[str, Any]:
    workflow_id = f"workflow_{task_request.task_id}_{int(datetime.now().timestamp())}"
    
    logger.info(f"🚀 Démarrage workflow {workflow_id} pour: {task_request.title}")
    
    try:
        initial_state = _create_initial_state(task_request, workflow_id)
        
        workflow_graph = create_workflow_graph()
        checkpointer = MemorySaver()
        app = workflow_graph.compile(checkpointer=checkpointer)
        
        config = {
            "configurable": {
                "thread_id": workflow_id,
                "task_id": task_request.task_id
            }
        }
        
        logger.info(f"📊 Exécution workflow avec configuration thread_id={workflow_id}")        
        final_state = None
        node_count = 0
        
        async for state in app.astream(initial_state, config=config):
            node_count += 1
            current_node = state.current_node if hasattr(state, 'current_node') else "unknown"            
            logger.info(f"📍 Nœud {node_count}: {current_node}")
            
            if state:
                final_state = state
                
            if node_count > 25:
                logger.error("⚠️ Limite de nœuds atteinte - arrêt du workflow")
                break
        
        if final_state:
            result = _process_final_result(final_state, task_request)
            logger.info(f"✅ Workflow {workflow_id} terminé avec succès")
            return result
        else:
            error_msg = "Workflow terminé sans état final"
            logger.error(f"❌ {error_msg}")
            return _create_error_result(task_request, error_msg)
            
    except Exception as e:
        error_msg = f"Erreur lors de l'exécution du workflow: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return _create_error_result(task_request, error_msg)


def _create_initial_state(task_request: TaskRequest, workflow_id: str) -> WorkflowState:
    return WorkflowState(
        workflow_id=workflow_id,
        status=WorkflowStatus.PENDING,
        current_node=None,
        completed_nodes=[],
        task=task_request,
        results={
            "ai_messages": [],
            "error_logs": [],
            "modified_files": [],
            "test_results": [],
            "debug_attempts": 0
        },
        error=None,
        started_at=datetime.now(),
        completed_at=None
    )


def _process_final_result(final_state: WorkflowState, task_request: TaskRequest) -> Dict[str, Any]:   
    current_status = final_state.status
    success = current_status == WorkflowStatus.COMPLETED
    
    duration = 0
    if final_state.started_at:
        end_time = final_state.completed_at or datetime.now()
        duration = (end_time - final_state.started_at).total_seconds()
    
    results = final_state.results or {}
    error_message = final_state.error
    completed_nodes = final_state.completed_nodes or []
    
    pr_url = None
    if "pr_info" in results:
        pr_info = results["pr_info"]
        if isinstance(pr_info, dict):
            pr_url = pr_info.get("pr_url")
        else:
            pr_url = getattr(pr_info, "pr_url", None)
    
    files_modified = 0
    tests_executed = 0
    qa_score = 0
    analysis_score = 0
    
    if "code_changes" in results:
        files_modified = len(results["code_changes"]) if isinstance(results["code_changes"], dict) else 0
    
    if "test_results" in results:
        test_results = results["test_results"]
        if isinstance(test_results, dict):
            tests_executed = test_results.get("total_tests", 0)
        elif isinstance(test_results, list):
            tests_executed = len(test_results)
    
    if "quality_assurance" in results:
        qa_data = results["quality_assurance"]
        qa_score = qa_data.get("qa_summary", {}).get("overall_score", 0)
    
    if "requirements_analysis" in results:
        analysis_data = results["requirements_analysis"]
        analysis_score = analysis_data.get("complexity_score", 5)
    
    result = {
        "success": success,
        "status": current_status.value if current_status else "unknown",
        "workflow_id": final_state.workflow_id,
        "task_id": task_request.task_id,
        "duration": duration,
        "completed_nodes": completed_nodes,
        "pr_url": pr_url,
        "error": error_message,
        "metrics": {
            "files_modified": files_modified,
            "tests_executed": tests_executed,
            "nodes_completed": len(completed_nodes),
            "duration_seconds": duration,
            "qa_score": qa_score,
            "analysis_complexity": analysis_score,
            "workflow_completeness": len(completed_nodes) / 8 * 100  # 8 nœuds au total
        },
        "results": results
    }
    
    logger.info(f"📊 Workflow terminé - Succès: {success}, Durée: {duration:.1f}s, Nœuds: {len(completed_nodes)}, QA: {qa_score}")
    
    return result


def _create_error_result(task_request: TaskRequest, error_msg: str) -> Dict[str, Any]:
    return {
        "success": False,
        "status": "failed",
        "workflow_id": f"error_{task_request.task_id}",
        "task_id": task_request.task_id,
        "duration": 0,
        "completed_nodes": [],
        "pr_url": None,
        "error": error_msg,
        "metrics": {
            "files_modified": 0,
            "tests_executed": 0,
            "nodes_completed": 0,
            "duration_seconds": 0,
            "qa_score": 0,
            "analysis_complexity": 0,
            "workflow_completeness": 0
        },
        "results": {}
    } 