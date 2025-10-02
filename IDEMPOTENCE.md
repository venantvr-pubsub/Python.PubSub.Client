# Classes d'Idempotence

Ce document explique le fonctionnement des classes d'idempotence dans le projet PubSub Client.

## Vue d'ensemble

L'idempotence est un mécanisme qui garantit qu'un même message ne sera traité qu'une seule fois, même s'il est reçu plusieurs fois. Cela est essentiel dans les systèmes
distribués où des messages peuvent être dupliqués en raison de retransmissions, de problèmes réseau ou de reconnexions.

## Classes disponibles

### 1. `IdempotenceFilter`

**Fichier:** `src/pubsub/idempotence_filter.py:5`

Filtre d'idempotence simple basé sur les `message_id`.

#### Fonctionnement

- Maintient une liste FIFO (First In, First Out) des `message_id` déjà traités
- Utilise une `deque` avec taille maximale configurable (par défaut 1000)
- Lorsque la limite est atteinte, les anciens IDs sont automatiquement supprimés

#### Méthodes principales

- **`should_process(message_id)`**: Vérifie si un message doit être traité
    - Retourne `True` si le message est nouveau ou si `message_id` est `None`
    - Retourne `False` si le message a déjà été traité
    - Ajoute automatiquement le `message_id` à la liste si le message est nouveau

- **`reset()`**: Vide complètement la liste des IDs mémorisés

- **`__len__()`**: Retourne le nombre d'IDs actuellement mémorisés

#### Exemple d'utilisation

```python
from python_pubsub_client.idempotence_filter import IdempotenceFilter

# Créer un filtre avec 500 IDs maximum
filter = IdempotenceFilter(max_size=500)

# Vérifier si un message doit être traité
if filter.should_process("msg-123"):
    # Traiter le message
    process_message(data)
```

### 2. `IdempotencyTracker`

**Fichier:** `src/pubsub/idempotency_tracker.py:7`

Tracker d'idempotence avancé et thread-safe basé sur le hachage du contenu des événements.

#### Fonctionnement

- Calcule un hash SHA-256 du contenu complet de l'événement (pas seulement l'ID)
- Thread-safe grâce à l'utilisation de verrous (`threading.Lock`)
- Utilise également une `deque` FIFO avec taille maximale (par défaut 1000)
- Permet de détecter les doublons même si les messages n'ont pas d'ID

#### Méthodes principales

- **`is_duplicate(event_data)`**: Vérifie si un événement a déjà été traité
    - Calcule le hash de l'événement
    - Retourne `True` si le hash est déjà présent

- **`mark_processed(event_data)`**: Marque un événement comme traité
    - Ajoute le hash de l'événement à la liste

- **`process_once(event_data, handler)`**: Méthode de commodité
    - Exécute le handler uniquement si l'événement n'est pas un doublon
    - Marque automatiquement l'événement comme traité après exécution
    - Retourne le résultat du handler ou `None` si doublon

- **`clear()`**: Vide tous les événements trackés

- **`size()`**: Retourne le nombre d'événements actuellement trackés

#### Exemple d'utilisation

```python
from python_pubsub_client.idempotency_tracker import IdempotencyTracker

# Créer un tracker
tracker = IdempotencyTracker(maxlen=1000)

# Méthode 1: Vérification manuelle
event_data = {"type": "user_created", "user_id": 123}
if not tracker.is_duplicate(event_data):
    process_event(event_data)
    tracker.mark_processed(event_data)

# Méthode 2: Utilisation de process_once
result = tracker.process_once(event_data, lambda: process_event(event_data))
```

## Intégration dans PubSubClient

**Fichier:** `src/pubsub/client.py:49`

Le `PubSubClient` intègre l'idempotence via `IdempotenceFilter`:

```python
client = PubSubClient(
    url="http://localhost:5000",
    consumer="MyConsumer",
    topics=["topic1"],
    enable_idempotence=True,  # Active l'idempotence
    idempotence_max_size=1000  # Taille du filtre
)
```

Lorsqu'activé:

- Les messages dupliqués sont automatiquement détectés et ignorés (ligne 152)
- Un log avec fond jaune est affiché pour chaque message dupliqué ignoré (ligne 153-156)
- Le handler n'est jamais appelé pour les doublons

## Différences entre les deux classes

| Critère               | IdempotenceFilter         | IdempotencyTracker                       |
|-----------------------|---------------------------|------------------------------------------|
| **Base de détection** | `message_id` uniquement   | Hash du contenu complet                  |
| **Thread-safety**     | Non (simple)              | Oui (avec locks)                         |
| **Cas d'usage**       | Messages avec IDs uniques | Événements sans ID ou contenu arbitraire |
| **Flexibilité**       | Simple et direct          | Plus robuste et flexible                 |
| **Intégration**       | Utilisé dans PubSubClient | Usage générique standalone               |

## Choix de la classe appropriée

- **Utilisez `IdempotenceFilter`** si:
    - Vos messages ont des IDs uniques
    - Vous utilisez le PubSubClient standard
    - Vous voulez une solution simple et légère

- **Utilisez `IdempotencyTracker`** si:
    - Vous devez tracker des événements sans IDs
    - Vous avez besoin de thread-safety explicite
    - Vous voulez détecter les doublons basés sur le contenu complet
    - Vous développez un worker ou service personnalisé

## Notes importantes

- Les deux classes utilisent une taille maximale: les anciens enregistrements sont automatiquement supprimés
- La détection de doublons n'est effective que pour les messages dans la fenêtre de mémorisation
- Pour une idempotence persistante (après redémarrage), il faudrait utiliser un stockage externe (Redis, base de données, etc.)
