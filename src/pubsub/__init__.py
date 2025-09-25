"""A simple and robust WebSocket Pub/Sub client for Python.

This package provides a client for connecting to Socket.IO-based
Pub/Sub servers, with automatic reconnection, message queuing,
and topic-based subscription support.
"""

from .events import AllProcessingCompleted
from .pubsub_client import PubSubClient
from .pubsub_message import PubSubMessage
from .service_bus import ServiceBus
from .threading_base import QueueWorkerThread, OrchestratorBase

__version__ = "0.1.0"
__all__ = ["PubSubClient", "PubSubMessage", "AllProcessingCompleted", "ServiceBus", "QueueWorkerThread", "OrchestratorBase"]
