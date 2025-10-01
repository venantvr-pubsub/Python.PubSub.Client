import hashlib
import threading
from collections import deque
from typing import Any, Callable, Optional


class IdempotencyTracker:
    """
    Thread-safe tracker to ensure idempotent event processing.
    Uses a FIFO deque with limited size to track recently processed events.
    """

    def __init__(self, maxlen: int = 1000):
        """
        Initialize the tracker.

        Args:
            maxlen: Maximum number of event hashes to keep in memory
        """
        self._processed_hashes = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    # noinspection PyMethodMayBeStatic
    def _compute_hash(self, event_data: Any) -> str:
        """
        Compute a deterministic hash for the event data.

        Args:
            event_data: The event data to hash (must be hashable or convertible to string)

        Returns:
            A hexadecimal hash string
        """
        # Convert to string representation for hashing
        event_str = str(sorted(event_data.items()) if isinstance(event_data, dict) else event_data)
        return hashlib.sha256(event_str.encode('utf-8')).hexdigest()

    def is_duplicate(self, event_data: Any) -> bool:
        """
        Check if this event has already been processed.

        Args:
            event_data: The event data to check

        Returns:
            True if this is a duplicate event, False otherwise
        """
        event_hash = self._compute_hash(event_data)

        with self._lock:
            return event_hash in self._processed_hashes

    def mark_processed(self, event_data: Any) -> None:
        """
        Mark an event as processed.

        Args:
            event_data: The event data to mark
        """
        event_hash = self._compute_hash(event_data)

        with self._lock:
            self._processed_hashes.append(event_hash)

    def process_once(self, event_data: Any, handler: Callable[[], Any]) -> Optional[Any]:
        """
        Execute a handler only if the event hasn't been processed yet.

        Args:
            event_data: The event data to check
            handler: The function to call if this is not a duplicate

        Returns:
            The result of the handler, or None if this was a duplicate
        """
        if self.is_duplicate(event_data):
            return None

        result = handler()
        self.mark_processed(event_data)
        return result

    def clear(self) -> None:
        """Clear all tracked events."""
        with self._lock:
            self._processed_hashes.clear()

    def size(self) -> int:
        """Get the current number of tracked events."""
        with self._lock:
            return len(self._processed_hashes)
