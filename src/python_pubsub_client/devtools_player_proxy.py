"""
Proxy HTTP pour rejouer les événements depuis DevTools.

Démarre un serveur HTTP sur un port aléatoire et s'enregistre auprès
de DevTools pour recevoir les événements rejoués.
"""
from __future__ import annotations

import socket
import threading
from typing import Any, Callable, Optional

import requests
from flask import Flask, request, jsonify

from .logger import logger


def _find_free_port(start_port: int = 10001, end_port: int = 65535) -> int:
    """
    Trouve un port libre dans la plage spécifiée.

    Args:
        start_port: Port de départ (défaut: 10001)
        end_port: Port de fin (défaut: 65535)

    Returns:
        Numéro de port libre

    Raises:
        RuntimeError: Si aucun port libre n'est trouvé
    """
    for port in range(start_port, end_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found between {start_port} and {end_port}")


class DevToolsPlayerProxy:
    """
    Proxy qui reçoit les événements rejoués de DevTools.

    Démarre un serveur HTTP local sur un port aléatoire, s'enregistre
    auprès de DevTools, et invoque une callback pour chaque événement reçu.

    Args:
        publish_callback: Fonction appelée pour publier les événements (signature: event_name, payload, producer)
        consumer_name: Nom du consumer pour l'enregistrement
        devtools_host: Hôte de DevTools (défaut: localhost)
        devtools_port: Port de l'API HTTP de DevTools (défaut: 5556)
    """

    def __init__(
        self,
        publish_callback: Callable[[str, Any, str], None],
        consumer_name: str,
        devtools_host: str = 'localhost',
        devtools_port: int = 5556
    ):
        self.publish_callback = publish_callback
        self.consumer_name = consumer_name
        self.devtools_host = devtools_host
        self.devtools_port = devtools_port
        self.devtools_base_url = f'http://{devtools_host}:{devtools_port}'

        # Trouver un port libre
        self.player_port = _find_free_port()
        self.player_url = f'http://localhost:{self.player_port}'

        # Créer l'application Flask
        self._app = Flask(__name__)
        self._app.add_url_rule('/replay', 'replay', self._handle_replay, methods=['POST'])

        # Thread du serveur
        self._server_thread: Optional[threading.Thread] = None
        self._registered = False

    def _handle_replay(self):
        """
        Endpoint qui reçoit les événements rejoués de DevTools.

        Payload attendu:
        {
            "event_name": str,
            "event_data": dict,
            "source": str
        }
        """
        try:
            data = request.get_json()
            event_name = data.get('event_name')
            event_data = data.get('event_data')
            source = data.get('source', 'DevToolsReplay')

            if not event_name or event_data is None:
                return jsonify({'error': 'Missing event_name or event_data'}), 400

            # Publier l'événement via la callback
            self.publish_callback(event_name, event_data, source)

            logger.debug(f"Replayed event: {event_name} from {source}")
            return jsonify({'status': 'replayed', 'event_name': event_name}), 200

        except Exception as e:
            logger.error(f"Error handling replay: {e}")
            return jsonify({'error': str(e)}), 500

    def start(self) -> bool:
        """
        Démarre le serveur player et s'enregistre auprès de DevTools.

        Returns:
            True si succès, False sinon
        """
        # Démarrer le serveur Flask dans un thread
        self._server_thread = threading.Thread(
            target=lambda: self._app.run(
                host='0.0.0.0',
                port=self.player_port,
                debug=False,
                use_reloader=False,
                threaded=True
            ),
            daemon=True,
            name=f"DevToolsPlayer-{self.player_port}"
        )
        self._server_thread.start()

        logger.info(f"✓ DevTools player started on port {self.player_port}")

        # S'enregistrer auprès de DevTools
        return self._register_with_devtools()

    def _register_with_devtools(self) -> bool:
        """
        Enregistre ce player auprès de DevTools.

        Returns:
            True si succès, False sinon
        """
        try:
            payload = {
                'player_endpoint': f'{self.player_url}/replay',
                'consumer_name': self.consumer_name
            }

            response = requests.post(
                f'{self.devtools_base_url}/api/player/register',
                json=payload,
                timeout=5
            )
            response.raise_for_status()
            self._registered = True
            logger.info(f"✓ Registered with DevTools event_recorder at {self.devtools_base_url}")
            return True

        except requests.RequestException as e:
            logger.warning(f"Failed to register with DevTools player: {e}")
            return False

    def unregister(self) -> bool:
        """
        Désenregistre ce player de DevTools.

        Returns:
            True si succès, False sinon
        """
        if not self._registered:
            return False

        try:
            payload = {
                'player_endpoint': f'{self.player_url}/replay'
            }

            response = requests.post(
                f'{self.devtools_base_url}/api/player/unregister',
                json=payload,
                timeout=5
            )
            response.raise_for_status()
            self._registered = False
            logger.info(f"✓ Unregistered from DevTools event_recorder")
            return True

        except requests.RequestException as e:
            logger.warning(f"Failed to unregister from DevTools player: {e}")
            return False

    def __repr__(self) -> str:
        return f"DevToolsPlayerProxy({self.player_url} -> {self.devtools_host}:{self.devtools_port})"
