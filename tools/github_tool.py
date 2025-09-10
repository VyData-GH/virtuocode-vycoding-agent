from datetime import datetime
from typing import Any, Dict, Optional
from github import Github, GithubException
from pydantic import Field

from .base_tool import BaseTool
from models.schemas import TaskRequest, WorkflowState, GitOperationResult, PullRequestInfo


class GitHubTool(BaseTool):
    
    name: str = "github_tool"
    description: str = """
    Outil pour interagir avec GitHub.
    
    Fonctionnalités:
    - Créer des Pull Requests
    - Pousser des branches
    - Ajouter des commentaires
    - Gérer les labels et assignations
    """
    
    github_client: Optional[Github] = Field(default=None)
    repository: Optional[Any] = Field(default=None)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.github_client = Github(self.settings.github_token)
    
    async def _arun(self, action: str, **kwargs) -> Dict[str, Any]:
        try:
            if action == "create_pull_request":
                return await self._create_pull_request(
                    repo_url=kwargs.get("repo_url"),
                    title=kwargs.get("title"),
                    body=kwargs.get("body"),
                    head_branch=kwargs.get("head_branch"),
                    base_branch=kwargs.get("base_branch", "main")
                )
            elif action == "push_branch":
                return await self._push_branch(
                    repo_url=kwargs.get("repo_url"),
                    branch=kwargs.get("branch"),
                    working_directory=kwargs.get("working_directory")
                )
            elif action == "add_comment":
                return await self._add_comment(
                    repo_url=kwargs.get("repo_url"),
                    pr_number=kwargs.get("pr_number"),
                    comment=kwargs.get("comment")
                )
            else:
                raise ValueError(f"Action non supportée: {action}")
                
        except Exception as e:
            return self.handle_error(e, f"github_tool.{action}")
    
    async def _create_pull_request(self, repo_url: str, title: str, body: str, 
                                 head_branch: str, base_branch: str = "main") -> Dict[str, Any]:
        try:
            repo_name = self._extract_repo_name(repo_url)
            repo = self.github_client.get_repo(repo_name)
            
            try:
                repo.get_branch(head_branch)
            except GithubException as e:
                if e.status == 404:
                    return {
                        "success": False,
                        "error": f"La branche {head_branch} n'existe pas sur GitHub"
                    }
                raise
            
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head_branch,
                base=base_branch
            )
            
            pr_info = PullRequestInfo(
                pr_id=pr.id,
                pr_number=pr.number,
                pr_url=pr.html_url,
                title=pr.title,
                body=pr.body or "",
                branch=head_branch,
                base_branch=base_branch,
                created_at=datetime.now()
            )
            
            self.log_operation(f"Création PR #{pr.number}", True, pr.html_url)
            
            return {
                "success": True,
                "pr_info": pr_info.dict(),
                "pr_url": pr.html_url,
                "pr_number": pr.number
            }
            
        except GithubException as e:
            if e.status == 422 and "pull request already exists" in str(e):
                try:
                    existing_prs = repo.get_pulls(
                        state="open",
                        head=f"{repo.owner.login}:{head_branch}",
                        base=base_branch
                    )
                    if existing_prs.totalCount > 0:
                        existing_pr = existing_prs[0]
                        pr_info = PullRequestInfo(
                            pr_id=existing_pr.id,
                            pr_number=existing_pr.number,
                            pr_url=existing_pr.html_url,
                            title=existing_pr.title,
                            body=existing_pr.body or "",
                            branch=head_branch,
                            base_branch=base_branch,
                            created_at=datetime.now()
                        )
                        
                        self.log_operation(f"PR existante trouvée #{existing_pr.number}", True)
                        return {
                            "success": True,
                            "pr_info": pr_info.dict(),
                            "pr_url": existing_pr.html_url,
                            "pr_number": existing_pr.number,
                            "message": "Pull Request existante utilisée"
                        }
                except Exception:
                    pass
            
            return self.handle_error(e, "création de la Pull Request")
        except Exception as e:
            return self.handle_error(e, "création de la Pull Request")
    
    async def _push_branch(self, repo_url: str, branch: str, working_directory: str) -> GitOperationResult:
        try:
            import subprocess
            import os
            
            original_cwd = os.getcwd()
            os.chdir(working_directory)
            
            try:
                add_result = subprocess.run(
                    ["git", "add", "."],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                commit_result = subprocess.run(
                    ["git", "commit", "-m", f"Implémentation automatique - {branch}"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                push_result = subprocess.run(
                    ["git", "push", "origin", branch],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                commit_hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                commit_hash = commit_hash_result.stdout.strip()
                
                git_result = GitOperationResult(
                    success=True,
                    operation="push",
                    message=f"Branche {branch} poussée avec succès",
                    branch_name=branch,
                    commit_hash=commit_hash
                )
                
                self.log_operation(f"Push branche {branch}", True, commit_hash)
                return git_result
                
            finally:
                os.chdir(original_cwd)
                
        except subprocess.CalledProcessError as e:
            error_msg = f"Erreur Git: {e.stderr}"
            self.logger.error(error_msg)
            return GitOperationResult(
                success=False,
                operation="push",
                message=error_msg,
                branch_name=branch
            )
        except Exception as e:
            return GitOperationResult(
                success=False,
                operation="push", 
                message=str(e),
                branch_name=branch
            )
    
    async def _add_comment(self, repo_url: str, pr_number: int, comment: str) -> Dict[str, Any]:
        try:
            repo_name = self._extract_repo_name(repo_url)
            repo = self.github_client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            
            comment_obj = pr.create_issue_comment(comment)
            
            self.log_operation(f"Commentaire ajouté PR #{pr_number}", True)
            
            return {
                "success": True,
                "comment_id": comment_obj.id,
                "comment_url": comment_obj.html_url
            }
            
        except Exception as e:
            return self.handle_error(e, f"ajout de commentaire à la PR #{pr_number}")
    
    def _extract_repo_name(self, repo_url: str) -> str:

        if repo_url.endswith('.git'):
            repo_url = repo_url[:-4]
        
        if 'github.com/' in repo_url:
            parts = repo_url.split('github.com/')[-1]
            return parts
        else:
            raise ValueError(f"URL de repository invalide: {repo_url}")
    
    def cleanup(self):
        if hasattr(self, 'github_client'):
            pass 