"""
ServiceBus de base avec les fonctionnalités essentielles.
Conçu pour être léger et simple d'utilisation.
"""

import collections
import inspect
import threading
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, Optional, get_type_hints

from pydantic import BaseModel

from .client import HandlerInfo, PubSubClient
from .logger import logger
from .pubsub_message import PubSubMessage


class ServiceBusBase(threading.Thread):
    """
    ServiceBus de base pour la communication Pub/Sub.
    Fournit les fonctionnalités essentielles sans la complexité additionnelle.
    """

    def __init__(
            self,
            url: str,
            consumer_name: str,
            enable_devtools: bool = True,
            devtools_port: int = 8765,
            enable_recording: bool = False,
            devtools_recording_port: int = 5556,
            recording_session_name: Optional[str] = None
    ):
        super().__init__(name=f"ServiceBus-{consumer_name}")
        self.daemon = True
        self.url = url
        self.consumer_name = consumer_name
        self.client: Optional[PubSubClient] = None
        self._topics = set()
        self._handlers: Dict[str, list[HandlerInfo]] = collections.defaultdict(list)
        self._event_schemas: Dict[str, type] = {}
        self._schema_lock = threading.Lock()
        self._devtools_recorder: Optional[Any] = None

        # Auto-start DevTools API for cross-process communication (replay)
        if enable_devtools:
            try:
                from .devtools_api import DevToolsAPI

                self._devtools_api = DevToolsAPI(self, port=devtools_port)
                self._devtools_api.start()
            except Exception as e:
                logger.warning(f"Failed to start DevTools API: {e}")

        # Auto-start DevTools recording proxy
        if enable_recording:
            try:
                from .devtools_recorder_proxy import DevToolsRecorderProxy

                self._devtools_recorder = DevToolsRecorderProxy(
                    devtools_host='localhost',
                    devtools_port=devtools_recording_port
                )
                self._devtools_recorder.start_session(recording_session_name)
            except Exception as e:
                logger.warning(f"Failed to start DevTools recording: {e}")

    def subscribe(self, event_name: str, subscriber: Callable):
        """
        Souscrit à un événement avec un handler.

        Args:
            event_name: Nom de l'événement
            subscriber: Fonction handler à appeler
        """
        self._topics.add(event_name)
        handler_info = HandlerInfo(handler=subscriber)
        self._handlers[event_name].append(handler_info)

        # Enregistrement du schéma
        with self._schema_lock:
            if event_name not in self._event_schemas:
                try:
                    type_hints = get_type_hints(subscriber)
                    event_arg = next(
                        arg for arg in inspect.signature(subscriber).parameters if arg != "self"
                    )
                    event_class = type_hints.get(event_arg)
                    if event_class:
                        self._event_schemas[event_name] = event_class
                        logger.info(
                            f"Schéma pour '{event_name}' enregistré dynamiquement comme '{event_class.__name__}'."
                        )
                except Exception as e:
                    logger.warning(
                        f"Impossible de déterminer dynamiquement le schéma pour '{event_name}' à partir de '{subscriber.__name__}': {e}"
                    )

        logger.debug(f"'{subscriber.__name__}' mis en attente pour l'abonnement à '{event_name}'.")

    def publish(self, event_name: str, payload: Any, producer_name: str):
        """
        Publie un événement.

        Args:
            event_name: Nom de l'événement
            payload: Données à publier
            producer_name: Nom du producteur
        """
        if self.client is None:
            logger.error(
                f"Impossible de publier '{event_name}': le ServiceBus n'a pas encore démarré."
            )
            return

        message = self._prepare_payload(payload, event_name)

        if message is None:
            return

        # Envoyer à DevTools pour enregistrement si activé
        if self._devtools_recorder:
            try:
                self._devtools_recorder.record_event(event_name, message, producer_name)
            except Exception as e:
                logger.debug(f"Failed to record event to DevTools: {e}")

        self.client.publish(
            topic=event_name, message=message, producer=producer_name, message_id=str(uuid.uuid4())
        )

    def _prepare_payload(self, payload: Any, event_name: str) -> Optional[Dict[str, Any]]:
        """
        Prépare et sérialise le payload en dictionnaire.
        """
        message: Optional[Dict[str, Any]] = None
        schema_to_register = None

        if is_dataclass(payload):
            schema_to_register = type(payload)
            message = asdict(payload)
        elif isinstance(payload, BaseModel):
            schema_to_register = type(payload)
            message = payload.model_dump()
        elif isinstance(payload, dict):
            message = payload
        else:
            logger.error(f"Type de payload non supporté : {type(payload)}")
            return None

        if schema_to_register:
            with self._schema_lock:
                if event_name not in self._event_schemas:
                    self._event_schemas[event_name] = schema_to_register

        return message

    def run(self):
        """Thread principal du ServiceBus."""
        logger.info(
            f"Le thread ServiceBus démarre. Connexion et abonnement aux topics: {list(self._topics)}"
        )
        self.client = PubSubClient(
            url=self.url, consumer=self.consumer_name, topics=list(self._topics)
        )

        for event_name, handler_infos in self._handlers.items():

            def create_master_handler(evt_name, handlers_list):
                def _master_handler(message: Dict[str, Any]):
                    if isinstance(message, str) and message.startswith("Subscribed to"):
                        return

                    event_class = self._event_schemas.get(evt_name)
                    validated_payload = message.get("message", message)

                    if event_class:
                        try:
                            if not isinstance(validated_payload, dict):
                                logger.warning(
                                    f"Message inattendu pour {evt_name}, attendu dict, reçu {type(validated_payload)}"
                                )
                                return
                            validated_payload = event_class(**validated_payload)
                        except TypeError as e:
                            logger.error(
                                f"Erreur validation pour '{evt_name}': {e}. Message: {message}"
                            )
                            return

                    for handler_info in handlers_list:
                        try:
                            pubsub_msg = PubSubMessage(
                                topic=evt_name,
                                message_id=message.get("message_id", str(uuid.uuid4())),
                                message=message.get("message"),
                                producer=message.get("producer", "unknown"),
                            )

                            handler_info.handler(validated_payload)

                            if self.client:
                                self.client.notify_consumption(
                                    pubsub_msg, handler_info.handler_name
                                )

                        except Exception as e:
                            logger.error(
                                f"Erreur dans l'abonné '{handler_info.handler.__name__}' pour '{evt_name}': {e}",
                                exc_info=True,
                            )

                return _master_handler

            master_handler = create_master_handler(event_name, handler_infos)
            self.client.register_handler(event_name, master_handler)

        logger.info("Tous les handlers sont enregistrés. Démarrage de l'écoute...")
        try:
            self.client.start()
        except Exception as e:
            logger.error(f"Le client Pub/Sub s'est arrêté avec une erreur : {e}")
        logger.info("ServiceBus arrêté.")

    def stop_recording(self) -> bool:
        """Arrête l'enregistrement DevTools et sauvegarde le fichier.

        Returns:
            True si succès, False sinon
        """
        if self._devtools_recorder:
            return self._devtools_recorder.stop_session()
        return False

    def stop(self):
        """Arrête le ServiceBus."""
        logger.info("Demande d'arrêt pour ServiceBus.")

        # Arrêter l'enregistrement si activé
        if self._devtools_recorder:
            try:
                self._devtools_recorder.stop_session()
            except Exception as e:
                logger.warning(f"Failed to stop DevTools recording: {e}")

        if self.client:
            self.client.stop()
