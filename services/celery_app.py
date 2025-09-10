from celery import Celery
from celery.signals import worker_ready, worker_shutting_down
from kombu import Exchange, Queue
from typing import Dict, Any, Optional
import asyncio
import os

from config.settings import get_settings
from models.schemas import TaskRequest
from graph.workflow_graph import run_workflow
from services.webhook_service import WebhookService
from services.monitoring_service import monitoring_dashboard
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

celery_app = Celery(
    "ai_agent_background",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["services.celery_app"]  
)

default_exchange = Exchange('ai_agent', type='topic')

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_pool_limit=10,
    
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    task_soft_time_limit=1500,    # 25 minutes
    task_time_limit=1800,         # 30 minutes
    
    task_default_exchange='ai_agent',
    task_default_exchange_type='topic',
    task_default_routing_key='task.default',
    task_create_missing_queues=True,
    
    task_queues=[
        Queue('webhooks', 
              exchange=default_exchange, 
              routing_key='webhook.*',
              queue_arguments={
                  'x-max-priority': 10,
                  'x-message-ttl': 900000,  # 15 minutes TTL
                  'x-dead-letter-exchange': 'ai_agent',
                  'x-dead-letter-routing-key': 'dead_letter.webhook'
              }),
        
        Queue('workflows', 
              exchange=default_exchange, 
              routing_key='workflow.*',
              queue_arguments={
                  'x-max-priority': 5,
                  'x-message-ttl': 3600000,  # 1 heure TTL
                  'x-dead-letter-exchange': 'ai_agent',
                  'x-dead-letter-routing-key': 'dead_letter.workflow'
              }),
        
        Queue('ai_generation', 
              exchange=default_exchange, 
              routing_key='ai.*',
              queue_arguments={
                  'x-max-priority': 7,
                  'x-message-ttl': 1800000,  # 30 minutes TTL
                  'x-dead-letter-exchange': 'ai_agent',
                  'x-dead-letter-routing-key': 'dead_letter.ai'
              }),
        
        Queue('tests', 
              exchange=default_exchange, 
              routing_key='test.*',
              queue_arguments={
                  'x-max-priority': 3,
                  'x-message-ttl': 1200000,  # 20 minutes TTL
                  'x-dead-letter-exchange': 'ai_agent',
                  'x-dead-letter-routing-key': 'dead_letter.test'
              }),
        
        Queue('dlq', 
              exchange=default_exchange, 
              routing_key='dead_letter.*',
              queue_arguments={
                  'x-message-ttl': 86400000,  # 24 heures TTL
              }),
    ],
    
    task_routes={
        "ai_agent_background.process_monday_webhook": {
            "queue": "webhooks",
            "routing_key": "webhook.monday",
            "priority": 9
        },
        "ai_agent_background.execute_workflow": {
            "queue": "workflows", 
            "routing_key": "workflow.langgraph",
            "priority": 5
        },
        "ai_agent_background.generate_code": {
            "queue": "ai_generation",
            "routing_key": "ai.generate.code",
            "priority": 7
        },
        "ai_agent_background.run_tests": {
            "queue": "tests",
            "routing_key": "test.execute",
            "priority": 3
        },
        "ai_agent_background.handle_dead_letter": {
            "queue": "dlq",
            "routing_key": "dead_letter.handler",
            "priority": 1
        }
    },
    
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    worker_disable_rate_limits=True,
    task_compression='gzip',
    result_compression='gzip',
    result_expires=3600,  # 1 heure
)


webhook_service = WebhookService()


@celery_app.task(
    bind=True, 
    name="ai_agent_background.process_monday_webhook",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 60},
    priority=9
)
def process_monday_webhook(self, payload: Dict[str, Any], signature: Optional[str] = None):
    task_id = self.request.id
    
    try:
        logger.info(f"🚀 Démarrage traitement webhook Celery", 
                   task_id=task_id, 
                   queue="webhooks",
                   routing_key="webhook.monday")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                webhook_service.process_webhook(payload, signature)
            )
            
            logger.info(f"✅ Webhook traité avec succès", 
                       task_id=task_id, 
                       success=result.get('success', False))
            
            return {
                "task_id": task_id,
                "status": "completed",
                "result": result,
                "webhook_payload": payload,
                "queue": "webhooks"
            }
            
        finally:
            loop.close()
            
    except Exception as exc:
        logger.error(f"❌ Erreur traitement webhook", 
                    task_id=task_id, 
                    error=str(exc), 
                    exc_info=True)
        
        if self.request.retries < self.max_retries:
            logger.info(f"🔄 Retry {self.request.retries + 1}/{self.max_retries}", task_id=task_id)
            raise self.retry(countdown=60, exc=exc)
        else:
            handle_dead_letter.delay({
                "original_task": "process_monday_webhook",
                "task_id": task_id,
                "payload": payload,
                "signature": signature,
                "error": str(exc),
                "retries_exhausted": True,
                "timestamp": task_id
            })
            
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
                "retries_exhausted": True,
                "sent_to_dlq": True
            }


