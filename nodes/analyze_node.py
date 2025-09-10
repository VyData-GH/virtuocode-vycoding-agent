from typing import Dict, Any
from models.schemas import WorkflowStatus, WorkflowState
from tools.ai_engine_hub import ai_hub, AIRequest, TaskType
from utils.logger import get_logger

logger = get_logger(__name__)


async def analyze_requirements(state: WorkflowState) -> WorkflowState:
    if not state.task:
        logger.error("❌ Aucune tâche à analyser")
        state.error = "Aucune tâche fournie pour l'analyse"
        return state
        
    logger.info(f"🔍 Analyse des requirements pour: {state.task.title}")
    
    state.current_node = "analyze_requirements"
    if "analyze_requirements" not in state.completed_nodes:
        state.completed_nodes.append("analyze_requirements")
    
    try:
        task = state.task
        
        analysis_context = {
            "task_title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "priority": task.priority,
            "acceptance_criteria": task.acceptance_criteria,
            "technical_context": task.technical_context,
            "files_to_modify": task.files_to_modify,
            "estimated_complexity": task.estimated_complexity,
            "repository_url": task.repository_url
        }
        
        analysis_prompt = _create_analysis_prompt(analysis_context)
        
        logger.info("🤖 Génération du plan d'analyse avec AI Engine Hub...")
        
        ai_request = AIRequest(
            prompt=analysis_prompt,
            task_type=TaskType.ANALYSIS,
            context=analysis_context
        )
        
        response = await ai_hub.analyze_requirements(ai_request)
        
        if not response.success:
            error_msg = f"Erreur lors de l'analyse des requirements: {response.error}"
            logger.error(error_msg)
            state.error = error_msg
            return state
        
        analysis_result = _parse_analysis_response(response.content)
        
        if not state.results:
            state.results = {}
            
        state.results["requirements_analysis"] = analysis_result
        
        if analysis_result.get("refined_files_to_modify"):
            task.files_to_modify = analysis_result["refined_files_to_modify"]
        
        if analysis_result.get("refined_complexity"):
            task.estimated_complexity = analysis_result["refined_complexity"]
        
        implementation_plan = analysis_result.get("implementation_plan", {})
        estimated_effort = analysis_result.get("estimated_effort", "Unknown")
        risk_level = analysis_result.get("risk_level", "Medium")
        
        logger.info(f"✅ Analyse requirements terminée",
                   estimated_effort=estimated_effort,
                   risk_level=risk_level,
                   files_count=len(analysis_result.get("refined_files_to_modify", [])),
                   steps_count=len(implementation_plan.get("steps", [])))
        
        state.results["analysis_summary"] = {
            "complexity_score": analysis_result.get("complexity_score", 5),
            "estimated_duration_minutes": analysis_result.get("estimated_duration_minutes", 30),
            "requires_external_deps": analysis_result.get("requires_external_deps", False),
            "breaking_changes_risk": analysis_result.get("breaking_changes_risk", False),
            "test_strategy": analysis_result.get("test_strategy", "unit"),
            "implementation_approach": analysis_result.get("implementation_approach", "standard")
        }
        
        return state
        
    except Exception as e:
        error_msg = f"Exception lors de l'analyse des requirements: {str(e)}"
        logger.error(error_msg, exc_info=True)
        state.error = error_msg
        return state


