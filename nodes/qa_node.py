import os
import subprocess
import asyncio
from typing import Dict, Any, List, Tuple
from pathlib import Path
from models.schemas import WorkflowStatus, WorkflowState
from utils.logger import get_logger

logger = get_logger(__name__)


async def quality_assurance_automation(state: WorkflowState) -> WorkflowState:
    if not state.task:
        logger.error("❌ Aucune tâche pour l'assurance qualité")
        state.error = "Aucune tâche fournie pour l'assurance qualité"
        return state
        
    logger.info(f"🔍 Assurance qualité pour: {state.task.title}")
    state.current_node = "quality_assurance_automation"
    if "quality_assurance_automation" not in state.completed_nodes:
        state.completed_nodes.append("quality_assurance_automation")
    
    try:
        working_directory = state.results.get("working_directory") if state.results else None
        if not working_directory or not os.path.exists(working_directory):
            error_msg = "Répertoire de travail non trouvé pour l'assurance qualité"
            logger.error(error_msg)
            state.error = error_msg
            return state
        
        project_info = await _detect_project_type(working_directory)
        
        modified_files = []
        if state.results and "code_changes" in state.results:
            code_changes = state.results["code_changes"]
            if isinstance(code_changes, dict):
                modified_files = list(code_changes.keys())
            elif isinstance(code_changes, list):
                modified_files = code_changes
        
        if not modified_files:
            modified_files = await _get_recent_python_files(working_directory)
        
        logger.info(f"📁 Fichiers à analyser: {len(modified_files)}")
        
        qa_results = await _run_quality_checks(working_directory, modified_files, project_info)
        
        qa_summary = _analyze_qa_results(qa_results)
        
        if not state.results:
            state.results = {}
            
        state.results["quality_assurance"] = {
            "qa_results": qa_results,
            "qa_summary": qa_summary,
            "project_info": project_info,
            "files_analyzed": modified_files,
            "overall_score": qa_summary["overall_score"],
            "passed_checks": qa_summary["passed_checks"],
            "total_checks": qa_summary["total_checks"],
            "critical_issues": qa_summary["critical_issues"],
            "quality_gate_passed": qa_summary["quality_gate_passed"]
        }
        
        logger.info(f"✅ Assurance qualité terminée",
                   overall_score=qa_summary["overall_score"],
                   passed_checks=qa_summary["passed_checks"],
                   total_checks=qa_summary["total_checks"],
                   critical_issues=qa_summary["critical_issues"],
                   quality_gate=qa_summary["quality_gate_passed"])
        
        if qa_summary["critical_issues"] > 0:
            logger.warning(f"⚠️ {qa_summary['critical_issues']} problèmes critiques détectés")
            
            critical_report = "\n".join([
                f"• {issue}" for issue in qa_summary.get("critical_issues_list", [])
            ])
            
            if "qa_report" not in state.results:
                state.results["qa_report"] = ""
            state.results["qa_report"] += f"\n🚨 Problèmes critiques QA:\n{critical_report}\n"
        
        return state
        
    except Exception as e:
        error_msg = f"Exception lors de l'assurance qualité: {str(e)}"
        logger.error(error_msg, exc_info=True)
        state.error = error_msg
        return state


async def _detect_project_type(working_directory: str) -> Dict[str, Any]:
    project_info = {
        "language": "python",
        "frameworks": [],
        "qa_tools_available": [],
        "config_files": {}
    }
    
    try:
        config_files_to_check = [
            "setup.py", "pyproject.toml", "requirements.txt", "Pipfile",
            ".flake8", "setup.cfg", "tox.ini", "pytest.ini",
            ".pylintrc", ".pre-commit-config.yaml", "mypy.ini"
        ]
        
        for config_file in config_files_to_check:
            config_path = os.path.join(working_directory, config_file)
            if os.path.exists(config_path):
                project_info["config_files"][config_file] = config_path
        
        requirements_files = [
            project_info["config_files"].get("requirements.txt"),
            project_info["config_files"].get("pyproject.toml")
        ]
        
        for req_file in requirements_files:
            if req_file and os.path.exists(req_file):
                with open(req_file, 'r') as f:
                    content = f.read().lower()
                    
                    frameworks = {
                        "django": "django",
                        "flask": "flask", 
                        "fastapi": "fastapi",
                        "pytest": "pytest",
                        "unittest": "unittest"
                    }
                    
                    for framework, name in frameworks.items():
                        if framework in content:
                            project_info["frameworks"].append(name)
        
        qa_tools = ["pylint", "flake8", "black", "isort", "bandit", "mypy", "prospector"]
        
        for tool in qa_tools:
            try:
                result = subprocess.run([tool, "--version"], 
                                      capture_output=True, 
                                      text=True, 
                                      timeout=5)
                if result.returncode == 0:
                    project_info["qa_tools_available"].append(tool)
            except:
                continue
        
        return project_info
        
    except Exception as e:
        logger.error(f"Erreur détection type projet: {e}")
        return project_info


async def _get_recent_python_files(working_directory: str) -> List[str]:
    python_files = []
    
    try:
        for root, dirs, files in os.walk(working_directory):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules', 'venv', 'env']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, working_directory)
                    python_files.append(rel_path)
        
        return python_files[:20]
        
    except Exception as e:
        logger.error(f"Erreur récupération fichiers Python: {e}")
        return []


