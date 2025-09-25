"""
Module ServiceBus avec architecture modulaire.

Organisation:
- ServiceBusBase: Version légère avec fonctionnalités essentielles
- EnhancedServiceBus: Version complète avec gestion d'état, stats et synchronisation

Pour la rétrocompatibilité, 'ServiceBus' est un alias vers ServiceBusBase.
"""

from .enhanced_service_bus import (
    EnhancedServiceBus,
    ServiceBusState,
    EventFuture,
    EventWaitManager
)
from .service_bus_base import ServiceBusBase

# Alias pour la rétrocompatibilité
ServiceBus = ServiceBusBase

__all__ = [
    'ServiceBus',  # Alias pour compatibilité
    'ServiceBusBase',  # Version de base
    'EnhancedServiceBus',  # Version avec fonctionnalités avancées
    'ServiceBusState',  # Enum des états
    'EventFuture',  # Future pour synchronisation
    'EventWaitManager'  # Gestionnaire d'événements
]
