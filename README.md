# MyDomoticz

Pages web personnalisées pour Domoticz, développées progressivement et versionnées avec Git.

## Tableau de bord — version courante v112

Le tableau de bord est actuellement en version **v112**. Les fichiers actifs sont `dashboard/maison-v112.html` (lanceur) et `dashboard/maison-dashboard-v112.html` (page autonome). Les anciennes versions, dont le couple historique `maison.html` / `maison-dashboard-v110.html`, sont conservées dans le dépôt.

Fonctions du tableau de bord :

- interface responsive pour PC, tablette et smartphone ;
- boîte de dialogue Paramètres avec contenu défilant et boutons Annuler/Enregistrer toujours visibles ;
- choix des intitulés de toutes les cartes entre **Long Name** (colonne B, par défaut) et **Short Names** (colonne G), mémorisé dans le navigateur et inclus dans les sauvegardes de paramètres ;
- sauvegarde des paramètres sur le Raspberry Pi : export JSON versionné et import complet, jeton caméra inclus ; fichiers protégés par permissions Linux restrictives et API authentifiée du service go2rtc-control ;
- sauvegarde indépendante de toutes les caméras sur le Raspberry Pi : sources RTSP, paramètres ONVIF et identifiants, audio/vidéo, profils locaux, profil préféré et orientation PTZ ; aperçu sans révélation des secrets et restauration atomique protégée contre les sessions de transcodage actives ; bibliothèque commune de profils et paramètres généraux exclus ;
- récupération des sauvegardes après effacement complet du navigateur grâce à une clé de récupération indépendante, avec session temporaire en lecture seule ;
- gestion des profils vidéo indépendants par caméra ; le lecteur applique le profil préféré et gère automatiquement l'acquisition, le heartbeat et la libération des sessions de transcodage ;
- bibliothèque commune de profils vidéo sur le Raspberry Pi : sauver un profil personnalisé, le charger dans une autre caméra ou le supprimer de la bibliothèque, sans manipulation de fichiers sur le PC ; les profils déjà copiés dans les caméras restent indépendants ;
- récupération indépendante du profil vidéo préféré à l'ouverture de chaque carte, même lorsque le lecteur reste arrêté ; en cas d'indisponibilité de l'API, affichage explicite « Profil vidéo : indisponible » ;
- en cas d'échec du démarrage vidéo, affichage d'un bandeau rouge avec le détail de l'erreur et un bouton « Réessayer » ; aucune relance automatique ; le passage en arrêt global efface l'alerte et réinitialise l'état d'échec ;
- cartes vidéo intégrées pour les lignes marquées caméra ; le lecteur passe par la passerelle média authentifiée du service de contrôle, sans accès navigateur direct à l'API go2rtc ; WebRTC est privilégié avec repli MSE/HLS ;
- le bouton de réduction des courbes du header replie les historiques en mode valeur et arrête également tous les flux vidéo actifs de la page ;
- panneau de pilotage PTZ par caméra : joystick tactile/souris avec déplacements relatifs ONVIF successifs et case à cocher permettant l’inversion des deux axes pour une caméra montée tête en bas, vitesse réglable, zoom logiciel de l’image (1× à 3×) et positions prédéfinies ONVIF ;
- consultation en lecture seule des équipements Domoticz ;
- affichage des équipements dont la troisième colonne du classeur associé à la page sélectionnée contient un type reconnu, dans le même ordre que les lignes du classeur ;
- cartes d'historique de température pour les lignes dont la troisième colonne contient `historique` (sans distinction de casse ni d'espaces superflus), avec périodes 24 heures, 7 jours, 30 jours et 1 an ;
- double clic sur une carte d'historique pour ouvrir le graphique agrandi, puis triple clic directement sur la courbe pour passer en plein écran ; la fermeture tactile du panneau quitte également correctement le plein écran natif ;
- boîte de dialogue « Action... » : une ligne dont la troisième colonne contient `VirtualSensorSlot` crée un bouton portant le libellé de la deuxième colonne ; les boutons suivent l'ordre des lignes du classeur, les lignes entièrement vides créent un passage à la rangée suivante, et ils envoient à Domoticz la commande d'activation (`switchcmd=On`) de l'IDX de la première colonne ;
- actualisation automatique réglable depuis la boîte de dialogue « Paramètres... » (30 secondes par défaut, de 5 secondes à 1 heure) ;
- mémorisation des paramètres dans le navigateur, avec possibilité de sauvegarde/restauration sur le serveur ;
- affichage de l'heure de dernière actualisation ;
- mise en page qui utilise toute la largeur disponible de l'onglet autonome.

