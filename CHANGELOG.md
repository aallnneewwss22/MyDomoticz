# Journal des modifications

## [Non publié]

### Ajouté
- Ajout d’une case à cocher « Caméra montée tête en bas » dans le panneau PTZ ; il inverse simultanément les deux axes du joystick et mémorise le réglage individuellement par caméra.
- Création de `maison-dashboard-v84.html` et mise à jour du lanceur.


### Modifié
- Le bouton du header qui replie toutes les cartes d'historique en mode valeur déclenche également l'arrêt global de tous les flux vidéo actifs de la page via le service go2rtc ; les flux déjà arrêtés ne reçoivent pas de commande supplémentaire.
- Le résultat de l'arrêt global (flux arrêtés, déjà arrêtés et éventuelles erreurs) est affiché dans la barre d'état.
- Création de `maison-dashboard-v83.html` et mise à jour du lanceur.

### Modifié
- Suppression complète de l’arrêt local des flux caméra : retrait du bouton, de son traitement et de la préférence locale associée. L’arrêt global via go2rtc et le redémarrage restent disponibles.
- Désactivation du bouton « Pilotage PTZ » lorsque le flux est arrêté ; vérification supplémentaire de l’état réel du flux côté service juste avant l’ouverture du panneau.
- Allègement du panneau PTZ : retrait des quatre libellés de section/champ demandés, conservation des commandes et ajout d’un nom accessible au sélecteur de positions prédéfinies.
- Harmonisation des espacements verticaux des commandes PTZ avec une grille régulière.
- Création de `maison-dashboard-v82.html` et mise à jour du lanceur.

### Simplifié
- Suppression du bouton STOP ONVIF et de son endpoint de commande, qui n'apportait pas d'effet utile sur la caméra testée. La pause locale du joystick est conservée pour interrompre l'émission de nouvelles impulsions `RelativeMove` lorsqu'on relâche le joystick ou quitte le panneau.
- Suppression de la création de positions prédéfinies : retrait du bouton « Mémoriser », du champ de nom et de leur traitement dans le navigateur et le service Python. La liste et le rappel des positions déjà enregistrées sur la caméra restent disponibles.
- Création de `maison-dashboard-v81.html` et mise à jour du lanceur.
- Suppression du test unitaire dédié à l'ancienne commande ONVIF `Stop` ; les tests de mouvement relatif et de rappel des positions restent en place.

### Modifié
- Remplacement du coefficient de déplacement fixe par deux gains `GainPTZ` configurables, ainsi que deux vitesses `VitesseONVIF` indépendantes pour les profils PC et Mobile.
- Suppression du slider de vitesse du panneau PTZ ; les quatre réglages sont désormais regroupés dans deux groupbox des paramètres et mémorisés dans le `localStorage` de chaque navigateur.
- Détection automatique du profil PC/Mobile selon le périphérique de pointage principal ; les valeurs initiales conservent le comportement précédent (gain 0,08 et vitesse ONVIF 0,50).
- Le navigateur applique désormais le gain aux composantes du joystick ; le service ONVIF transmet directement les translations relatives normalisées.

### Modifié
- Inversion des deux axes du joystick PTZ : gauche/droite et haut/bas correspondent désormais aux sens physiques attendus.

### Ajouté
- Déplacements physiques PTZ par petits pas `RelativeMove` successifs ; abandon de `ContinuousMove`, qui échoue avec la Tapo C200 testée.
- Zoom logiciel du lecteur dans le panneau PTZ (1× à 3×), avec indicateur et réinitialisation ; aucune commande de zoom ONVIF n’est envoyée.
- Encapsulation temporaire du lecteur vidéo dans une fenêtre de recadrage ; le lecteur retrouve son emplacement et son affichage d’origine à la fermeture du panneau.
- Création de `maison-dashboard-v80.html` et mise à jour du lanceur.
- Panneau de pilotage PTZ par caméra, avec vidéo agrandie, joystick tactile/souris NippleJS, vitesse réglable, zoom continu, arrêt explicite et gestion des positions prédéfinies ONVIF.
- API ONVIF dans le service auxiliaire Python avec configuration indépendante par caméra ; les identifiants sont conservés uniquement dans le registre privé du Raspberry Pi.
- Commande Audio activé / Audio coupé sur chaque carte caméra, avec un état partagé entre tous les navigateurs et conservé sur le Raspberry Pi.
- Le service auxiliaire bascule l'unique source go2rtc entre le RTSP original (audio activé) et la variante vidéo seule avec #media=video (audio coupé), en recréant le flux actif.
- Persistance de la préférence audio dans le registre privé des caméras ; un choix fait pendant un arrêt global est appliqué au prochain démarrage.
- Création de maison-dashboard-v77.html ; les lecteurs vidéo restent préservés pendant les actualisations ordinaires.

