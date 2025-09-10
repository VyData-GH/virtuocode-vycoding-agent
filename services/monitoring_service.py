import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import structlog
from fastapi import WebSocket 
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from utils.logger import get_logger
from models.schemas import WorkflowStatus, WorkflowState


logger = get_logger(__name__)


@dataclass
class MetricPoint:
    timestamp: datetime
    value: float
    labels: Dict[str, str]
    metric_name: str


@dataclass
class WorkflowMetrics:
    workflow_id: str
    task_id: str
    status: str
    duration: Optional[float] = None
    steps_completed: int = 0
    errors_count: int = 0
    ai_provider: Optional[str] = None
    ai_tokens_used: int = 0
    ai_cost: float = 0.0
    tests_passed: int = 0
    tests_failed: int = 0
    files_modified: int = 0
    pr_created: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MonitoringDashboard:
    
    def __init__(self):
        self.metrics_store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.workflow_metrics: Dict[str, WorkflowMetrics] = {}
        self.active_workflows: Dict[str, Dict] = {}
        self.connected_clients: List[WebSocket] = []
        self.alert_rules: List[Dict] = []
        
        self.real_time_stats = {
            "active_workflows": 0,
            "completed_today": 0,
            "failed_today": 0,
            "avg_duration": 0.0,
            "success_rate": 100.0,
            "ai_costs_today": 0.0,
            "tests_run_today": 0
        }
        
    async def start_monitoring(self):
        logger.info("🚀 Démarrage du monitoring custom")
        
        asyncio.create_task(self._metrics_aggregator())
        asyncio.create_task(self._alert_checker())
        asyncio.create_task(self._cleanup_old_metrics())
        
    async def record_metric(self, metric_name: str, value: float, labels: Dict[str, str] = None):
        labels = labels or {}
        point = MetricPoint(
            timestamp=datetime.now(),
            value=value,
            labels=labels,
            metric_name=metric_name
        )
        
        self.metrics_store[metric_name].append(point)
        
        await self._broadcast_metric(point)
        
    async def start_workflow_monitoring(self, workflow_id: str, task_request: Dict):
        workflow_metrics = WorkflowMetrics(
            workflow_id=workflow_id,
            task_id=task_request.get("task_id", "unknown"),
            status=WorkflowStatus.PENDING.value,
            ai_provider=task_request.get("preferred_ai_provider", "claude")
        )
        
        self.workflow_metrics[workflow_id] = workflow_metrics
        self.active_workflows[workflow_id] = {
            "start_time": time.time(),
            "current_step": "starting",
            "progress": 0,
            "logs": deque(maxlen=100)
        }
        
        self.real_time_stats["active_workflows"] += 1
        
        logger.info(
            "📊 Monitoring démarré pour workflow",
            workflow_id=workflow_id,
            task_id=workflow_metrics.task_id
        )
        
        await self.record_metric("workflow_started", 1, {
            "workflow_id": workflow_id,
            "task_type": task_request.get("task_type", "unknown")
        })
        
    async def update_workflow_step(self, workflow_id: str, step_name: str, 
                                 progress: int, logs: List[str] = None):
        if workflow_id not in self.active_workflows:
            return
            
        workflow = self.active_workflows[workflow_id]
        workflow["current_step"] = step_name
        workflow["progress"] = progress
        
        if logs:
            for log in logs:
                workflow["logs"].append({
                    "timestamp": datetime.now().isoformat(),
                    "step": step_name,
                    "message": log
                })
        
        if workflow_id in self.workflow_metrics:
            self.workflow_metrics[workflow_id].steps_completed = progress
            
        await self.record_metric("workflow_progress", progress, {
            "workflow_id": workflow_id,
            "step": step_name
        })
        
        await self._broadcast_workflow_update(workflow_id)
        
    async def complete_workflow(self, workflow_id: str, success: bool, 
                                                             final_state: WorkflowState = None):
        if workflow_id not in self.active_workflows:
            return
            
        workflow = self.active_workflows[workflow_id]
        metrics = self.workflow_metrics.get(workflow_id)
        
        if metrics:
            duration = time.time() - workflow["start_time"]
            metrics.duration = duration
            metrics.status = WorkflowStatus.COMPLETED.value if success else WorkflowStatus.FAILED.value
            
            if final_state:
                metrics.files_modified = len(getattr(final_state, 'modified_files', []) or [])
                test_results = getattr(final_state, 'test_results', []) or []
                metrics.tests_passed = sum(1 for t in test_results if getattr(t, 'passed', False))
                metrics.tests_failed = sum(1 for t in test_results if not getattr(t, 'passed', False))
                metrics.pr_created = getattr(final_state, 'pr_info', None) is not None
                error_logs = getattr(final_state, 'error_logs', []) or []
                metrics.errors_count = len(error_logs)
        
        self.real_time_stats["active_workflows"] -= 1
        if success:
            self.real_time_stats["completed_today"] += 1
        else:
            self.real_time_stats["failed_today"] += 1
            
        total_today = self.real_time_stats["completed_today"] + self.real_time_stats["failed_today"]
        if total_today > 0:
            self.real_time_stats["success_rate"] = (self.real_time_stats["completed_today"] / total_today) * 100
        
        await self.record_metric("workflow_completed", 1, {
            "workflow_id": workflow_id,
            "success": str(success),
            "duration": str(duration) if duration else "0"
        })
        
        del self.active_workflows[workflow_id]
        
        logger.info(
            f"{'✅' if success else '❌'} Workflow terminé",
            workflow_id=workflow_id,
            success=success,
            duration=duration
        )
        
    async def log_ai_usage(self, workflow_id: str, provider: str, 
                          tokens_used: int, estimated_cost: float):
        if workflow_id in self.workflow_metrics:
            metrics = self.workflow_metrics[workflow_id]
            metrics.ai_provider = provider
            metrics.ai_tokens_used += tokens_used
            metrics.ai_cost += estimated_cost
            
        self.real_time_stats["ai_costs_today"] += estimated_cost
        
        await self.record_metric("ai_tokens_used", tokens_used, {
            "provider": provider,
            "workflow_id": workflow_id
        })
        
        await self.record_metric("ai_cost", estimated_cost, {
            "provider": provider,
            "workflow_id": workflow_id
        })
        
    async def add_alert_rule(self, name: str, condition: str, threshold: float, 
                           message: str):
        rule = {
            "name": name,
            "condition": condition,
            "threshold": threshold,
            "message": message,
            "last_triggered": None
        }
        self.alert_rules.append(rule)
        
    async def get_dashboard_data(self) -> Dict[str, Any]:
        return {
            "real_time_stats": self.real_time_stats,
            "active_workflows": {
                wf_id: {
                    **workflow,
                    "metrics": self.workflow_metrics.get(wf_id, {}).to_dict() if wf_id in self.workflow_metrics else {}
                }
                for wf_id, workflow in self.active_workflows.items()
            },
            "recent_metrics": {
                name: [asdict(point) for point in list(points)[-50:]]
                for name, points in self.metrics_store.items()
            },
            "completed_workflows_today": [
                {
                    "workflow_id": wf_id,
                    **metrics.to_dict()
                }
                for wf_id, metrics in self.workflow_metrics.items()
                if metrics.status in [WorkflowStatus.COMPLETED.value, WorkflowStatus.FAILED.value]
                and self._is_today(datetime.now())
            ]
        }
        
    async def register_websocket(self, websocket: WebSocket):
        self.connected_clients.append(websocket)
        
        initial_data = await self.get_dashboard_data()
        await websocket.send_json({
            "type": "initial_data",
            "data": initial_data
        })
        
    async def unregister_websocket(self, websocket: WebSocket):
        if websocket in self.connected_clients:
            self.connected_clients.remove(websocket)
            
    async def _broadcast_metric(self, metric: MetricPoint):
        if not self.connected_clients:
            return
            
        message = {
            "type": "metric_update",
            "data": asdict(metric)
        }
        
        disconnected = []
        for client in self.connected_clients:
            try:
                await client.send_json(message)
            except:
                disconnected.append(client)
                
        for client in disconnected:
            self.connected_clients.remove(client)
            
    async def _broadcast_workflow_update(self, workflow_id: str):   
        if not self.connected_clients or workflow_id not in self.active_workflows:
            return
            
        workflow_data = {
            **self.active_workflows[workflow_id],
            "metrics": self.workflow_metrics.get(workflow_id, {}).to_dict() if workflow_id in self.workflow_metrics else {}
        }
        
        message = {
            "type": "workflow_update",
            "workflow_id": workflow_id,
            "data": workflow_data
        }
        
        for client in self.connected_clients[:]:
            try:
                await client.send_json(message)
            except:
                self.connected_clients.remove(client)
                
    async def _metrics_aggregator(self):
        while True:
            try:
                completed_workflows = [
                    m for m in self.workflow_metrics.values() 
                    if m.duration is not None
                ]
                
                if completed_workflows:
                    avg_duration = sum(m.duration for m in completed_workflows) / len(completed_workflows)
                    self.real_time_stats["avg_duration"] = round(avg_duration, 2)
                    
                total_tests = sum(
                    m.tests_passed + m.tests_failed 
                    for m in self.workflow_metrics.values()
                )
                self.real_time_stats["tests_run_today"] = total_tests
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error("Erreur dans l'agrégateur de métriques", error=str(e))
                await asyncio.sleep(30)
                
    async def _alert_checker(self):
        while True:
            try:
                for rule in self.alert_rules:
                    if rule["condition"] == "error_rate > threshold":
                        total = self.real_time_stats["completed_today"] + self.real_time_stats["failed_today"]
                        if total > 0:
                            error_rate = (self.real_time_stats["failed_today"] / total) * 100
                            if error_rate > rule["threshold"]:
                                await self._trigger_alert(rule, {"error_rate": error_rate})
                                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error("Erreur dans le vérificateur d'alertes", error=str(e))
                await asyncio.sleep(60)
                
    async def _trigger_alert(self, rule: Dict, context: Dict):
        now = datetime.now()
        
        if rule["last_triggered"]:
            if (now - rule["last_triggered"]).seconds < 3600:
                return
                
        rule["last_triggered"] = now
        
        alert_message = {
            "type": "alert",
            "rule": rule["name"],
            "message": rule["message"],
            "context": context,
            "timestamp": now.isoformat()
        }
        
        logger.warning(
            f"🚨 ALERTE: {rule['name']}",
            rule=rule["name"],
            context=context
        )
        
        for client in self.connected_clients[:]:
            try:
                await client.send_json(alert_message)
            except:
                self.connected_clients.remove(client)
                
    async def _cleanup_old_metrics(self):
        while True:
            try:
                cutoff = datetime.now() - timedelta(hours=24)
                
                for metric_name, points in self.metrics_store.items():
                    while points and points[0].timestamp < cutoff:
                        points.popleft()
                        
                old_workflows = [
                    wf_id for wf_id, metrics in self.workflow_metrics.items()
                    if metrics.status in [WorkflowStatus.COMPLETED.value, WorkflowStatus.FAILED.value]
                    and (datetime.now() - datetime.fromisoformat(metrics.workflow_id.split("_")[-1]) if "_" in metrics.workflow_id else datetime.now()).days > 7
                ]
                
                for wf_id in old_workflows:
                    del self.workflow_metrics[wf_id]
                    
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error("Erreur dans le nettoyage des métriques", error=str(e))
                await asyncio.sleep(3600)
                
    def _is_today(self, timestamp: datetime) -> bool:
        return timestamp.date() == datetime.now().date()


