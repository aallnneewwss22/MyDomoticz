# MyDomoticz

Pages web personnalisées pour Domoticz, développées progressivement et versionnées avec Git.

## Tableau de bord — v1.0

Le tableau de bord est fourni sous deux fichiers :

- `dashboard/maison.html` : page d'entrée à installer dans le menu **Custom** de Domoticz ;
- `dashboard/maison-dashboard.html` : tableau de bord autonome, destiné à s'ouvrir dans son propre onglet.

Fonctions du tableau de bord :

- interface responsive pour PC, tablette et smartphone ;
- consultation en lecture seule des équipements Domoticz ;
- affichage limité aux IDX 44, 48, 52 et 322 ; les autres équipements sont ignorés ;
- recherche par nom ou valeur et filtre par catégorie ;
- actualisation automatique toutes les 30 secondes ;
- état de connexion et heure de dernière actualisation ;
- mise en page qui utilise toute la largeur disponible de l'onglet autonome.

Aucune commande n'est envoyée aux équipements.

## Installation

1. Sauvegarder le répertoire `www/templates` de Domoticz.
2. Copier `dashboard/maison.html` vers `www/templates/maison.html`.
3. Copier `dashboard/maison-dashboard.html` vers `www/templates/maison-dashboard.html`, dans le même répertoire.
4. Activer le menu **Custom** dans les paramètres Domoticz si cette option est disponible dans la version installée.
5. Recharger l'interface Domoticz puis ouvrir **Custom → maison**.

La page d'entrée tente d'ouvrir le tableau de bord dans un nouvel onglet. Si le navigateur bloque l'ouverture automatique, cliquer sur **Ouvrir le tableau de bord**.

Le fichier autonome doit rester à côté du lanceur dans `www/templates`, car le lien est relatif. Le chemin du répertoire Domoticz dépend de l'installation : vérifier le chemin réel sur le Raspberry Pi avant de copier les fichiers.

## Lisibilité du code

Le HTML, le CSS et le JavaScript sont indentés et séparés en blocs lisibles. Le lanceur et le tableau de bord ont des responsabilités distinctes, ce qui permet de modifier l'un sans mélanger sa logique avec l'autre.

## Développement et gestion de versions

- `main` contient les versions validées.
- Une branche `feature/...` ou `fix/...` est utilisée pour chaque évolution.
- Les modifications sont proposées par Pull Request vers `main`.
- Tester la page sur l'installation réelle avant de fusionner.
- Ne jamais committer de mot de passe, jeton, données privées ou copie de `domoticz.db`.

## API et sécurité

Le tableau de bord essaie l'endpoint JSON `type=devices`, puis `type=command&param=getdevices` en repli. Les endpoints et champs disponibles peuvent varier selon la version de Domoticz ; cette page doit donc être validée sur l'installation cible.

La page est en lecture seule. Ne pas exposer l'API Domoticz directement sur Internet sans protection appropriée.

## Documentation

- [Journal des modifications](CHANGELOG.md)
- [Repères sur la base SQLite Domoticz](docs/database-domoticz.md)
