# Journal des modifications

Ce fichier retrace les évolutions notables de MyDomoticz, de la plus récente à la plus ancienne. Il décrit les changements du projet, sans détailler les opérations Git ou les statuts des Pull Requests.

## [Non publié]

### Ajouté
- Ouverture du tableau de bord dans un nouvel onglet lorsqu'il est lancé depuis le cadre Domoticz, avec un lien de secours si le navigateur bloque l'ouverture automatique.
- Mise en page autonome élargie pour exploiter toute la largeur disponible du navigateur.

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