def _create_analysis_prompt(context: Dict[str, Any]) -> str:
    prompt = f"""
# 🔍 ANALYSE DÉTAILLÉE DES REQUIREMENTS - AI-Agent

Tu es un expert en analyse de requirements pour le développement logiciel automatisé.
Analyse en profondeur cette tâche et génère un plan d'implémentation structuré.

## 📋 INFORMATIONS DE LA TÂCHE

**Titre**: {context['task_title']}
**Type**: {context['task_type']}
**Priorité**: {context['priority']}

**Description**: 
{context['description']}

**Critères d'acceptation**:
{context.get('acceptance_criteria', 'Non spécifiés')}

**Contexte technique**:
{context.get('technical_context', 'Non spécifié')}

**Fichiers suggérés à modifier**:
{context.get('files_to_modify', 'Non spécifiés')}

**Complexité estimée initiale**: {context.get('estimated_complexity', 'Non évaluée')}

**Repository**: {context['repository_url']}

## 🎯 TÂCHES D'ANALYSE REQUISES

Fournis une analyse structurée au format JSON avec les clés suivantes :

```json
{{
    "summary": "Résumé en 2-3 phrases de ce qui doit être fait",
    "complexity_analysis": {{
        "complexity_score": "Nombre de 1 à 10",
        "complexity_factors": ["Liste des facteurs de complexité"],
        "technical_challenges": ["Défis techniques identifiés"]
    }},
    "implementation_plan": {{
        "approach": "Approche d'implémentation recommandée",
        "steps": [
            {{
                "step": 1,
                "description": "Description de l'étape",
                "estimated_time_minutes": 15,
                "dependencies": ["Dépendances de cette étape"],
                "deliverables": ["Livrables de cette étape"]
            }}
        ]
    }},
    "files_analysis": {{
        "refined_files_to_modify": ["Liste affinée des fichiers à modifier"],
        "new_files_to_create": ["Nouveaux fichiers à créer"],
        "files_to_test": ["Fichiers nécessitant des tests spécifiques"]
    }},
    "requirements_breakdown": {{
        "functional_requirements": ["Requirements fonctionnels"],
        "non_functional_requirements": ["Requirements non-fonctionnels"],
        "acceptance_criteria_refined": ["Critères d'acceptation détaillés"]
    }},
    "risk_assessment": {{
        "risk_level": "Low/Medium/High",
        "potential_risks": ["Risques identifiés"],
        "mitigation_strategies": ["Stratégies d'atténuation"]
    }},
    "testing_strategy": {{
        "test_types_needed": ["unit", "integration", "e2e"],
        "test_scenarios": ["Scénarios de test clés"],
        "edge_cases": ["Cas limites à tester"]
    }},
    "external_dependencies": {{
        "requires_external_deps": false,
        "new_packages_needed": ["Nouveaux packages requis"],
        "api_integrations": ["Intégrations API nécessaires"]
    }},
    "estimated_effort": {{
        "estimated_duration_minutes": 45,
        "confidence_level": "High/Medium/Low",
        "effort_breakdown": {{
            "analysis": 10,
            "implementation": 25,
            "testing": 10,
            "debugging": 5,
            "documentation": 5
        }}
    }},
    "success_criteria": {{
        "definition_of_done": ["Critères de fin de tâche"],
        "quality_gates": ["Seuils de qualité à respecter"],
        "acceptance_tests": ["Tests d'acceptation à valider"]
    }}
}}
```

## 🚨 INSTRUCTIONS IMPORTANTES

1. **Sois spécifique** : Évite les généralités, donne des détails concrets
2. **Pense aux dépendances** : Identifie les interconnexions entre composants
3. **Considère la maintenance** : L'impact sur le code existant
4. **Anticipe les problèmes** : Les points de friction potentiels
5. **Optimise pour l'automatisation** : Plan adapté à l'exécution par AI-Agent

Réponds UNIQUEMENT avec le JSON structuré, sans texte additionnel.
"""
    
    return prompt


def _parse_analysis_response(response_content: str) -> Dict[str, Any]:
    """Parse et valide la réponse d'analyse IA."""
    
    import json
    import re
    
    try:
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            analysis_result = json.loads(json_str)
        else:
            analysis_result = {"error": "Format de réponse invalide"}
        
        default_analysis = {
            "summary": "Analyse en cours...",
            "complexity_score": 5,
            "estimated_duration_minutes": 30,
            "risk_level": "Medium",
            "refined_files_to_modify": [],
            "implementation_plan": {"steps": []},
            "requires_external_deps": False,
            "breaking_changes_risk": False,
            "test_strategy": "unit",
            "implementation_approach": "standard"
        }
        
        for key, default_value in default_analysis.items():
            if key not in analysis_result:
                analysis_result[key] = default_value
        
        if "complexity_analysis" in analysis_result:
            analysis_result["complexity_score"] = analysis_result["complexity_analysis"].get("complexity_score", 5)
        
        if "estimated_effort" in analysis_result:
            analysis_result["estimated_duration_minutes"] = analysis_result["estimated_effort"].get("estimated_duration_minutes", 30)
        
        if "risk_assessment" in analysis_result:
            analysis_result["risk_level"] = analysis_result["risk_assessment"].get("risk_level", "Medium")
        
        if "files_analysis" in analysis_result:
            analysis_result["refined_files_to_modify"] = analysis_result["files_analysis"].get("refined_files_to_modify", [])
        
        if "external_dependencies" in analysis_result:
            analysis_result["requires_external_deps"] = analysis_result["external_dependencies"].get("requires_external_deps", False)
        
        return analysis_result
        
    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON analyse: {e}")
        return {
            "error": f"Erreur parsing: {str(e)}",
            "raw_response": response_content[:500],  # Premiers 500 caractères pour debug
            "complexity_score": 5,
            "estimated_duration_minutes": 30,
            "risk_level": "Medium",
            "refined_files_to_modify": [],
            "implementation_plan": {"steps": []},
            "requires_external_deps": False
        }
    except Exception as e:
        logger.error(f"Erreur inattendue parsing analyse: {e}")
        return {
            "error": f"Erreur inattendue: {str(e)}",
            "complexity_score": 5,
            "estimated_duration_minutes": 30,
            "risk_level": "High",
            "refined_files_to_modify": [],
            "implementation_plan": {"steps": []},
            "requires_external_deps": False
        } 