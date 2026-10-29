# Journal des modifications

Ce fichier retrace les évolutions notables de MyDomoticz, de la plus récente à la plus ancienne. Il décrit les changements du projet, sans détailler les opérations Git ou les statuts des Pull Requests.

## [Non publié]

### Ajouté
- Lecture dynamique des IDX depuis la première colonne du classeur `IDX2.xlsx` ou `IDX2.XLS`, chargé au démarrage de la page.
- Séparation entre une page d'entrée Domoticz et le tableau de bord autonome, installé à côté dans `www/templates`.
- Ouverture automatique du tableau de bord dans un nouvel onglet, avec un lien de secours si le navigateur bloque l'ouverture.
- Mise en page autonome utilisant toute la largeur disponible du navigateur.

### Amélioré
- Ajout d'un paramètre d'URL variable à chaque ouverture du tableau de bord pour éviter la réutilisation d'une ancienne page HTML en cache.
- Ajout d’un paramètre variable à l’URL du classeur Excel, en complément de `cache: "no-store"`, pour éviter la réutilisation d’une ancienne copie de `IDX2.xlsx`.
- Mise en forme du HTML, du CSS et du JavaScript pour faciliter la lecture et la maintenance.
- Suppression de la liste d’IDX codée en dur au profit du classeur Excel.

### Documentation
- Ajout du présent journal pour suivre les évolutions du projet au fil des versions.


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
