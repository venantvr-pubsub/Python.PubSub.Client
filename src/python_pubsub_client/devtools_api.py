"""
API HTTP pour communication avec DevTools (processus séparé).

Permet à DevTools de publier des événements sur le ServiceBus depuis un autre processus.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, TYPE_CHECKING

from flask import Flask, request, jsonify

if TYPE_CHECKING:
    from .service_bus import ServiceBus


class DevToolsAPI:
    """Mini serveur HTTP pour permettre à DevTools de publier des événements.

    Args:
        service_bus: Instance ServiceBus sur laquelle publier
        port: Port HTTP pour l'API (défaut: 8765)
    """

    def __init__(self, service_bus: ServiceBus, port: int = 8765):
        self.service_bus = service_bus
        self.port = port
        self.app = Flask(__name__)
        self._register_routes()

    def _register_routes(self) -> None:
        """Enregistre les routes Flask."""

        @self.app.route('/api/publish', methods=['POST'])
        def publish():
            """Endpoint pour publier un événement depuis DevTools.

            Request JSON:
                event_name: Nom de l'événement
                event_data: Données de l'événement (dict)
                source: Source de l'événement (défaut: "DevTools")

            Returns:
                JSON avec success: true/false
            """
            data = request.json
            event_name = data['event_name']
            event_data = data['event_data']
            source = data.get('source', 'DevTools')

            try:
                # Publier sur le ServiceBus
                # Note: event_data est déjà un dict, pas besoin de reconstruction
                self.service_bus.publish(event_name, event_data, source)
                return jsonify({'success': True})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/health', methods=['GET'])
        def health():
            """Healthcheck endpoint."""
            return jsonify({'status': 'ok', 'service': 'ServiceBus DevTools API'})

    def start(self) -> None:
        """Lance l'API dans un thread daemon + écrit fichier discovery."""
        # Thread daemon pour l'API Flask
        thread = threading.Thread(
            target=lambda: self.app.run(
                host='0.0.0.0',
                port=self.port,
                debug=False,
                use_reloader=False
            ),
            daemon=True
        )
        thread.start()

        # Écrire fichier discovery pour auto-détection par DevTools
        discovery_file = Path.home() / '.servicebus_endpoint.json'
        discovery_file.write_text(json.dumps({
            'host': 'localhost',
            'port': self.port
        }))

        print(f"✓ DevTools API started at http://localhost:{self.port}")
        print(f"  Discovery file: {discovery_file}")
