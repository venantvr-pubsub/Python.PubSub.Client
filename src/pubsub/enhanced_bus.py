"""
ServiceBus amélioré avec fonctionnalités avancées.
Hérite de ServiceBusBase et ajoute la gestion d'état, les statistiques,
la synchronisation d'événements et le retry policy.
"""
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import field, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from .base_bus import ServiceBusBase
from .client import PubSubClient
from .logger import logger
from .pubsub_message import PubSubMessage


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
    pubsub_message: Optional[PubSubMessage] = None

    def set_result(self, message: PubSubMessage) -> None:
        """Marque l'événement comme traité avec le message reçu."""
        if not self.future.done():
            self.pubsub_message = message
            self.future.set_result(message)

    def set_exception(self, exception: Exception) -> None:
        """Marque l'événement comme échoué."""
        if not self.future.done():
            self.future.set_exception(exception)

    def wait(self, timeout: Optional[float] = None) -> PubSubMessage:
        """Attend que l'événement soit traité."""
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

        old_events = [
            event_id for event_id, event in self._events.items()
            if event.created_at < cutoff_time and event.is_done()
        ]

        for event_id in old_events:
            del self._events[event_id]


class EnhancedServiceBus(ServiceBusBase):
    """
    ServiceBus amélioré avec gestion d'état, statistiques et synchronisation d'événements.
    Conçu pour les applications critiques nécessitant une fiabilité accrue.
    """

    def __init__(self, url: str, consumer_name: str, max_workers: Optional[int] = None, retry_policy: Optional[Dict] = None):
        super().__init__(url, consumer_name)
        self.daemon = False  # Ne pas être daemon pour garantir un arrêt propre

        # État et contrôle
        self._state = ServiceBusState.STOPPED
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._start_event = threading.Event()
        self._error_event = threading.Event()

        # Gestion des événements et synchronisation
        self._event_manager = EventWaitManager()
        self._pending_events: Dict[str, EventFuture] = {}
        self._pending_lock = threading.RLock()

        if max_workers is None:
            max_workers = int(os.getenv("PUBSUB_THREAD_POOL_SIZE", "10"))

        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ServiceBus-Worker")

        # Politique de retry
        self._retry_policy = retry_policy or {
            "max_attempts": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2
        }

        # Statistiques
        self._stats = {
            "messages_received": 0,
            "messages_processed": 0,
            "messages_failed": 0,
            "last_error": None,
            "start_time": None
        }
        self._stats_lock = threading.Lock()

    @property
    def state(self) -> ServiceBusState:
        """Retourne l'état actuel du ServiceBus."""
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: ServiceBusState) -> None:
        """Change l'état du ServiceBus de manière thread-safe."""
        with self._state_lock:
            old_state = self._state
            if old_state == new_state:
                return
            self._state = new_state
            logger.info(f"ServiceBus state changed: {old_state.value} -> {new_state.value}")

    def publish_and_wait(self, event_name: str, payload: Any, producer_name: Optional[str] = None,
                         timeout: float = 30.0) -> EventFuture:
        """
        Publie un événement et retourne un Future pour attendre sa confirmation.
        """
        if self.state != ServiceBusState.RUNNING:
            raise RuntimeError(f"Cannot publish in state {self.state.value}")

        event_future = self._event_manager.create_event_future(event_name, timeout)
        message = self._prepare_payload(payload, event_name)

        if message is None:
            exc = TypeError(f"Unsupported payload type: {type(payload)}")
            event_future.set_exception(exc)
            return event_future

        pubsub_msg = PubSubMessage.new(
            topic=event_name,
            message=message,
            producer=producer_name or self.consumer_name,
            message_id=event_future.event_id
        )

        with self._pending_lock:
            self._pending_events[event_future.event_id] = event_future

        try:
            self.client.publish(
                topic=pubsub_msg.topic,
                message=pubsub_msg.message,
                producer=pubsub_msg.producer,
                message_id=pubsub_msg.message_id
            )
        except Exception as e:
            with self._pending_lock:
                self._pending_events.pop(event_future.event_id, None)
            event_future.set_exception(e)

        return event_future

    # noinspection PyMethodMayBeStatic
    def wait_for_events(self, event_futures: List[EventFuture], timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Attend que plusieurs événements soient traités.
        """
        results = {}
        start_time = time.monotonic()

        for event_future in event_futures:
            remaining_timeout = timeout
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                remaining_timeout = max(0.0, timeout - elapsed)
                if remaining_timeout == 0:
                    results[event_future.event_id] = TimeoutError(f"Global timeout waiting for event {event_future.event_id}")
                    continue

            try:
                results[event_future.event_id] = event_future.wait(timeout=remaining_timeout)
            except Exception as e:
                results[event_future.event_id] = e

        return results

    def wait_for_start(self, timeout: float = 10.0) -> bool:
        """
        Attend que le ServiceBus soit complètement démarré.
        """
        return self._start_event.wait(timeout)

    def run(self):
        """Thread principal du ServiceBus avec gestion améliorée."""
        self._set_state(ServiceBusState.STARTING)
        try:
            logger.info(f"ServiceBus thread starting. Subscribing to topics: {list(self._topics)}")
            self.client = PubSubClient(url=self.url, consumer=self.consumer_name, topics=list(self._topics))

            with self._stats_lock:
                self._stats["start_time"] = time.time()

            self._register_enhanced_handlers()

            logger.info("All handlers registered. Starting to listen...")
            self._set_state(ServiceBusState.RUNNING)
            self._start_event.set()

            self.client.start()

        except Exception as e:
            logger.error(f"Pub/Sub client stopped with an error: {e}", exc_info=True)
            self._set_state(ServiceBusState.ERROR)
            self._error_event.set()
            with self._stats_lock:
                self._stats["last_error"] = str(e)
        finally:
            self._cleanup()
            logger.info("ServiceBus thread finished.")

    def _register_enhanced_handlers(self):
        """Enregistre les handlers avec gestion des stats et événements."""
        for event_name, handler_infos in self._handlers.items():
            def create_master_handler(evt_name, handlers_list):
                def _master_handler(message: Dict[str, Any]):
                    if isinstance(message, str) and message.startswith("Subscribed to"):
                        return

                    with self._stats_lock:
                        self._stats["messages_received"] += 1

                    message_id = message.get("message_id", str(uuid.uuid4()))
                    event_future = self._event_manager.get_event(message_id)

                    validated_payload = self._validate_payload(evt_name, message)
                    if validated_payload is None:
                        return

                    # Si c'est une réponse attendue, on résout le Future
                    if event_future:
                        self._event_manager.remove_event(message_id)
                        with self._pending_lock:
                            self._pending_events.pop(message_id, None)
                        # La réponse est le payload validé, pas le message brut
                        event_future.set_result(validated_payload)

                    for handler_info in handlers_list:
                        self._executor.submit(
                            self._execute_handler_with_retry,
                            handler_info,
                            validated_payload
                        )
                return _master_handler
            master_handler = create_master_handler(event_name, handler_infos)
            self.client.register_handler(event_name, master_handler)

    def _validate_payload(self, event_name: str, message: Dict[str, Any]) -> Optional[Any]:
        """Valide et déserialise le payload, retourne l'objet ou None."""
        event_class = self._event_schemas.get(event_name)
        if not event_class:
            return message

        try:
            if not isinstance(message, dict):
                logger.warning(f"Unexpected message type for {event_name}, expected dict, got {type(message)}")
                return None
            return event_class(**message)
        except Exception as e:
            logger.error(f"Validation error for '{event_name}': {e}. Message: {message}", exc_info=True)
            with self._stats_lock:
                self._stats["messages_failed"] += 1
            return None

    def _execute_handler_with_retry(self, handler_info, validated_payload: Any) -> None:
        """Exécute un handler avec retry et gestion d'erreurs."""
        attempts = 0
        delay = self._retry_policy["initial_delay"]
        max_attempts = self._retry_policy["max_attempts"]

        while attempts < max_attempts:
            try:
                result = handler_info.handler(validated_payload)

                # Si le handler retourne une valeur (pour les RPC), on la publie comme réponse
                if result is not None and hasattr(validated_payload, 'message_id'):
                    response_topic = f"response.{validated_payload.topic}"
                    self.publish(response_topic, result, self.consumer_name)

                with self._stats_lock:
                    self._stats["messages_processed"] += 1
                return
            except Exception as e:
                attempts += 1
                if attempts >= max_attempts:
                    logger.error(f"Handler '{handler_info.handler_name}' failed after {attempts} attempts for topic '{validated_payload.topic}': {e}", exc_info=True)
                    with self._stats_lock:
                        self._stats["messages_failed"] += 1
                else:
                    logger.warning(f"Handler retry {attempts}/{max_attempts} for topic '{validated_payload.topic}': {e}")
                    time.sleep(delay)
                    delay = min(delay * self._retry_policy["exponential_base"], self._retry_policy["max_delay"])

    def _cleanup(self) -> None:
        """Nettoie toutes les ressources."""
        logger.info("Cleaning up ServiceBus resources...")
        self._executor.shutdown(wait=True)
        with self._pending_lock:
            for event_future in self._pending_events.values():
                event_future.set_exception(RuntimeError("ServiceBus stopped"))
            self._pending_events.clear()

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Arrête le ServiceBus de manière propre.
        """
        if self.state in (ServiceBusState.STOPPED, ServiceBusState.STOPPING):
            return True

        logger.info(f"Stopping ServiceBus {self.consumer_name}")
        self._set_state(ServiceBusState.STOPPING)
        self._stop_event.set()

        if self.client:
            self.client.stop()

        if self.is_alive():
            self.join(timeout)

        success = not self.is_alive()
        if success:
            self._set_state(ServiceBusState.STOPPED)
        else:
            logger.warning(f"ServiceBus {self.consumer_name} did not stop cleanly")

        return success

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du ServiceBus."""
        with self._stats_lock:
            stats = self._stats.copy()
            if stats["start_time"]:
                stats["uptime"] = time.time() - stats["start_time"]
            return stats