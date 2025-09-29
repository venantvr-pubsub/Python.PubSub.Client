import http.server
import queue
import socketserver
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import Optional, List

from ..base_bus import ServiceBusBase
from ..config import get_env
from ..events import AllProcessingCompleted
from ..logger import logger

STATUS_PAGE_PORT = int(get_env("STATUS_PAGE_PORT", "8000"))  # 8000


class InternalLogger:
    """A thread-safe class for storing a worker's latest log messages."""

    def __init__(self, maxlen: int = 10):
        self._logs = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def log(self, message: str):
        """Adds a timestamped message to the log list."""
        with self._lock:
            timestamp = time.strftime("%H:%M:%S")
            self._logs.append(f"[{timestamp}] {message}")

    def get_logs(self) -> List[str]:
        """Returns a copy of the current log list."""
        with self._lock:
            return list(self._logs)


class QueueWorkerThread(threading.Thread, ABC):
    """
    Abstract base class for a worker thread that consumes tasks
    from a queue (Producer-Consumer pattern).
    """

    def __init__(self, service_bus: Optional[ServiceBusBase] = None, name: Optional[str] = None):
        """
        Initializes the worker thread.
        :param service_bus: The service bus for event-based communication.
        :param name: The thread name, useful for logs.
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
        """Records an internal log message for this thread via InternalLogger."""
        self.internal_logs.log(message)

    def get_status(self) -> dict:
        """Returns the worker's base status."""
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
        Abstract method. Child classes MUST implement it
        to subscribe to ServiceBus events.
        """
        pass

    def add_task(self, method_name: str, *args, **kwargs) -> None:
        """Utility method to add a task to the queue."""
        self.work_queue.put((method_name, args, kwargs))

    def run(self) -> None:
        """
        The main work loop. Managed by the parent class.
        It retrieves tasks and calls the corresponding method.
        """
        logger.info(f"Thread '{self.name}' started.")
        while self._running:
            try:
                task = self.work_queue.get(timeout=1)
                if task is None:  # Stop signal
                    break

                self._last_activity_time = time.time()

                method_name, args, kwargs = task
                try:
                    method = getattr(self, method_name)
                    method(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error executing task '{method_name}' in '{self.name}': {e}", exc_info=True)
                finally:
                    # Crucial for queue.join() to work!
                    self.work_queue.task_done()
            except queue.Empty:
                continue
        logger.info(f"Work loop for '{self.name}' has ended.")

    def stop(self, timeout: Optional[float] = 30) -> None:
        """
        Stops the thread GRACEFULLY with timeout protection.
        """
        logger.info(f"Stop requested for '{self.name}'. Waiting for queued tasks to complete...")
        # Add timeout protection to prevent infinite blocking
        start_time = time.time()
        while not self.work_queue.empty():
            if timeout and (time.time() - start_time) > timeout:
                logger.warning(f"Timeout reached while stopping '{self.name}'. Force stopping...")
                break
            time.sleep(0.1)
        self._running = False
        self.work_queue.put(None)
        if self.is_alive():
            self.join(timeout=5)  # Add timeout to prevent deadlock
        logger.info(f"Thread '{self.name}' has completed all tasks and is stopped.")


class _StatusServer(threading.Thread):
    """A simple HTTP server to display worker status."""

    def __init__(self, services_to_monitor: List[QueueWorkerThread]):
        super().__init__(name="StatusServer", daemon=True)
        self.services_to_monitor = services_to_monitor
        self.html_content = "<html><body>Initializing...</body></html>"
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

    # noinspection PyMethodMayBeStatic
    def _load_template(self) -> tuple[str, str]:
        """Load HTML template and CSS from files."""
        template_dir = Path(__file__).parent / "templates"
        html_path = template_dir / "status_page.html"
        css_path = template_dir / "status_page.css"

        # Default templates if files don't exist
        default_html = '''<!DOCTYPE html>
<html><head><title>Service Status</title>
<meta http-equiv="refresh" content="5"><meta charset="UTF-8">
<style>$$CSS_CONTENT$$</style></head>
<body><h1>Thread Status</h1>
<p>Last update: $$UPDATE_TIME$$</p>
<table><tr><th>Service (Thread)</th><th>Status</th>
<th>Queued Tasks</th><th>Last Activity</th><th>Recent Logs</th></tr>
$$TABLE_ROWS$$</table></body></html>'''

        default_css = '''body{font-family:monospace;margin:2em;background-color:#2b2b2b;color:#d4d4d4}
h1,p{color:#d4d4d4}table{border-collapse:collapse;width:100%;box-shadow:0 2px 5px rgba(0,0,0,.1)}
th,td{border:1px solid #555;padding:12px;text-align:left;vertical-align:top}
th{background-color:#0056b3;color:#fff}tr:nth-child(even){background-color:#3c3c3c}
.status-alive{color:#4CAF50;font-weight:700}.status-dead{color:#dc3545;font-weight:700}
.logs ul{margin:0;padding-left:20px}.logs li{margin-bottom:4px}
.logs{font-size:0.9em;white-space:pre-wrap;max-height:200px;overflow-y:auto;display:block}'''

        try:
            if html_path.exists():
                with open(html_path, 'r', encoding='utf-8') as f:
                    html_template = f.read()
            else:
                html_template = default_html

            if css_path.exists():
                with open(css_path, 'r', encoding='utf-8') as f:
                    css_content = f.read()
            else:
                css_content = default_css

            # Check if template needs CSS replacement
            if '$$CSS_CONTENT$$' in html_template:
                html_template = html_template.replace('$$CSS_CONTENT$$', css_content)

            return html_template, css_content
        except Exception as e:
            logger.warning(f"Failed to load template files: {e}. Using defaults.")
            # Replace CSS placeholder in default template
            return default_html.replace('$$CSS_CONTENT$$', default_css), default_css

    def _update_html_content(self):
        statuses = [service.get_status() for service in self.services_to_monitor]
        html_template, _ = self._load_template()

        table_rows = ""
        for status in statuses:
            status_class = "status-alive" if status.get("is_alive") else "status-dead"
            status_text = "Alive" if status.get("is_alive") else "Stopped"

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
                logs_html += "<li><i>No internal logs.</i></li>"
            else:
                for log_entry in recent_logs:
                    logs_html += f"<li>{log_entry}</li>"
            logs_html += "</ul></div>"

            table_rows += f"""<tr>
                    <td>{status.get("name", "N/A")}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{status.get("tasks_in_queue", "N/A")}</td>
                    <td>{last_activity_str}</td>
                    <td>{logs_html}</td>
                </tr>"""

        # Use replace instead of format to avoid issues with CSS braces
        # Support multiple placeholder formats for compatibility
        update_time_str = time.strftime("%Y-%m-%d %H:%M:%S")

        # Replace all placeholders
        html = html_template.replace('$$UPDATE_TIME$$', update_time_str)
        html = html.replace('$$TABLE_ROWS$$', table_rows)
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
            self.httpd = socketserver.TCPServer(("", STATUS_PAGE_PORT), StatusHandler)
            logger.info(f"Status server listening on http://localhost:{STATUS_PAGE_PORT}")
            # Use timeout to prevent blocking on shutdown
            self.httpd.timeout = 1
            while self._running:
                self.httpd.handle_request()
        except OSError as e:
            logger.error(f"Unable to start status server on port {STATUS_PAGE_PORT}. Port already in use? Error: {e}")

    def stop(self):
        if not self._running: return
        logger.info(f"Stopping status server on port {STATUS_PAGE_PORT}...")
        self._running = False
        if self.httpd:
            try:
                # Don't use shutdown() with handle_request() loop
                # Just close the server socket
                self.httpd.server_close()
                logger.info(f"Status server on port {STATUS_PAGE_PORT} stopped successfully")
            except Exception as e:
                logger.warning(f"Error stopping HTTP server: {e}")


class OrchestratorBase(ABC):
    """
    Base class for an orchestrator that manages the lifecycle
    of a service-based (threads) application.
    """

    def __init__(self, service_bus: ServiceBusBase, enable_status_page: bool = True):
        self.service_bus = service_bus
        self.services: List[QueueWorkerThread] = []
        self._processing_completed = threading.Event()

        self._status_server: Optional[_StatusServer] = None

        if enable_status_page:
            self.register_services()  # Must register services first
            self._status_server = _StatusServer(self.services)

        if not self.services:  # Ensure register_services was called
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
        logger.info(f"Starting {len(self.services)} services and ServiceBus...")
        all_services = self.services + [self.service_bus]
        if self._status_server:
            all_services.append(self._status_server)

        for service in all_services:
            if not service.is_alive():
                service.start()
        time.sleep(1)

    # noinspection PyTypeChecker
    def _stop_services(self) -> None:
        logger.info("Stopping all services...")
        all_services = self.services + [self.service_bus]
        if self._status_server:
            all_services.append(self._status_server)

        for service in reversed(all_services):
            if hasattr(service, 'stop') and callable(service.stop):
                service.stop()
        logger.info("All services have been stopped gracefully.")

    def _on_all_processing_completed(self, _event: AllProcessingCompleted) -> None:
        logger.info("Processing completion signal received. Triggering shutdown.")
        self._processing_completed.set()

    def run(self) -> None:
        """Main entry point that executes the complete lifecycle."""
        self._start_services()
        self.start_workflow()
        self._processing_completed.wait()
        self._stop_services()
        logger.info("Orchestrator execution completed.")
