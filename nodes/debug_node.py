from typing import Dict, Any

from models.schemas import WorkflowStatus
from tools.claude_code_tool import ClaudeCodeTool
from utils.logger import get_logger
from anthropic import Client
from config.settings import get_settings

logger = get_logger(__name__)

async def debug_code(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"🔧 Debug en cours pour: {state.task.title}")
    
    state.results["current_status"] = "DEBUGGING".lower()
    state.results["debug_attempts"] += 1
    state.results["ai_messages"].append(f"Début du debug (tentative {state.debug_attempts}/{state.max_debug_attempts})...")
    
    try:
        if not state.results["test_results"]:
            error_msg = "Aucun résultat de test disponible pour le debug"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["should_continue"] = False
            return state
        
        latest_test_result = state.results["test_results"][-1]
        
        if latest_test_result.success:
            state.results["ai_messages"].append("✅ Tests déjà réussis, pas de debug nécessaire")
            state.results["should_continue"] = True
            return state
        
        claude_tool = ClaudeCodeTool()
        claude_tool.working_directory = state.results["working_directory"]
        
        settings = get_settings()
        anthropic_client = Client(api_key=settings.anthropic_api_key)
        
        logger.info("🔍 Analyse détaillée de l'erreur...")
        error_analysis = await _analyze_error_in_detail(
            latest_test_result, state, claude_tool
        )
        
        debug_prompt = await _create_debug_prompt(
            state.task, latest_test_result, error_analysis, state
        )
        
        logger.info("🤖 Génération de correctifs avec Claude...")
        
        response = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=4000,
            messages=[{
                "role": "user", 
                "content": debug_prompt
            }]
        )
        
        debug_solution = response.content[0].text
        state.results["ai_messages"].append(f"🔧 Solution proposée:\n{debug_solution[:200]}...")
        
        success = await _apply_debug_corrections(
            claude_tool, anthropic_client, debug_solution, state
        )
        
        if success:
            state.results["ai_messages"].append("✅ Corrections appliquées avec succès")
            state.results["last_operation_result"] = f"Debug réussi (tentative {state.debug_attempts})"
            logger.info(f"✅ Corrections appliquées - Tentative {state.debug_attempts}")
        else:
            state.results["ai_messages"].append("❌ Échec de l'application des corrections")
            state.results["last_operation_result"] = f"Debug échoué (tentative {state.debug_attempts})"
            logger.error(f"❌ Échec des corrections - Tentative {state.debug_attempts}")
        
        state.results["should_continue"] = True
        
    except Exception as e:
        error_msg = f"Exception lors du debug: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        state.results["error_logs"].append(error_msg)
        state.results["ai_messages"].append(f"❌ Exception debug: {error_msg}")
        state.results["last_operation_result"] = error_msg
        state.results["should_continue"] = True
    
    logger.info(f"🏁 Debug terminé - Tentative {state.debug_attempts}/{state.max_debug_attempts}")
    return state

async def _analyze_error_in_detail(test_result, state: Dict[str, Any], claude_tool: ClaudeCodeTool) -> str:
    analysis = f"""ANALYSE D'ERREUR DÉTAILLÉE

## Résultat du test
- Commande: {test_result.test_command}
- Code de sortie: {test_result.exit_code}
- Durée: {test_result.duration:.2f}s

## Sortie standard:
{test_result.stdout}

## Erreurs:
{test_result.stderr}

## Fichiers modifiés dans cette session:
{', '.join(state.get('modified_files', [])) or 'Aucun'}

## Changements de code récents:
"""
    
    for file_path, content in state.get("code_changes", {}).items():
        analysis += f"\n### {file_path}:\n```\n{content[:500]}...\n```\n"
    
    try:
        log_files = ["error.log", "debug.log", "test.log", ".pytest_cache/README.md"]
        for log_file in log_files:
            log_result = await claude_tool._arun(action="read_file", file_path=log_file)
            if log_result["success"]:
                analysis += f"\n### Contenu {log_file}:\n{log_result['content'][:300]}...\n"
    except:
        pass
    
    return analysis

async def _create_debug_prompt(task, test_result, error_analysis: str, state: Dict[str, Any]) -> str:
    prompt = f"""Tu es un expert en debugging. Tu dois analyser et corriger les erreurs suivantes.

## TÂCHE ORIGINALE
**Titre**: {task.title}
**Description**: {task.description}

## TENTATIVE DE DEBUG
**Tentative actuelle**: {state.debug_attempts}/{state.max_debug_attempts}

## ANALYSE D'ERREUR
{error_analysis}

## HISTORIQUE DES ERREURS PRÉCÉDENTES
{chr(10).join(state.get('error_logs', [])) or 'Aucune erreur précédente'}

## INSTRUCTIONS POUR LE DEBUG

1. **Identifie** la cause racine de l'erreur
2. **Propose** des corrections spécifiques
3. **Applique** les corrections de manière ciblée
4. **Évite** de refaire complètement le code sauf si nécessaire

Utilise ce format pour tes corrections:

```action:debug_fix
problem: [Description du problème identifié]
solution: [Description de la solution]
file_path: [Chemin du fichier à corriger]
content:
[Le contenu corrigé du fichier]
```

OU pour des commandes de correction:

```action:debug_command
problem: [Description du problème]
command: [Commande à exécuter]
explanation: [Pourquoi cette commande résout le problème]
```

**Concentre-toi sur UNE correction à la fois** pour éviter d'introduire de nouveaux bugs."""

    return prompt

