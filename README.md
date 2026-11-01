# MyDomoticz

Pages web personnalisées pour Domoticz, développées progressivement et versionnées avec Git.

## Tableau de bord — v1.0

Le tableau de bord est fourni sous deux fichiers :

- `dashboard/maison.html` : page d'entrée à installer dans le menu **Custom** de Domoticz ;
- `dashboard/maison-dashboard-v16.html` : version actuelle du tableau de bord autonome, destinée à s'ouvrir dans son propre onglet.

Le suffixe `-vN` du tableau de bord fait partie de la stratégie de cache : chaque évolution du tableau de bord crée un nouveau fichier numéroté afin que le navigateur demande une URL différente.

Fonctions du tableau de bord :

- interface responsive pour PC, tablette et smartphone ;
- consultation en lecture seule des équipements Domoticz ;
- affichage des équipements dont la troisième colonne de `IDX2.xlsx` ou `IDX2.XLS` contient `main`, dans le même ordre que leurs lignes dans le classeur ;
- cartes d'historique de température pour les lignes dont la troisième colonne contient `historique` (sans distinction de casse ni d'espaces superflus), avec périodes 24 heures, 7 jours, 30 jours et 1 an ;
- boîte de dialogue « Action... » : une ligne dont la troisième colonne contient `VirtualSensorSlot` crée un bouton portant le libellé de la deuxième colonne ; les boutons suivent l'ordre des lignes du classeur, les lignes entièrement vides créent un passage à la rangée suivante, et ils envoient à Domoticz la commande d'activation (`switchcmd=On`) de l'IDX de la première colonne ;
- actualisation automatique réglable depuis la boîte de dialogue « Paramètres... » (30 secondes par défaut, de 5 secondes à 1 heure) ;
- mémorisation de la période choisie dans le navigateur ;
- affichage de l'heure de dernière actualisation ;
- mise en page qui utilise toute la largeur disponible de l'onglet autonome.

Les commandes d'activation sont limitées aux IDX déclarés dans les lignes d'action du classeur. Cette première version suppose que l'API JSON Domoticz est accessible sans authentification depuis le navigateur, sur la même origine que le tableau de bord.

## Installation

1. Sauvegarder le répertoire `www/templates` de Domoticz.
2. Copier `dashboard/maison.html` vers `www/templates/maison.html`.
3. Copier le dernier fichier numéroté du tableau de bord — actuellement `dashboard/maison-dashboard-v16.html` — vers `www/templates/maison-dashboard-v16.html`, dans le même répertoire.
4. Activer le menu **Custom** dans les paramètres Domoticz si cette option est disponible dans la version installée.
5. Recharger l'interface Domoticz puis ouvrir **Custom → maison**.

La page d'entrée tente d'ouvrir le tableau de bord dans un nouvel onglet. Si le navigateur bloque l'ouverture automatique, cliquer sur **Ouvrir le tableau de bord**.

Le fichier autonome doit rester à côté du lanceur dans `www/templates`, car le lanceur ouvre le chemin correspondant à la version courante. Le chemin du répertoire Domoticz dépend de l'installation : vérifier le chemin réel sur le Raspberry Pi avant de copier les fichiers.

### ZIP de déploiement généré par la Pull Request

Lorsqu'une Pull Request modifie le tableau de bord, GitHub Actions construit l'artefact `maison-dashboard-raspberry-pi`. Il contient à la racine du ZIP :

- `maison.html` ;
- le fichier versionné actuellement référencé par le lanceur, par exemple `maison-dashboard-v16.html` ;
- `LISEZ-MOI.txt`, qui rappelle le chemin de destination et les fichiers à copier.

Pour le récupérer, ouvrir la Pull Request, suivre son exécution dans **Checks** ou **Actions**, puis télécharger l'artefact `maison-dashboard-raspberry-pi` depuis le détail de l'exécution réussie. Décompresser le ZIP et copier les deux fichiers HTML dans `/home/pi/domoticz/www/templates` sur le Raspberry Pi. Le classeur `IDX2.xlsx` ou `IDX2.XLS` n'est pas inclus : il reste à gérer séparément et doit être conservé dans le répertoire s'il est utilisé par l'installation.

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

### Règle de versionnement des fichiers du tableau de bord

À chaque évolution fonctionnelle de la page autonome :

1. Repérer le numéro le plus élevé de `maison-dashboard-vN.html` dans la branche de référence.
2. Créer le fichier suivant, avec le numéro incrémenté de 1, en partant de la dernière version du tableau de bord.
3. Appliquer les changements au nouveau fichier, sans écraser ni supprimer les versions précédentes.
4. Modifier `dashboard/maison.html` pour qu'il ouvre ce nouveau nom de fichier.
5. Ajouter une entrée au `CHANGELOG.md` indiquant la nouvelle version et l'évolution apportée.
6. Indiquer dans la Pull Request les fichiers à déployer sur le Raspberry Pi.

Le numéro de version est déterminé par les fichiers présents dans le dépôt, et non par le numéro de Pull Request ou par la mémoire de la conversation. Le lanceur et le nouveau fichier numéroté doivent être déployés ensemble. L'utilisateur conserve la validation et la fusion de la Pull Request ainsi que le déploiement sur l'installation réelle.

Cette convention de nommage contourne les caches qui semblent ignorer les paramètres de requête. Elle ne remplace pas une configuration correcte des en-têtes HTTP, mais fournit un mécanisme simple et traçable.

## API et sécurité

Le tableau de bord essaie l'endpoint JSON `type=devices`, puis `type=command&param=getdevices` en repli. Les endpoints et champs disponibles peuvent varier selon la version de Domoticz ; cette page doit donc être validée sur l'installation cible.

La page est en lecture seule. Ne pas exposer l'API Domoticz directement sur Internet sans protection appropriée.

## Documentation

- [Journal des modifications](CHANGELOG.md)
- [Repères sur la base SQLite Domoticz](docs/database-domoticz.md)