async def _run_quality_checks(working_directory: str, files: List[str], project_info: Dict[str, Any]) -> Dict[str, Any]:
    qa_results = {}
    available_tools = project_info.get("qa_tools_available", [])
    
    if "pylint" in available_tools and files:
        qa_results["pylint"] = await _run_pylint(working_directory, files)
    
    if "flake8" in available_tools and files:
        qa_results["flake8"] = await _run_flake8(working_directory, files)
    
    if "black" in available_tools and files:
        qa_results["black"] = await _run_black_check(working_directory, files)
    
    if "isort" in available_tools and files:
        qa_results["isort"] = await _run_isort_check(working_directory, files)
    
    if "bandit" in available_tools and files:
        qa_results["bandit"] = await _run_bandit(working_directory, files)
    
    if "mypy" in available_tools and files:
        qa_results["mypy"] = await _run_mypy(working_directory, files)
    
    return qa_results


async def _run_tool_command(working_directory: str, command: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        return process.returncode, stdout.decode(), stderr.decode()
        
    except asyncio.TimeoutError:
        logger.warning(f"Timeout pour la commande: {' '.join(command)}")
        return -1, "", "Timeout"
    except Exception as e:
        logger.error(f"Erreur exécution commande {command}: {e}")
        return -1, "", str(e)


async def _run_pylint(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:5]
    
    command = ["pylint", "--output-format=json", "--disable=C0114,C0116"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    result = {
        "tool": "pylint",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": 0,
        "critical_issues": 0,
        "output": stdout,
        "error": stderr
    }
    try:
        import json
        if stdout:
            issues = json.loads(stdout)
            result["issues_count"] = len(issues)
            result["critical_issues"] = len([i for i in issues if i.get("type") in ["error", "fatal"]])
    except:
        pass
    
    return result


async def _run_flake8(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:5]
    
    command = ["flake8", "--max-line-length=88", "--extend-ignore=E203,W503"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    issues_count = len(stdout.split('\n')) - 1 if stdout.strip() else 0
    
    return {
        "tool": "flake8",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": issues_count,
        "critical_issues": issues_count if returncode != 0 else 0,
        "output": stdout,
        "error": stderr
    }


async def _run_black_check(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:5]
    
    command = ["black", "--check", "--diff"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    return {
        "tool": "black",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": 1 if returncode != 0 else 0,
        "critical_issues": 0,
        "output": stdout,
        "error": stderr
    }


async def _run_isort_check(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:5]
    
    command = ["isort", "--check-only", "--diff"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    return {
        "tool": "isort",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": 1 if returncode != 0 else 0,
        "critical_issues": 0,
        "output": stdout,
        "error": stderr
    }


async def _run_bandit(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:5]
    
    command = ["bandit", "-f", "json"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    result = {
        "tool": "bandit",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": 0,
        "critical_issues": 0,
        "output": stdout,
        "error": stderr
    }
    
    try:
        import json
        if stdout:
            bandit_result = json.loads(stdout)
            issues = bandit_result.get("results", [])
            result["issues_count"] = len(issues)
            result["critical_issues"] = len([i for i in issues if i.get("issue_severity") in ["HIGH", "MEDIUM"]])
    except:
        pass
    
    return result


async def _run_mypy(working_directory: str, files: List[str]) -> Dict[str, Any]:
    files_to_check = files[:3]
    
    command = ["mypy", "--ignore-missing-imports"] + files_to_check
    returncode, stdout, stderr = await _run_tool_command(working_directory, command)
    
    issues_count = len([line for line in stdout.split('\n') if ': error:' in line]) if stdout else 0
    
    return {
        "tool": "mypy",
        "returncode": returncode,
        "passed": returncode == 0,
        "issues_count": issues_count,
        "critical_issues": 0,
        "output": stdout,
        "error": stderr
    }


def _analyze_qa_results(qa_results: Dict[str, Any]) -> Dict[str, Any]:
    total_checks = len(qa_results)
    passed_checks = sum(1 for result in qa_results.values() if result.get("passed", False))
    total_issues = sum(result.get("issues_count", 0) for result in qa_results.values())
    critical_issues = sum(result.get("critical_issues", 0) for result in qa_results.values())
    
    if total_checks == 0:
        overall_score = 100
    else:
        base_score = (passed_checks / total_checks) * 100
        penalty = min(critical_issues * 10, 50)
        overall_score = max(0, base_score - penalty)
    
    quality_gate_passed = (
        overall_score >= 70 and
        critical_issues <= 3     # Maximum de problèmes critiques
    )
    
    critical_issues_list = []
    for tool, result in qa_results.items():
        if result.get("critical_issues", 0) > 0:
            critical_issues_list.append(f"{tool}: {result['critical_issues']} problèmes critiques")
    
    return {
        "overall_score": round(overall_score, 1),
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "total_issues": total_issues,
        "critical_issues": critical_issues,
        "critical_issues_list": critical_issues_list,
        "quality_gate_passed": quality_gate_passed,
        "tools_summary": {
            tool: {
                "passed": result.get("passed", False),
                "issues": result.get("issues_count", 0),
                "critical": result.get("critical_issues", 0)
            }
            for tool, result in qa_results.items()
        }
    } 