### Compatibilité
- Les caméras déjà enregistrées conservent leur comportement audio actuel après la mise à jour ; l'audio reste activé par défaut jusqu'à une action explicite.

### Corrigé
- Correction de l'installation ONVIF : récupération de l'archive source `onvif-zeep 0.2.12`, vérification de son empreinte SHA-256 et installation de l'ensemble des ressources WSDL dans `vendor/wsdl`.

Ce fichier retrace les évolutions notables de MyDomoticz, de la plus récente à la plus ancienne. Il décrit les changements du projet, sans détailler les opérations Git ou les statuts des Pull Requests.

## [Non publié]

### Ajouté
- Nouveau type de ligne « caméra » dans les classeurs IDX : la colonne A contient le nom du flux go2rtc, la colonne B son libellé et la colonne C le marqueur « caméra ».
- Cartes vidéo intégrées utilisant le lecteur universel go2rtc (stream.html) avec sélection automatique WebRTC/MSE/HLS.
- Adresse du serveur go2rtc configurable dans les paramètres du tableau de bord, mémorisée dans le navigateur ; valeur par défaut : même hôte que Domoticz, port 1984.
- Documentation et exemple de configuration go2rtc sans identifiants réels. Les secrets RTSP restent dans la configuration locale de go2rtc, jamais dans Excel.
- Création de maison-dashboard-v73.html.

### Modifié
- Le chargement des classeurs accepte désormais les noms de flux caméra en première colonne, en plus des IDX numériques Domoticz.


### Ajouté
- Personnalisation du nom affiché de chaque page depuis les paramètres : sélection du fichier IDX, modification du libellé, validation avec `+` et réinitialisation au nom technique.
- Mémorisation des correspondances dans le navigateur, indépendamment du nom réel du classeur.
- Création de `maison-dashboard-v69.html`.


### Modifié
- Découverte automatique des pages au chargement : le dashboard recherche les classeurs `IDX1.xlsx` à `IDX9.xlsx` dans son propre répertoire et construit le menu dans l'ordre numérique.
- Le nom affiché de chaque page est le nom du classeur sans extension ; les extensions `.xlsx` et `.XLSX` sont acceptées.
- Suppression des déclarations de pages codées en dur : ajouter ou retirer un classeur suffit à modifier les pages disponibles.
- Création de `maison-dashboard-v68.html`.

### Ajouté
- Préparation du mode multi-pages avec un menu déroulant dans le header : **Maison** charge `IDX2.xlsx` et **Page 2** charge `IDX1.xlsx`.
- Sélection de page mémorisée dans le navigateur ; chaque page recharge indépendamment ses équipements, historiques et actions depuis son propre classeur Excel.
- Protection contre les réponses asynchrones tardives lors d'un changement de page, afin d'éviter de mélanger les équipements de deux configurations.
- Création de `maison-dashboard-v67.html`.


### Ajouté
- Prise en charge des équipements `switchV` (état binaire en lecture seule) et `switchT` (bouton ON/OFF commandable) déclarés en troisième colonne de `IDX2.xlsx`.
- Lecture des états binaires depuis les données des équipements Domoticz ; après une commande `switchT`, relecture de l'état pour confirmer la mise à jour.
- Colonne E facultative : nom officiel d'une icône Lucide en `kebab-case` (par exemple `lightbulb`, `door-open`, `car-front`, `footprints`, `droplets` ou `thermometer`) ; une valeur vide utilise une icône automatique et un nom inconnu retombe sur `house`.
- Chargement de la bibliothèque Lucide et rendu réel des SVG sur les cartes classiques, `switchV` et `switchT` ; suppression de la table de conversion en emojis.
- Boutons `switchT` arrondis, colorés et légèrement en relief.
- Création de `maison-dashboard-v66.html`.

