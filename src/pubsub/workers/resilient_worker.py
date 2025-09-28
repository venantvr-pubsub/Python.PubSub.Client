import queue
import time
from abc import ABC
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Optional

from .threading_base import QueueWorkerThread
from ..base_bus import ServiceBusBase
from ..events import WorkerFailed
from ..logger import logger


class ResilientWorkerThread(QueueWorkerThread, ABC):
    """
    Une version améliorée du QueueWorkerThread qui intègre des stratégies
    de résilience comme les timeouts de tâches et les seuils d'échecs.
    """

    def __init__(
            self,
            service_bus: Optional[ServiceBusBase] = None,
            name: Optional[str] = None,
            task_timeout: int = 60,  # Timeout de 60 secondes par tâche
            max_consecutive_failures: int = 5,  # 5 échecs de suite max
    ):
        super().__init__(service_bus, name)
        self._task_timeout = task_timeout
        self._max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._last_activity_time = time.time()

    def get_status(self) -> dict:
        """Retourne l'état de santé du worker."""
        return {
            "name": self.name,
            "is_alive": self.is_alive(),
            "tasks_in_queue": self.work_queue.qsize(),
            "consecutive_failures": self._consecutive_failures,
            "last_activity_time": self._last_activity_time,
        }

    def run(self) -> None:
        """
        Boucle de travail principale qui exécute les tâches avec un timeout
        et un compteur d'échecs.
        """
        logger.info(f"Thread résilient '{self.name}' démarré (timeout={self._task_timeout}s, max_failures={self._max_consecutive_failures}).")

        with ThreadPoolExecutor(max_workers=1) as executor:
            while self._running:
                try:
                    task = self.work_queue.get(timeout=1)
                    if task is None:
                        break

                    method_name, args, kwargs = task

                    try:
                        method = getattr(self, method_name)
                        future = executor.submit(method, *args, **kwargs)
                        future.result(timeout=self._task_timeout)

                        self._consecutive_failures = 0
                        self._last_activity_time = time.time()

                    except TimeoutError:
                        self._consecutive_failures += 1
                        logger.error(f"TÂCHE TIMEOUT dans '{self.name}': La tâche '{method_name}' a dépassé les {self._task_timeout}s.")
                    except Exception as e:
                        self._consecutive_failures += 1
                        logger.error(f"ERREUR TÂCHE dans '{self.name}': La tâche '{method_name}' a échoué: {e}", exc_info=True)
                    finally:
                        self.work_queue.task_done()

                    if self._consecutive_failures >= self._max_consecutive_failures:
                        self._handle_unhealthy_state()
                        break

                except queue.Empty:
                    continue

        logger.info(f"La boucle de travail de '{self.name}' est terminée.")

    def _handle_unhealthy_state(self):
        """Gère l'état où le worker est considéré comme non fiable."""
        error_message = f"Le worker '{self.name}' est devenu instable après {self._consecutive_failures} échecs consécutifs."
        logger.critical(error_message)

        if self.service_bus:
            event = WorkerFailed(worker_name=self.name, reason=error_message)
            self.service_bus.publish("WorkerFailed", event, self.__class__.__name__)

        self._running = False