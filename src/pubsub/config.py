# src/pubsub/config.py

import logging
import os
from typing import Optional
from dotenv import load_dotenv

# Essayer de charger les variables d'environnement depuis un fichier .env
try:
    load_dotenv()
    print("✅ Configuration loaded from .env file")
except ImportError:
    print("ℹ️ python-dotenv not installed, using system environment variables only.")


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Récupère une variable d'environnement avec le préfixe PUBSUB_."""
    return os.getenv(f"PUBSUB_{key.upper()}", default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Récupère une variable d'environnement de type booléen."""
    value = get_env(key, str(default))
    return value.lower() in ("true", "1", "yes", "on")


def setup_logging() -> None:
    """
    Configure le logging pour la librairie et l'application.

    Cette fonction lit les variables d'environnement PUBSUB_LOG_*
    et initialise le logger racine de Python. Elle ne doit être
    appelée qu'une seule fois au démarrage de l'application.
    """
    log_level = get_env("LOG_LEVEL", "INFO").upper()
    log_format = get_env(
        "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Récupère le logger racine pour appliquer la configuration globale
    root_logger = logging.getLogger()

    # S'assure de ne pas ajouter de handlers si déjà configuré
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Configure le niveau du logger racine
    root_logger.setLevel(log_level)

    # Configure le handler pour la console
    if get_env_bool("LOG_TO_CONSOLE", True):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(console_handler)

    # Configure le handler pour un fichier si spécifié
    log_file = get_env("LOG_FILE")
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter(log_format))
            root_logger.addHandler(file_handler)
        except (IOError, FileNotFoundError) as e:
            logging.error(f"Could not configure file logging to {log_file}: {e}")

    logging.info(f"Logging configured to level {log_level}")

