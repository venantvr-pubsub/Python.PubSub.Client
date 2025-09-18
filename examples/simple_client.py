#!/usr/bin/env python
# -*- coding: utf-8 -*-
# examples/simple_client.py

"""Example usage of the PubSub Client with environment configuration.

This script demonstrates how to use the PubSub client to subscribe to topics
and handle messages, with configuration loaded from environment variables.

Prerequisites:
    1. Install the package in development mode: pip install -e .
    2. Copy .env.example to .env and adjust settings
    3. Make sure the PubSub server is running
    4. Run this example: python examples/simple_client.py
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

# Import from the installed package
from pubsub import PubSubClient

# Try to load environment variables from .env file
try:
    # noinspection PyUnresolvedReferences
    from dotenv import load_dotenv

    # Look for .env file in project root (parent of examples/)
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded configuration from {env_path}")
    else:
        print(f"ℹ️ No .env file found at {env_path}, using defaults")
except ImportError:
    print("⚠️ python-dotenv not installed. Using system environment variables only.")
    print("   Install with: pip install python-dotenv")


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with PUBSUB_ prefix."""
    return os.getenv(f"PUBSUB_{key}", default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    value = get_env(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int = 0) -> int:
    """Get integer environment variable."""
    try:
        return int(get_env(key, str(default)))
    except ValueError:
        return default


def get_env_list(key: str, default: Optional[list] = None) -> list:
    """Get list from comma-separated environment variable."""
    value = get_env(key, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(",")]


def setup_logging():
    """Configure logging from environment variables."""
    log_level = get_env("LOG_LEVEL", "INFO").upper()
    log_format = get_env("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Configure console logging
    if get_env_bool("LOG_TO_CONSOLE", True):
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format=log_format
        )

    # Configure file logging if specified
    log_file = get_env("LOG_FILE", "")
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        logging.getLogger().addHandler(file_handler)

    return logging.getLogger(__name__)


def main() -> None:
    """Entry point for the pubsub client demo."""
    # Setup logging
    logger = setup_logging()

    # Load configuration from environment
    server_url = get_env("SERVER_URL", "http://localhost:5000")
    consumer_name = get_env("CONSUMER_NAME", "demo-client")
    topics = get_env_list("TOPICS", ["notifications", "alerts", "updates"])

    # Display configuration
    logger.info("=" * 60)
    logger.info("PubSub Client Configuration")
    logger.info("=" * 60)
    logger.info(f"Server URL: {server_url}")
    logger.info(f"Consumer: {consumer_name}")
    logger.info(f"Topics: {topics}")
    logger.info(f"Debug Mode: {get_env_bool('DEBUG', False)}")
    logger.info("=" * 60)

    # Create a client instance
    client = PubSubClient(
        url=server_url,
        consumer=consumer_name,
        topics=topics
    )

    # Register handlers for different topics
    def handle_notification(message: Any) -> None:
        """Handle notification messages."""
        logger.info(f"📬 Notification received: {message}")

    def handle_alert(message: Any) -> None:
        """Handle alert messages."""
        logger.warning(f"⚠️ Alert received: {message}")

    def handle_update(message: Any) -> None:
        """Handle update messages."""
        logger.info(f"🔄 Update received: {message}")

    # Register the handlers
    client.register_handler("notifications", handle_notification)
    client.register_handler("alerts", handle_alert)
    client.register_handler("updates", handle_update)

    # Optional: Auto-publish test messages (configured via environment)
    if os.getenv("EXAMPLE_AUTO_PUBLISH", "false").lower() in ("true", "1", "yes", "on"):
        publish_delay = int(os.getenv("EXAMPLE_PUBLISH_DELAY", "2"))
        message_interval = int(os.getenv("EXAMPLE_MESSAGE_INTERVAL", "5"))
        producer_name = os.getenv("EXAMPLE_PRODUCER_NAME", "example-producer")

        def publish_test_messages():
            """Publish test messages after a delay."""
            time.sleep(publish_delay)
            logger.info("🚀 Starting to publish test messages...")

            message_count = 0
            while True:
                message_count += 1

                # Publish to different topics in rotation
                if message_count % 3 == 1:
                    client.publish(
                        topic="notifications",
                        message={
                            "text": f"Test notification #{message_count}",
                            "timestamp": time.time()
                        },
                        producer=producer_name,
                        message_id=f"notif-{message_count}-{int(time.time())}"
                    )
                    logger.debug(f"Published notification #{message_count}")

                elif message_count % 3 == 2:
                    client.publish(
                        topic="alerts",
                        message={
                            "level": "warning" if message_count % 2 == 0 else "info",
                            "text": f"Test alert #{message_count}",
                            "code": f"ALERT_{message_count:03d}"
                        },
                        producer=producer_name,
                        message_id=f"alert-{message_count}-{int(time.time())}"
                    )
                    logger.debug(f"Published alert #{message_count}")

                else:
                    client.publish(
                        topic="updates",
                        message={
                            "version": f"1.0.{message_count}",
                            "changes": [f"Change {i}" for i in range(1, 4)],
                            "timestamp": time.time()
                        },
                        producer=producer_name,
                        message_id=f"update-{message_count}-{int(time.time())}"
                    )
                    logger.debug(f"Published update #{message_count}")

                time.sleep(message_interval)

        # Start publishing thread
        import threading
        publisher = threading.Thread(target=publish_test_messages, daemon=True)
        publisher.start()
        logger.info(f"📤 Auto-publishing enabled (interval: {message_interval}s)")

    try:
        logger.info(f"🚀 Starting client connected to {server_url}")
        logger.info(f"📡 Subscribed to topics: {topics}")
        logger.info("Press Ctrl+C to stop...\n")

        # Start the client (blocking call)
        client.start()
    except KeyboardInterrupt:
        logger.info("\n👋 Client stopped by user")
    except Exception as e:
        logger.error(f"❌ An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()