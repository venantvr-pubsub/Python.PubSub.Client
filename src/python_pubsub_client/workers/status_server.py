import http.server
import json
import socketserver
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, List

from ..config import get_env
from ..logger import logger

# Importation conditionnelle pour éviter une dépendance circulaire lors de l'exécution
# tout en fournissant les informations de type pour les analyseurs de code.
if TYPE_CHECKING:
    from .threading_base import QueueWorkerThread

STATUS_PAGE_PORT = int(get_env("STATUS_PAGE_PORT", "8000"))


class StatusServer(threading.Thread):
    """Un serveur HTTP dédié à l'affichage du statut des workers via une page web dynamique."""

    def __init__(self, services_to_monitor: List["QueueWorkerThread"]):
        super().__init__(name="StatusServer", daemon=True)
        self.services_to_monitor = services_to_monitor
        self.html_content = "<html><body>Initializing...</body></html>"
        self.json_content = "{}"
        self.content_lock = threading.Lock()
        self._running = True
        self._server_ready = threading.Event()
        self._shutdown_complete = threading.Event()
        self.httpd = None
        self.content_generator_thread = None

    def run(self):
        """Démarre la boucle de génération de contenu et le serveur HTTP."""
        self.content_generator_thread = threading.Thread(
            target=self._generate_content_loop, daemon=True
        )
        self.content_generator_thread.start()
        self._start_http_server()
        self._shutdown_complete.set()

    def _generate_content_loop(self):
        """Met à jour continuellement le contenu HTML et JSON avec gestion des erreurs."""
        while self._running:
            try:
                self._update_content()
            except Exception as e:
                logger.error(f"Error updating status content: {e}", exc_info=True)
                with self.content_lock:
                    self.html_content = f"<html><body><h1>Status Server Error</h1><p>Failed to generate status page: {e}</p></body></html>"
                    self.json_content = json.dumps({"error": str(e)})
            time.sleep(5)  # Intervalle de mise à jour du contenu

    # noinspection PyMethodMayBeStatic
    def _load_templates(self) -> dict:
        """Charge les templates HTML, CSS, et JS depuis les fichiers."""
        template_dir = Path(__file__).parent / "templates"
        html_path = template_dir / "status_page.html"
        css_path = template_dir / "status_page.css"
        js_path = template_dir / "status_page.js"
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_template = f.read()
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()
            with open(js_path, "r", encoding="utf-8") as f:
                js_content = f.read()
            return {"html": html_template, "css": css_content, "js": js_content}
        except Exception as e:
            logger.error(f"Failed to load template files: {e}")
            raise RuntimeError(f"Template files not found at {template_dir}.")

    def _update_content(self):
        """Génère et met en cache les données JSON et la page HTML finale."""
        templates = self._load_templates()
        statuses = [service.get_status() for service in self.services_to_monitor]
        update_time = time.time() * 1000  # JavaScript's Date object expects milliseconds

        # Génère le contenu JSON pour le point de terminaison de l'API
        json_data = json.dumps({"services": statuses, "update_time": update_time})

        # Génère le HTML final en injectant le contenu CSS et JS dans le template
        html = templates["html"]
        html = html.replace("$$CSS_CONTENT$$", templates["css"])
        html = html.replace("$$JS_CONTENT$$", templates["js"])

        # Met à jour le contenu en cache de manière thread-safe
        with self.content_lock:
            self.json_content = json_data
            self.html_content = html

    def _start_http_server(self):
        """Démarre la boucle principale du serveur HTTP."""
        parent = self

        class StatusHandler(http.server.SimpleHTTPRequestHandler):
            """Gestionnaire de requêtes personnalisé pour servir le HTML et le JSON."""

            def do_GET(self):
                try:
                    if self.path == "/":
                        self.send_response(200)
                        self.send_header("Content-type", "text/html; charset=utf-8")
                        self.end_headers()
                        with parent.content_lock:
                            self.wfile.write(bytes(parent.html_content, "utf8"))
                    elif self.path == "/status.json":
                        self.send_response(200)
                        self.send_header("Content-type", "application/json; charset=utf-8")
                        self.end_headers()
                        with parent.content_lock:
                            self.wfile.write(bytes(parent.json_content, "utf8"))
                    else:
                        self.send_error(404, "File Not Found")
                except Exception as e:
                    logger.error(f"Error handling HTTP request: {e}", exc_info=False)

            # Silences the default logging of HTTP requests to the console
            # noinspection PyShadowingBuiltins
            def log_message(self, format, *args):
                return

        try:
            # Permet la réutilisation du socket pour éviter les erreurs "Address already in use"
            socketserver.TCPServer.allow_reuse_address = True
            # noinspection PyTypeChecker
            self.httpd = socketserver.TCPServer(("", STATUS_PAGE_PORT), StatusHandler)
            self.httpd.timeout = 1
            logger.info(f"Status server listening on http://localhost:{STATUS_PAGE_PORT}")
            self._server_ready.set()

            # Boucle principale du serveur
            while self._running:
                try:
                    # Le try/except protège chaque requête individuellement
                    self.httpd.handle_request()
                except Exception as e:
                    # Si une requête échoue, on logue l'erreur et on continue.
                    if self._running:
                        logger.error(f"Error in HTTP server loop: {e}", exc_info=True)

        except OSError as e:
            logger.error(
                f"Unable to start status server on port {STATUS_PAGE_PORT}. Port already in use? Error: {e}"
            )
            self._server_ready.set()
        except Exception as e:
            logger.error(f"Unexpected error starting HTTP server: {e}", exc_info=True)
            self._server_ready.set()
        finally:
            if self.httpd:
                try:
                    self.httpd.server_close()
                except Exception as e:
                    logger.warning(f"Error closing HTTP server: {e}")

    def stop(self, timeout: float = 5.0):
        """Arrête le serveur de statut de manière propre."""
        if not self._running:
            return
        logger.info(f"Stopping status server on port {STATUS_PAGE_PORT}...")
        self._running = False
        if not self._shutdown_complete.wait(timeout=timeout):
            logger.warning(f"Status server did not shut down cleanly within {timeout}s")
        logger.info(f"Status server on port {STATUS_PAGE_PORT} stopped successfully")
