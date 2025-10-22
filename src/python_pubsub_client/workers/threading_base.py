import queue
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import List, Optional

from .status_server import StatusServer
from ..base_bus import ServiceBusBase
from ..events import AllProcessingCompleted
from ..logger import logger


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
                    logger.error(
                        f"Error executing task '{method_name}' in '{self.name}': {e}", exc_info=True
                    )
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


class OrchestratorBase(ABC):
    """
    Base class for an orchestrator that manages the lifecycle
    of a service-based (threads) application.
    """

    def __init__(self, service_bus: ServiceBusBase, enable_status_page: bool = True):
        self.service_bus = service_bus
        self.services: List[QueueWorkerThread] = []
        self._processing_completed = threading.Event()

        # Le type hint et l'instanciation utilisent maintenant la classe importée
        self._status_server: Optional[StatusServer] = None

        if enable_status_page:
            self.register_services()  # Must register services first
            self._status_server = StatusServer(self.services)

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
            if hasattr(service, "stop") and callable(service.stop):
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
