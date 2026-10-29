# MyDomoticz

Pages web personnalisées pour Domoticz, développées progressivement et versionnées avec Git.

## Tableau de bord — v1.0

Le premier tableau de bord se trouve dans [`dashboard/maison.html`](dashboard/maison.html).

Fonctions :
- interface responsive pour PC, tablette et smartphone ;
- consultation en lecture seule des équipements Domoticz ;
- recherche par nom ou valeur et filtre par catégorie ;
- actualisation automatique toutes les 30 secondes ;
- état de connexion et heure de dernière actualisation ;
- ouverture automatique du tableau de bord dans un nouvel onglet lorsqu'il est lancé depuis le cadre Domoticz ;
- affichage autonome utilisant toute la largeur disponible du navigateur.

Si le navigateur bloque l'ouverture automatique, cliquer sur le lien proposé dans la page d'entrée. Cette première version n'envoie aucune commande aux équipements.

## Installation

1. Sauvegarder le répertoire `www/templates` de Domoticz.
2. Copier `dashboard/maison.html` vers `www/templates/maison.html`.
3. Activer le menu **Custom** dans les paramètres Domoticz si cette option est disponible dans la version installée.
4. Recharger l'interface Domoticz puis ouvrir **Custom → maison**.
5. La page tente d'ouvrir le tableau de bord dans un nouvel onglet. Si le navigateur bloque cette ouverture automatique, cliquer sur **Ouvrir le tableau de bord dans un nouvel onglet**.

Le chemin du répertoire Domoticz dépend de l'installation. Vérifier le chemin réel sur le Raspberry Pi avant de copier le fichier.

## Développement et gestion de versions

- `main` contient les versions validées.
- Une branche `feature/...` ou `fix/...` est utilisée pour chaque évolution.
- Les modifications sont proposées par Pull Request vers `main`.
- Tester la page sur l'installation réelle avant de fusionner.
- Ne jamais committer de mot de passe, jeton, données privées ou copie de `domoticz.db`.

## API et sécurité

La page essaie l'endpoint JSON `type=devices`, puis `type=command&param=getdevices` en repli. Les endpoints et champs disponibles peuvent varier selon la version de Domoticz ; cette page doit donc être validée sur l'installation cible.

La page est en lecture seule. Ne pas exposer l'API Domoticz directement sur Internet sans protection appropriée.

## Documentation

- [Journal des modifications](CHANGELOG.md)
- [Repères sur la base SQLite Domoticz](docs/database-domoticz.md)