Les commandes d'activation sont limitées aux IDX déclarés dans les lignes d'action du classeur. Cette première version suppose que l'API JSON Domoticz est accessible sans authentification depuis le navigateur, sur la même origine que le tableau de bord.



### Types d'équipements et icônes dans les classeurs de page

Chaque page utilise un classeur distinct. Le nom affiché dans le menu peut être personnalisé depuis **Paramètres** : sélectionner le fichier, modifier le nom associé, valider avec `+`, puis enregistrer les paramètres. Sans personnalisation, le nom technique (`IDX1`, `IDX2`, etc.) est conservé. Les correspondances sont mémorisées dans le navigateur et ne modifient jamais les noms des classeurs.

Le classeur utilise les colonnes suivantes : A = IDX Domoticz (ou nom du flux go2rtc pour une caméra), B = nom long et libellé des actions, C = type, D = vue initiale (pour les historiques), E = icône facultative, G = nom court des cartes. Le mode **Long Name** utilise la colonne B ; le mode **Short Names** utilise la colonne G. Si le libellé choisi est vide, l'autre colonne de nom sert de repli.

Valeurs reconnues en colonne C :
- `scalaire` : carte de valeur classique ;
- `temp` et `counter` : cartes avec valeur et historique ;
- `switchV` : état binaire en lecture seule, affiché avec un voyant et le texte ON/OFF ;
- `switchT` : bouton ON/OFF commandable ; la commande est envoyée à Domoticz puis l'état est relu ;
- `VirtualSensorSlot` : bouton d'action dans la boîte « Actions Domoticz » ;
- `caméra` : carte vidéo ; la colonne A contient le nom du flux défini dans go2rtc (caractères autorisés : lettres, chiffres, point, tiret et soulignement).

La colonne E contient directement le nom officiel d'une icône de la bibliothèque **Lucide**, en minuscules et au format `kebab-case` (sans préfixe ni emoji). Exemples : `thermometer`, `droplets`, `lightbulb`, `door-open`, `car-front`, `footprints`, `lock`, `bell-ring`, `zap`, `camera`, `plug` ou `house`. La colonne peut rester vide : une icône est alors choisie automatiquement selon la catégorie de l'équipement. Si le nom indiqué n'existe pas dans la version Lucide chargée, une icône générique (`house`) est utilisée. La même convention s'applique aux cartes classiques, `switchV` et `switchT`.


### Pilotage PTZ ONVIF

Chaque carte caméra dispose d'un bouton **Pilotage PTZ** qui ouvre un panneau avec la vidéo agrandie, un joystick et les commandes de zoom. Les paramètres ONVIF (hôte, port, identifiant et mot de passe) se configurent séparément pour chaque caméra depuis ce panneau. Les identifiants sont conservés uniquement dans le registre privé du service auxiliaire sur le Raspberry Pi. Le service utilise `onvif-zeep` et la bibliothèque JavaScript [NippleJS](https://github.com/yoannmoinet/nipplejs) pour le joystick tactile. Les positions prédéfinies déjà enregistrées sur la caméra peuvent être rappelées. Le pilotage PTZ n'est accessible que lorsque le flux vidéo est actif.

### Caméras RTSP avec go2rtc

Les flux RTSP ne sont pas lus directement par le navigateur. Pour les afficher, installer go2rtc sur le Raspberry Pi (ou sur un autre serveur du réseau), y déclarer les sources RTSP et utiliser dans le classeur une ligne dont la colonne C vaut « caméra ». La colonne A contient uniquement le nom du flux go2rtc, par exemple « salon », et la colonne B son libellé. Les identifiants RTSP restent dans le fichier de configuration local de go2rtc.

