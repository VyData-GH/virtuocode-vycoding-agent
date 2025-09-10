from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from enum import Enum
from pydantic import BaseModel
import asyncio

from anthropic import Client as AnthropicClient
from openai import OpenAI
from config.settings import get_settings
from utils.logger import get_logger


class AIProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"


class TaskType(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REFACTORING = "refactoring"
    ANALYSIS = "analysis"


class AIRequest(BaseModel):
    prompt: str
    task_type: TaskType
    context: Optional[Dict[str, Any]] = None
    max_tokens: int = 4000
    temperature: float = 0.1


class AIResponse(BaseModel):
    content: str
    provider: AIProvider
    model_used: str
    tokens_used: Optional[int] = None
    success: bool = True
    error: Optional[str] = None


class AIProviderInterface(ABC):
    
    @abstractmethod
    async def generate_code(self, request: AIRequest) -> AIResponse:
        pass
    
    @abstractmethod
    async def analyze_requirements(self, task: Dict[str, Any]) -> AIResponse:
        pass
    
    @abstractmethod
    async def review_code(self, code: str, context: str = "") -> AIResponse:
        pass
    
    @abstractmethod
    async def debug_code(self, code: str, error: str, context: str = "") -> AIResponse:
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        pass


class ClaudeProvider(AIProviderInterface):
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)
        self.client = AnthropicClient(api_key=self.settings.anthropic_api_key)
        self.model = "claude-3-sonnet-20240229"
    
    async def generate_code(self, request: AIRequest) -> AIResponse:
        try:
            prompt = self._build_code_prompt(request)
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return AIResponse(
                content=response.content[0].text,
                provider=AIProvider.CLAUDE,
                model_used=self.model,
                tokens_used=response.usage.output_tokens if hasattr(response, 'usage') else None
            )
            
        except Exception as e:
            self.logger.error(f"Erreur Claude: {e}")
            return AIResponse(
                content="",
                provider=AIProvider.CLAUDE,
                model_used=self.model,
                success=False,
                error=str(e)
            )
    
    async def analyze_requirements(self, task: Dict[str, Any]) -> AIResponse:
        prompt = f"""
Analyse la tâche suivante et fournis une analyse détaillée :

Titre: {task.get('title', '')}
Description: {task.get('description', '')}
Contexte: {task.get('context', '')}

Fournis :
1. Résumé des exigences
2. Technologies recommandées
3. Plan d'implémentation étape par étape
4. Risques potentiels et mitigations
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.CODE_GENERATION,
            context=task
        )
        
        return await self.generate_code(request)
    
    async def review_code(self, code: str, context: str = "") -> AIResponse:
        prompt = f"""
Effectue une revue détaillée du code suivant :

Code :
```
{code}
```

Contexte : {context}

Analyse :
1. Qualité du code et bonnes pratiques
2. Sécurité et vulnérabilités potentielles
3. Performance et optimisations
4. Tests manquants
5. Documentation nécessaire
6. Suggestions d'amélioration
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.CODE_REVIEW,
            context={"code": code, "context": context}
        )
        
        return await self.generate_code(request)
    
    async def debug_code(self, code: str, error: str, context: str = "") -> AIResponse:
        prompt = f"""
Aide-moi à débugger ce code qui produit l'erreur suivante :

Erreur : {error}

Code problématique :
```
{code}
```

Contexte : {context}

Fournis :
1. Analyse de la cause de l'erreur
2. Solution corrigée
3. Explication de la correction
4. Suggestions pour éviter ce type d'erreur
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.DEBUGGING,
            context={"code": code, "error": error, "context": context}
        )
        
        return await self.generate_code(request)
    
    def is_available(self) -> bool:
        return bool(self.settings.anthropic_api_key)
    
    def _build_code_prompt(self, request: AIRequest) -> str:
        context_str = ""
        if request.context:
            context_str = f"\nContexte : {request.context}"
        
        return f"""Tu es un développeur expert. {request.prompt}{context_str}

Fournis uniquement le code demandé, bien structuré et commenté."""


class OpenAIProvider(AIProviderInterface):
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model = "gpt-4"
    
    async def generate_code(self, request: AIRequest) -> AIResponse:
        try:
            prompt = self._build_code_prompt(request)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=request.max_tokens,
                temperature=request.temperature
            )
            
            return AIResponse(
                content=response.choices[0].message.content,
                provider=AIProvider.OPENAI,
                model_used=self.model,
                tokens_used=response.usage.total_tokens if response.usage else None
            )
            
        except Exception as e:
            self.logger.error(f"Erreur OpenAI: {e}")
            return AIResponse(
                content="",
                provider=AIProvider.OPENAI,
                model_used=self.model,
                success=False,
                error=str(e)
            )
    
    async def analyze_requirements(self, task: Dict[str, Any]) -> AIResponse:
        prompt = f"""
Analyse cette tâche de développement :

Titre: {task.get('title', '')}
Description: {task.get('description', '')}