async def _apply_debug_corrections(
    claude_tool: ClaudeCodeTool,
    anthropic_client: Client,
    debug_solution: str,
    state: Dict[str, Any]
) -> bool:
    """Applique les corrections de debug proposées par Claude."""
    
    import re
    
    corrections_applied = 0
    total_corrections = 0
    
    fix_pattern = r'```action:debug_fix\n(.*?)\n```'
    fixes = re.findall(fix_pattern, debug_solution, re.DOTALL)
    
    for fix_content in fixes:
        total_corrections += 1
        logger.info(f"🔧 Application correction fichier {total_corrections}")
        
        try:
            success = await _apply_file_fix(claude_tool, fix_content, state)
            if success:
                corrections_applied += 1
        except Exception as e:
            logger.error(f"Erreur lors de la correction fichier: {e}")
            state.results["error_logs"].append(f"Erreur correction fichier: {str(e)}")
    
    command_pattern = r'```action:debug_command\n(.*?)\n```'
    commands = re.findall(command_pattern, debug_solution, re.DOTALL)
    
    for command_content in commands:
        total_corrections += 1
        logger.info(f"🔧 Exécution commande debug {total_corrections}")
        
        try:
            success = await _apply_debug_command(claude_tool, command_content, state)
            if success:
                corrections_applied += 1
        except Exception as e:
            logger.error(f"Erreur lors de la commande debug: {e}")
            state.results["error_logs"].append(f"Erreur commande debug: {str(e)}")
    
    if total_corrections == 0:
        logger.info("Aucune correction structurée trouvée, tentative d'application directe...")
        success = await _apply_direct_debug_solution(claude_tool, debug_solution, state)
        if success:
            corrections_applied = 1
            total_corrections = 1
    
    success_rate = corrections_applied / max(total_corrections, 1)
    logger.info(f"📊 Corrections appliquées: {corrections_applied}/{total_corrections} (taux: {success_rate:.1%})")
    
    return success_rate > 0

async def _apply_file_fix(claude_tool: ClaudeCodeTool, fix_content: str, state: Dict[str, Any]) -> bool:
    try:
        lines = fix_content.strip().split('\n')
        problem = ""
        solution = ""
        file_path = ""
        content = ""
        
        content_started = False
        for line in lines:
            if line.startswith('problem:'):
                problem = line.split(':', 1)[1].strip()
            elif line.startswith('solution:'):
                solution = line.split(':', 1)[1].strip()
            elif line.startswith('file_path:'):
                file_path = line.split(':', 1)[1].strip()
            elif line.startswith('content:'):
                content_started = True
            elif content_started:
                content += line + '\n'
        
        if file_path and content:
            old_content_result = await claude_tool._arun(action="read_file", file_path=file_path)
            
            result = await claude_tool._arun(
                action="write_file",
                file_path=file_path,
                content=content.strip()
            )
            
            if result["success"]:
                state.results["code_changes"][file_path] = content.strip()
                if file_path not in state.results["modified_files"]:
                    state.results["modified_files"].append(file_path)
                
                state.results["ai_messages"].append(f"🔧 Correction appliquée: {file_path} - {problem}")
                logger.info(f"✅ Correction appliquée: {file_path}")
                return True
            else:
                error = result.get("error", "Erreur inconnue")
                state.results["error_logs"].append(f"Échec correction {file_path}: {error}")
                logger.error(f"❌ Échec correction {file_path}: {error}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur application correction fichier: {e}")
        return False

async def _apply_debug_command(claude_tool: ClaudeCodeTool, command_content: str, state: Dict[str, Any]) -> bool:
    try:
        lines = command_content.strip().split('\n')
        problem = ""
        command = ""
        explanation = ""
        
        for line in lines:
            if line.startswith('problem:'):
                problem = line.split(':', 1)[1].strip()
            elif line.startswith('command:'):
                command = line.split(':', 1)[1].strip()
            elif line.startswith('explanation:'):
                explanation = line.split(':', 1)[1].strip()
        
        if command:
            result = await claude_tool._arun(action="execute_command", command=command)
            
            if result["success"]:
                state.results["ai_messages"].append(f"🔧 Commande debug exécutée: {command}")
                logger.info(f"✅ Commande debug réussie: {command}")
                return True
            else:
                error = result.get("stderr", result.get("error", "Erreur inconnue"))
                state.results["error_logs"].append(f"Échec commande debug '{command}': {error}")
                logger.error(f"❌ Échec commande debug '{command}': {error}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur application commande debug: {e}")
        return False

async def _apply_direct_debug_solution(claude_tool: ClaudeCodeTool, debug_solution: str, state: Dict[str, Any]) -> bool:
    try:
        import re
        code_blocks = re.findall(r'```(?:python|javascript|typescript)?\n(.*?)\n```', debug_solution, re.DOTALL)
        
        if code_blocks:
            code_content = code_blocks[0]
            
            target_file = None
            if state.get("modified_files"):
                target_file = state.results["modified_files"][-1]
            else:
                if "def " in code_content or "import " in code_content:
                    target_file = "debug_fix.py"
                elif "function " in code_content or "const " in code_content:
                    target_file = "debug_fix.js"
                else:
                    target_file = "debug_fix.txt"
            
            result = await claude_tool._arun(
                action="write_file",
                file_path=target_file,
                content=code_content
            )
            
            if result["success"]:
                state.results["code_changes"][target_file] = code_content
                if target_file not in state.results["modified_files"]:
                    state.results["modified_files"].append(target_file)
                state.results["ai_messages"].append(f"🔧 Correction directe appliquée: {target_file}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Erreur application solution directe: {e}")
        return False 