import collections
import inspect
import threading  # L'import de threading est déjà là
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, get_type_hints, Optional, Dict

from .logger import logger
# noinspection PyPackageRequirements
from .pubsub_client import HandlerInfo, PubSubClient


class ServiceBus(threading.Thread):
    def __init__(self, url: str, consumer_name: str):
        super().__init__()
        self.daemon = True
        self.url = url
        self.consumer_name = consumer_name
        self.client: Optional[PubSubClient] = None
        self._topics = set()
        self._handlers: Dict[str, list[HandlerInfo]] = collections.defaultdict(list)
        self._event_schemas: Dict[str, type] = {}

        # AJOUT : Le verrou pour protéger l'accès au dictionnaire des schémas
        self._schema_lock = threading.Lock()

    def subscribe(self, event_name: str, subscriber: Callable):
        self._topics.add(event_name)
        handler_info = HandlerInfo(handler=subscriber)
        self._handlers[event_name].append(handler_info)

        # On utilise le verrou pour rendre l'opération "vérifier puis agir" atomique
        with self._schema_lock:
            if event_name not in self._event_schemas:
                try:
                    type_hints = get_type_hints(subscriber)
                    event_arg = next(arg for arg in inspect.signature(subscriber).parameters if arg != 'self')
                    event_class = type_hints.get(event_arg)
                    if event_class:
                        self._event_schemas[event_name] = event_class
                        logger.info(f"Schéma pour '{event_name}' enregistré dynamiquement comme '{event_class.__name__}'.")
                except Exception as e:
                    logger.warning(
                        f"Impossible de déterminer dynamiquement le schéma pour '{event_name}' à partir de '{subscriber.__name__}': {e}"
                    )

        logger.debug(f"'{subscriber.__name__}' mis en attente pour l'abonnement à '{event_name}'.")

    # La méthode run reste inchangée, elle ne fait que LIRE le dictionnaire une fois la configuration terminée.
    def run(self):
        logger.info(f"Le thread ServiceBus démarre. Connexion et abonnement aux topics: {list(self._topics)}")
        self.client = PubSubClient(url=self.url, consumer=self.consumer_name, topics=list(self._topics))
        for event_name, handler_infos in self._handlers.items():
            def create_master_handler(e_name, handlers_list):
                def _master_handler(message: Dict[str, Any]):
                    if isinstance(message, str) and message.startswith("Subscribed to"):
                        return

                    # La lecture n'a pas besoin de lock si les écritures sont terminées avant le démarrage.
                    # Mais par sécurité, on pourrait aussi locker la lecture si des abonnements peuvent arriver tardivement.
                    event_class = self._event_schemas.get(e_name)
                    validated_payload = message

                    if event_class:
                        # noinspection PyShadowingNames
                        try:
                            if not isinstance(message, dict):
                                logger.warning(
                                    f"Message inattendu pour {e_name}, attendu dict, reçu {type(message)}"
                                )
                                return
                            validated_payload = event_class(**message)
                        except TypeError as e:
                            logger.error(f"Erreur validation pour '{e_name}': {e}. Message: {message}")
                            return
                    for handler_info in handlers_list:
                        # noinspection PyShadowingNames
                        try:
                            handler_info.handler(validated_payload)

                            self.client.notify_consumption(validated_payload, str(uuid.uuid4()), handler_info.metadata, e_name)

                        except Exception as e:
                            logger.error(f"Erreur dans l'abonné '{handler_info.handler.__name__}' pour '{e_name}': {e}", exc_info=True)

                return _master_handler

            master_handler = create_master_handler(event_name, handler_infos)
            # On peut passer une metadata personnalisée pour le master handler
            # self.client.register_handler(event_name, master_handler, metadata=f"master_handler_{event_name}")
            # self.client.register_handler(event_name, master_handler, metadata=self.get_handler_class_name(master_handler))
            self.client.register_handler(event_name, master_handler)
            # TODO : pour metadata il faudrait self.consumer...
        logger.info("Tous les handlers sont enregistrés. Démarrage de l'écoute...")
        try:
            self.client.start()
        except Exception as e:
            logger.error(f"Le client Pub/Sub s'est arrêté avec une erreur : {e}")
        logger.info("ServiceBus arrêté.")

    @staticmethod
    def get_handler_class_name(handler_func):
        if hasattr(handler_func, '__self__'):
            # C'est une méthode d'instance
            return handler_func.__self__.__class__.__name__
        elif hasattr(handler_func, '__qualname__'):
            # Extraire le nom de classe du qualname
            parts = handler_func.__qualname__.split('.')
            if len(parts) > 1:
                return parts[0]
        return handler_func.__name__  # Fonction simple

    def publish(self, event_name: str, payload: Any, metadata: str):
        if self.client is None:
            logger.error(f"Impossible de publier '{event_name}': le ServiceBus n'a pas encore démarré.")
            return

        if is_dataclass(payload):
            # Il faut aussi protéger l'écriture potentielle dans publish
            with self._schema_lock:
                if event_name not in self._event_schemas:
                    self._event_schemas[event_name] = type(payload)
            message = asdict(payload)
        elif isinstance(payload, dict):
            message = payload
        else:
            logger.error(f"Type de payload non supporté : {type(payload)}")
            return

        self.client.publish(
            # topic=event_name, message=message, producer=self.client.consumer, message_id=str(uuid.uuid4())
            topic = event_name, message = message, producer = metadata, message_id = str(uuid.uuid4())
        )

    @staticmethod
    def stop():
        logger.info("Demande d'arrêt pour ServiceBus.")
        pass
