"""
Proxy HTTP pour enregistrer les événements vers DevTools.

Envoie automatiquement tous les événements publiés vers DevTools
pour enregistrement en temps réel.
"""
from __future__ import annotations

import requests
from typing import Any, Optional

from .logger import logger


class DevToolsRecorderProxy:
    """Proxy qui envoie les événements à DevTools pour enregistrement.

    Utilisé pour capturer automatiquement tous les événements publiés
    et les enregistrer dans DevTools via HTTP.

    Args:
        devtools_host: Hôte de DevTools (défaut: localhost)
        devtools_port: Port de l'API HTTP de DevTools (défaut: 5556)
    """

    def __init__(self, devtools_host: str = 'localhost', devtools_port: int = 5556):
        self.devtools_host = devtools_host
        self.devtools_port = devtools_port
        self.base_url = f'http://{devtools_host}:{devtools_port}'
        self._session_started = False

    def start_session(self, session_name: Optional[str] = None) -> bool:
        """Démarre une session d'enregistrement dans DevTools.

        Args:
            session_name: Nom de la session (optionnel)

        Returns:
            True si succès, False sinon
        """
        try:
            payload = {}
            if session_name:
                payload['session_name'] = session_name

            response = requests.post(
                f'{self.base_url}/api/record/start',
                json=payload,
                timeout=5
            )
            response.raise_for_status()
            self._session_started = True
            logger.info(f"✓ DevTools recording session started: {session_name or 'auto'}")
            return True
        except requests.RequestException as e:
            logger.warning(f"Failed to start DevTools recording session: {e}")
            return False

    def record_event(self, event_name: str, event_data: Any, source: str) -> None:
        """Enregistre un événement dans DevTools.

        Args:
            event_name: Nom de l'événement
            event_data: Données de l'événement
            source: Source de l'événement
        """
        if not self._session_started:
            logger.debug("DevTools recording session not started, skipping event")
            return

        try:
            response = requests.post(
                f'{self.base_url}/api/record/event',
                json={
                    'event_name': event_name,
                    'event_data': event_data,
                    'source': source
                },
                timeout=5
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.debug(f"Failed to record event to DevTools: {e}")

    def stop_session(self) -> bool:
        """Arrête la session d'enregistrement et sauvegarde.

        Returns:
            True si succès, False sinon
        """
        if not self._session_started:
            return False

        try:
            response = requests.post(
                f'{self.base_url}/api/record/stop',
                timeout=5
            )
            response.raise_for_status()
            result = response.json()
            self._session_started = False
            logger.info(f"✓ DevTools recording saved: {result.get('filename')} ({result.get('event_count')} events)")
            return True
        except requests.RequestException as e:
            logger.warning(f"Failed to stop DevTools recording session: {e}")
            return False

    def __repr__(self) -> str:
        return f"DevToolsRecorderProxy({self.devtools_host}:{self.devtools_port})"
