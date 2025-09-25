# -*- coding: utf-8 -*-
from dataclasses import dataclass


# Assurez-vous que le chemin vers votre module pubsub est correct
# sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

# Mocks pour permettre l'exécution du script sans les vraies classes
class ServiceBusBase:
    def __init__(self, url, consumer_id): pass

    def subscribe(self, event_name, handler): pass

    def publish(self, event_name, payload, source): pass


class EnhancedServiceBus(ServiceBusBase):
    def __init__(self, url, consumer_id, max_workers=None, retry_policy=None):
        super().__init__(url, consumer_id)


class logger:
    @staticmethod
    def info(msg): print(f"INFO: {msg}")

    @staticmethod
    def error(msg): print(f"ERROR: {msg}")

@dataclass
class SimpleEvent:
    message: str
    timestamp: float


def demo_base_service_bus():
    """Démo du ServiceBusBase - léger et simple."""
    logger.info("=== ServiceBusBase Demo ===")

    bus = ServiceBusBase("http://localhost:3000", "simple-consumer")

    def handle_event(event: SimpleEvent):
        logger.info(f"[BASE] Reçu: {event.message}")

    # Souscription simple
    bus.subscribe("simple.event", handle_event)

    # Publication simple (fire and forget)
    bus.publish("simple.event", {"message": "Hello", "timestamp": 123.45}, "demo")

    logger.info("ServiceBusBase: Léger, simple, efficace pour les cas basiques")


def demo_enhanced_service_bus():
    """Démo d'EnhancedServiceBus - complet avec sync et stats."""
    logger.info("\n=== EnhancedServiceBus Demo ===")

    bus = EnhancedServiceBus(
        "http://localhost:3000",
        "advanced-consumer",
        max_workers=10,
        retry_policy={
            "max_attempts": 3,
            "initial_delay": 0.5
        }
    )

    def handle_event(event: SimpleEvent):
        logger.info(f"[ENHANCED] Reçu: {event.message}")
        return {"status": "processed"}

    bus.subscribe("advanced.event", handle_event)

    # Démarrer le bus (dans un vrai cas, ce serait dans un thread)
    # bus.start()

    # Attendre que le service soit prêt
    # if bus.wait_for_start(timeout=10):
    #     logger.info(f"État actuel: {bus.state.value}")

    # Publication avec attente de confirmation
    # future = bus.publish_and_wait(
    #     "advanced.event",
    #     {"message": "Hello with confirmation", "timestamp": 456.78},
    #     timeout=5.0
    # )

    # try:
    #     result = future.wait()
    #     logger.info(f"Confirmation reçue: {result}")
    # except TimeoutError:
    #     logger.error("Timeout en attente de confirmation")

    # Statistiques
    # stats = bus.get_stats()
    # logger.info(f"Statistiques: {stats}")

    logger.info("EnhancedServiceBus: Idéal pour trading, avec sync et monitoring")


def show_comparison():
    """Affiche une comparaison des deux versions."""
    print("\n📊 COMPARAISON DES DEUX VERSIONS\n")
    print("┌─────────────────────────┬──────────────────────┬──────────────────────┐")
    print("│ Fonctionnalité          │ ServiceBusBase       │ EnhancedServiceBus   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Pub/Sub basique         │ ✅                   │ ✅                   │")
    print("│ Validation schémas      │ ✅                   │ ✅                   │")
    print("│ PubSubMessage           │ ✅                   │ ✅                   │")
    print("│ Thread-safe             │ ✅                   │ ✅                   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Gestion d'état          │ ❌                   │ ✅                   │")
    print("│ Publish & Wait          │ ❌                   │ ✅                   │")
    print("│ Sync multi-événements   │ ❌                   │ ✅                   │")
    print("│ Statistiques            │ ❌                   │ ✅                   │")
    print("│ Retry policy            │ ❌                   │ ✅                   │")
    print("│ ThreadPool              │ ❌                   │ ✅                   │")
    print("│ Cleanup automatique     │ ❌                   │ ✅                   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Empreinte mémoire       │ Légère               │ Moyenne              │")
    print("│ Complexité              │ Simple               │ Avancée              │")
    print("│ Cas d'usage             │ Applications simples │ Trading, critique    │")
    print("└─────────────────────────┴──────────────────────┴──────────────────────┘")

    print("\n💡 RECOMMANDATIONS:")
    print("• ServiceBusBase: Parfait pour les applications simples avec pub/sub basique.")
    print("• EnhancedServiceBus: Idéal pour le trading et les systèmes critiques.")
    print("• Migration facile: EnhancedServiceBus hérite de ServiceBusBase.")


if __name__ == "__main__":
    demo_base_service_bus()
    demo_enhanced_service_bus()
    show_comparison()