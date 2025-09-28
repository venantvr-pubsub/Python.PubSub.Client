"""
Tests unitaires pour EnhancedServiceBus.
Tests des fonctionnalités avancées : état, stats, publish_and_wait, retry policy.
"""
import os
import sys
import time
import unittest
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from unittest.mock import Mock, patch

# Assure que le répertoire 'src' est dans le path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

from pubsub.enhanced_bus import (
    EnhancedServiceBus,
    ServiceBusState,
    EventFuture,
    EventWaitManager
)
from pubsub.pubsub_message import PubSubMessage


@dataclass
class TestRpcEvent:
    """Événement de test pour la détection de schéma RPC."""
    value: int


class TestEnhancedServiceBus(unittest.TestCase):
    """Tests pour EnhancedServiceBus."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.url = os.getenv("PUBSUB_SERVER_URL", "http://localhost:3000")
        self.consumer_name = "test-enhanced"
        self.service_bus = EnhancedServiceBus(
            self.url,
            self.consumer_name,
            max_workers=2,
            retry_policy={"max_attempts": 2, "initial_delay": 0.01}
        )

    def test_initialization(self):
        """Test de l'initialisation avec paramètres avancés."""
        self.assertEqual(self.service_bus.url, self.url)
        self.assertFalse(self.service_bus.daemon)
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)

    def test_state_property(self):
        """Test de la propriété state."""
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)
        self.service_bus._set_state(ServiceBusState.STARTING)
        self.assertEqual(self.service_bus.state, ServiceBusState.STARTING)

    def test_state_transitions(self):
        """Test des transitions d'état."""
        transitions = [
            (ServiceBusState.STOPPED, ServiceBusState.STARTING),
            (ServiceBusState.STARTING, ServiceBusState.RUNNING),
            (ServiceBusState.RUNNING, ServiceBusState.STOPPING),
            (ServiceBusState.STOPPING, ServiceBusState.STOPPED),
        ]
        for old_state, new_state in transitions:
            self.service_bus._state = old_state
            self.service_bus._set_state(new_state)
            self.assertEqual(self.service_bus.state, new_state)

    def test_publish_and_wait_wrong_state(self):
        """Test publish_and_wait dans un mauvais état."""
        with self.assertRaisesRegex(RuntimeError, "Cannot publish in state stopped"):
            self.service_bus.publish_and_wait("test.event", {"data": "test"})

    @patch('pubsub.enhanced_bus.PubSubClient')
    def test_publish_and_wait_success(self, mock_client_class):
        """Test que publish_and_wait publie bien un message."""
        mock_client = Mock()
        self.service_bus.client = mock_client
        self.service_bus._state = ServiceBusState.RUNNING
        future = self.service_bus.publish_and_wait("test.event", {"data": "test"})

        self.assertIsInstance(future, EventFuture)
        mock_client.publish.assert_called_once()
        self.assertIn(future.event_id, self.service_bus._pending_events)

    @patch('pubsub.enhanced_bus.PubSubClient')
    def test_rpc_logic_with_publish_and_wait(self, mock_client_class):
        """Test que publish_and_wait retourne bien le résultat du handler."""
        # 1. Configuration
        mock_client = mock_client_class.return_value
        self.service_bus.client = mock_client
        self.service_bus._state = ServiceBusState.RUNNING

        event_name = "compute.request"
        request_payload = TestRpcEvent(value=10)
        expected_response = {"result": 20}

        def compute_handler(event: TestRpcEvent) -> dict:
            return {"result": event.value * 2}

        handler_mock = Mock(wraps=compute_handler)
        handler_mock.__name__ = "compute_handler_mock"

        self.service_bus.subscribe(event_name, handler_mock)

        # Simuler le démarrage pour enregistrer les handlers sur le client
        self.service_bus._register_enhanced_handlers()

        # 2. Action
        future = self.service_bus.publish_and_wait(event_name, request_payload)

        mock_client.register_handler.assert_called_once_with(event_name, unittest.mock.ANY)
        master_handler = mock_client.register_handler.call_args.args[1]

        incoming_message = {
            "topic": event_name,
            "message": {"value": 10},
            "message_id": future.event_id
        }
        master_handler(incoming_message)

        # 3. Vérification
        result = future.wait(timeout=1)

        handler_mock.assert_called_once_with(request_payload)
        self.assertEqual(result, expected_response)

    def test_wait_for_start(self):
        """Test de wait_for_start."""
        self.assertFalse(self.service_bus.wait_for_start(timeout=0.01))
        self.service_bus._start_event.set()
        self.assertTrue(self.service_bus.wait_for_start(timeout=0.01))

    def test_get_stats(self):
        """Test de récupération des statistiques."""
        stats = self.service_bus.get_stats()
        expected_keys = ["messages_received", "messages_processed", "messages_failed", "last_error", "start_time"]
        for key in expected_keys:
            self.assertIn(key, stats)

    def test_stats_with_uptime(self):
        """Test des statistiques avec uptime."""
        self.service_bus._stats["start_time"] = time.time() - 10
        stats = self.service_bus.get_stats()
        self.assertIn("uptime", stats)
        self.assertGreaterEqual(stats["uptime"], 10)

    def test_stop_already_stopped(self):
        """Test d'arrêt quand déjà arrêté."""
        self.assertTrue(self.service_bus.stop(timeout=0.1))

    def test_stop_with_running_state(self):
        """Test d'arrêt avec état RUNNING."""
        self.service_bus._state = ServiceBusState.RUNNING
        self.service_bus.client = Mock()
        self.service_bus.stop(timeout=0.1)
        self.service_bus.client.stop.assert_called_once()
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)


class TestEventWaitManager(unittest.TestCase):
    """Tests pour EventWaitManager."""

    def setUp(self):
        self.manager = EventWaitManager()

    def test_create_event_future(self):
        future = self.manager.create_event_future("test.event", timeout=5.0)
        self.assertIsInstance(future, EventFuture)

    def test_get_event(self):
        future = self.manager.create_event_future("test.event")
        retrieved = self.manager.get_event(future.event_id)
        self.assertEqual(retrieved, future)

    def test_remove_event(self):
        future = self.manager.create_event_future("test.event")
        self.manager.remove_event(future.event_id)
        self.assertIsNone(self.manager.get_event(future.event_id))


class TestEventFuture(unittest.TestCase):
    """Tests pour EventFuture."""

    def setUp(self):
        self.future = EventFuture(event_name="test.event", timeout=5.0)

    def test_set_result(self):
        message = PubSubMessage.new("test.event", {"data": "test"}, "producer")
        self.future.set_result(message)
        self.assertTrue(self.future.is_done())

    def test_set_exception(self):
        exception = RuntimeError("Test error")
        self.future.set_exception(exception)
        with self.assertRaises(RuntimeError):
            self.future.wait(timeout=0.1)

    def test_wait_timeout(self):
        with self.assertRaises(TimeoutError):
            self.future.wait(timeout=0.1)


if __name__ == '__main__':
    unittest.main()