@celery_app.task(
    bind=True, 
    name="ai_agent_background.execute_workflow",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 120},
    priority=5
)
def execute_workflow(self, task_request_dict: Dict[str, Any]):
    task_id = self.request.id
    workflow_id = f"celery_{task_id}"
    
    try:
        task_request = TaskRequest(**task_request_dict)
        
        logger.info(f"🔄 Démarrage workflow LangGraph", 
                   task_id=task_id,
                   workflow_title=task_request.title,
                   queue="workflows")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(
                monitoring_dashboard.start_workflow_monitoring(workflow_id, task_request_dict)
            )
            
            result = loop.run_until_complete(run_workflow(task_request))
            
            loop.run_until_complete(
                monitoring_dashboard.complete_workflow(workflow_id, result.get('success', False), result)
            )
            
            logger.info(f"✅ Workflow terminé", 
                       task_id=task_id,
                       success=result.get('success', False),
                       duration=result.get('duration', 0))
            
            return {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "status": "completed",
                "result": result,
                "queue": "workflows"
            }
            
        finally:
            loop.close()
            
    except Exception as exc:
        logger.error(f"❌ Erreur workflow", 
                    task_id=task_id, 
                    error=str(exc), 
                    exc_info=True)
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                monitoring_dashboard.complete_workflow(workflow_id, False)
            )
            loop.close()
        except:
            pass
        
        if self.request.retries < self.max_retries:
            logger.info(f"🔄 Retry workflow {self.request.retries + 1}/{self.max_retries}", task_id=task_id)
            raise self.retry(countdown=120, exc=exc)  # 2 minutes entre retries
        else:
            handle_dead_letter.delay({
                "original_task": "execute_workflow", 
                "task_id": task_id,
                "task_request": task_request_dict,
                "workflow_id": workflow_id,
                "error": str(exc),
                "retries_exhausted": True
            })
            
            return {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(exc),
                "retries_exhausted": True,
                "sent_to_dlq": True
            }


@celery_app.task(
    bind=True, 
    name="ai_agent_background.generate_code",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 2, 'countdown': 30},
    priority=7
)
def generate_code_task(self, prompt: str, provider: str = "claude", context: Dict[str, Any] = None):
    task_id = self.request.id
    
    try:
        from tools.ai_engine_hub import AIEngineHub
        
        logger.info(f"🤖 Génération code IA", 
                   task_id=task_id, 
                   provider=provider,
                   queue="ai_generation")
        
        ai_hub = AIEngineHub()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                ai_hub.generate_code(prompt, provider, context or {})
            )
            
            logger.info(f"✅ Code généré", 
                       task_id=task_id,
                       provider=provider,
                       tokens_used=result.get('tokens_used', 0))
            
            return {
                "task_id": task_id,
                "status": "completed",
                "provider": provider,
                "result": result,
                "queue": "ai_generation"
            }
            
        finally:
            loop.close()
            
    except Exception as exc:
        logger.error(f"❌ Erreur génération code", 
                    task_id=task_id, 
                    provider=provider,
                    error=str(exc), 
                    exc_info=True)
        
        if self.request.retries < self.max_retries:
            alt_provider = "openai" if provider == "claude" else "claude"
            logger.info(f"🔄 Retry avec {alt_provider}", task_id=task_id)
            
            return generate_code_task.retry(
                countdown=30,
                exc=exc,
                args=[prompt, alt_provider, context]
            )
        else:
            handle_dead_letter.delay({
                "original_task": "generate_code",
                "task_id": task_id,
                "prompt": prompt,
                "provider": provider,
                "context": context,
                "error": str(exc),
                "retries_exhausted": True
            })
            
            return {
                "task_id": task_id,
                "status": "failed",
                "provider": provider,
                "error": str(exc),
                "retries_exhausted": True,
                "sent_to_dlq": True
            }