### Ajouté
- Reconnaissance du marqueur `counter` en troisième colonne de `IDX2.xlsx`, avec affichage de la valeur et consultation de l'historique comme pour `temp`.
- Utilisation de l'API Domoticz `type=command&param=graph&sensor=counter` pour les historiques de compteurs ; les équipements `temp` conservent `sensor=temp`.
- Activation de `method=1` pour l'historique journalier des compteurs afin de récupérer les mesures de consommation instantanée ; les périodes longues restent en mode agrégé.
- Lecture robuste des champs `v1`, `v2` et `v3` lorsqu'ils sont présents et non vides, avec cumul des phases disponibles ; recours à `v` pour les compteurs qui ne fournissent pas ces champs.
- Création de `maison-dashboard-v27.html`.

### Amélioré
- Resserrement supplémentaire de l'espace entre les dates de l'axe horizontal et le séparateur des statistiques : marge portée de -6 à -12 px, soit 6 px supplémentaires gagnés sur la hauteur de la carte.
- Création de `maison-dashboard-v21.html`.

### Amélioré
- Réduction de l'espace entre les libellés de dates de l'axe horizontal et le séparateur des statistiques dans les cartes d'historique ; la hauteur totale des cartes diminue de 6 px sans modifier le tracé.
- Création de `maison-dashboard-v20.html`.

### Amélioré
- Remplacement des libellés du header par des icônes : actualisation, paramètres et actions. Les boutons conservent une taille uniforme et disposent d'intitulés accessibles et d'infobulles.
- Création de `maison-dashboard-v19.html`.


### Amélioré
- Taille des icônes réduite sur les cartes d'équipement sans courbe (34 px au lieu de 42 px).
- Création de `maison-dashboard-v18.html`.


### Amélioré
- Cartes d'équipement classiques harmonisées avec les cartes d'historique : marges intérieures et interlignes resserrés, bordure renforcée.
- Création de `maison-dashboard-v17.html`.


### Amélioré
- Marges supérieures réduites dans les cartes d'historique et espace sous les dates de l'axe horizontal diminué.
- Création de `maison-dashboard-v16.html`.


### Amélioré
- Interlignes resserrés entre le nom, la valeur et le libellé des cartes d'historique.
- Création de `maison-dashboard-v15.html`.


### Amélioré
- Libellés des boutons de période raccourcis sur les cartes d'historique : `24 H`, `7 J`, `30 J` et `1 A`.
- Création de `maison-dashboard-v14.html`.


### Amélioré
- Ajout d'un séparateur horizontal au-dessus des statistiques des cartes d'historique.
- Réduction de l'espace entre l'axe horizontal et ses libellés de dates.
- Création de `maison-dashboard-v13.html`.

### Amélioré
- Contraste renforcé pour tous les boutons : bordures plus épaisses, fonds et textes différenciés selon le thème, états de survol, de sélection, de focus et de désactivation mieux marqués.
- Création de `maison-dashboard-v12.html`.

### Ajouté
- Les lignes dont la troisième colonne de `IDX2.xlsx` / `IDX2.XLS` contient `historique` affichent une carte intégrée avec température actuelle, courbe et statistiques min./moy./max.
- Choix de période : 24 heures, 7 jours, 30 jours ou 1 an, via l'API historique Domoticz.
- Reconnaissance de `historique` insensible à la casse et aux espaces superflus.
- Création de `maison-dashboard-v11.html`.

### Modifié
- La troisième colonne de `IDX2.xlsx` / `IDX2.XLS` utilise désormais des marqueurs explicites : `main` affiche l'équipement dans la grille et `VirtualSensorSlot` crée un bouton dans « Action... ».
- Les lignes entièrement vides conservent leur rôle de séparateurs de rangée ; les cellules contenant une autre valeur ne sont pas traitées.
- Création de `maison-dashboard-v10.html` pour cette évolution.

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


