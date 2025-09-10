from typing import Dict, Any

from models.schemas import WorkflowStatus, TestResult
from tools.claude_code_tool import ClaudeCodeTool
from utils.logger import get_logger

logger = get_logger(__name__)

async def run_tests(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"🧪 Lancement des tests pour: {state.task.title}")
    if 'ai_messages' not in state.results:
        state.results['ai_messages'] = []
    
    state.results["current_status"] = "TESTING".lower()
    state.results["ai_messages"].append("Début des tests...")
    
    try:
        if not state.get("working_directory"):
            error_msg = "Aucun répertoire de travail disponible pour les tests"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["should_continue"] = False
            return state
        
        from tools.testing_engine import TestingEngine, TestType
        
        testing_engine = TestingEngine()
        testing_engine.working_directory = state.results["working_directory"]
        
        logger.info("🧪 Lancement de la suite complète de tests...")
        test_results = await testing_engine._arun(
            "run_all_tests",
            working_directory=state.results["working_directory"],
            include_coverage=True
        )
        
        if not test_results.get("success"):
            logger.warning("⚠️  Aucune commande de test détectée, utilisation de commandes par défaut")
            test_commands = ["npm test", "python -m pytest", "python -m unittest"]
        
        test_result = None
        for test_cmd in test_commands:
            logger.info(f"🚀 Exécution: {test_cmd}")
            state.results["ai_messages"].append(f"🧪 Test en cours: {test_cmd}")
            
            try:
                test_result = await claude_tool._run_tests(test_cmd)
                
                if test_result.exit_code != -1:
                    break
                    
            except Exception as e:
                logger.warning(f"Échec exécution {test_cmd}: {e}")
                continue
        
        if not test_result:
            error_msg = "Aucune commande de test fonctionnelle trouvée"
            test_result = TestResult(
                success=False,
                test_type="general",
                exit_code=-1,
                stdout="",
                stderr=error_msg,
                duration=0.0,
                test_command="N/A"
            )
        
        state.results["test_results"].append(test_result)
        
        if test_result.success:
            state.results["ai_messages"].append("✅ Tests réussis ! Passage à la finalisation.")
            state.results["last_operation_result"] = "Tests réussis"
            state.results["should_continue"] = True
            
            logger.info("✅ Tests réussis - Passage à la finalisation")
            
        else:
            error_analysis = await _analyze_test_failure(test_result, state)
            
            state.results["ai_messages"].append(f"❌ Tests échoués: {error_analysis}")
            state.results["error_logs"].append(f"Échec tests: {error_analysis}")
            state.results["last_operation_result"] = f"Tests échoués: {error_analysis}"
            
            if state.results["debug_attempts"] < state.results["max_debug_attempts"]:
                state.results["should_continue"] = True
                logger.info(f"🔧 Tests échoués - Passage au debug (tentative {state.debug_attempts + 1}/{state.max_debug_attempts})")
            else:
                state.results["should_continue"] = False
                state.results["current_status"] = "FAILED".lower()
                state.results["ai_messages"].append(f"❌ Limite de tentatives de debug atteinte ({state.max_debug_attempts})")
                logger.error(f"❌ Limite de debug atteinte - Arrêt du workflow")
        
    except Exception as e:
        error_msg = f"Exception lors des tests: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        error_test_result = TestResult(
            success=False,
            test_type="exception",
            exit_code=-999,
            stdout="",
            stderr=error_msg,
            duration=0.0,
            test_command="exception"
        )
        
        state.results["test_results"].append(error_test_result)
        state.results["error_logs"].append(error_msg)
        state.results["ai_messages"].append(f"❌ Exception tests: {error_msg}")
        state.results["last_operation_result"] = error_msg
        state.results["should_continue"] = True
    
    logger.info("🏁 Tests terminés")
    return state

