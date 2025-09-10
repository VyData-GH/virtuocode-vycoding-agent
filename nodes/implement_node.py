from typing import Dict, Any, List

from models.schemas import WorkflowStatus
from tools.claude_code_tool import ClaudeCodeTool
from utils.logger import get_logger
from anthropic import Client
from config.settings import get_settings

logger = get_logger(__name__)

async def implement_task(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"💻 Implémentation de la tâche: {state.task.title}")
    
    state.results["current_status"] = "IN_PROGRESS".lower()
    state.results["ai_messages"].append("Début de l'implémentation...")
    
    try:
        working_directory = state.results.get("working_directory") if hasattr(state, "results") else None
        if not working_directory:
            error_msg = "Environnement non préparé - répertoire de travail manquant"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["last_operation_result"] = error_msg
            state.results["should_continue"] = False
            return state
        
        from tools.ai_engine_hub import ai_hub, AIRequest, TaskType, AIProvider
        
        claude_tool = ClaudeCodeTool()
        claude_tool.working_directory = working_directory
        
        task = state.task
        
        logger.info("📋 Analyse de la structure du projet...")
        project_analysis = await _analyze_project_structure(claude_tool)
        
        previous_errors = state.results.get("error_logs", []) if hasattr(state, "results") else []
        implementation_prompt = await _create_implementation_prompt(
            task, project_analysis, previous_errors
        )
        
        logger.info("🤖 Génération du plan d'implémentation avec le moteur IA...")
        
        ai_request = AIRequest(
            prompt=implementation_prompt,
            task_type=TaskType.CODE_GENERATION,
            context={"task": task.dict(), "project_analysis": project_analysis}
        )
        
        response = await ai_hub.generate_code(ai_request)
        
        if not response.success:
            error_msg = f"Erreur lors de la génération du plan: {response.error}"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["last_operation_result"] = error_msg
            state.results["should_continue"] = False
            return state
        
        implementation_plan = response.content
        state.results["ai_messages"].append(f"📋 Plan généré:\n{implementation_plan[:200]}...")
        
        success = await _execute_implementation_plan(
            claude_tool, anthropic_client, implementation_plan, task, state
        )
        
        if success:
            state.results["ai_messages"].append("✅ Implémentation terminée avec succès")
            state.results["last_operation_result"] = "Implémentation réussie"
            logger.info("✅ Implémentation terminée avec succès")
        else:
            state.results["ai_messages"].append("❌ Échec de l'implémentation")
            state.results["last_operation_result"] = "Échec implémentation"
            logger.error("❌ Échec de l'implémentation")
        
        state.results["should_continue"] = True
        
    except Exception as e:
        error_msg = f"Exception lors de l'implémentation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        state.results["error_logs"].append(error_msg)
        state.results["ai_messages"].append(f"❌ Exception: {error_msg}")
        state.results["last_operation_result"] = error_msg
        state.results["should_continue"] = True
    
    logger.info("🏁 Implémentation terminée")
    return state

async def _analyze_project_structure(claude_tool: ClaudeCodeTool) -> str:
    try:
        ls_result = await claude_tool._arun(action="execute_command", command="find . -type f -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.json' | head -20")
        
        structure_info = "Structure du projet:\n"
        if ls_result["success"]:
            structure_info += ls_result["stdout"]
        
        config_files = ["package.json", "requirements.txt", "setup.py", "README.md"]
        for config_file in config_files:
            try:
                config_result = await claude_tool._arun(action="read_file", file_path=config_file)
                if config_result["success"]:
                    structure_info += f"\n\n=== {config_file} ===\n"
                    structure_info += config_result["content"][:500] + "..."
            except:
                continue
        
        return structure_info
        
    except Exception as e:
        logger.warning(f"Impossible d'analyser la structure: {e}")
        return "Structure du projet non disponible"

async def _create_implementation_prompt(task, project_analysis: str, error_logs: List[str]) -> str:
    prompt = f"""Tu es un développeur expert. Tu dois implémenter la tâche suivante dans un projet existant.

## TÂCHE À IMPLÉMENTER
**Titre**: {task.title}
**Description**: {task.description}
**Branche**: {task.git_branch}
**Priorité**: {task.priority}

## CONTEXTE DU PROJET
{project_analysis}

## HISTORIQUE D'ERREURS (si tentatives précédentes)
{chr(10).join(error_logs) if error_logs else "Aucune erreur précédente"}

## INSTRUCTIONS

1. **Analyse** d'abord le code existant pour comprendre l'architecture.
2. **Planifie** les modifications nécessaires.
3. **Implémente** les changements de manière incrémentale.
4. **Respecte** les conventions du projet existant.

Réponds avec un plan d'implémentation structuré sous cette forme:

```
PLAN D'IMPLÉMENTATION

## 1. ANALYSE
- [Description de ce que tu as compris du projet]
- [Fichiers importants identifiés]

## 2. MODIFICATIONS REQUISES
- [Liste des fichiers à modifier/créer]
- [Description des changements pour chaque fichier]

## 3. ÉTAPES D'EXÉCUTION
1. [Première étape avec commandes/modifications]
2. [Deuxième étape avec commandes/modifications]
3. [etc.]

## 4. TESTS À VÉRIFIER
- [Tests ou validations à effectuer]
```

Sois précis et concret dans tes instructions."""

    return prompt

