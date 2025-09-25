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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

from pubsub.enhanced_service_bus import (
    EnhancedServiceBus,
    ServiceBusState,
    EventFuture,
    EventWaitManager
)
from pubsub.pubsub_message import PubSubMessage


@dataclass
class TestEvent:
    """Événement de test."""
    name: str
    value: int


class TestEnhancedServiceBus(unittest.TestCase):
    """Tests pour EnhancedServiceBus."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.url = "http://localhost:3000"
        self.consumer_name = "test-enhanced"
        self.service_bus = EnhancedServiceBus(
            self.url,
            self.consumer_name,
            max_workers=5,
            retry_policy={
                "max_attempts": 2,
                "initial_delay": 0.1,
                "max_delay": 1.0,
                "exponential_base": 2
            }
        )

    def test_initialization(self):
        """Test de l'initialisation avec paramètres avancés."""
        self.assertEqual(self.service_bus.url, self.url)
        self.assertEqual(self.service_bus.consumer_name, self.consumer_name)
        self.assertFalse(self.service_bus.daemon)  # EnhancedServiceBus n'est pas daemon
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)
        self.assertIsNotNone(self.service_bus._executor)
        self.assertIsNotNone(self.service_bus._event_manager)
        self.assertEqual(self.service_bus._retry_policy["max_attempts"], 2)

    def test_state_property(self):
        """Test de la propriété state."""
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)

        # Test du changement d'état
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
        with self.assertRaises(RuntimeError) as context:
            self.service_bus.publish_and_wait("test.event", {"data": "test"})

        self.assertIn("Cannot publish in state stopped", str(context.exception))

    @patch('pubsub.enhanced_service_bus.PubSubClient')
    def test_publish_and_wait_success(self, mock_client_class):
        """Test publish_and_wait avec succès."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        self.service_bus.client = mock_client
        self.service_bus._state = ServiceBusState.RUNNING

        # Publier et obtenir un future
        future = self.service_bus.publish_and_wait(
            "test.event",
            {"data": "test"},
            producer_name="test-producer",
            timeout=5.0
        )

        # Vérifier le type
        self.assertIsInstance(future, EventFuture)
        self.assertEqual(future.event_name, "test.event")
        self.assertEqual(future.timeout, 5.0)

        # Vérifier l'appel à publish
        mock_client.publish.assert_called_once()

    def test_wait_for_start(self):
        """Test de wait_for_start."""
        # Par défaut, l'événement n'est pas set
        result = self.service_bus.wait_for_start(timeout=0.1)
        self.assertFalse(result)

        # Simuler le démarrage
        self.service_bus._start_event.set()
        result = self.service_bus.wait_for_start(timeout=0.1)
        self.assertTrue(result)

    def test_get_stats(self):
        """Test de récupération des statistiques."""
        stats = self.service_bus.get_stats()

        # Vérifier les clés
        expected_keys = ["messages_received", "messages_processed", "messages_failed", "last_error", "start_time"]
        for key in expected_keys:
            self.assertIn(key, stats)

        # Vérifier les valeurs initiales
        self.assertEqual(stats["messages_received"], 0)
        self.assertEqual(stats["messages_processed"], 0)
        self.assertEqual(stats["messages_failed"], 0)
        self.assertIsNone(stats["last_error"])
        self.assertIsNone(stats["start_time"])

    def test_stats_with_uptime(self):
        """Test des statistiques avec uptime."""
        # Simuler un temps de démarrage
        self.service_bus._stats["start_time"] = time.time() - 10  # Démarré il y a 10 secondes

        stats = self.service_bus.get_stats()

        self.assertIn("uptime", stats)
        self.assertGreaterEqual(stats["uptime"], 10)

    def test_stop_already_stopped(self):
        """Test d'arrêt quand déjà arrêté."""
        result = self.service_bus.stop(timeout=0.1)
        self.assertTrue(result)  # Déjà arrêté, donc succès

    def test_stop_with_running_state(self):
        """Test d'arrêt avec état RUNNING."""
        self.service_bus._state = ServiceBusState.RUNNING
        mock_client = Mock()
        self.service_bus.client = mock_client

        # Le thread n'est pas vraiment démarré, donc join retournera rapidement
        result = self.service_bus.stop(timeout=0.1)

        mock_client.stop.assert_called_once()
        self.assertEqual(self.service_bus.state, ServiceBusState.STOPPED)


class TestEventWaitManager(unittest.TestCase):
    """Tests pour EventWaitManager."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.manager = EventWaitManager()

    def test_create_event_future(self):
        """Test de création d'un EventFuture."""
        future = self.manager.create_event_future("test.event", timeout=5.0)

        self.assertIsInstance(future, EventFuture)
        self.assertEqual(future.event_name, "test.event")
        self.assertEqual(future.timeout, 5.0)
        self.assertFalse(future.is_done())

    def test_get_event(self):
        """Test de récupération d'un événement."""
        future = self.manager.create_event_future("test.event")
        event_id = future.event_id

        # Récupérer l'événement
        retrieved = self.manager.get_event(event_id)
        self.assertEqual(retrieved, future)

        # Événement inexistant
        self.assertIsNone(self.manager.get_event("unknown-id"))

    def test_remove_event(self):
        """Test de suppression d'un événement."""
        future = self.manager.create_event_future("test.event")
        event_id = future.event_id

        # Supprimer l'événement
        removed = self.manager.remove_event(event_id)
        self.assertEqual(removed, future)

        # Vérifier qu'il n'existe plus
        self.assertIsNone(self.manager.get_event(event_id))

        # Supprimer un événement inexistant
        self.assertIsNone(self.manager.remove_event("unknown-id"))


class TestEventFuture(unittest.TestCase):
    """Tests pour EventFuture."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.future = EventFuture(event_name="test.event", timeout=5.0)

    def test_set_result(self):
        """Test de set_result."""
        message = PubSubMessage(
            topic="test.event",
            message_id="123",
            message={"data": "test"},
            producer="test-producer"
        )

        self.future.set_result(message)

        self.assertTrue(self.future.is_done())
        self.assertEqual(self.future.pubsub_message, message)

    def test_set_exception(self):
        """Test de set_exception."""
        exception = RuntimeError("Test error")
        self.future.set_exception(exception)

        self.assertTrue(self.future.is_done())

        with self.assertRaises(RuntimeError):
            self.future.wait(timeout=0.1)

    def test_wait_timeout(self):
        """Test du timeout sur wait."""
        with self.assertRaises(TimeoutError):
            self.future.wait(timeout=0.1)


if __name__ == '__main__':
    unittest.main()
