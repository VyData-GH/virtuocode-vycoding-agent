import asyncio
import httpx
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode
from pydantic import Field

from .base_tool import BaseTool
from config.settings import get_settings
from models.schemas import TaskRequest
from utils.logger import get_logger


class MondayTool(BaseTool):
    
    name: str = "monday_tool"
    description: str = """
    Outil pour interagir avec Monday.com via OAuth.
    
    Fonctionnalités:
    - Récupérer les informations des items Monday.com
    - Mettre à jour le statut des tâches
    - Ajouter des commentaires
    - Marquer les tâches comme terminées
    - Parser les webhooks Monday.com
    - Mettre à jour les valeurs des colonnes
    """
    
    # Configuration OAuth Monday.com
    client_id: Optional[str] = Field(default=None)
    client_key: Optional[str] = Field(default=None) 
    app_id: Optional[str] = Field(default=None)
    
    base_url: str = "https://api.monday.com/v2"
    oauth_url: str = "https://auth.monday.com/oauth2/token"
    

    def __init__(self):
        super().__init__()
        
        self.client_id = self.settings.monday_client_id
        self.client_key = self.settings.monday_client_key
        self.app_id = self.settings.monday_app_id
        
        object.__setattr__(self, 'api_token', self.settings.monday_api_token)
        
        object.__setattr__(self, '_access_token', None)
        object.__setattr__(self, '_token_expires_at', None)

    async def _get_access_token(self) -> str:
        
        if self.api_token:
            return self.api_token
        
        raise Exception("Monday.com API Token non configuré")

    async def _make_request(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        
        try:
            access_token = await self._get_access_token()
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "API-Version": "2024-01"
            }
            
            payload = {
                "query": query,
                "variables": variables or {}
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code != 200:
                    error_msg = f"Erreur API Monday.com: {response.status_code} - {response.text}"
                    self.logger.error(error_msg)
                    return {"success": False, "error": error_msg}
                
                data = response.json()
                
                if "errors" in data:
                    error_msg = f"Erreurs GraphQL Monday.com: {data['errors']}"
                    self.logger.error(error_msg)
                    return {"success": False, "error": error_msg}
                
                return {"success": True, "data": data.get("data", {})}
                
        except Exception as e:
            error_msg = f"Exception lors de la requête Monday.com: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}

    async def _arun(self, action: str, **kwargs) -> Dict[str, Any]:
        
        try:
            if action == "get_item_info":
                return await self._get_item_info(kwargs["item_id"])
            elif action == "update_item_status":
                return await self._update_item_status(kwargs["item_id"], kwargs["status"])
            elif action == "add_comment":
                return await self._add_comment(kwargs["item_id"], kwargs["comment"])
            elif action == "complete_task":
                return await self._complete_task(
                    kwargs["item_id"], 
                    kwargs.get("pr_url"), 
                    kwargs.get("completion_comment")
                )
            elif action == "update_column_value":
                return await self._update_column_value(
                    kwargs["item_id"], 
                    kwargs["column_id"], 
                    kwargs["value"]
                )
            else:
                return {"success": False, "error": f"Action non supportée: {action}"}
                
        except Exception as e:
            return self.handle_error(e, f"action {action}")

    def parse_monday_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        
        try:
            if "event" not in payload:
                self.logger.info("Webhook ignoré - pas d'événement")
                return None
            
            event = payload["event"]
            
            event_type = event.get("type")
            if event_type not in ["update_column_value", "change_status", "status_changed"]:
                self.logger.info(f"Webhook ignoré - type d'événement: {event_type}")
                return None
            

            pulse_id = event.get("pulseId")
            pulse_name = event.get("pulseName", "")
            board_id = event.get("boardId")
            
            if not pulse_id:
                self.logger.warning("Webhook ignoré - pas de pulseId")
                return None
            
            column_values = event.get("columnValues", {})
            
            task_info = {
                "task_id": str(pulse_id),
                "title": pulse_name,
                "description": column_values.get("description", {}).get("text", ""),
                "task_type": column_values.get("task_type", {}).get("text", "feature"),
                "priority": column_values.get("priority", {}).get("text", "medium"),
                "repository_url": column_values.get("repository_url", {}).get("text", ""),
                "branch_name": column_values.get("branch_name", {}).get("text"),
                "acceptance_criteria": column_values.get("acceptance_criteria", {}).get("text"),
                "technical_context": column_values.get("technical_context", {}).get("text"),
                "estimated_complexity": column_values.get("estimated_complexity", {}).get("text"),
                "board_id": str(board_id) if board_id else None
            }
            
            files_text = column_values.get("files_to_modify", {}).get("text", "")
            if files_text:
                task_info["files_to_modify"] = [f.strip() for f in files_text.split(",")]
            
            self.logger.info(f"✅ Tâche extraite du webhook: {task_info['title']}")
            return task_info
            
        except Exception as e:
            self.logger.error(f"Erreur lors du parsing webhook: {e}")
            return None

    async def _get_item_info(self, item_id: str) -> Dict[str, Any]:
        
        query = """
        query GetItem($itemId: [ID!]) {
            items(ids: $itemId) {
                id
                name
                board {
                    id
                    name
                }
                column_values {
                    id
                    text
                    value
                }
                state
                created_at
                updated_at
            }
        }
        """
        
        variables = {"itemId": [item_id]}
        
        try:
            result = await self._make_request(query, variables)
            
            if result["success"] and result["data"].get("items"):
                item_data = result["data"]["items"][0]
                return {
                    "success": True,
                    "item": item_data,
                    "id": item_data["id"],
                    "name": item_data["name"],
                    "board_id": item_data["board"]["id"],
                    "column_values": {
                        col["id"]: {"text": col["text"], "value": col["value"]} 
                        for col in item_data["column_values"]
                    }
                }
            else:
                return {"success": False, "error": f"Item {item_id} non trouvé"}
                
        except Exception as e:
            return self.handle_error(e, f"récupération des infos de l'item {item_id}")

    async def _update_item_status(self, item_id: str, status: str) -> Dict[str, Any]:
        
        status_mapping = {
            "À faire": "todo",
            "En cours": "working_on_it", 
            "En revue": "review",
            "Terminé": "done",
            "Bloqué": "stuck"
        }
        
        status_value = status_mapping.get(status, status.lower())
        
        query = """
        mutation UpdateItemStatus($itemId: ID!, $boardId: ID!, $columnId: String!, $value: JSON!) {
            change_column_value(
                item_id: $itemId, 
                board_id: $boardId, 
                column_id: $columnId, 
                value: $value
            ) {
                id
                name
            }
        }
        """
        
        variables = {
            "itemId": item_id,
            "boardId": self.settings.monday_board_id,
            "columnId": self.settings.monday_status_column_id,
            "value": json.dumps({"label": status})
        }
        
        try:
            result = await self._make_request(query, variables)
            
            if result["success"]:
                self.logger.info(f"✅ Statut mis à jour: {item_id} → {status}")
                return {"success": True, "status": status, "item_id": item_id}
            else:
                return result
                
        except Exception as e:
            return self.handle_error(e, f"mise à jour du statut de l'item {item_id}")

    async def _add_comment(self, item_id: str, comment: str) -> Dict[str, Any]:
        
        query = """
        mutation AddComment($itemId: ID!, $body: String!) {
            create_update(item_id: $itemId, body: $body) {
                id
                body
                created_at
            }
        }
        """
        
        variables = {
            "itemId": item_id,
            "body": comment
        }
        
        try:
            result = await self._make_request(query, variables)
            
            if result["success"]:
                self.logger.info(f"✅ Commentaire ajouté à l'item {item_id}")
                return {
                    "success": True, 
                    "comment_id": result["data"]["create_update"]["id"],
                    "item_id": item_id
                }
            else:
                return result
                
        except Exception as e:
            return self.handle_error(e, f"ajout de commentaire à l'item {item_id}")

    async def _update_column_value(self, item_id: str, column_id: str, value: str) -> Dict[str, Any]:
        """Met à jour la valeur d'une colonne spécifique."""
        
        query = """
        mutation UpdateColumnValue($itemId: ID!, $boardId: ID!, $columnId: String!, $value: JSON!) {
            change_column_value(
                item_id: $itemId,
                board_id: $boardId, 
                column_id: $columnId,
                value: $value
            ) {
                id
                name
            }
        }
        """
        
        variables = {
            "itemId": item_id,
            "boardId": self.settings.monday_board_id,
            "columnId": column_id,
            "value": json.dumps(value)
        }
        
        try:
            result = await self._make_request(query, variables)
            
            if result["success"]:
                self.logger.info(f"✅ Colonne {column_id} mise à jour pour l'item {item_id}")
                return {"success": True, "column_id": column_id, "value": value}
            else:
                return result
                
        except Exception as e:
            return self.handle_error(e, f"mise à jour de la colonne {column_id}")

    async def _complete_task(self, item_id: str, pr_url: Optional[str] = None, 
                           completion_comment: Optional[str] = None) -> Dict[str, Any]:
        """Marque une tâche comme terminée avec toutes les mises à jour nécessaires."""
        try:
            results = []
            
            status_result = await self._update_item_status(item_id, "Terminé")
            results.append(("status_update", status_result))
            
            if not completion_comment:
                completion_comment = f"""🎉 **Tâche terminée automatiquement par l'agent IA**

✅ **Statut**: Implémentation terminée avec succès
📅 **Complété le**: {datetime.now().strftime('%d/%m/%Y à %H:%M')}"""
            
            if pr_url:
                completion_comment += f"\n🔗 **Pull Request**: {pr_url}"
            
            comment_result = await self._add_comment(item_id, completion_comment)
            results.append(("comment", comment_result))
            
            if pr_url:
                try:
                    pr_column_result = await self._update_column_value(
                        item_id, 
                        "lien_pr",  
                        pr_url
                    )
                    results.append(("pr_link", pr_column_result))
                except Exception:
                    pass
            
            critical_success = (
                status_result.get("success", False) and 
                comment_result.get("success", False)
            )
            
            if critical_success:
                self.logger.info(f"✅ Tâche {item_id} marquée comme terminée")
                return {
                    "success": True,
                    "message": "Tâche terminée avec succès",
                    "operations": results,
                    "item_id": item_id,
                    "pr_url": pr_url
                }
            else:
                failed_ops = [op for op, result in results if not result.get("success", False)]
                return {
                    "success": False,
                    "error": f"Échec des opérations: {failed_ops}",
                    "operations": results
                }
                
        except Exception as e:
            return self.handle_error(e, f"completion de la tâche {item_id}")

    def handle_error(self, error: Exception, context: str) -> Dict[str, Any]:
        error_msg = f"Erreur Monday.com lors de {context}: {str(error)}"
        self.logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "context": context
        } 