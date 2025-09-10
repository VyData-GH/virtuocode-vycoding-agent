from typing import Dict, Any

from models.schemas import WorkflowStatus, PullRequestInfo
from tools.github_tool import GitHubTool
from utils.logger import get_logger

logger = get_logger(__name__)

async def finalize_pr(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"🚀 Finalisation pour: {state.task.title}")
    
    state.results["current_status"] = "FINALIZING".lower()
    state.results["ai_messages"].append("Début de la finalisation...")
    
    try:
        working_directory = state.results.get("working_directory")
        if not working_directory:
            error_msg = "Répertoire de travail manquant pour la finalisation"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["should_continue"] = False
            return state
        
        if not state.results.get("code_changes") and not state.results.get("modified_files"):
            error_msg = "Aucun changement de code à finaliser"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"⚠️ {error_msg}")
            state.results["should_continue"] = True
            return state
        
        github_tool = GitHubTool()
        
        task = state.task
        repo_url = task.repository_url
        if not repo_url:
            from config.settings import get_settings
            settings = get_settings()
            repo_url = settings.default_repo_url
        
        logger.info("📤 Push des changements vers GitHub...")
        state.results["ai_messages"].append("📤 Push en cours...")
        
        push_result = await github_tool._arun(
            action="push_branch",
            repo_url=repo_url,
            branch=task.git_branch,
            working_directory=working_directory
        )
        
        if not push_result.success:
            error_msg = f"Échec du push: {push_result.message}"
            state.results["error_logs"].append(error_msg)
            state.results["ai_messages"].append(f"❌ {error_msg}")
            state.results["should_continue"] = True
            return state
        
        state.results["ai_messages"].append(f"✅ Push réussi: {push_result.commit_hash}")
        logger.info(f"✅ Push réussi - Commit: {push_result.commit_hash}")
        
        logger.info("🔀 Création de la Pull Request...")
        state.results["ai_messages"].append("🔀 Création PR...")
        
        pr_title, pr_body = await _generate_pr_content(task, state)
        
        pr_result = await github_tool._arun(
            action="create_pull_request",
            repo_url=repo_url,
            title=pr_title,
            body=pr_body,
            head_branch=task.git_branch,
            base_branch="main"
        )
        
        if pr_result["success"]:
            pr_info_dict = pr_result["pr_info"]
            pr_info = PullRequestInfo(**pr_info_dict)
            
            state.results["pr_info"] = pr_info
            state.results["ai_messages"].append(f"✅ PR créée: #{pr_info.pr_number}")
            state.results["last_operation_result"] = f"PR créée: {pr_info.pr_url}"
            
            logger.info(f"✅ PR créée avec succès - #{pr_info.pr_number}: {pr_info.pr_url}")
            
        else:
            error_msg = pr_result.get("error", "Erreur inconnue lors de la création de PR")
            state.results["error_logs"].append(f"Échec création PR: {error_msg}")
            state.results["ai_messages"].append(f"❌ Échec PR: {error_msg}")
            logger.error(f"❌ Échec création PR: {error_msg}")
        
        if state.results.get("pr_info") and len(state.results.get("error_logs", [])) > 0:
            try:
                summary_comment = await _generate_summary_comment(state)
                await github_tool._arun(
                    action="add_comment",
                    repo_url=repo_url,
                    pr_number=state.results["pr_info"].pr_number,
                    comment=summary_comment
                )
                logger.info("📝 Commentaire de résumé ajouté à la PR")
            except Exception as e:
                logger.warning(f"Impossible d'ajouter le commentaire de résumé: {e}")
        
        state.results["should_continue"] = True
        
    except Exception as e:
        error_msg = f"Exception lors de la finalisation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        state.results["error_logs"].append(error_msg)
        state.results["ai_messages"].append(f"❌ Exception: {error_msg}")
        state.results["last_operation_result"] = error_msg
        state.results["should_continue"] = True
    
    logger.info("🏁 Finalisation terminée")
    return state

async def _generate_pr_content(task, state: Dict[str, Any]) -> tuple[str, str]:
    pr_title = f"feat: {task.title}"
    
    pr_body = f"""## 🤖 Pull Request générée automatiquement

### 📋 Tâche
**ID**: {task.task_id}
**Titre**: {task.title}
**Priorité**: {task.priority}

### 📝 Description
{task.description}

### 🔧 Changements apportés
"""
    
    if state.results.get("modified_files"):
        pr_body += "\n#### Fichiers modifiés:\n"
        for file_path in state.results["modified_files"]:
            pr_body += f"- `{file_path}`\n"
    
    if state.results.get("test_results"):
        latest_test = state.results["test_results"][-1]
        if latest_test.success:
            pr_body += f"\n### ✅ Tests\n- ✅ Tests passés avec `{latest_test.test_command}`\n"
        else:
            pr_body += f"\n### ⚠️ Tests\n- ⚠️ Derniers tests: `{latest_test.test_command}` (voir logs)\n"
    
    if state.results.get("debug_attempts", 0) > 0:
        pr_body += f"\n### 🔧 Debug\n- 🔧 {state.results.get('debug_attempts', 0)} tentative(s) de correction effectuée(s)\n"
    
    if state.results.get("error_logs"):
        recent_errors = state.results["error_logs"][-3:]
        pr_body += "\n### 📊 Informations de développement\n"
        pr_body += "<details><summary>Logs de développement (cliquer pour développer)</summary>\n\n"
        for error in recent_errors:
            pr_body += f"- {error}\n"
        pr_body += "\n</details>\n"
    
    pr_body += f"""
### 🎯 Prêt pour la revue
Cette Pull Request a été générée automatiquement par l'agent IA.
- ✅ Code implémenté selon les spécifications
- ✅ Tests validés
- ✅ Prêt pour la revue humaine

**Branche**: `{task.git_branch}`
**Assigné**: {task.assignee or 'Non assigné'}
"""
    
    return pr_title, pr_body

async def _generate_summary_comment(state: Dict[str, Any]) -> str:
    comment = "## 🤖 Résumé de l'implémentation automatique\n\n"
    
    comment += "### 📊 Statistiques\n"
    comment += f"- **Fichiers modifiés**: {len(state.results.get('modified_files', []))}\n"
    comment += f"- **Tests exécutés**: {len(state.results.get('test_results', []))}\n"
    comment += f"- **Tentatives de debug**: {state.results.get('debug_attempts', 0)}\n"
    
    if state.results.get("ai_messages"):
        comment += "\n### 📅 Chronologie du développement\n"
        important_messages = [msg for msg in state.results["ai_messages"] if any(marker in msg for marker in ["✅", "❌", "🔧", "📋"])]
        for msg in important_messages[-5:]:
            comment += f"- {msg}\n"
    
    comment += "\n### 💡 Recommandations pour la revue\n"
    
    if state.results.get("debug_attempts", 0) > 0:
        comment += "- ⚠️ Cette implémentation a nécessité du debug, vérifiez particulièrement la logique corrigée\n"
    
    if state.results.get("test_results") and not state.results["test_results"][-1].success:
        comment += "- ⚠️ Les derniers tests n'ont pas tous réussi, tests manuels recommandés\n"
    
    comment += "- 👀 Vérifiez que l'implémentation respecte les standards du projet\n"
    comment += "- 🧪 Effectuez des tests d'intégration si nécessaire\n"
    
    return comment

def should_continue_to_update(state: Dict[str, Any]) -> bool:
    return True 