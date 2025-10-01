from collections import deque
from typing import Optional


class IdempotenceFilter:
    """
    Filtre d'idempotence qui maintient une liste FIFO des message_id déjà traités.

    Si un message avec un message_id déjà présent dans la liste est reçu,
    il sera considéré comme un doublon et ignoré.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialise le filtre d'idempotence.

        :param max_size: Nombre maximum de message_id à conserver (défaut: 1000)
        """
        self.max_size = max_size
        self._seen_ids: deque[str] = deque(maxlen=max_size)

    def should_process(self, message_id: Optional[str]) -> bool:
        """
        Vérifie si un message doit être traité en fonction de son message_id.

        :param message_id: L'identifiant unique du message
        :return: True si le message doit être traité, False s'il s'agit d'un doublon
        """
        if message_id is None:
            # Si pas de message_id, on traite le message
            return True

        if message_id in self._seen_ids:
            # Message déjà traité, on le ignore
            return False

        # Nouveau message, on l'ajoute à la liste et on le traite
        self._seen_ids.append(message_id)
        return True

    def reset(self) -> None:
        """Réinitialise le filtre en vidant la liste des message_id."""
        self._seen_ids.clear()

    def __len__(self) -> int:
        """Retourne le nombre de message_id actuellement mémorisés."""
        return len(self._seen_ids)
