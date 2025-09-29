import http.server
import queue
import socketserver
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional, List

from ..base_bus import ServiceBusBase
from ..config import get_env
from ..events import AllProcessingCompleted
from ..logger import logger

DIAGNOSTIC_STATUS_PORT = int(get_env("DIAGNOSTIC_STATUS_PORT", "8000"))  # 8000


class InternalLogger:
    """Une classe thread-safe pour stocker les derniers messages de log d'un worker."""

    def __init__(self, maxlen: int = 10):
        self._logs = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def log(self, message: str):
        """Ajoute un message horodaté à la liste des logs."""
        with self._lock:
            timestamp = time.strftime("%H:%M:%S")
            self._logs.append(f"[{timestamp}] {message}")

    def get_logs(self) -> List[str]:
        """Retourne une copie de la liste des logs actuels."""
        with self._lock:
            return list(self._logs)


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

        self.internal_logs = InternalLogger(maxlen=10)
        self._last_activity_time = time.time()

        if self.service_bus:
            self.setup_event_subscriptions()

    def log_message(self, message: str):
        """Enregistre un message de log interne pour ce thread via l'InternalLogger."""
        self.internal_logs.log(message)

    def get_status(self) -> dict:
        """Retourne l'état de base du worker."""
        return {
            "name": self.name,
            "is_alive": self.is_alive(),
            "tasks_in_queue": self.work_queue.qsize(),
            "recent_logs": self.internal_logs.get_logs(),
            "last_activity_time": self._last_activity_time,
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

                self._last_activity_time = time.time()

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
        <html><head><title>Statut des Services</title><meta http-equiv="refresh" content="5"><meta charset="UTF-8">
        <style>
            body{font-family:monospace;margin:2em;background-color:#2b2b2b;color:#d4d4d4} h1,p{color:#d4d4d4}
            table{border-collapse:collapse;width:100%;box-shadow:0 2px 5px rgba(0,0,0,.1)}
            th,td{border:1px solid #555;padding:12px;text-align:left;vertical-align:top}
            th{background-color:#0056b3;color:#fff} tr:nth-child(even){background-color:#3c3c3c}
            .status-alive{color:#4CAF50;font-weight:700} .status-dead{color:#dc3545;font-weight:700}
            .logs ul{margin:0;padding-left:20px;}
            .logs li{margin-bottom:4px;}
            .logs{font-size:0.9em;white-space:pre-wrap;max-height:200px;overflow-y:auto;display:block;}
        </style>
        </head><body><h1>Statut des Threads</h1><p>Dernière mise à jour: """ + time.strftime("%Y-%m-%d %H:%M:%S") + """</p>
        <table>
            <tr>
                <th>Service (Thread)</th>
                <th>État</th>
                <th>Tâches en attente</th>
                <th>Dernière Activité</th>
                <th>Logs Récents</th>
            </tr>"""
        for status in statuses:
            status_class = "status-alive" if status.get("is_alive") else "status-dead"
            status_text = "Vivant" if status.get("is_alive") else "Arrêté"

            last_activity_ts = status.get("last_activity_time")
            if last_activity_ts:
                now = time.time()
                delta_seconds = int(now - last_activity_ts)
                last_activity_str = f"{time.strftime('%H:%M:%S', time.localtime(last_activity_ts))} ({delta_seconds}s ago)"
            else:
                last_activity_str = "N/A"

            logs_html = "<div class='logs'><ul>"
            recent_logs = status.get("recent_logs", [])
            if not recent_logs:
                logs_html += "<li><i>Aucun log interne.</i></li>"
            else:
                for log_entry in recent_logs:
                    logs_html += f"<li>{log_entry}</li>"
            logs_html += "</ul></div>"

            html += f"""<tr>
                    <td>{status.get("name", "N/A")}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{status.get("tasks_in_queue", "N/A")}</td>
                    <td>{last_activity_str}</td>
                    <td>{logs_html}</td>
                </tr>"""
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
            self.httpd = socketserver.TCPServer(("", DIAGNOSTIC_STATUS_PORT), StatusHandler)
            logger.info(f"Serveur de statut écoute sur http://localhost:{DIAGNOSTIC_STATUS_PORT}")
            while self._running: self.httpd.handle_request()
        except OSError as e:
            logger.error(f"Impossible de démarrer le serveur de statut sur le port {DIAGNOSTIC_STATUS_PORT}. Port déjà utilisé ? Erreur: {e}")

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
