"""
Exemple d'utilisation du ServiceBus amélioré pour un bot de trading.
Utilise PubSubMessage comme conteneur d'événements avec synchronisation.
"""
import logging
import os
import time
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from typing import List

# Note: Using EnhancedServiceBus for advanced features like publish_and_wait
from pubsub import EnhancedServiceBus as ServiceBus

# Configuration du logging pour cet exemple
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class OrderRequest:
    symbol: str
    quantity: float
    price: float
    side: str  # "buy" ou "sell"


@dataclass
class OrderConfirmation:
    order_id: str
    symbol: str
    status: str
    filled_qty: float
    avg_price: float
    timestamp: float


@dataclass
class MarketDataRequest:
    symbol: str


@dataclass
class MarketData:
    symbol: str
    bid: float
    ask: float
    volume: float
    timestamp: float


class TradingBot:
    """Bot de trading utilisant le ServiceBus avec attente synchrone."""

    def __init__(self, service_bus: ServiceBus):
        self.service_bus = service_bus
        self.positions = {}

    def execute_trade_with_confirmation(self, symbol: str, quantity: float, max_price: float) -> bool:
        """
        Exécute un trade et attend la confirmation.
        """
        try:
            # 1. Demander les données de marché et attendre
            logger.info(f"[BOT] Demande des données de marché pour {symbol}")
            market_future = self.service_bus.publish_and_wait(
                "market.data.request",
                {"symbol": symbol},
                producer_name="trading-bot",
                timeout=5.0
            )

            # Attendre les données : wait() retourne directement le dict de réponse
            market_data: dict = market_future.wait()
            logger.info(f"[BOT] Données reçues: bid={market_data.get('bid')}, ask={market_data.get('ask')}")

            # 2. Vérifier le prix
            ask_price = market_data.get('ask', 0)
            if not ask_price or ask_price > max_price:
                logger.warning(f"[BOT] Prix trop élevé ou invalide: {ask_price} > {max_price}")
                return False

            # 3. Créer et envoyer l'ordre
            order = OrderRequest(
                symbol=symbol,
                quantity=quantity,
                price=ask_price * 1.001,  # Légèrement au-dessus de l'ask
                side="buy"
            )

            logger.info(f"[BOT] Envoi de l'ordre: {quantity} {symbol} @ {order.price}")
            order_future = self.service_bus.publish_and_wait(
                "order.submit",
                order,
                producer_name="trading-bot",
                timeout=10.0
            )

            # 4. Attendre la confirmation : wait() retourne directement l'objet OrderConfirmation
            confirmation: OrderConfirmation = order_future.wait()

            if confirmation.status == "filled":
                logger.info(f"[BOT] ✅ Ordre exécuté: {confirmation.filled_qty} @ {confirmation.avg_price}")
                self.positions[symbol] = self.positions.get(symbol, 0) + confirmation.filled_qty
                return True
            else:
                logger.warning(f"[BOT] ❌ Ordre non rempli: {confirmation.status}")
                return False

        except TimeoutError as e:
            logger.error(f"[BOT] Timeout: {e}")
            return False
        except Exception as e:
            logger.error(f"[BOT] Erreur: {e}", exc_info=True)
            return False

    def execute_batch_orders(self, orders: List[OrderRequest]) -> dict:
        """
        Exécute plusieurs ordres en parallèle et attend toutes les confirmations.
        """
        futures = []
        for order in orders:
            logger.info(f"[BOT] Envoi ordre batch: {order.quantity} {order.symbol}")
            future = self.service_bus.publish_and_wait(
                "order.submit",
                order,
                producer_name="trading-bot",
                timeout=15.0
            )
            futures.append(future)

        logger.info(f"[BOT] Attente de {len(futures)} confirmations...")
        results = self.service_bus.wait_for_events(futures, timeout=20.0)

        summary = {"success": 0, "failed": 0, "orders": {}}
        for event_id, result in results.items():
            if isinstance(result, Exception):
                logger.error(f"[BOT] Ordre {event_id} échoué: {result}")
                summary["failed"] += 1
            else:
                # result est maintenant directement l'objet OrderConfirmation
                logger.info(f"[BOT] Ordre {event_id} confirmé: {result.status}")
                summary["success"] += 1
                summary["orders"][event_id] = result
        return summary


# Handlers simulés pour les réponses
def market_data_handler(request: MarketDataRequest) -> dict:
    """Simule un fournisseur de données de marché."""
    logger.info(f"[MARKET] Requête reçue pour {request.symbol}")
    return {
        "symbol": request.symbol, "bid": 50000.0, "ask": 50010.0,
        "volume": 1234.56, "timestamp": time.time()
    }


def order_handler(order: OrderRequest) -> OrderConfirmation:
    """Simule un système d'exécution d'ordres."""
    logger.info(f"[BROKER] Ordre reçu: {order.quantity} {order.symbol} @ {order.price}")
    return OrderConfirmation(
        order_id=f"ORD-{int(time.time())}", symbol=order.symbol, status="filled",
        filled_qty=order.quantity, avg_price=order.price, timestamp=time.time()
    )


def main():
    """Démonstration du bot de trading."""
    server_url = os.getenv("PUBSUB_SERVER_URL", "http://localhost:3000")
    consumer_name = os.getenv("PUBSUB_CONSUMER_NAME", "trading-bot")
    max_workers = int(os.getenv("PUBSUB_THREAD_POOL_SIZE", "10"))

    service_bus = ServiceBus(url=server_url, consumer_name=consumer_name, max_workers=max_workers)

    service_bus.subscribe("market.data.request", market_data_handler)
    service_bus.subscribe("order.submit", order_handler)

    service_bus.start()
    if not service_bus.wait_for_start(timeout=10):
        logger.error("ServiceBus failed to start")
        return

    bot = TradingBot(service_bus)
    try:
        logger.info("\n=== TEST 1: Trade simple ===")
        success = bot.execute_trade_with_confirmation("BTCUSDT", 0.001, 60000)
        logger.info(f"Résultat: {'✅ Succès' if success else '❌ Échec'}")

        logger.info("\n=== TEST 2: Ordres parallèles ===")
        batch_orders = [
            OrderRequest("ETHUSDT", 0.01, 3000.0, "buy"),
            OrderRequest("BNBUSDT", 0.1, 400.0, "buy"),
            OrderRequest("ADAUSDT", 10.0, 0.6, "buy")
        ]
        results = bot.execute_batch_orders(batch_orders)
        logger.info(f"Résultats batch: {results['success']} succès, {results['failed']} échecs")
        logger.info(f"\n=== Positions finales: {bot.positions} ===")
        time.sleep(2)
    finally:
        logger.info("\n=== Arrêt du bot ===")
        if service_bus.stop(timeout=10):
            logger.info("ServiceBus arrêté proprement")
        stats = service_bus.get_stats()
        logger.info(f"Statistiques finales: {stats}")

if __name__ == "__main__":
    main()