@celery_app.task(
    bind=True, 
    name="ai_agent_background.run_tests",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 2, 'countdown': 30},
    priority=3
)
def run_tests_task(self, workflow_id: str, code_changes: Dict[str, str], test_types: list = None):
    task_id = self.request.id
    test_types = test_types or ["unit", "integration", "security"]
    
    try:
        from tools.testing_engine import TestingEngine
        
        logger.info(f"🧪 Exécution tests", 
                   task_id=task_id,
                   workflow_id=workflow_id,
                   test_types=test_types,
                   queue="tests")
        
        testing_engine = TestingEngine()
        

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(
                testing_engine.run_comprehensive_tests(code_changes, test_types)
            )
            
            total_tests = sum(len(result.get('results', [])) for result in results.values())
            passed_tests = sum(
                len([r for r in result.get('results', []) if r.get('passed', False)]) 
                for result in results.values()
            )
            
            logger.info(f"✅ Tests terminés", 
                       task_id=task_id,
                       total_tests=total_tests,
                       passed_tests=passed_tests,
                       success_rate=f"{(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "0%")
            
            return {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "status": "completed",
                "results": results,
                "summary": {
                    "total_tests": total_tests,
                    "passed_tests": passed_tests,
                    "failed_tests": total_tests - passed_tests,
                    "success_rate": (passed_tests/total_tests*100) if total_tests > 0 else 0
                },
                "queue": "tests"
            }
            
        finally:
            loop.close()
            
    except Exception as exc:
        logger.error(f"❌ Erreur tests", 
                    task_id=task_id,
                    error=str(exc), 
                    exc_info=True)
        
        if self.request.retries < 2:
            logger.info(f"🔄 Retry tests {self.request.retries + 1}/2", task_id=task_id)
            raise self.retry(countdown=30, exc=exc)
        else:
            # Envoyer vers DLQ
            handle_dead_letter.delay({
                "original_task": "run_tests",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "code_changes": code_changes,
                "test_types": test_types,
                "error": str(exc),
                "retries_exhausted": True
            })
            
            return {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(exc),
                "retries_exhausted": True,
                "sent_to_dlq": True
            }


@celery_app.task(name="ai_agent_background.handle_dead_letter", priority=1)
def handle_dead_letter(failed_task_data: Dict[str, Any]):
    try:
        task_id = failed_task_data.get("task_id", "unknown")
        original_task = failed_task_data.get("original_task", "unknown")
        error = failed_task_data.get("error", "Unknown error")
        
        logger.error(f"💀 Tâche en Dead Letter Queue", 
                    dlq_task_id=task_id,
                    original_task=original_task,
                    error=error,
                    queue="dlq")
        
        # TODO: Implémenter stockage en DB des échecs
        
        # TODO: Implémenter notification email/Slack
        
        return {
            "dlq_processed": True,
            "original_task": original_task,
            "task_id": task_id,
            "timestamp": failed_task_data.get("timestamp"),
            "action": "logged_and_stored"
        }
        
    except Exception as exc:
        logger.error(f"❌ Erreur traitement DLQ", error=str(exc))
        return {
            "dlq_processed": False,
            "error": str(exc)
        }


@celery_app.task(name="ai_agent_background.cleanup_old_tasks")
def cleanup_old_tasks():
    try:
        from datetime import datetime, timedelta
        
        logger.info("🧹 Nettoyage des anciennes tâches Celery")
        
        celery_app.backend.cleanup()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            pass
        finally:
            loop.close()
            
        logger.info("✅ Nettoyage terminé")
        return {"status": "completed", "timestamp": datetime.now().isoformat()}
        
    except Exception as exc:
        logger.error(f"❌ Erreur nettoyage", error=str(exc))
        return {"status": "failed", "error": str(exc)}


celery_app.conf.beat_schedule = {
    "cleanup-old-tasks": {
        "task": "ai_agent_background.cleanup_old_tasks",
        "schedule": 24 * 60 * 60,
    },
}


@worker_ready.connect
def worker_ready_handler(sender=None, **kwargs):
    logger.info(f"🚀 Celery worker prêt", 
               worker=sender,
               broker="RabbitMQ",
               backend="PostgreSQL")


@worker_shutting_down.connect
def worker_shutting_down_handler(sender=None, **kwargs):
    logger.info(f"🛑 Celery worker arrêt", worker=sender)


def submit_task(task_name: str, *args, **kwargs):
    try:
        task_options = {}
        if 'priority' in kwargs:
            task_options['priority'] = kwargs.pop('priority')
            
        task = celery_app.send_task(task_name, args=args, kwargs=kwargs, **task_options)
        logger.info(f"📨 Tâche soumise", 
                   task_name=task_name, 
                   task_id=task.id,
                   broker="RabbitMQ")
        return task
    except Exception as exc:
        logger.error(f"❌ Erreur soumission tâche", 
                    task_name=task_name, 
                    error=str(exc))
        raise


if __name__ == "__main__":
    celery_app.start() 