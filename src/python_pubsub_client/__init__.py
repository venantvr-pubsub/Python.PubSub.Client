"""A simple and robust WebSocket Pub/Sub client for Python.

This package provides a client for connecting to Socket.IO-based
Pub/Sub servers, with automatic reconnection, message queuing,
and topic-based subscription support.
"""

from .base_bus import ServiceBusBase, DevToolsConfig, EventRecorderConfig, MockExchangeConfig

# Core components
from .client import PubSubClient

# Event models
from .events import AllProcessingCompleted, WorkerFailed
from .idempotency_tracker import IdempotencyTracker
from .pubsub_message import PubSubMessage

# Worker utilities
from .workers import (
    OrchestratorBase,
    QueueWorkerThread,
)

# Alias for backward compatibility and simple use cases
ServiceBus = ServiceBusBase

__version__ = "0.2.0"
__all__ = [
    # Core
    "ServiceBus",
    "ServiceBusBase",
    "PubSubClient",
    "PubSubMessage",
    # Configuration
    "DevToolsConfig",
    "EventRecorderConfig",
    "MockExchangeConfig",
    # Events
    "AllProcessingCompleted",
    "WorkerFailed",
    # Workers
    "OrchestratorBase",
    "QueueWorkerThread",
    "IdempotencyTracker",
]