Le lecteur et les fonctions de commande caméra utilisent la passerelle authentifiée `go2rtc-control` (port 1985 par défaut). L'API HTTP go2rtc reste confinée au Raspberry Pi sur 127.0.0.1:1984 et n'est jamais appelée directement par le navigateur. Le port WebRTC 8555 (TCP/UDP) transporte toujours le média directement entre le navigateur et go2rtc ; vérifier les candidats ICE et la configuration réseau selon l'installation.

Exemple de configuration sans identifiants réels : [docs/go2rtc.example.yaml](docs/go2rtc.example.yaml). Guide de mise en place : [docs/cameras-go2rtc.md](docs/cameras-go2rtc.md).

**Sécurité :** ne placez pas d'URL RTSP avec identifiant ou mot de passe dans Excel. Ne publiez jamais le port 1984 de l'API go2rtc. La passerelle média exige le jeton du service de contrôle et un ticket de lecture à usage unique. L'accès WAN n'est pas activé par défaut : il nécessitera une configuration HTTPS, des origines autorisées et les redirections/candidats ICE adaptés, dans une évolution dédiée.

## Navigation multi-pages

Le menu déroulant est construit automatiquement au démarrage en recherchant `IDX1.xlsx` à `IDX9.xlsx` dans le même répertoire que le HTML. Chaque classeur trouvé crée une page portant son nom sans extension (par exemple **IDX1**, **IDX2**). Les extensions `.xlsx` et `.XLSX` sont acceptées. Les pages sont présentées dans l'ordre numérique ; un fichier absent ne crée pas d'entrée. La page sélectionnée est mémorisée dans le navigateur. Le header, les paramètres, les actions, les cartes, les icônes Lucide et les communications avec Domoticz restent communs ; seul le classeur chargé change. Pour ajouter ou retirer une page, il suffit d'ajouter ou de retirer le classeur correspondant.

Les deux classeurs doivent être placés à côté du HTML dans `/home/pi/domoticz/www/templates`. Ils ne sont pas inclus dans le ZIP, afin de préserver les configurations propres à l'installation.

## Installation

1. Sauvegarder le répertoire `www/templates` de Domoticz.
2. Copier ensemble `dashboard/maison-v111.html` et `dashboard/maison-dashboard-v111.html` vers `www/templates`.
3. Dans le menu **Custom** de Domoticz, renseigner l'URL du lanceur `maison-v111.html`.
4. Recharger l'interface Domoticz puis ouvrir l'entrée **Custom** correspondante.

La page d'entrée tente d'ouvrir le tableau de bord dans un nouvel onglet. Si le navigateur bloque l'ouverture automatique, cliquer sur **Ouvrir le tableau de bord**.

Le fichier autonome doit rester à côté du lanceur dans `www/templates`, car le lanceur ouvre le chemin correspondant à la version courante. Le chemin du répertoire Domoticz dépend de l'installation : vérifier le chemin réel sur le Raspberry Pi avant de copier les fichiers.

### ZIP de déploiement généré par la Pull Request

Lorsqu'une Pull Request modifie le tableau de bord, GitHub Actions construit l'artefact `maison-dashboard-raspberry-pi`. Pour les évolutions à venir, il contiendra à la racine du ZIP les deux fichiers HTML versionnés avec le même indice :

- `maison-vN.html` ;
- `maison-dashboard-vN.html` ;
- `LISEZ-MOI.txt`, qui rappelle le chemin de destination et les fichiers à copier.

Pour le récupérer, ouvrir la Pull Request, suivre son exécution dans **Checks** ou **Actions**, puis télécharger l'artefact `maison-dashboard-raspberry-pi` depuis le détail de l'exécution réussie. Décompresser le ZIP et copier les deux fichiers HTML versionnés dans `/home/pi/domoticz/www/templates` sur le Raspberry Pi. Après chaque évolution, mettre à jour l'URL de l'entrée **Custom** Domoticz pour qu'elle pointe vers le nouveau lanceur `maison-vN.html`. Les classeurs `IDX2.xlsx` et `IDX1.xlsx` ne sont pas inclus : ils restent à gérer séparément et doivent être conservés dans le répertoire `templates`.