Fournis une analyse structurée incluant :
- Compréhension des exigences
- Architecture recommandée  
- Plan d'implémentation
- Considérations techniques
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.CODE_GENERATION,
            context=task
        )
        
        return await self.generate_code(request)
    
    async def review_code(self, code: str, context: str = "") -> AIResponse:
        prompt = f"""
Revue de code détaillée :

```{code}```

Contexte: {context}

Analyse la qualité, sécurité, performance et fournis des améliorations.
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.CODE_REVIEW
        )
        
        return await self.generate_code(request)
    
    async def debug_code(self, code: str, error: str, context: str = "") -> AIResponse:
        prompt = f"""
Debug ce code qui produit l'erreur: {error}

Code:
```{code}```

Contexte: {context}

Fournis la solution corrigée avec explication.
"""
        
        request = AIRequest(
            prompt=prompt,
            task_type=TaskType.DEBUGGING
        )
        
        return await self.generate_code(request)
    
    def is_available(self) -> bool:
        return bool(self.settings.openai_api_key)
    
    def _build_code_prompt(self, request: AIRequest) -> str:
        return f"{request.prompt}\n\nFournis du code de qualité production avec commentaires."


class AIEngineHub:
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.providers: Dict[AIProvider, AIProviderInterface] = {}
        self._initialize_providers()
        
        self.task_preferences = {
            TaskType.CODE_GENERATION: [AIProvider.CLAUDE, AIProvider.OPENAI],
            TaskType.CODE_REVIEW: [AIProvider.CLAUDE, AIProvider.OPENAI],
            TaskType.DEBUGGING: [AIProvider.CLAUDE, AIProvider.OPENAI],
            TaskType.DOCUMENTATION: [AIProvider.OPENAI, AIProvider.CLAUDE],
            TaskType.TESTING: [AIProvider.CLAUDE, AIProvider.OPENAI],
            TaskType.REFACTORING: [AIProvider.CLAUDE, AIProvider.OPENAI],
            TaskType.ANALYSIS: [AIProvider.CLAUDE, AIProvider.OPENAI]
        }
    
    def _initialize_providers(self):
        claude = ClaudeProvider()
        if claude.is_available():
            self.providers[AIProvider.CLAUDE] = claude
            self.logger.info("✅ Claude provider initialisé")
        
        openai = OpenAIProvider()
        if openai.is_available():
            self.providers[AIProvider.OPENAI] = openai
            self.logger.info("✅ OpenAI provider initialisé")
        
        if not self.providers:
            self.logger.warning("⚠️ Aucun provider IA disponible")
    
    def get_best_provider(self, task_type: TaskType, preferred_provider: Optional[AIProvider] = None) -> Optional[AIProviderInterface]:
        if preferred_provider and preferred_provider in self.providers:
            return self.providers[preferred_provider]
        
        preferences = self.task_preferences.get(task_type, list(self.providers.keys()))
        
        for provider in preferences:
            if provider in self.providers:
                self.logger.info(f"🤖 Provider sélectionné: {provider.value} pour {task_type.value}")
                return self.providers[provider]
        
        self.logger.error(f"❌ Aucun provider disponible pour {task_type.value}")
        return None
    
    async def generate_code(self, request: AIRequest, preferred_provider: Optional[AIProvider] = None) -> AIResponse:
        provider = self.get_best_provider(request.task_type, preferred_provider)
        
        if not provider:
            return AIResponse(
                content="",
                provider=AIProvider.CLAUDE,
                model_used="none",
                success=False,
                error="Aucun provider IA disponible"
            )
        
        return await provider.generate_code(request)
    
    async def analyze_requirements(self, request: AIRequest, preferred_provider: Optional[AIProvider] = None) -> AIResponse:
        provider = self.get_best_provider(TaskType.ANALYSIS, preferred_provider)
        
        if not provider:
            return AIResponse(
                content="Analyse impossible - aucun provider disponible",
                provider=AIProvider.CLAUDE,
                model_used="none",
                success=False,
                error="Aucun provider IA disponible"
            )
        
        return await provider.analyze_requirements(request.context or {})
    
    async def review_code(self, code: str, context: str = "", preferred_provider: Optional[AIProvider] = None) -> AIResponse:
        provider = self.get_best_provider(TaskType.CODE_REVIEW, preferred_provider)
        
        if not provider:
            return AIResponse(
                content="Revue impossible - aucun provider disponible",
                provider=AIProvider.CLAUDE,
                model_used="none",
                success=False,
                error="Aucun provider IA disponible"
            )
        
        return await provider.review_code(code, context)
    
    async def debug_code(self, code: str, error: str, context: str = "", preferred_provider: Optional[AIProvider] = None) -> AIResponse:
        provider = self.get_best_provider(TaskType.DEBUGGING, preferred_provider)
        
        if not provider:
            return AIResponse(
                content="Debug impossible - aucun provider disponible",
                provider=AIProvider.CLAUDE,
                model_used="none",
                success=False,
                error="Aucun provider IA disponible"
            )
        
        return await provider.debug_code(code, error, context)
    
    def get_available_providers(self) -> List[AIProvider]:
        return list(self.providers.keys())
    
    def get_provider_stats(self) -> Dict[str, Any]:
        return {
            "available_providers": [p.value for p in self.providers.keys()],
            "total_providers": len(self.providers),
            "task_preferences": {t.value: [p.value for p in prefs] for t, prefs in self.task_preferences.items()}
        }


ai_hub = AIEngineHub() 