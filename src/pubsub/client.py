import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests
import socketio

from .logger import logger
from .pubsub_message import PubSubMessage

RED_ON_YELLOW = "\033[31;43m"
BLACK_ON_YELLOW = "\033[30;43m"
RED = "\033[31m"
RESET = "\033[0m"


@dataclass
class HandlerInfo:
    handler: Callable[[Any], None]
    handler_name: str = field(init=False)

    def __post_init__(self):
        self.handler_name = self._get_handler_class_name()

    def _get_handler_class_name(self) -> str:
        """
        Méthode d'instance privée qui analyse self.handler.
        """
        # Note: on utilise self.handler directement ici
        handler_func = self.handler

        if hasattr(handler_func, '__self__'):
            return handler_func.__self__.__class__.__name__

        if hasattr(handler_func, '__qualname__'):
            parts = handler_func.__qualname__.split('.')
            if len(parts) > 1:
                return parts[-2]

        return handler_func.__name__


class PubSubClient:
    def __init__(self, url: str, consumer: str, topics: List[str]):
        """
        Initialize the PubSub client.

        :param url: URL of the Socket.IO server, e.g., http://localhost:5000
        :param consumer: Consumer name (e.g., 'alice')
        :param topics: List of topics to subscribe to
        """
        reconnection_str = os.getenv("PUBSUB_RECONNECTION_ENABLED", "true").lower()
        reconnection = reconnection_str in ("true", "1", "yes", "on")
        reconnection_attempts = int(os.getenv("PUBSUB_RECONNECTION_ATTEMPTS", "0"))
        reconnection_delay = int(os.getenv("PUBSUB_RECONNECTION_DELAY_MS", "2000"))
        reconnection_delay_max = int(os.getenv("PUBSUB_RECONNECTION_DELAY_MAX_MS", "10000"))

        self.url = url.rstrip("/")
        self.consumer = consumer
        self.topics = topics
        self.handlers: Dict[str, HandlerInfo] = {}  # topic → HandlerInfo
        self.message_queue: queue.Queue[Any] = (
            queue.Queue()
        )  # Queue for processing messages sequentially
        self.running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Create Socket.IO client with explicit reconnection settings
        self.socket_client = socketio.Client(
            reconnection=reconnection,
            reconnection_attempts=reconnection_attempts,  # Infinite reconnection attempts
            reconnection_delay=reconnection_delay,  # Delay between reconnection attempts (ms)
            reconnection_delay_max=reconnection_delay_max,  # Max delay for reconnection
        )

        # Register generic events
        self.socket_client.on("connect", self.on_connect)
        self.socket_client.on("message", self.on_message)
        self.socket_client.on("disconnect", self.on_disconnect)
        self.socket_client.on("new_message", self.on_new_message)

    def register_handler(self, topic: str, handler_func: Callable[[Any], None]) -> None:
        """
        Register a custom handler for a given topic.

        :param topic: Topic to handle
        :param handler_func: Function to call when a message is received
        """
        self.handlers[topic] = HandlerInfo(handler=handler_func)

    def on_connect(self) -> None:
        """Handle connection to the server."""
        logger.info(f"[{self.consumer}] Connected to server {self.url}")
        self.socket_client.emit("subscribe", {"consumer": self.consumer, "topics": self.topics})
        self.running = True

        # Start worker thread only if it's not already running
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self.process_queue, daemon=True)
            self._worker_thread.start()

    def on_message(self, data: Dict[str, Any]) -> None:
        """
        Handle incoming messages by adding them to the queue.

        :param data: Message data containing topic, message_id, message, and producer
        """
        logger.info(f"[{self.consumer}] Queuing message: {data}")
        self.message_queue.put(data)

    def process_queue(self) -> None:
        """Process messages from the queue one by one."""
        while not self._stop_event.is_set():
            try:
                # Check if we should stop even if queue is not empty
                if not self.running and self.message_queue.empty():
                    break

                data = self.message_queue.get(timeout=1.0)
                # Ici on a le message sous forme de dictionnary...
                topic = data["topic"]
                message_id = data.get("message_id")
                message = data["message"]
                producer = data.get("producer")

                # Créer un objet PubSubMessage
                pubsub_message = PubSubMessage(
                    topic=topic,
                    message_id=message_id,
                    message=message,
                    producer=producer
                )

                logger.info(
                    f"[{self.consumer}] Processing message from topic [{BLACK_ON_YELLOW}{topic}{RESET}]: "
                    f"{message} (from {producer}, ID={message_id})"
                )

                if topic in self.handlers:
                    try:
                        handler_info = self.handlers[topic]
                        handler_info.handler(message)

                        self.notify_consumption(pubsub_message, handler_info.handler_name)

                    except Exception as e:
                        logger.error(f"[{self.consumer}] Error in handler for topic {BLACK_ON_YELLOW}{topic}{RESET}: {e}")
                else:
                    logger.warning(f"[{self.consumer}] No handler for topic {BLACK_ON_YELLOW}{topic}{RESET}.")

                # Notify consumption
                # self.sio.emit(
                #     "consumed",
                #     {
                #         "consumer": self.consumer,
                #         "topic": topic,
                #         "message_id": message_id,
                #         "message": message,
                #     },
                # )

                self.message_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[{self.consumer}] Error processing message: {e}")

    def notify_consumption(self, pubsub_message: PubSubMessage, handler_name: str):
        # Notify consumption
        self.socket_client.emit(
            "consumed",
            {
                "consumer": handler_name,
                "topic": pubsub_message.topic,
                "message_id": pubsub_message.message_id,
                "message": pubsub_message.message,
            },
        )

    def on_disconnect(self) -> None:
        """Handle disconnection from the server."""
        logger.info(
            f"[{self.consumer}] Disconnected from server. "
            "Reconnection will be attempted automatically."
        )
        self.running = False  # Pause queue processing until reconnected

    def on_new_message(self, data: Dict[str, Any]) -> None:
        """Handle new message events."""
        logger.info(f"[{self.consumer}] New message: {data}")

    def publish(self, topic: str, message: Any, producer: str, message_id: str) -> None:
        """
        Publish a message via HTTP POST to the pubsub backend.

        :param topic: Topic to publish to
        :param message: Message content
        :param producer: Name of the producer
        :param message_id: Unique message ID
        """
        msg = PubSubMessage.new(topic, message, producer, message_id)
        url = f"{self.url}/publish"
        logger.info(f"[{self.consumer}] Publishing to {BLACK_ON_YELLOW}{topic}{RESET}: {msg.to_dict()}")
        try:
            resp = requests.post(url, json=msg.to_dict(), timeout=10)
            resp.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)
            logger.info(f"[{self.consumer}] Publish response: {resp.json()}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[{self.consumer}] Connection error during publish: {e}")
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"[{self.consumer}] HTTP error during publish: "
                f"{e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            logger.error(f"[{self.consumer}] An unexpected error occurred during publish: {e}")

    def start(self) -> None:
        """Start the client and connect to the server."""
        logger.info(f"Starting client {self.consumer} with topics {self.topics}")
        try:
            self.socket_client.connect(self.url)
            self.socket_client.wait()
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the client and clean up resources."""
        logger.info(f"Stopping client {self.consumer}")
        self.running = False
        self._stop_event.set()

        # Disconnect from server
        if self.socket_client.connected:
            self.socket_client.disconnect()

        # Wait for worker thread to finish
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
