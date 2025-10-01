// Attend que le DOM soit entièrement chargé avant d'exécuter le script
document.addEventListener('DOMContentLoaded', function () {
    // Intervalle de rafraîchissement en millisecondes
    const POLLING_INTERVAL = 5000; // 5 secondes
    // Seuil d'inactivité avant de passer l'affichage des secondes aux minutes
    const INACTIVITY_THRESHOLD_SECONDS = 60;

    // Récupération des éléments du DOM
    const tableBody = document.getElementById('status-table-body');
    const updateTimeSpan = document.getElementById('update-time');
    const errorContainer = document.getElementById('error-container');
    const statusIndicator = document.getElementById('status-indicator');
    let pollTimer; // Variable pour stocker le timer du polling

    /**
     * Formate un timestamp Unix en une chaîne de caractères "HH:MM:SS (X temps écoulé)".
     * @param {number} unixTimestamp - Le timestamp en secondes.
     * @returns {string} La chaîne de caractères formatée.
     */
    function formatTimeAgo(unixTimestamp) {
        if (!unixTimestamp) return "N/A";
        const now = new Date();
        const lastActivity = new Date(unixTimestamp * 1000);
        const deltaSeconds = Math.round((now - lastActivity) / 1000);

        const timeStr = lastActivity.toLocaleTimeString();

        // Affiche les minutes si l'inactivité dépasse le seuil
        if (deltaSeconds < INACTIVITY_THRESHOLD_SECONDS) {
            return `${timeStr} (${deltaSeconds}s ago)`;
        } else {
            const deltaMinutes = Math.round(deltaSeconds / 60);
            return `${timeStr} (${deltaMinutes} min ago)`;
        }
    }

    /**
     * Récupère les données de statut depuis le serveur et met à jour la page.
     */
    async function fetchStatus() {
        // Annule le timer précédent pour éviter des appels qui se chevauchent
        clearTimeout(pollTimer);

        try {
            const response = await fetch('/status.json');
            if (!response.ok) {
                // Gère les erreurs HTTP (ex: 404, 500)
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            // Valide le format des données reçues. Si invalide, le rafraîchissement s'arrête.
            if (!data || !Array.isArray(data.services)) {
                throw new Error("Invalid data format received.");
            }

            // Si la requête réussit, on cache le message d'erreur et on met l'indicateur au vert
            errorContainer.classList.add('d-none');
            statusIndicator.classList.remove('text-danger');
            statusIndicator.classList.add('text-success');

            // Mise à jour de l'heure de la dernière mise à jour
            updateTimeSpan.textContent = new Date(data.update_time).toLocaleTimeString();
            tableBody.innerHTML = ''; // Vide le contenu actuel du tableau

            // Boucle sur chaque service pour construire le tableau
            data.services.forEach(service => {
                // Crée la ligne principale avec les informations du service
                const mainRow = document.createElement('tr');
                const statusBadge = service.is_alive
                    ? '<span class="badge bg-success">Alive</span>'
                    : '<span class="badge bg-danger">Stopped</span>';

                mainRow.innerHTML = `
                    <td>${service.name || 'N/A'}</td>
                    <td>${statusBadge}</td>
                    <td>${service.tasks_in_queue || '0'}</td>
                    <td>${formatTimeAgo(service.last_activity_time)}</td>
                `;

                // Crée une seconde ligne dédiée aux logs, qui s'étend sur toute la largeur
                const logsRow = document.createElement('tr');
                const logsCell = document.createElement('td');
                logsCell.colSpan = 4; // Fait en sorte que la cellule prenne 4 colonnes

                let logsHtml = '<div class="logs-container">';
                if (service.recent_logs && service.recent_logs.length > 0) {
                    logsHtml += '<ul>';
                    service.recent_logs.forEach(log => {
                        logsHtml += `<li>${log}</li>`;
                    });
                    logsHtml += '</ul>';
                } else {
                    logsHtml += '<p class="no-logs-msg"><i>No internal logs.</i></p>';
                }
                logsHtml += '</div>';

                logsCell.innerHTML = logsHtml;
                logsRow.appendChild(logsCell);

                // Ajoute les deux lignes au corps du tableau
                tableBody.appendChild(mainRow);
                tableBody.appendChild(logsRow);
            });

        } catch (error) {
            console.error('Failed to fetch status:', error);
            // Affiche le conteneur d'erreur et change l'indicateur en rouge
            errorContainer.classList.remove('d-none');
            statusIndicator.classList.remove('text-success');
            statusIndicator.classList.add('text-danger');
            // Arrête le polling en cas d'erreur pour ne pas surcharger le réseau
            return;
        }

        // Si tout s'est bien passé, on planifie le prochain appel
        pollTimer = setTimeout(fetchStatus, POLLING_INTERVAL);
    }

    // Lance le premier appel pour initialiser la page
    fetchStatus();
});
