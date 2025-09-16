# examples/simple_client.py

import logging
import sys
from typing import Any

# L'importation se fait maintenant depuis le nom du package 'pubsub'
from src.pubsub.pubsub_client import PubSubClient

# Pour que cet exemple fonctionne sans installer le package,
# nous ajoutons le dossier 'src' au path. Un utilisateur final n'aura pas besoin de faire ça.
# Il fera simplement 'pip install simple-pubsub-client'
sys.path.insert(0, "../src")

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# L'URL doit être configurable, pas en dur
BASE_URL = "http://localhost:5000"


def main() -> None:
    """Entry point for the pubsub client demo."""
    # Le code ci-dessous est un exemple de comment utiliser la bibliothèque
    client = PubSubClient(url=BASE_URL, consumer="demo-client", topics=["test"])

    # Enregistrer un handler pour un topic spécifique
    def handle_test_message(message: Any):
        logger.info(f"Handler personnalisé pour 'test' a reçu : {message}")

    client.register_handler("test", handle_test_message)

    try:
        # La méthode start() gère la connexion et l'attente
        client.start()
    except KeyboardInterrupt:
        logger.info("Client déconnecté par l'utilisateur.")
    except Exception as e:
        logger.error(f"Une erreur est survenue: {e}")


if __name__ == "__main__":
    main()
