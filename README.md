# Python PubSub Client

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PyPI Version](https://img.shields.io/pypi/v/python-pubsub-client)](https://pypi.org/project/python-pubsub-client/)
[![Build Status](https://img.shields.io/github/actions/workflow/status/venantvr/Python.PubSub.Client/ci.yml?branch=master)](https://github.com/venantvr/Python.PubSub.Client/actions)
[![Coverage Status](https://img.shields.io/codecov/c/github/venantvr/Python.PubSub.Client)](https://codecov.io/gh/venantvr/Python.PubSub.Client)

A simple, robust, and production-ready WebSocket Pub/Sub client for Python, built on Socket.IO.

## ✨ Features

- 🔄 **Automatic reconnection** with exponential backoff
- 📨 **Message queuing** for reliable sequential processing
- 🎯 **Topic-based subscription** with custom handlers
- 🔌 **Both publish and subscribe** capabilities
- 📝 **Comprehensive logging** for debugging
- 🧪 **Type hints** for better IDE support
- ⚡ **Async message processing** with threading
- 🛡️ **Error handling** with graceful degradation

## 📦 Installation

### From PyPI

```bash
pip install python-pubsub-client
```

### From Source (Production)

```bash
git clone https://github.com/venantvr/Python.PubSub.Client.git
cd Python.PubSub.Client
pip install .
```

### Development Installation

```bash
git clone https://github.com/venantvr/Python.PubSub.Client.git
cd Python.PubSub.Client

# Install in editable mode with development dependencies
make dev
# Or manually:
pip install -e ".[dev]"
```

## ⚙️ Configuration

The client can be configured using environment variables. Copy `.env.example` to `.env` and adjust the values:

```bash
cp .env.example .env
# Edit .env with your configuration
```

Key configuration options:

- `PUBSUB_SERVER_URL`: WebSocket server URL (default: `http://localhost:5000`)
- `PUBSUB_CONSUMER_NAME`: Client identifier (default: `demo-client`)
- `PUBSUB_TOPICS`: Comma-separated list of topics to subscribe
- `PUBSUB_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

See `.env.example` for all available options.

## 🚀 Quick Start

### Basic Usage

```python
from pubsub import PubSubClient  # Simple import thanks to __init__.py

# Create client
client = PubSubClient(
    url="http://localhost:5000",
    consumer="alice",
    topics=["notifications", "updates"]
)

# Register message handlers
def handle_notification(message):
    print(f"Received notification: {message}")

client.register_handler("notifications", handle_notification)

# Start the client
client.start()
```

### Publishing Messages

```python
# Publish a message to a topic
# noinspection PyUnresolvedReferences
client.publish(
    topic="notifications",
    message={"type": "alert", "content": "Hello World!"},
    producer="alice",
    message_id="msg-001"
)
```

### Advanced Example

```python
import logging
from pubsub import PubSubClient

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create client with multiple topics
client = PubSubClient(
    url="http://localhost:5000",
    consumer="service-a",
    topics=["orders", "inventory", "shipping"]
)

# Define custom handlers for each topic
def process_order(message):
    order_id = message.get("order_id")
    print(f"Processing order: {order_id}")
    # Your order processing logic here

def update_inventory(message):
    item_id = message.get("item_id")
    quantity = message.get("quantity")
    print(f"Updating inventory for item {item_id}: {quantity}")
    # Your inventory logic here

def track_shipping(message):
    tracking_number = message.get("tracking_number")
    print(f"Tracking shipment: {tracking_number}")
    # Your shipping logic here

# Register handlers
client.register_handler("orders", process_order)
client.register_handler("inventory", update_inventory)
client.register_handler("shipping", track_shipping)

# Start client (blocking)
try:
    client.start()
except KeyboardInterrupt:
    print("Shutting down client...")
```

## 🛠️ Development

### Prerequisites

- Python 3.9 or higher
- pip and virtualenv
- Make (optional, for using Makefile commands)

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/venantvr/Python.PubSub.Client.git
cd Python.PubSub.Client

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
make dev
# Or manually:
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
make test

# Run specific test file
pytest tests/test_client.py -v
```

### Code Quality

```bash
# Format code
make format

# Run linters
make lint

# Run all checks (linters and tests)
make check
```

## 📁 Project Structure

```
Python.PubSub.Client/
├── src/
│   └── pubsub/
│       ├── __init__.py
│       ├── pubsub_client.py     # Main client implementation
│       └── pubsub_message.py    # Message model
├── tests/
│   ├── __init__.py
│   ├── test_client.py
│   └── test_message.py
├── examples/
│   └── simple_client.py         # Example usage
├── Makefile                      # Development commands
├── pyproject.toml               # Project configuration (single source of truth)
└── README.md                    # This file
```

## 🧪 Testing

The project uses pytest for testing. Tests are located in the `tests/` directory.

```bash
# Run tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=pubsub --cov-report=html
```

## 📝 API Reference

### PubSubClient

#### Constructor

```python
PubSubClient(url: str, consumer: str, topics: List[str])
```

- `url`: WebSocket server URL
- `consumer`: Consumer identifier
- `topics`: List of topics to subscribe to

#### Methods

##### `register_handler(topic: str, handler_func: Callable[[Any], None]) -> None`

Register a callback function for a specific topic.

##### `publish(topic: str, message: Any, producer: str, message_id: str) -> None`

Publish a message to a topic via HTTP POST.

##### `start() -> None`

Start the client and begin listening for messages (blocking).

##### `stop() -> None`

Stop the client gracefully and clean up resources.

### PubSubMessage

#### Constructor

```python
PubSubMessage.new(topic: str, message: Any, producer: str, message_id: str)
```

Create a new message instance.

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please ensure:

- Code follows the project's style guidelines (Black formatting)
- All tests pass
- Coverage remains above 80%
- Documentation is updated as needed

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [python-socketio](https://python-socketio.readthedocs.io/)
- Inspired by various Pub/Sub patterns and implementations
- Thanks to all contributors!

## 📧 Contact

- Author: venantvr
- Email: venantvr@gmail.com
- GitHub: [@venantvr](https://github.com/venantvr)

## 🐛 Bug Reports

Please report bugs via [GitHub Issues](https://github.com/venantvr/Python.PubSub.Client/issues).

## 📈 Roadmap

- [ ] Add support for message persistence
- [ ] Implement message encryption
- [ ] Add metrics and monitoring
- [ ] Support for multiple server URLs (failover)
- [ ] GraphQL subscription support
- [ ] WebRTC data channel support

---

Made with ❤️ by [venantvr](https://github.com/venantvr)