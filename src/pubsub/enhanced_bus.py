"""
ServiceBus amélioré avec fonctionnalités avancées.
Hérite de ServiceBusBase et ajoute la gestion d'état, les statistiques,
la synchronisation d'événements et le retry policy.
"""
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import field, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from .base_bus import ServiceBusBase
from .client import PubSubClient
from .logger import logger


class ServiceBusState(Enum):
    """États possibles du ServiceBus."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class EventFuture:
    """Future pour attendre la réception/traitement d'un événement."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    future: Future = field(default_factory=Future)
    event_name: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    timeout: Optional[float] = None
    pubsub_message: Optional[Any] = None  # Can hold any result type

    def set_result(self, result: Any) -> None:
        """Marque l'événement comme traité avec le résultat du handler."""
        if not self.future.done():
            self.pubsub_message = result
            self.future.set_result(result)

    def set_exception(self, exception: Exception) -> None:
        """Marque l'événement comme échoué."""
        if not self.future.done():
            self.future.set_exception(exception)

    def wait(self, timeout: Optional[float] = None) -> Any:
        """Attend que l'événement soit traité et retourne le résultat."""
        effective_timeout = timeout or self.timeout
        return self.future.result(timeout=effective_timeout)

    def is_done(self) -> bool:
        return self.future.done()


class EventWaitManager:
    """
    Gestionnaire pour synchroniser l'attente d'événements multiples.
    """
    def __init__(self):
        self._events: Dict[str, EventFuture] = {}
        self._lock = threading.RLock()
        self._cleanup_interval = timedelta(minutes=5)
        self._last_cleanup = datetime.now()

    def create_event_future(self, event_name: str, timeout: Optional[float] = None) -> EventFuture:
        """Crée un future pour attendre un événement."""
        with self._lock:
            event_future = EventFuture(
                event_id=str(uuid.uuid4()),
                event_name=event_name,
                timeout=timeout
            )
            self._events[event_future.event_id] = event_future
            self._cleanup_old_events()
            return event_future

    def get_event(self, event_id: str) -> Optional[EventFuture]:
        """Récupère un EventFuture par son ID."""
        with self._lock:
            return self._events.get(event_id)

    def remove_event(self, event_id: str) -> Optional[EventFuture]:
        """Supprime et retourne un EventFuture."""
        with self._lock:
            return self._events.pop(event_id, None)

    def _cleanup_old_events(self) -> None:
        """Nettoie les événements anciens pour éviter les fuites mémoire."""
        now = datetime.now()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        cutoff_time = now - timedelta(hours=1)
        old_events_ids = [
            event_id for event_id, event in self._events.items()
            if event.created_at < cutoff_time and event.is_done()
        ]
        for event_id in old_events_ids:
            with self._lock:
                self._events.pop(event_id, None)


