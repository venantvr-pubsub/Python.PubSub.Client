import os
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# Mocks pour permettre l'exécution du script sans les vraies classes
class ServiceBusBase:

    # noinspection PyUnusedLocal
    def __init__(self, url, consumer_id): pass

    def subscribe(self, event_name, handler): pass

    def publish(self, event_name, payload, source): pass


class EnhancedServiceBus(ServiceBusBase):

    # noinspection PyUnusedLocal
    def __init__(self, url, consumer_id, max_workers=None, retry_policy=None):
        super().__init__(url, consumer_id)


# noinspection PyPep8Naming
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
    server_url = os.getenv("PUBSUB_SERVER_URL", "http://localhost:3000")
    bus = ServiceBusBase(server_url, "simple-consumer")

    def handle_event(event: SimpleEvent):
        logger.info(f"[BASE] Reçu: {event.message}")

    bus.subscribe("simple.event", handle_event)
    bus.publish("simple.event", {"message": "Hello", "timestamp": 123.45}, "demo")
    logger.info("ServiceBusBase: Léger, simple, efficace pour les cas basiques")


def demo_enhanced_service_bus():
    """Démo d'EnhancedServiceBus - complet avec sync et stats."""
    logger.info("\n=== EnhancedServiceBus Demo ===")
    server_url = os.getenv("PUBSUB_SERVER_URL", "http://localhost:3000")
    max_workers = int(os.getenv("PUBSUB_THREAD_POOL_SIZE", "10"))

    bus = EnhancedServiceBus(
        server_url,
        "advanced-consumer",
        max_workers=max_workers,
        retry_policy={"max_attempts": 3, "initial_delay": 0.5}
    )

    def handle_event(event: SimpleEvent):
        logger.info(f"[ENHANCED] Reçu: {event.message}")
        return {"status": "processed"}

    bus.subscribe("advanced.event", handle_event)
    logger.info("EnhancedServiceBus: Idéal pour trading, avec sync et monitoring")


def show_comparison_rich():
    """Affiche une comparaison en utilisant la bibliothèque rich."""
    console = Console()
    console.print()  # Ajoute un saut de ligne

    # Création du tableau
    table = Table(
        title="📊 COMPARAISON DES DEUX VERSIONS",
        show_header=True,
        header_style="bold cyan",
        box=None  # Utilise un style de boîte simple
    )
    table.add_column("Fonctionnalité", style="dim", width=25)
    table.add_column("ServiceBusBase", justify="center")
    table.add_column("EnhancedServiceBus", justify="center")

    # Ajout des lignes par section
    table.add_row("Pub/Sub basique", "✅", "✅")
    table.add_row("Validation schémas", "✅", "✅")
    table.add_row("PubSubMessage", "✅", "✅")
    table.add_row("Thread-safe", "✅", "✅")
    table.add_section()
    table.add_row("Gestion d'état", "❌", "[bold green]✅[/bold green]")
    table.add_row("Publish & Wait", "❌", "[bold green]✅[/bold green]")
    table.add_row("Sync multi-événements", "❌", "[bold green]✅[/bold green]")
    table.add_row("Statistiques", "❌", "[bold green]✅[/bold green]")
    table.add_row("Retry policy", "❌", "[bold green]✅[/bold green]")
    table.add_row("ThreadPool", "❌", "[bold green]✅[/bold green]")
    table.add_row("Cleanup automatique", "❌", "[bold green]✅[/bold green]")
    table.add_section()
    table.add_row("Empreinte mémoire", "Légère", "[yellow]Moyenne[/yellow]")
    table.add_row("Complexité", "Simple", "[yellow]Avancée[/yellow]")
    table.add_row("Cas d'usage", "Applications simples", "[yellow]Trading, critique[/yellow]")

    console.print(table)

    # Affichage des recommandations dans un panneau stylisé
    recommendations_text = Text()
    recommendations_text.append("• ServiceBusBase: Parfait pour les applications simples avec pub/sub basique.\n")
    recommendations_text.append("• EnhancedServiceBus: Idéal pour le trading et les systèmes critiques.\n")
    recommendations_text.append("• Migration facile: EnhancedServiceBus hérite de ServiceBusBase.", style="italic")

    console.print(
        Panel(recommendations_text, title="💡 RECOMMANDATIONS", border_style="yellow", title_align="left")
    )


if __name__ == "__main__":
    demo_base_service_bus()
    demo_enhanced_service_bus()
    show_comparison_rich()  # On appelle la nouvelle fonction
