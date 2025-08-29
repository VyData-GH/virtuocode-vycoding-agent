import logging
import structlog
from rich.console import Console
from rich.logging import RichHandler
from typing import Any, Dict


def configure_logging(debug: bool = False, log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)    
    console = Console(force_terminal=True)
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=debug,
        markup=True,
        rich_tracebacks=True
    )
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[rich_handler]
    )
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            
            structlog.dev.ConsoleRenderer(colors=True) if debug 
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    if not hasattr(get_logger, '_configured'):
        configure_logging()
        get_logger._configured = True    
    return structlog.get_logger(name)


class LoggerMixin:    
    @property
    def logger(self) -> structlog.BoundLogger:
        if not hasattr(self, '_logger'):
            self._logger = get_logger(self.__class__.__module__)
        return self._logger


app_logger = get_logger("ai-automation-agent")


def log_workflow_step(step_name: str, task_id: str, **kwargs) -> None:
    app_logger.info(
        f"🔄 Étape: {step_name}",
        step=step_name,
        task_id=task_id,
        **kwargs
    )


def log_error(error: Exception, context: Dict[str, Any] = None) -> None:
    context = context or {}    
    app_logger.error(
        f"❌ Erreur: {str(error)}",
        error_type=type(error).__name__,
        error_message=str(error),
        **context,
        exc_info=True
    )


def log_success(message: str, **kwargs) -> None:
    app_logger.info(f"✅ {message}", **kwargs)


def log_warning(message: str, **kwargs) -> None:
    app_logger.warning(f"⚠️ {message}", **kwargs) 