monitoring_dashboard = MonitoringDashboard()

def monitor_workflow_step(step_name: str):
    def decorator(func):
        async def wrapper(state: WorkflowState, *args, **kwargs):
            workflow_id = getattr(getattr(state, 'task', None), 'task_id', "unknown") if getattr(state, 'task', None) else "unknown"
            
            start_time = time.time()
            
            try:
                await monitoring_dashboard.update_workflow_step(
                    workflow_id, 
                    step_name, 
                    getattr(state, 'current_progress', 0),
                    [f"Début de l'étape: {step_name}"]
                )
                
                result = await func(state, *args, **kwargs)
                
                execution_time = time.time() - start_time
                await monitoring_dashboard.update_workflow_step(
                    workflow_id,
                    step_name,
                    getattr(state, 'current_progress', 0) + 10,
                    [f"Étape terminée: {step_name}"]
                )
                
                logger.info(f"✅ Étape {step_name} terminée", extra={
                    "workflow_id": workflow_id,
                    "step_name": step_name,
                    "duration": execution_time,
                    "progress": getattr(state, 'current_progress', 0)
                })
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                await monitoring_dashboard.record_metric(
                    f"step_{step_name}_duration", 
                    duration,
                    {"workflow_id": workflow_id, "status": "error"}
                )
                
                await monitoring_dashboard.update_workflow_step(
                    workflow_id,
                    step_name,
                    getattr(state, 'current_progress', 0),
                    [f"Erreur dans l'étape: {step_name} - {str(e)}"]
                )
                
                raise
                
        return wrapper
    return decorator


@asynccontextmanager
async def workflow_monitoring_context(workflow_id: str, task_request: Dict):    
    try:
        await monitoring_dashboard.start_workflow_monitoring(workflow_id, task_request)
        yield monitoring_dashboard
    except Exception as e:
        await monitoring_dashboard.complete_workflow(workflow_id, False)
        raise
    else:
        await monitoring_dashboard.complete_workflow(workflow_id, True) 