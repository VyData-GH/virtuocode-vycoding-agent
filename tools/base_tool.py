from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from langchain.tools import BaseTool as LangChainBaseTool
from pydantic import Field

from config.settings import get_settings
from utils.logger import get_logger


class BaseTool(LangChainBaseTool, ABC):
    settings: Any = Field(default_factory=get_settings)
    logger: Any = Field(default_factory=lambda: get_logger(__name__))
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)
    
    @abstractmethod
    async def _arun(self, *args, **kwargs) -> Any:
        pass
    
    def _run(self, *args, **kwargs) -> Any:
        import asyncio
        return asyncio.run(self._arun(*args, **kwargs))
    
    def log_operation(self, operation: str, success: bool, details: Optional[str] = None):
        log_level = "info" if success else "error"
        message = f"{operation} - {'Succès' if success else 'Échec'}"
        if details:
            message += f": {details}"
        getattr(self.logger, log_level)(message)
    
    def handle_error(self, error: Exception, operation: str) -> Dict[str, Any]: 
        error_msg = f"Erreur lors de {operation}: {str(error)}"
        self.logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "error": error_msg,
            "operation": operation
        } 