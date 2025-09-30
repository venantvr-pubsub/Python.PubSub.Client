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
        self._server_ready = threading.Event()
        self._shutdown_complete = threading.Event()
        self.httpd = None
        self.html_generator_thread = None

    def run(self):
        self.html_generator_thread = threading.Thread(target=self._generate_status_loop, daemon=True)
        self.html_generator_thread.start()
        self._start_http_server()
        self._shutdown_complete.set()

    def _generate_status_loop(self):
        """Continuously updates HTML content with error recovery."""
        while self._running:
            try:
                self._update_html_content()
            except Exception as e:
                logger.error(f"Error updating status HTML: {e}", exc_info=True)
                # Set fallback content on error
                with self.html_lock:
                    self.html_content = f"<html><body><h1>Status Server Error</h1><p>Failed to generate status page: {e}</p></body></html>"
            time.sleep(5)

    # noinspection PyMethodMayBeStatic
    def _load_template(self) -> str:
        """Load HTML template and CSS from files."""
        template_dir = Path(__file__).parent / "templates"
        html_path = template_dir / "status_page.html"
        css_path = template_dir / "status_page.css"

        try:
            # Load HTML template
            with open(html_path, 'r', encoding='utf-8') as f:
                html_template = f.read()

            # Load CSS content
            with open(css_path, 'r', encoding='utf-8') as f:
                css_content = f.read()

            # Replace CSS placeholder in HTML template
            if '$$CSS_CONTENT$$' in html_template:
                html_template = html_template.replace('$$CSS_CONTENT$$', css_content)

            return html_template
        except Exception as e:
            logger.error(f"Failed to load template files: {e}")
            raise RuntimeError(f"Template files not found at {template_dir}. "
                               "Ensure status_page.html and status_page.css exist.")

    def _update_html_content(self):
        statuses = [service.get_status() for service in self.services_to_monitor]
        html_template = self._load_template()

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
                try:
                    if self.path == '/':
                        self.send_response(200)
                        self.send_header("Content-type", "text/html; charset=utf-8")
                        self.end_headers()
                        with parent.html_lock:
                            self.wfile.write(bytes(parent.html_content, "utf8"))
                    else:
                        self.send_error(404, "File Not Found")
                except Exception as e:
                    logger.error(f"Error handling HTTP request: {e}", exc_info=False)

            # noinspection PyShadowingBuiltins
            def log_message(self, format, *args):
                return

        try:
            # Allow socket reuse to prevent "Address already in use" errors
            socketserver.TCPServer.allow_reuse_address = True
            # noinspection PyTypeChecker
            self.httpd = socketserver.TCPServer(("", STATUS_PAGE_PORT), StatusHandler)
            self.httpd.timeout = 1
            logger.info(f"Status server listening on http://localhost:{STATUS_PAGE_PORT}")
            self._server_ready.set()

            # Serve requests until stopped
            while self._running:
                try:
                    self.httpd.handle_request()
                except Exception as e:
                    if self._running:  # Only log if we're still supposed to be running
                        logger.error(f"Error in HTTP server loop: {e}", exc_info=True)

        except OSError as e:
            logger.error(f"Unable to start status server on port {STATUS_PAGE_PORT}. Port already in use? Error: {e}")
            self._server_ready.set()  # Signal ready even on failure so startup doesn't block
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
        """Stops the status server gracefully with proper cleanup."""
        if not self._running:
            return

        logger.info(f"Stopping status server on port {STATUS_PAGE_PORT}...")
        self._running = False

        # Wait for the server thread to finish its current operation
        if not self._shutdown_complete.wait(timeout=timeout):
            logger.warning(f"Status server did not shut down cleanly within {timeout}s")

        logger.info(f"Status server on port {STATUS_PAGE_PORT} stopped successfully")


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

        # Wait for status server to be ready if it exists
        if self._status_server:
            # noinspection PyProtectedMember
            if not self._status_server._server_ready.wait(timeout=5):
                logger.warning("Status server did not become ready within 5 seconds")

        # Give other services a moment to initialize
        time.sleep(0.5)

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
