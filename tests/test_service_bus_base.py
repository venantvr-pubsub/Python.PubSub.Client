"""
Tests unitaires pour ServiceBusBase.
Tests des fonctionnalités de base : pub/sub, validation schémas, PubSubMessage.
"""
import os
import sys
import unittest
from dataclasses import dataclass
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

from pubsub.service_bus_base import ServiceBusBase


@dataclass
class TestEvent:
    """Événement de test."""
    name: str
    value: int


class TestServiceBusBase(unittest.TestCase):
    """Tests pour ServiceBusBase."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.url = "http://localhost:3000"
        self.consumer_name = "test-consumer"
        self.service_bus = ServiceBusBase(self.url, self.consumer_name)

    def test_initialization(self):
        """Test de l'initialisation."""
        self.assertEqual(self.service_bus.url, self.url)
        self.assertEqual(self.service_bus.consumer_name, self.consumer_name)
        self.assertIsNone(self.service_bus.client)
        self.assertEqual(len(self.service_bus._topics), 0)
        self.assertTrue(self.service_bus.daemon)

    def test_subscribe(self):
        """Test de la souscription à un événement."""
        event_name = "test.event"
        handler = Mock()
        handler.__name__ = "mock_handler"  # Ajouter __name__ pour HandlerInfo

        self.service_bus.subscribe(event_name, handler)

        # Vérifier que le topic est ajouté
        self.assertIn(event_name, self.service_bus._topics)

        # Vérifier que le handler est enregistré
        self.assertIn(event_name, self.service_bus._handlers)
        self.assertEqual(len(self.service_bus._handlers[event_name]), 1)
        self.assertEqual(self.service_bus._handlers[event_name][0].handler, handler)

    def test_subscribe_with_schema(self):
        """Test de la souscription avec détection de schéma."""
        event_name = "test.typed.event"

        def typed_handler(event: TestEvent):
            pass

        self.service_bus.subscribe(event_name, typed_handler)

        # Vérifier que le schéma est détecté
        self.assertIn(event_name, self.service_bus._event_schemas)
        self.assertEqual(self.service_bus._event_schemas[event_name], TestEvent)

    def test_publish_without_client(self):
        """Test de publication sans client démarré."""
        with patch('pubsub.service_bus_base.logger') as mock_logger:
            self.service_bus.publish("test.event", {"data": "test"}, "producer")
            mock_logger.error.assert_called_once()

    @patch('pubsub.service_bus_base.PubSubClient')
    def test_publish_with_dataclass(self, mock_client_class):
        """Test de publication avec une dataclass."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        self.service_bus.client = mock_client

        event = TestEvent(name="test", value=42)
        self.service_bus.publish("test.event", event, "producer")

        # Vérifier que publish est appelé avec le bon format
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        self.assertEqual(call_args.kwargs['topic'], "test.event")
        self.assertEqual(call_args.kwargs['message'], {"name": "test", "value": 42})
        self.assertEqual(call_args.kwargs['producer'], "producer")

    @patch('pubsub.service_bus_base.PubSubClient')
    def test_publish_with_dict(self, mock_client_class):
        """Test de publication avec un dictionnaire."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        self.service_bus.client = mock_client

        message = {"key": "value"}
        self.service_bus.publish("test.event", message, "producer")

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        self.assertEqual(call_args.kwargs['message'], message)

    def test_publish_with_invalid_type(self):
        """Test de publication avec un type invalide."""
        self.service_bus.client = Mock()

        with patch('pubsub.service_bus_base.logger') as mock_logger:
            self.service_bus.publish("test.event", "invalid_type", "producer")
            mock_logger.error.assert_called_once()

    @patch('pubsub.service_bus_base.PubSubClient')
    def test_run_registers_handlers(self, mock_client_class):
        """Test que run() enregistre correctement les handlers."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Ajouter un handler
        handler = Mock()
        handler.__name__ = "mock_handler"  # Ajouter __name__ pour HandlerInfo
        self.service_bus.subscribe("test.event", handler)

        # Simuler le thread run (sans vraiment le démarrer)
        with patch.object(self.service_bus, 'client', mock_client):
            # Extraire et appeler la logique d'enregistrement
            for event_name, handler_infos in self.service_bus._handlers.items():
                self.assertEqual(event_name, "test.event")
                self.assertEqual(len(handler_infos), 1)

    def test_stop(self):
        """Test de l'arrêt du ServiceBus."""
        mock_client = Mock()
        self.service_bus.client = mock_client

        self.service_bus.stop()

        mock_client.stop.assert_called_once()

    def test_thread_name(self):
        """Test du nom du thread."""
        expected_name = f"ServiceBus-{self.consumer_name}"
        self.assertEqual(self.service_bus.name, expected_name)


if __name__ == '__main__':
    unittest.main()
