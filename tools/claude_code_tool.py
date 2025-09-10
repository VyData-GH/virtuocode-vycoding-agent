import os
import tempfile
import subprocess
from typing import Any, Dict, List, Optional
from pydantic import Field
from anthropic import Client

from .base_tool import BaseTool
from models.schemas import TaskRequest, WorkflowState, TestResult


class ClaudeCodeTool(BaseTool):
    name: str = "claude_code_tool"
    description: str = """
    Outil pour écrire, modifier et tester du code.
    Utilise Claude pour générer du code de qualité.
    
    Fonctionnalités:
    - Lire des fichiers de code
    - Écrire/modifier des fichiers
    - Exécuter des commandes système
    - Lancer des tests
    - Analyser des erreurs
    """
    
    anthropic_client: Optional[Client] = Field(default=None)
    working_directory: Optional[str] = Field(default=None)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.anthropic_client = Client(api_key=self.settings.anthropic_api_key)
    
    async def _arun(self, action: str, **kwargs) -> Dict[str, Any]:
        try:
            if action == "read_file":
                return await self._read_file(kwargs.get("file_path"))
            elif action == "write_file":
                return await self._write_file(
                    kwargs.get("file_path"), 
                    kwargs.get("content")
                )
            elif action == "modify_file":
                return await self._modify_file(
                    kwargs.get("file_path"),
                    kwargs.get("description"),
                    kwargs.get("context", {})
                )
            elif action == "execute_command":
                return await self._execute_command(kwargs.get("command"))
            elif action == "run_tests":
                return await self._run_tests(kwargs.get("test_command", "npm test"))
            elif action == "setup_environment":
                return await self._setup_environment(kwargs.get("repo_url"), kwargs.get("branch"))
            else:
                raise ValueError(f"Action non supportée: {action}")
                
        except Exception as e:
            return self.handle_error(e, f"claude_code_tool.{action}")
    
    async def _read_file(self, file_path: str) -> Dict[str, Any]:
        try:
            full_path = self._get_full_path(file_path)
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.log_operation(f"Lecture fichier {file_path}", True)
            return {
                "success": True,
                "content": content,
                "file_path": file_path
            }
        except Exception as e:
            return self.handle_error(e, f"lecture du fichier {file_path}")
    
    async def _write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        try:
            full_path = self._get_full_path(file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.log_operation(f"Écriture fichier {file_path}", True)
            return {
                "success": True,
                "file_path": file_path,
                "bytes_written": len(content.encode('utf-8'))
            }
        except Exception as e:
            return self.handle_error(e, f"écriture du fichier {file_path}")
    
    async def _modify_file(self, file_path: str, description: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            current_content_result = await self._read_file(file_path)
            if not current_content_result["success"]:
                return current_content_result
            
            current_content = current_content_result["content"]
            
            prompt = f"""
Tu es un développeur expert. Tu dois modifier le fichier suivant selon la description fournie.

Fichier: {file_path}
Contenu actuel:
```
{current_content}
```

Description de la modification à effectuer:
{description}

Contexte supplémentaire:
{context}

Réponds UNIQUEMENT avec le nouveau contenu complet du fichier, sans explication.
"""
            
            response = self.anthropic_client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            new_content = response.content[0].text.strip()
            
            write_result = await self._write_file(file_path, new_content)
            if write_result["success"]:
                self.log_operation(f"Modification fichier {file_path}", True, description)
                write_result["modification_description"] = description
            
            return write_result
            
        except Exception as e:
            return self.handle_error(e, f"modification du fichier {file_path}")
    
    async def _execute_command(self, command: str) -> Dict[str, Any]:
        try:
            cwd = self.working_directory or os.getcwd()
            
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            
            success = result.returncode == 0
            self.log_operation(f"Commande: {command}", success, 
                             f"Code: {result.returncode}")
            
            return {
                "success": success,
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
        except subprocess.TimeoutExpired:
            return self.handle_error(
                TimeoutError("Commande expirée"), 
                f"exécution de la commande: {command}"
            )
        except Exception as e:
            return self.handle_error(e, f"exécution de la commande: {command}")
    
    async def _run_tests(self, test_command: str) -> TestResult:
        import time
        start_time = time.time()
        
        try:
            result = await self._execute_command(test_command)
            duration = time.time() - start_time
            
            test_result = TestResult(
                success=result["success"],
                test_type="automated",
                exit_code=result["exit_code"],
                stdout=result["stdout"],
                stderr=result["stderr"],
                duration=duration,
                test_command=test_command
            )
            
            self.log_operation("Tests", test_result.success, 
                             metadata={"duration": duration, "test_command": test_command})
            return test_result
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Erreur lors des tests: {e}")
            return TestResult(
                success=False,
                test_type="error",
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=duration,
                test_command=test_command
            )
    
    async def _setup_environment(self, repo_url: str, branch: str) -> Dict[str, Any]:
        try:
            self.working_directory = tempfile.mkdtemp(prefix="ai_agent_")
            
            clone_result = await self._execute_command(f"git clone {repo_url} .")
            if not clone_result["success"]:
                return clone_result
            
            checkout_result = await self._execute_command(f"git checkout -b {branch}")
            if not checkout_result["success"]:
                return checkout_result
            
            install_commands = [
                "npm install",
                "pip install -r requirements.txt",
                "yarn install"
            ]
            
            for cmd in install_commands:
                if os.path.exists(os.path.join(self.working_directory, 
                                             "package.json" if "npm" in cmd else "requirements.txt")):
                    install_result = await self._execute_command(cmd)
                    if install_result["success"]:
                        break
            
            self.log_operation("Configuration environnement", True, 
                             f"Branche: {branch}, Répertoire: {self.working_directory}")
            
            return {
                "success": True,
                "working_directory": self.working_directory,
                "branch": branch,
                "repo_url": repo_url
            }
            
        except Exception as e:
            return self.handle_error(e, "configuration de l'environnement")
    
    def _get_full_path(self, file_path: str) -> str:
        if os.path.isabs(file_path):
            return file_path
        
        base_dir = self.working_directory or os.getcwd()
        return os.path.join(base_dir, file_path) 