async def _detect_test_commands(claude_tool: ClaudeCodeTool) -> list[str]:
    test_commands = []
    
    try:
        
        package_json_result = await claude_tool._arun(action="read_file", file_path="package.json")
        if package_json_result["success"]:
            import json
            try:
                package_data = json.loads(package_json_result["content"])
                scripts = package_data.get("scripts", {})
                
                if "test" in scripts:
                    test_commands.append("npm test")
                if "test:unit" in scripts:
                    test_commands.append("npm run test:unit")
                if "jest" in scripts:
                    test_commands.append("npm run jest")
                    
                if not test_commands:
                    test_commands.extend(["npm test", "yarn test", "npx jest"])
                    
            except json.JSONDecodeError:
                test_commands.append("npm test")
        
        requirements_result = await claude_tool._arun(action="read_file", file_path="requirements.txt")
        setup_py_result = await claude_tool._arun(action="read_file", file_path="setup.py")
        pyproject_result = await claude_tool._arun(action="read_file", file_path="pyproject.toml")
        
        if any(result["success"] for result in [requirements_result, setup_py_result, pyproject_result]):
            all_content = ""
            for result in [requirements_result, setup_py_result, pyproject_result]:
                if result["success"]:
                    all_content += result["content"].lower()
            
            if "pytest" in all_content:
                test_commands.extend(["python -m pytest", "pytest"])
            if "unittest" in all_content:
                test_commands.append("python -m unittest discover")
            if "nose" in all_content:
                test_commands.append("nosetests")
            
            if not any("python" in cmd for cmd in test_commands):
                test_commands.extend([
                    "python -m pytest",
                    "python -m unittest discover", 
                    "python -m pytest tests/",
                    "python -m unittest"
                ])
        
        makefile_result = await claude_tool._arun(action="read_file", file_path="Makefile")
        if makefile_result["success"] and "test" in makefile_result["content"].lower():
            test_commands.append("make test")
        
        cargo_result = await claude_tool._arun(action="read_file", file_path="Cargo.toml")
        if cargo_result["success"]:
            test_commands.append("cargo test")
        
        go_mod_result = await claude_tool._arun(action="read_file", file_path="go.mod")
        if go_mod_result["success"]:
            test_commands.append("go test ./...")
        
        composer_result = await claude_tool._arun(action="read_file", file_path="composer.json")
        if composer_result["success"]:
            test_commands.extend(["composer test", "./vendor/bin/phpunit"])
        
    except Exception as e:
        logger.warning(f"Erreur lors de la détection des commandes de test: {e}")
    
    seen = set()
    unique_commands = []
    for cmd in test_commands:
        if cmd not in seen:
            seen.add(cmd)
            unique_commands.append(cmd)
    
    return unique_commands

async def _analyze_test_failure(test_result: TestResult, state: Dict[str, Any]) -> str:
    error_output = test_result.stderr or test_result.stdout
    
    error_patterns = {
        "module not found": "Module manquant - vérifier les imports et dépendances",
        "no module named": "Module Python manquant - vérifier les imports",
        "cannot find module": "Module Node.js manquant - vérifier package.json",
        "import error": "Erreur d'import - vérifier les chemins et dépendances",
        "syntax error": "Erreur de syntaxe dans le code",
        "indentation error": "Erreur d'indentation Python",
        "unexpected token": "Erreur de syntaxe JavaScript/TypeScript",
        "command not found": "Commande de test non trouvée - installer les dépendances",
        "permission denied": "Problème de permissions - vérifier l'exécutable",
        "connection refused": "Problème de connexion - services externes requis?",
        "timeout": "Test trop lent - optimiser ou augmenter timeout",
        "assertion": "Assertion échouée - logique métier incorrecte",
        "failed": "Test(s) échoué(s)",
        "error": "Erreur générale"
    }
    
    error_analysis = "Échec de test non spécifique"

    error_output_lower = error_output.lower()
    for pattern, description in error_patterns.items():
        if pattern in error_output_lower:
            error_analysis = description
            break
    
    if test_result.exit_code == 127:
        error_analysis = "Commande de test non trouvée - installer les dépendances"
    elif test_result.exit_code == 2:
        error_analysis = "Erreur de configuration ou arguments invalides"
    elif test_result.exit_code == 1:
        error_analysis = "Tests échoués - vérifier la logique métier"
    
    error_lines = error_output.split('\n')[:5]
    relevant_errors = [line.strip() for line in error_lines if line.strip() and not line.startswith('===')]
    
    if relevant_errors:
        error_context = ' | '.join(relevant_errors[:2])
        error_analysis += f" ({error_context})"
    
    return error_analysis

def should_continue_to_debug(state: Dict[str, Any]) -> bool:
    if not state.results["test_results"]:
        return False
    
    latest_test = state.results["test_results"][-1]
    
    if latest_test.success:
        return False
    
    if state.results["debug_attempts"] >= state.results["max_debug_attempts"]:
        return False
    
    return True

def should_continue_to_finalize(state: Dict[str, Any]) -> bool:
    if not state.results["test_results"]:
        return False    
    latest_test = state.results["test_results"][-1]
    return latest_test.success 