L'artefact est temporaire (conservation de 14 jours) et correspond au contenu de la branche de la Pull Request au moment de l'exécution ; attendre la réussite du workflow après les dernières modifications avant de télécharger le ZIP.

Les anciennes versions numérotées peuvent être conservées sur le Raspberry Pi pour faciliter un retour arrière. Seul le fichier indiqué par le lanceur est ouvert automatiquement.

## Lisibilité du code

Le HTML, le CSS et le JavaScript sont indentés et séparés en blocs lisibles. Le lanceur et le tableau de bord ont des responsabilités distinctes, ce qui permet de modifier l'un sans mélanger sa logique avec l'autre.

## Développement et gestion de versions

- `main` contient les versions validées.
- Une branche `feature/...` ou `fix/...` est utilisée pour chaque évolution.
- Les modifications sont proposées par Pull Request vers `main`.
- Tester la page sur l'installation réelle avant de fusionner.
- Ne jamais committer de mot de passe, jeton, données privées ou copie de `domoticz.db`.

### Règle de versionnement des deux fichiers HTML du tableau de bord

À chaque évolution fonctionnelle du tableau de bord, créer une nouvelle paire de fichiers portant exactement le même indice (la paire active est actuellement v111) :

- `dashboard/maison-vN.html` : lanceur à renseigner dans le menu **Custom** de Domoticz ;
- `dashboard/maison-dashboard-vN.html` : page autonome ouverte par le lanceur.

Procédure obligatoire :

1. Avant d'attribuer un indice, examiner `main`, les branches existantes et les Pull Requests (ouvertes ou fermées) afin de repérer tous les numéros déjà utilisés ou réservés.
2. Attribuer un indice supérieur au plus élevé déjà attribué, puis l'utiliser pour les deux fichiers de la paire.
3. Ne jamais réutiliser un indice déjà attribué ou réservé, même si la Pull Request correspondante n'a finalement apporté aucune modification, a été abandonnée, fermée ou n'a pas été fusionnée. Un indice attribué est définitivement consommé.
4. Créer les deux nouveaux fichiers à partir de la dernière version validée ; ne pas écraser les fichiers des versions précédentes.
5. Adapter le lanceur pour qu'il ouvre le fichier autonome portant le même indice.
6. Mettre à jour le README, le CHANGELOG et l'artefact ZIP de déploiement ; préciser dans la Pull Request les deux fichiers à installer et la nouvelle URL à renseigner dans le menu **Custom**.

Le numéro n'est jamais déduit du numéro de Pull Request. Il est suivi à partir des fichiers, des branches et de l'historique des Pull Requests. Toute mise à jour d'une PR conserve l'indice qui lui a été attribué ; une nouvelle évolution indépendante reçoit un nouvel indice. Les deux fichiers d'une paire doivent toujours être déployés ensemble.

Cette convention donne à chaque version une URL distincte et évite que le navigateur réutilise une ancienne copie du lanceur ou du tableau de bord. Elle constitue un contournement pragmatique du cache navigateur, particulièrement utile pendant les phases de développement et de test : chaque nouvelle version est demandée sous une URL inédite, sans devoir désactiver globalement le cache ni modifier les règles HTTP de Domoticz. Elle ne remplace pas une politique de cache adaptée côté serveur ; elle permet simplement de travailler avec le comportement de cache existant.

L'utilisateur met à jour l'entrée **Custom** après chaque évolution et peut supprimer périodiquement les anciennes paires de fichiers du Raspberry Pi. L'utilisateur conserve la validation et la fusion des Pull Requests ainsi que le déploiement sur l'installation réelle.

## API et sécurité

Le tableau de bord essaie l'endpoint JSON `type=devices`, puis `type=command&param=getdevices` en repli. Les endpoints et champs disponibles peuvent varier selon la version de Domoticz ; cette page doit donc être validée sur l'installation cible.

La page est en lecture seule. Ne pas exposer l'API Domoticz directement sur Internet sans protection appropriée.

## Documentation

- [Accès distant à Domoticz avec WireGuard et Freebox](docs/acces-distant-wireguard.md)
- [Journal des modifications](CHANGELOG.md)
- [Repères sur la base SQLite Domoticz](docs/database-domoticz.md)
