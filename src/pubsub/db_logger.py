import logging
import sqlite3
import threading
import time


class SQLiteHandler(logging.Handler):
    """
    Un gestionnaire de logs thread-safe qui écrit les enregistrements dans une base de données SQLite3.
    """

    def __init__(self, db_file: str, table_name: str = "logs"):
        """
        Initialise le gestionnaire.

        Args:
            db_file (str): Le chemin vers le fichier de la base de données SQLite.
            table_name (str): Le nom de la table pour stocker les logs.
        """
        super().__init__()
        self.db_file = db_file
        self.table_name = table_name
        self.lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        """Crée la table de logs si elle n'existe pas."""
        try:
            with self.lock:
                # check_same_thread=False est utile car la connexion peut être créée
                # par un thread différent de celui qui l'utilise.
                conn = sqlite3.connect(self.db_file, check_same_thread=False)
                cursor = conn.cursor()
                # Utiliser IF NOT EXISTS pour éviter les erreurs lors des exécutions suivantes
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created REAL,
                        asctime TEXT,
                        name TEXT,
                        levelname TEXT,
                        message TEXT,
                        pathname TEXT,
                        lineno INTEGER
                    )
                """)
                conn.commit()
                conn.close()
        except sqlite3.Error as e:
            # On ne peut pas utiliser le logger ici, car cela pourrait créer une boucle de récursion.
            # On écrit directement sur la sortie d'erreur standard.
            import sys
            print(f"Erreur lors de la création de la table SQLite pour le logging : {e}", file=sys.stderr)

    def emit(self, record: logging.LogRecord):
        """
        Sauvegarde un enregistrement de log dans la base de données.

        Args:
            record (logging.LogRecord): L'enregistrement de log à sauvegarder.
        """
        try:
            with self.lock:
                # Utiliser une nouvelle connexion pour chaque 'emit' garantit la sécurité entre threads.
                conn = sqlite3.connect(self.db_file, check_same_thread=False)
                cursor = conn.cursor()

                # Formater le timestamp pour lisibilité
                asctime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)) + f",{int(record.msecs):03d}"

                # Le message est formaté par le formateur du gestionnaire.
                msg = self.format(record)

                cursor.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        created, asctime, name, levelname, message, pathname, lineno
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.created,
                        asctime,
                        record.name,
                        record.levelname,
                        msg,
                        record.pathname,
                        record.lineno,
                    ),
                )
                conn.commit()
                conn.close()
        except sqlite3.Error as e:
            import sys
            print(f"Erreur lors de l'écriture du log dans la base de données SQLite : {e}", file=sys.stderr)

    def close(self):
        """Ferme le gestionnaire."""
        # Aucune connexion n'est gardée ouverte, donc il n'y a rien à faire.
        super().close()
