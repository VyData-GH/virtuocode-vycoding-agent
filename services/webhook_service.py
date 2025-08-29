
import asyncio
import hmac
import hashlib
from typing import Dict, Any, Optional
from utils.logger import get_logger
from config.settings import get_settings
from models.schemas import TaskRequest

logger = get_logger(__name__)


class WebhookService:
    """Service pour traiter les webhooks de Monday.com."""
    
    def __init__(self):
        self.settings = get_settings()
        logger.info("🔗 Service Webhook initialisé")
    
    def _verify_signature(self, payload_body: str, signature: str) -> bool:
        """Vérifie la signature du webhook Monday.com."""
        if not signature or not self.settings.webhook_secret:
            logger.warning("⚠️ Signature ou secret webhook manquant")
            return False
        
        try:
            # Monday.com envoie la signature au format "sha256=..."
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            expected_signature = hmac.new(
                self.settings.webhook_secret.encode('utf-8'),
                payload_body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"❌ Erreur lors de la vérification de signature: {e}")
            return False
    
    async def process_webhook(self, payload: Dict[str, Any], signature: Optional[str] = None) -> Dict[str, Any]:
        """Traite un webhook reçu de Monday.com."""
        try:
            logger.info(f"📥 Traitement webhook Monday.com")
            
            # En mode debug, on skip la vérification de signature
            if not self.settings.debug and signature:
                if not self._verify_signature(str(payload), signature):
                    raise ValueError("Signature webhook invalide")
            
            # Vérifier si c'est un challenge webhook
            if "challenge" in payload:
                logger.info("✅ Challenge webhook détecté")
                return {"status": "challenge_accepted", "challenge": payload["challenge"]}
            
            # Pour le test, on crée une réponse simple
            logger.info("✅ Webhook traité avec succès")
            return {
                "status": "webhook_processed",
                "message": "Webhook reçu et traité en mode test",
                "payload_keys": list(payload.keys()) if payload else []
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur lors du traitement webhook: {e}")
            return {
                "status": "error",
                "error": str(e)
            } 