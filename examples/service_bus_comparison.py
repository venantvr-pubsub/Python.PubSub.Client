"""
Exemple montrant les diff\u00e9rences entre ServiceBusBase et EnhancedServiceBus.
"""
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/src')

from pubsub.service_bus import ServiceBusBase, EnhancedServiceBus
from pubsub.logger import logger


@dataclass
class SimpleEvent:
    message: str
    timestamp: float


def demo_base_service_bus():
    """D\u00e9mo du ServiceBusBase - l\u00e9ger et simple."""
    logger.info("=== ServiceBusBase Demo ===")

    bus = ServiceBusBase("http://localhost:3000", "simple-consumer")

    def handle_event(event: SimpleEvent):
        logger.info(f"[BASE] Re\u00e7u: {event.message}")

    # Souscription simple
    bus.subscribe("simple.event", handle_event)

    # Publication simple (fire and forget)
    bus.publish("simple.event", {"message": "Hello", "timestamp": 123.45}, "demo")

    logger.info("ServiceBusBase: L\u00e9ger, simple, efficace pour les cas basiques")


def demo_enhanced_service_bus():
    """D\u00e9mo d'EnhancedServiceBus - complet avec sync et stats."""
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
        logger.info(f"[ENHANCED] Re\u00e7u: {event.message}")
        return {"status": "processed"}

    bus.subscribe("advanced.event", handle_event)

    # D\u00e9marrer le bus (dans un vrai cas, ce serait dans un thread)
    # bus.start()

    # Attendre que le service soit pr\u00eat
    # if bus.wait_for_start(timeout=10):
    #     logger.info(f"\u00c9tat actuel: {bus.state.value}")

    # Publication avec attente de confirmation
    # future = bus.publish_and_wait(
    #     "advanced.event",
    #     {"message": "Hello with confirmation", "timestamp": 456.78},
    #     timeout=5.0
    # )

    # try:
    #     result = future.wait()
    #     logger.info(f"Confirmation re\u00e7ue: {result}")
    # except TimeoutError:
    #     logger.error("Timeout en attente de confirmation")

    # Statistiques
    # stats = bus.get_stats()
    # logger.info(f"Statistiques: {stats}")

    logger.info("EnhancedServiceBus: Id\u00e9al pour trading, avec sync et monitoring")


def show_comparison():
    """Affiche une comparaison des deux versions."""
    print("\n📊 COMPARAISON DES DEUX VERSIONS\n")
    print("┌─────────────────────────┬──────────────────────┬──────────────────────┐")
    print("│ Fonctionnalit\u00e9          │ ServiceBusBase       │ EnhancedServiceBus   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Pub/Sub basique         │ ✅                   │ ✅                   │")
    print("│ Validation sch\u00e9mas      │ ✅                   │ ✅                   │")
    print("│ PubSubMessage           │ ✅                   │ ✅                   │")
    print("│ Thread-safe             │ ✅                   │ ✅                   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Gestion d'\u00e9tat          │ ❌                   │ ✅                   │")
    print("│ Publish & Wait          │ ❌                   │ ✅                   │")
    print("│ Sync multi-\u00e9v\u00e9nements  │ ❌                   │ ✅                   │")
    print("│ Statistiques            │ ❌                   │ ✅                   │")
    print("│ Retry policy            │ ❌                   │ ✅                   │")
    print("│ ThreadPool              │ ❌                   │ ✅                   │")
    print("│ Cleanup automatique     │ ❌                   │ ✅                   │")
    print("├─────────────────────────┼──────────────────────┼──────────────────────┤")
    print("│ Empreinte m\u00e9moire      │ L\u00e9g\u00e8re              │ Moyenne              │")
    print("│ Complexit\u00e9             │ Simple               │ Avanc\u00e9e             │")
    print("│ Cas d'usage            │ Applications simples │ Trading, critique    │")
    print("└─────────────────────────┴──────────────────────┴──────────────────────┘")

    print("\n💡 RECOMMANDATIONS:")
    print("• ServiceBusBase: Parfait pour les applications simples avec pub/sub basique")
    print("• EnhancedServiceBus: Id\u00e9al pour le trading et les syst\u00e8mes critiques")
    print("• Migration facile: EnhancedServiceBus h\u00e9rite de ServiceBusBase")


if __name__ == "__main__":
    demo_base_service_bus()
    demo_enhanced_service_bus()
    show_comparison()
