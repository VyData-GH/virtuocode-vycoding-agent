"""Outil Monday.com pour la gestion des tickets."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import requests
from pydantic import Field

from .base_tool import BaseTool
from models.schemas import MondayUpdateRequest


class MondayTool(BaseTool):
    """Outil pour interagir avec l'API Monday.com."""
    
    name: str = "monday_tool"
    description: str = """
    Outil pour interagir avec Monday.com.
    
    Fonctionnalités:
    - Mettre à jour le statut des tâches
    - Ajouter des commentaires
    - Modifier les colonnes personnalisées
    - Récupérer les informations des items
    """
    
    api_url: str = "https://api.monday.com/v2"
    headers: Dict[str, str] = Field(default_factory=dict)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.headers = {
            "Authorization": f"Bearer {self.settings.monday_api_key}",
            "Content-Type": "application/json"
        }
    
    async def _arun(self, action: str, **kwargs) -> Dict[str, Any]:
        """Exécute une action Monday.com."""
        try:
            if action == "update_item_status":
                return await self._update_item_status(
                    item_id=kwargs.get("item_id"),
                    status=kwargs.get("status"),
                    column_id=kwargs.get("column_id")
                )
            elif action == "add_comment":
                return await self._add_comment(
                    item_id=kwargs.get("item_id"),
                    comment=kwargs.get("comment")
                )
            elif action == "update_column_value":
                return await self._update_column_value(
                    item_id=kwargs.get("item_id"),
                    column_id=kwargs.get("column_id"),
                    value=kwargs.get("value")
                )
            elif action == "get_item_info":
                return await self._get_item_info(kwargs.get("item_id"))
            elif action == "complete_task":
                return await self._complete_task(
                    item_id=kwargs.get("item_id"),
                    pr_url=kwargs.get("pr_url"),
                    completion_comment=kwargs.get("completion_comment")
                )
            else:
                raise ValueError(f"Action non supportée: {action}")
                
        except Exception as e:
            return self.handle_error(e, f"monday_tool.{action}")
    
    async def _update_item_status(self, item_id: str, status: str, 
                                column_id: Optional[str] = None) -> Dict[str, Any]:
        """Met à jour le statut d'un item Monday."""
        try:
            if not column_id:
                column_id = self.settings.monday_status_column_id
            
            query = """
            mutation ($item_id: ID!, $column_id: String!, $value: JSON!) {
                change_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
                    id
                    name
                    column_values {
                        id
                        text
                    }
                }
            }
            """
            
            # Formater la valeur selon le type de colonne statut Monday
            status_value = {"label": status}
            
            variables = {
                "item_id": item_id,
                "column_id": column_id,
                "value": status_value
            }
            
            response = await self._make_request(query, variables)
            
            if response.get("data", {}).get("change_column_value"):
                self.log_operation(f"Mise à jour statut item {item_id}", True, 
                                 f"Nouveau statut: {status}")
                return {
                    "success": True,
                    "item_id": item_id,
                    "new_status": status,
                    "response": response["data"]["change_column_value"]
                }
            else:
                error_msg = response.get("errors", [{}])[0].get("message", "Erreur inconnue")
                return {
                    "success": False,
                    "error": f"Échec mise à jour statut: {error_msg}"
                }
                
        except Exception as e:
            return self.handle_error(e, f"mise à jour du statut de l'item {item_id}")
    
    async def _add_comment(self, item_id: str, comment: str) -> Dict[str, Any]:
        """Ajoute un commentaire à un item Monday."""
        try:
            query = """
            mutation ($item_id: ID!, $body: String!) {
                create_update(item_id: $item_id, body: $body) {
                    id
                    body
                    created_at
                }
            }
            """
            
            variables = {
                "item_id": item_id,
                "body": comment
            }
            
            response = await self._make_request(query, variables)
            
            if response.get("data", {}).get("create_update"):
                self.log_operation(f"Commentaire ajouté item {item_id}", True)
                return {
                    "success": True,
                    "comment_id": response["data"]["create_update"]["id"],
                    "item_id": item_id
                }
            else:
                error_msg = response.get("errors", [{}])[0].get("message", "Erreur inconnue")
                return {
                    "success": False,
                    "error": f"Échec ajout commentaire: {error_msg}"
                }
                
        except Exception as e:
            return self.handle_error(e, f"ajout de commentaire à l'item {item_id}")
    
    async def _update_column_value(self, item_id: str, column_id: str, value: Any) -> Dict[str, Any]:
        """Met à jour une valeur de colonne spécifique."""
        try:
            query = """
            mutation ($item_id: ID!, $column_id: String!, $value: JSON!) {
                change_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
                    id
                    name
                }
            }
            """
            
            variables = {
                "item_id": item_id,
                "column_id": column_id,
                "value": value
            }
            
            response = await self._make_request(query, variables)
            
            if response.get("data", {}).get("change_column_value"):
                self.log_operation(f"Mise à jour colonne {column_id} item {item_id}", True)
                return {
                    "success": True,
                    "item_id": item_id,
                    "column_id": column_id,
                    "new_value": value
                }
            else:
                error_msg = response.get("errors", [{}])[0].get("message", "Erreur inconnue")
                return {
                    "success": False,
                    "error": f"Échec mise à jour colonne: {error_msg}"
                }
                
        except Exception as e:
            return self.handle_error(e, f"mise à jour de la colonne {column_id}")
    
    async def _get_item_info(self, item_id: str) -> Dict[str, Any]:
        """Récupère les informations détaillées d'un item."""
        try:
            query = """
            query ($item_id: [ID!]) {
                items(ids: $item_id) {
                    id
                    name
                    state
                    created_at
                    updated_at
                    column_values {
                        id
                        text
                        value
                    }
                    updates {
                        id
                        body
                        created_at
                    }
                }
            }
            """
            
            variables = {"item_id": [item_id]}
            
            response = await self._make_request(query, variables)
            
            if response.get("data", {}).get("items"):
                item_data = response["data"]["items"][0]
                self.log_operation(f"Récupération info item {item_id}", True)
                return {
                    "success": True,
                    "item": item_data
                }
            else:
                return {
                    "success": False,
                    "error": "Item non trouvé"
                }
                
        except Exception as e:
            return self.handle_error(e, f"récupération des infos de l'item {item_id}")
    
    async def _complete_task(self, item_id: str, pr_url: Optional[str] = None, 
                           completion_comment: Optional[str] = None) -> Dict[str, Any]:
        """Marque une tâche comme terminée avec toutes les mises à jour nécessaires."""
        try:
            results = []
            
            # 1. Mettre à jour le statut à "Terminé"
            status_result = await self._update_item_status(item_id, "Terminé")
            results.append(("status_update", status_result))
            
            # 2. Ajouter un commentaire de completion
            if not completion_comment:
                completion_comment = f"""🎉 **Tâche terminée automatiquement par l'agent IA**

✅ **Statut**: Implémentation terminée avec succès
📅 **Complété le**: {datetime.now().strftime('%d/%m/%Y à %H:%M')}"""
            
            if pr_url:
                completion_comment += f"\n🔗 **Pull Request**: {pr_url}"
            
            comment_result = await self._add_comment(item_id, completion_comment)
            results.append(("comment", comment_result))
            
            # 3. Si URL PR fournie, la mettre dans une colonne dédiée (si configurée)
            if pr_url:
                try:
                    # Essayer de mettre l'URL dans une colonne "PR Link" (colonne texte)
                    pr_column_result = await self._update_column_value(
                        item_id, 
                        "lien_pr",  # ID de colonne à configurer
                        pr_url
                    )
                    results.append(("pr_link", pr_column_result))
                except Exception:
                    # Si la colonne n'existe pas, on ignore cette étape
                    pass
            
            # Vérifier que les opérations critiques ont réussi
            critical_success = (
                status_result.get("success", False) and 
                comment_result.get("success", False)
            )
            
            if critical_success:
                self.log_operation(f"Tâche complétée item {item_id}", True, pr_url)
                return {
                    "success": True,
                    "item_id": item_id,
                    "pr_url": pr_url,
                    "operations": results
                }
            else:
                return {
                    "success": False,
                    "error": "Échec d'une ou plusieurs opérations critiques",
                    "operations": results
                }
                
        except Exception as e:
            return self.handle_error(e, f"completion de la tâche {item_id}")
    
    async def _make_request(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Effectue une requête GraphQL vers l'API Monday."""
        payload = {
            "query": query,
            "variables": variables
        }
        
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            self.logger.error(f"Erreur requête Monday API: {e}")
            raise
    
    def parse_monday_webhook(self, webhook_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse les données d'un webhook Monday pour extraire les infos de tâche."""
        try:
            # Structure typique d'un webhook Monday.com
            event = webhook_data.get("event", {})
            
            if not event:
                return None
            
            # Extraire les informations pertinentes
            item_id = str(event.get("pulseId", ""))
            board_id = str(event.get("boardId", ""))
            
            # Vérifier que c'est le bon board
            if board_id != self.settings.monday_board_id:
                self.logger.info(f"Webhook ignoré - Board ID différent: {board_id}")
                return None
            
            # Récupérer les valeurs des colonnes
            column_values = event.get("columnValues", {})
            
            return {
                "item_id": item_id,
                "board_id": board_id,
                "title": event.get("pulseName", ""),
                "column_values": column_values,
                "event_type": webhook_data.get("type", ""),
                "raw_event": event
            }
            
        except Exception as e:
            self.logger.error(f"Erreur parsing webhook Monday: {e}")
            return None 