class EnhancedServiceBus(ServiceBusBase):
    """
    ServiceBus amélioré avec gestion d'état, statistiques et synchronisation d'événements.
    """
    def __init__(self, url: str, consumer_name: str, max_workers: Optional[int] = None, retry_policy: Optional[Dict] = None):
        super().__init__(url, consumer_name)
        self.daemon = False

        self._state = ServiceBusState.STOPPED
        self._state_lock = threading.RLock()
        self._start_event = threading.Event()

        self._event_manager = EventWaitManager()
        self._pending_events: Dict[str, EventFuture] = {}
        self._pending_lock = threading.RLock()

        if max_workers is None:
            max_workers = int(os.getenv("PUBSUB_THREAD_POOL_SIZE", "10"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ServiceBus-Worker")

        self._retry_policy = retry_policy or {
            "max_attempts": 3, "initial_delay": 1.0, "max_delay": 30.0, "exponential_base": 2
        }
        self._stats = {
            "messages_received": 0, "messages_processed": 0, "messages_failed": 0,
            "last_error": None, "start_time": None
        }
        self._stats_lock = threading.Lock()

    @property
    def state(self) -> ServiceBusState:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: ServiceBusState) -> None:
        with self._state_lock:
            old_state = self._state
            if old_state != new_state:
                self._state = new_state
                logger.info(f"ServiceBus state changed: {old_state.value} -> {new_state.value}")

    def publish_and_wait(self, event_name: str, payload: Any, producer_name: Optional[str] = None,
                         timeout: float = 30.0) -> EventFuture:
        if self.state != ServiceBusState.RUNNING:
            raise RuntimeError(f"Cannot publish in state {self.state.value}")

        event_future = self._event_manager.create_event_future(event_name, timeout)
        message = self._prepare_payload(payload, event_name)

        if message is None:
            exc = TypeError(f"Unsupported payload type: {type(payload)}")
            event_future.set_exception(exc)
            return event_future

        with self._pending_lock:
            self._pending_events[event_future.event_id] = event_future

        try:
            self.client.publish(
                topic=event_name, message=message, producer=producer_name or self.consumer_name,
                message_id=event_future.event_id
            )
        except Exception as e:
            with self._pending_lock:
                self._pending_events.pop(event_future.event_id, None)
            event_future.set_exception(e)
        return event_future

    def wait_for_events(self, event_futures: List[EventFuture], timeout: Optional[float] = None) -> Dict[str, Any]:
        results = {}
        start_time = time.monotonic()
        for future in event_futures:
            remaining = timeout
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                remaining = max(0.0, timeout - elapsed)
            try:
                results[future.event_id] = future.wait(timeout=remaining)
            except Exception as e:
                results[future.event_id] = e
        return results

    def wait_for_start(self, timeout: float = 10.0) -> bool:
        return self._start_event.wait(timeout)

    def run(self):
        self._set_state(ServiceBusState.STARTING)
        try:
            self.client = PubSubClient(url=self.url, consumer=self.consumer_name, topics=list(self._topics))
            with self._stats_lock:
                self._stats["start_time"] = time.time()
            self._register_enhanced_handlers()
            self._set_state(ServiceBusState.RUNNING)
            self._start_event.set()
            logger.info("EnhancedServiceBus is running.")
            self.client.start()
        except Exception as e:
            logger.error(f"EnhancedServiceBus stopped with an error: {e}", exc_info=True)
            self._set_state(ServiceBusState.ERROR)
            with self._stats_lock:
                self._stats["last_error"] = str(e)
        finally:
            self._cleanup()
            logger.info("EnhancedServiceBus has shut down.")

    def _register_enhanced_handlers(self):
        for event_name, handler_infos in self._handlers.items():
            master_handler = self._create_master_handler(event_name, handler_infos)
            self.client.register_handler(event_name, master_handler)

    def _create_master_handler(self, evt_name: str, handlers_list: list):
        def _master_handler(message: Dict[str, Any]):
            if not isinstance(message, dict): return
            with self._stats_lock:
                self._stats["messages_received"] += 1

            message_id = message.get("message_id")
            event_future = self._event_manager.get_event(message_id) if message_id else None

            validated_payload = self._validate_payload(evt_name, message)
            if validated_payload is None:
                if event_future:
                    exc = TypeError(f"Validation failed for event '{evt_name}'")
                    event_future.set_exception(exc)
                    self._event_manager.remove_event(message_id)
                return

            if event_future:
                self._handle_rpc_call(event_future, validated_payload, handlers_list)
            else:
                for handler_info in handlers_list:
                    self._executor.submit(self._execute_handler_with_retry, handler_info, validated_payload)

        return _master_handler

    def _handle_rpc_call(self, future: EventFuture, payload: Any, handlers: list):
        if not handlers:
            future.set_result(payload)  # No handler, return the message itself
            self._event_manager.remove_event(future.event_id)
            return

        handler_info = handlers[0]  # For RPC, we only consider the first registered handler
        try:
            response = handler_info.handler(payload)
            future.set_result(response)
        except Exception as e:
            future.set_exception(e)
        finally:
            self._event_manager.remove_event(future.event_id)
            with self._pending_lock:
                self._pending_events.pop(future.event_id, None)

    def _validate_payload(self, event_name: str, message: Dict[str, Any]) -> Optional[Any]:
        event_class = self._event_schemas.get(event_name)
        if not event_class: return message
        try:
            return event_class(**message)
        except Exception as e:
            logger.error(f"Validation error for '{event_name}': {e}. Message: {message}", exc_info=True)
            with self._stats_lock:
                self._stats["messages_failed"] += 1
            return None

    def _execute_handler_with_retry(self, handler_info, validated_payload: Any):
        """Executes a standard (non-RPC) handler with retry."""
        attempts = 0
        policy = self._retry_policy
        delay = policy["initial_delay"]

        while attempts < policy["max_attempts"]:
            try:
                handler_info.handler(validated_payload)
                with self._stats_lock:
                    self._stats["messages_processed"] += 1
                return
            except Exception as e:
                attempts += 1
                if attempts >= policy["max_attempts"]:
                    logger.error(f"Handler '{handler_info.handler_name}' failed after {attempts} attempts: {e}", exc_info=True)
                    with self._stats_lock:
                        self._stats["messages_failed"] += 1
                else:
                    logger.warning(f"Handler retry {attempts}/{policy['max_attempts']} for event: {e}")
                    time.sleep(delay)
                    delay = min(delay * policy["exponential_base"], policy["max_delay"])

    def _cleanup(self):
        logger.info("Cleaning up EnhancedServiceBus resources...")
        self._executor.shutdown(wait=True)
        with self._pending_lock:
            for future in self._pending_events.values():
                future.set_exception(RuntimeError("ServiceBus stopped"))
            self._pending_events.clear()

    def stop(self, timeout: float = 10.0) -> bool:
        if self.state in (ServiceBusState.STOPPED, ServiceBusState.STOPPING):
            return True
        self._set_state(ServiceBusState.STOPPING)
        if self.client: self.client.stop()
        if self.is_alive(): self.join(timeout)
        success = not self.is_alive()
        self._set_state(ServiceBusState.STOPPED)
        if not success:
            logger.warning(f"EnhancedServiceBus {self.consumer_name} did not stop cleanly.")
        return success

    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            stats = self._stats.copy()
            if stats["start_time"]:
                stats["uptime"] = time.time() - stats["start_time"]
            return stats