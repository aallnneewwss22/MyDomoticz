# Journal des modifications

Ce fichier retrace les évolutions notables de MyDomoticz, de la plus récente à la plus ancienne. Il décrit les changements du projet, sans détailler les opérations Git ou les statuts des Pull Requests.

## [Non publié]

### Modifié
- Les lignes entièrement vides de `IDX2.xlsx` / `IDX2.XLS` créent un début de nouvelle rangée dans la grille des équipements et dans la boîte « Action... ».
- Création de `maison-dashboard-v9.html` pour cette évolution.

### Modifié
- Les équipements de la fenêtre principale et les boutons de la boîte « Action... » suivent explicitement l'ordre des lignes du classeur `IDX2.xlsx` / `IDX2.XLS`.
- Création de `maison-dashboard-v8.html` pour cette évolution.

### Ajouté
- Choix du thème graphique depuis la boîte de dialogue « Paramètres... » : Automatique, Classique clair, Sombre, Nature et Bleu nuit.
- Mémorisation du thème choisi dans le navigateur ; le mode Automatique suit la préférence clair/sombre du système.
- Création de `maison-dashboard-v7.html` pour cette évolution.


### Ajouté
- Bouton « Action... » ouvrant une boîte de dialogue alimentée par les lignes de `IDX2.xlsx` / `IDX2.XLS` dont la troisième colonne est renseignée.
- Chaque bouton reprend le libellé de la deuxième colonne et envoie à Domoticz une commande d'activation (`switchcmd=On`) pour l'IDX de la première colonne.
- Création de `maison-dashboard-v6.html` pour cette évolution.

### Modifié
- Le tableau de bord distingue maintenant les lignes d'affichage (troisième colonne vide) des lignes d'action (troisième colonne renseignée).
- Les équipements associés à une ligne dont la troisième colonne de `IDX2.xlsx` / `IDX2.XLS` est renseignée ne sont plus affichés.
- Création de `maison-dashboard-v5.html` pour cette évolution.


### Ajouté
- Bouton « Paramètres... » permettant de régler la période d'actualisation automatique de 5 secondes à 1 heure (30 secondes par défaut), avec mémorisation du réglage dans le navigateur.
- Création de `maison-dashboard-v4.html` pour cette évolution.

### Modifié
- Simplification du tableau de bord : le header ne conserve que le bouton « Actualiser », la section « Résumé » et le texte de version/fonctionnement en bas de page sont supprimés.

### Ajouté
- Lecture dynamique des IDX depuis la première colonne du classeur `IDX2.xlsx` ou `IDX2.XLS`, chargé au démarrage de la page.
- Séparation entre une page d'entrée Domoticz et le tableau de bord autonome, installé à côté dans `www/templates`.
- Ouverture automatique du tableau de bord dans un nouvel onglet, avec un lien de secours si le navigateur bloque l'ouverture.
- Mise en page autonome utilisant toute la largeur disponible du navigateur.
- Règle de versionnement documentée : chaque évolution du tableau de bord autonome crée un nouveau fichier `maison-dashboard-vN.html`, avec un numéro supérieur au précédent.
- Génération automatique par GitHub Actions d'un ZIP de déploiement contenant le lanceur, le tableau de bord versionné actif et un fichier d'instructions, pour les Pull Requests qui modifient le tableau de bord.

### Amélioré
- Utilisation de `maison-dashboard-v2.html` pour contourner les caches qui ignorent les paramètres de requête dans l'URL du tableau de bord.
- Ajout d'un paramètre d'URL variable à chaque ouverture du tableau de bord pour éviter la réutilisation d'une ancienne page HTML en cache.
- Ajout d’un paramètre variable à l’URL du classeur Excel, en complément de `cache: "no-store"`, pour éviter la réutilisation d’une ancienne copie de `IDX2.xlsx`.
- Mise en forme du HTML, du CSS et du JavaScript pour faciliter la lecture et la maintenance.
- Suppression de la liste d’IDX codée en dur au profit du classeur Excel.

### Documentation
- Le README décrit la procédure d'incrémentation, la mise à jour du lanceur, la conservation des anciennes versions, les fichiers à déployer ensemble et la récupération de l'artefact ZIP généré par GitHub Actions.


## [1.0.0] — 2026-10-29

### Ajouté
- Première page de tableau de bord Domoticz responsive pour PC, tablette et smartphone.
- Affichage des équipements avec recherche et filtre par catégorie.
- Actualisation automatique toutes les 30 secondes et indicateur de connexion.
- Consultation en lecture seule : aucun ordre n'est envoyé aux équipements.
- Documentation d'installation et de gestion des versions dans le README.
- Notes sur l'exploration de la base SQLite Domoticz.

### Sécurité
- Ajout de règles d'exclusion pour éviter de versionner les bases de données locales, secrets et fichiers temporaires.

### À valider
- Compatibilité des endpoints de l'API JSON avec la version de Domoticz installée sur le Raspberry Pi.
- Fonctionnement de la page dans l'interface Domoticz réelle.


