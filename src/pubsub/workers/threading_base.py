import http.server
import queue
import socketserver
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, List

from ..base_bus import ServiceBusBase
from ..events import AllProcessingCompleted
from ..logger import logger

STATUS_PORT = 8000


class QueueWorkerThread(threading.Thread, ABC):
    """
    Classe de base abstraite pour un thread de travail qui consomme des tâches
    depuis une file d'attente (pattern Producer-Consumer).
    """

    def __init__(self, service_bus: Optional[ServiceBusBase] = None, name: Optional[str] = None):
        """
        Initialise le thread de travail.
        :param service_bus: Le bus de services pour la communication par événements.
        :param name: Le nom du thread, utile pour les logs.
        """
        super().__init__(name=name or self.__class__.__name__)
        self.service_bus = service_bus
        self.work_queue = queue.Queue()
        self._running = True

        if self.service_bus:
            self.setup_event_subscriptions()

    def get_status(self) -> dict:
        """Retourne l'état de base du worker."""
        return {
            "name": self.name,
            "is_alive": self.is_alive(),
            "tasks_in_queue": self.work_queue.qsize(),
        }

    @abstractmethod
    def setup_event_subscriptions(self) -> None:
        """
        Méthode abstraite. Les classes enfants DOIVENT l'implémenter
        pour s'abonner aux événements du ServiceBus.
        """
        pass

    def add_task(self, method_name: str, *args, **kwargs) -> None:
        """Méthode utilitaire pour ajouter une tâche à la file d'attente."""
        self.work_queue.put((method_name, args, kwargs))

    def run(self) -> None:
        """
        La boucle de travail principale. Gérée par la classe mère.
        Elle récupère les tâches et appelle la méthode correspondante.
        """
        logger.info(f"Thread '{self.name}' démarré.")
        while self._running:
            try:
                task = self.work_queue.get(timeout=1)
                if task is None:  # Le signal d'arrêt
                    break

                method_name, args, kwargs = task
                try:
                    method = getattr(self, method_name)
                    method(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Erreur d'exécution de la tâche '{method_name}' dans '{self.name}': {e}", exc_info=True)
                finally:
                    # Crucial pour que queue.join() fonctionne !
                    self.work_queue.task_done()
            except queue.Empty:
                continue
        logger.info(f"La boucle de travail de '{self.name}' est terminée.")

    def stop(self) -> None:
        """
        Arrête le thread PROPREMENT.
        """
        logger.info(f"Demande d'arrêt pour '{self.name}'. Attente de la fin des tâches en file...")
        self.work_queue.join()
        self._running = False
        self.work_queue.put(None)
        if self.is_alive():
            self.join()
        logger.info(f"Thread '{self.name}' a terminé toutes ses tâches et est arrêté.")


class _StatusServer(threading.Thread):
    """Un serveur HTTP simple pour afficher le statut des workers."""

    def __init__(self, services_to_monitor: List[QueueWorkerThread]):
        super().__init__(name="StatusServer", daemon=True)
        self.services_to_monitor = services_to_monitor
        self.html_content = "<html><body>Initialisation...</body></html>"
        self.html_lock = threading.Lock()
        self._running = True
        self.httpd = None

    def run(self):
        html_generator_thread = threading.Thread(target=self._generate_status_loop, daemon=True)
        html_generator_thread.start()
        self._start_http_server()

    def _generate_status_loop(self):
        while self._running:
            self._update_html_content()
            time.sleep(5)

    def _update_html_content(self):
        statuses = [service.get_status() for service in self.services_to_monitor]
        html = """
        <html><head><title>Statut des Services</title><meta http-equiv="refresh" content="5">
        <meta charset="UTF-8">
        <style>body{font-family:Arial,sans-serif;margin:2em;background-color:#f4f4f9;color:#333}h1{color:#333}table{border-collapse:collapse;width:100%;box-shadow:0 2px 5px rgba(0,0,0,.1)}th,td{border:1px solid #ddd;padding:12px;text-align:left}th{background-color:#0056b3;color:#fff}tr:nth-child(even){background-color:#f2f2f2}.status-alive{color:#28a745;font-weight:700}.status-dead{color:#dc3545;font-weight:700}</style>
        </head><body><h1>Statut des Threads</h1><p>Dernière mise à jour: """ + time.strftime("%Y-%m-%d %H:%M:%S") + """</p>
        <table><tr><th>Service (Thread)</th><th>État</th><th>Tâches en attente</th></tr>"""
        for status in statuses:
            status_class = "status-alive" if status.get("is_alive") else "status-dead"
            status_text = "Vivant" if status.get("is_alive") else "Arrêté"
            html += f"""<tr><td>{status.get("name", "N/A")}</td><td class="{status_class}">{status_text}</td><td>{status.get("tasks_in_queue", "N/A")}</td></tr>"""
        html += "</table></body></html>"
        with self.html_lock:
            self.html_content = html

    def _start_http_server(self):
        parent = self

        class StatusHandler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    with parent.html_lock:
                        self.wfile.write(bytes(parent.html_content, "utf8"))
                else:
                    self.send_error(404, "File Not Found")

            # noinspection PyShadowingBuiltins
            def log_message(self, format, *args):
                return

        try:
            # noinspection PyTypeChecker
            self.httpd = socketserver.TCPServer(("", STATUS_PORT), StatusHandler)
            logger.info(f"Serveur de statut écoute sur http://localhost:{STATUS_PORT}")
            while self._running: self.httpd.handle_request()
        except OSError as e:
            logger.error(f"Impossible de démarrer le serveur de statut sur le port {STATUS_PORT}. Port déjà utilisé ? Erreur: {e}")

    def stop(self):
        if not self._running: return
        self._running = False
        if self.httpd: self.httpd.server_close()


class OrchestratorBase(ABC):
    """
    Classe de base pour un orchestrateur qui gère le cycle de vie
    d'une application basée sur des services (threads).
    """

    def __init__(self, service_bus: ServiceBusBase, enable_status_page: bool = True):  # <-- MODIFICATION
        self.service_bus = service_bus
        self.services: List[QueueWorkerThread] = []
        self._processing_completed = threading.Event()

        self._status_server: Optional[_StatusServer] = None
        if enable_status_page:
            self.register_services()  # On doit enregistrer les services d'abord
            self._status_server = _StatusServer(self.services)

        if not self.services:  # S'assurer que register_services a été appelé
            self.register_services()

        self.setup_event_subscriptions()
        self.service_bus.subscribe("AllProcessingCompleted", self._on_all_processing_completed)

    @abstractmethod
    def register_services(self) -> None:
        pass

    @abstractmethod
    def setup_event_subscriptions(self) -> None:
        pass

    @abstractmethod
    def start_workflow(self) -> None:
        pass

    # noinspection PyTypeChecker
    def _start_services(self) -> None:
        logger.info(f"Démarrage de {len(self.services)} services et du ServiceBus...")
        all_services = self.services + [self.service_bus]
        if self._status_server:
            all_services.append(self._status_server)

        for service in all_services:
            if not service.is_alive():
                service.start()
        time.sleep(1)

    # noinspection PyTypeChecker
    def _stop_services(self) -> None:
        logger.info("Arrêt de tous les services...")
        all_services = self.services + [self.service_bus]
        if self._status_server:
            all_services.append(self._status_server)

        for service in reversed(all_services):
            if hasattr(service, 'stop') and callable(service.stop):
                service.stop()
        logger.info("Tous les services ont été arrêtés proprement.")

    def _on_all_processing_completed(self, _event: AllProcessingCompleted) -> None:
        logger.info("Signal de fin d'analyse reçu. Déclenchement de l'arrêt.")
        self._processing_completed.set()

    def run(self) -> None:
        """Point d'entrée principal qui exécute le cycle de vie complet."""
        self._start_services()
        self.start_workflow()
        self._processing_completed.wait()
        self._stop_services()
        logger.info("Exécution de l'orchestrateur terminée.")