async def _execute_implementation_plan(
    claude_tool: ClaudeCodeTool, 
    anthropic_client: Client,
    implementation_plan: str,
    task,
    state: Dict[str, Any]
) -> bool:
    
    try:
        logger.info("🚀 Exécution du plan d'implémentation...")
        
        execution_prompt = f"""Maintenant, exécute le plan d'implémentation suivant étape par étape.

PLAN À EXÉCUTER:
{implementation_plan}

TÂCHE:
{task.description}

Pour chaque fichier que tu dois modifier ou créer, utilise ce format exact:

```action:modify_file
file_path: chemin/vers/fichier.py
description: Description de la modification
content:
[Le contenu complet du fichier modifié]
```

OU pour exécuter des commandes:

```action:execute_command
command: la commande à exécuter
```

Commence par la première étape maintenant. N'exécute qu'une seule action à la fois."""

        response = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=4000,
            messages=[{"role": "user", "content": execution_prompt}]
        )
        
        execution_steps = response.content[0].text
        
        success = await _parse_and_execute_actions(claude_tool, execution_steps, state)
        
        return success
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution du plan: {e}")
        state.results["error_logs"].append(f"Erreur exécution plan: {str(e)}")
        return False

async def _parse_and_execute_actions(claude_tool: ClaudeCodeTool, execution_text: str, state: Dict[str, Any]) -> bool:
    
    import re
    
    success_count = 0
    total_actions = 0
    
    action_pattern = r'```action:(\w+)\n(.*?)\n```'
    actions = re.findall(action_pattern, execution_text, re.DOTALL)
    
    for action_type, action_content in actions:
        total_actions += 1
        logger.info(f"🔧 Exécution action: {action_type}")
        
        try:
            if action_type == "modify_file":
                success = await _execute_file_modification(claude_tool, action_content, state)
            elif action_type == "execute_command":
                success = await _execute_command_action(claude_tool, action_content, state)
            else:
                logger.warning(f"Type d'action non reconnu: {action_type}")
                continue
            
            if success:
                success_count += 1
                
        except Exception as e:
            logger.error(f"Erreur lors de l'action {action_type}: {e}")
            state.results["error_logs"].append(f"Erreur action {action_type}: {str(e)}")
    
    if total_actions == 0:
        logger.info("Aucune action structurée trouvée, tentative de traitement direct...")
        code_blocks = re.findall(r'```(?:python|javascript|typescript)?\n(.*?)\n```', execution_text, re.DOTALL)
        
        if code_blocks:
            await _handle_direct_code_modification(claude_tool, code_blocks[0], state)
            return True
    
    success_rate = success_count / max(total_actions, 1)
    logger.info(f"📊 Actions exécutées: {success_count}/{total_actions} (taux: {success_rate:.1%})")
    
    return success_rate >= 0.5

async def _execute_file_modification(claude_tool: ClaudeCodeTool, action_content: str, state: Dict[str, Any]) -> bool:
    try:
        lines = action_content.strip().split('\n')
        file_path = None
        description = ""
        content = ""
        
        content_started = False
        for line in lines:
            if line.startswith('file_path:'):
                file_path = line.split(':', 1)[1].strip()
            elif line.startswith('description:'):
                description = line.split(':', 1)[1].strip()
            elif line.startswith('content:'):
                content_started = True
            elif content_started:
                content += line + '\n'
        
        if file_path and content:
            result = await claude_tool._arun(
                action="write_file",
                file_path=file_path,
                content=content.strip()
            )
            
            if result["success"]:
                state.results["code_changes"][file_path] = content.strip()
                state.results["modified_files"].append(file_path)
                state.results["ai_messages"].append(f"✅ Fichier modifié: {file_path}")
                logger.info(f"✅ Fichier modifié: {file_path}")

                return True
            else:
                error = result.get("error", "Erreur inconnue")
                state.results["error_logs"].append(f"Échec modification {file_path}: {error}")
                logger.error(f"❌ Échec modification {file_path}: {error}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur modification fichier: {e}")
        return False

async def _execute_command_action(claude_tool: ClaudeCodeTool, action_content: str, state: Dict[str, Any]) -> bool:
    try:
        command = None
        for line in action_content.strip().split('\n'):
            if line.startswith('command:'):
                command = line.split(':', 1)[1].strip()
                break
        
        if command:
            result = await claude_tool._arun(action="execute_command", command=command)
            
            if result["success"]:
                state.results["ai_messages"].append(f"✅ Commande exécutée: {command}")
                logger.info(f"✅ Commande exécutée: {command}")
                return True
            else:
                error = result.get("stderr", result.get("error", "Erreur inconnue"))
                state.results["error_logs"].append(f"Échec commande '{command}': {error}")
                logger.error(f"❌ Échec commande '{command}': {error}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur exécution commande: {e}")
        return False

async def _handle_direct_code_modification(claude_tool: ClaudeCodeTool, code_content: str, state: Dict[str, Any]) -> bool:
    try:
        if "def " in code_content or "import " in code_content:
            filename = "main.py"    
        elif "function " in code_content or "const " in code_content:
            filename = "main.js"
        else:
            filename = "implementation.txt"
        
        result = await claude_tool._arun(
            action="write_file",
            file_path=filename,
            content=code_content
        )
        
        if result["success"]:
            state.results["code_changes"][filename] = code_content
            state.results["modified_files"].append(filename)
            state.results["ai_messages"].append(f"✅ Code ajouté: {filename}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur modification directe: {e}")
        return False 