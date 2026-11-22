# Service de commande go2rtc

Service auxiliaire local permettant au tableau de bord MyDomoticz de commander les flux définis dans go2rtc.

## Sauvegardes des paramètres caméra

Les sauvegardes des caméras sont indépendantes des sauvegardes générales de l'application. Elles sont créées depuis le groupe « Sauvegarde des paramètres de toutes les caméras » de la boîte Paramètres du tableau de bord.

- Production : `/var/lib/go2rtc-control/camera-settings-backups`.
- Test : `/var/lib/go2rtc-control-test/camera-settings-backups`.
- Répertoires 0700 et fichiers JSON 0600, écrits atomiquement.
- Le fichier versionné contient les sources RTSP, les paramètres audio/vidéo, les identifiants ONVIF, les profils locaux et leur sélection, ainsi que l'orientation PTZ.
- Les fichiers sont en clair, comme le registre caméra existant : les permissions du système de fichiers limitent l'accès au compte du service. Une personne ayant un accès privilégié au Raspberry Pi peut néanmoins lire ces secrets.
- L'API exige toujours le jeton caméra Bearer. La clé et la session de récupération ne donnent aucun accès aux sauvegardes caméra.
- L'aperçu n'envoie au navigateur que les noms de caméras et les catégories de paramètres modifiés ; aucune URL RTSP ni valeur d'identifiant/mot de passe n'est transmise.
- La restauration remplace l'ensemble du registre caméra. Elle ne modifie ni les paramètres généraux, ni les jetons d'accès/récupération, ni la bibliothèque commune de profils. Les profils chargés depuis cette bibliothèque restent inclus en tant que profils locaux indépendants.
- Une session de transcodage active bloque la restauration. Les flux qui étaient arrêtés le restent ; les flux actifs reçoivent la source de la sauvegarde. En cas d'échec, le service tente de rétablir les sources précédentes avant de signaler l'erreur.

Le réglage PTZ « caméra montée tête en bas », auparavant local au navigateur, est désormais conservé dans le registre caméra sur le Raspberry Pi. À la première ouverture PTZ après mise à jour, une ancienne valeur locale est migrée si aucune valeur serveur n'existe encore.

## Les trois états

- **Marche** : le lecteur vidéo est affiché dans la page.
- **Arrêt local** : le lecteur est arrêté dans ce navigateur uniquement ; go2rtc continue de fournir le flux.
- **Arrêt global** : le flux ciblé est supprimé de go2rtc. Les autres clients qui l'utilisent peuvent être interrompus, mais le service go2rtc reste actif.

**Important :** l'API DELETE de go2rtc retire également la définition du flux de son YAML. Pour éviter toute perte de source, ce service conserve donc une copie privée indépendante des sources caméra dans `/var/lib/go2rtc-control/cameras.json`. L'arrêt global ne supprime jamais cette copie. Le bouton Marche recrée le flux à partir du registre.

## Installation et mise à jour

Depuis le dossier extrait sur le Raspberry Pi :

```bash
cd service/go2rtc-control
sudo bash install.sh
```

L'installation standard déploie les deux environnements indépendants, soit quatre unités systemd :

| Élément | Production | Test |
| --- | --- | --- |
| go2rtc | `go2rtc.service` | `go2rtc-test.service` |
| Contrôle | `go2rtc-control.service` | `go2rtc-control-test.service` |
| Binaire go2rtc | `/usr/local/bin/go2rtc` | `/home/pi/go2rtc-test/go2rtc` |
| YAML | `/etc/go2rtc/go2rtc.yaml` | `/home/pi/go2rtc-test/go2rtc.yaml` |
| API go2rtc | `127.0.0.1:1984` | `127.0.0.1:1987` |
| RTSP / WebRTC | `8554 / 8555` | `8556 / 8557` |
| API de contrôle | `0.0.0.0:1985` | `127.0.0.1:1986` |
| Registre | `/var/lib/go2rtc-control/cameras.json` | `/var/lib/go2rtc-control-test/cameras.json` |
| Sauvegardes générales | `/var/lib/go2rtc-control/settings-backups` | `/var/lib/go2rtc-control-test/settings-backups` |
| Sauvegardes caméras | `/var/lib/go2rtc-control/camera-settings-backups` | `/var/lib/go2rtc-control-test/camera-settings-backups` |
| Bibliothèque profils | `/var/lib/go2rtc-control/profile-library` | `/var/lib/go2rtc-control-test/profile-library` |

**Prérequis à ne pas oublier :** les deux exécutables go2rtc et les deux fichiers YAML doivent déjà être installés et préparés avant de lancer ce script :
- Production : binaire `/usr/local/bin/go2rtc` et YAML `/etc/go2rtc/go2rtc.yaml` (ou le chemin donné par `GO2RTC_CONFIG`).
- Test : binaire `/home/pi/go2rtc-test/go2rtc` et YAML `/home/pi/go2rtc-test/go2rtc.yaml`.

L'installateur ne télécharge, n'installe, ne met à jour et ne remplace **ni les binaires go2rtc ni les fichiers YAML**. Il installe/met à jour le code et les unités systemd des services de contrôle, ainsi que leurs dépendances. Il redémarre ensuite les deux instances go2rtc et les deux services de contrôle : les flux vidéo peuvent être interrompus momentanément.

Au démarrage, le script affiche un avertissement récapitulatif et demande de taper exactement `OUI` avant de poursuivre. En mode non interactif, il refuse de continuer sauf si `GO2RTC_INSTALL_CONFIRM=oui` est explicitement défini ; l'avertissement reste affiché.

Pour adapter le chemin YAML ou l'origine du tableau de bord :

```bash
sudo GO2RTC_CONFIG=/chemin/go2rtc.yaml DASHBOARD_ORIGIN=http://192.168.1.21:8080 bash install.sh
```

Avant l'installation, réalise la préparation décrite dans [MIGRATION.md](MIGRATION.md) : sauvegarde vérifiée, séparation des deux YAML et des ports, copie indépendante du binaire de production et préparation du binaire/YAML de test, puis vérification des deux fichiers d'environnement. Le script refuse de poursuivre si un des deux binaires ou YAML est absent, ou si les paramètres réseau/API/registre d'un environnement ne correspondent pas à ses valeurs réservées. Il installe les quatre unités systemd, déploie le code dans `/opt/go2rtc-control` et `/opt/go2rtc-control-test`, et installe les dépendances ONVIF dans chacun des deux environnements. Les fichiers d'environnement existants et les jetons désignés par `TOKEN_FILE` sont conservés ; un jeton n'est créé que si son fichier est absent. Les deux registres existants ne sont jamais copiés, fusionnés, remplacés ni réinitialisés par le script d'installation.

**Initialisation et migration des registres :** chaque service de contrôle utilise exclusivement son propre registre. Si celui-ci est absent lors du premier démarrage, le service l'initialise à partir du YAML de son instance go2rtc. Si un registre existe déjà, il n'est ni remplacé ni fusionné ; le service peut uniquement appliquer la migration de schéma déjà prévue par l'application lorsqu'une ancienne structure est détectée. Cette migration conserve les sources RTSP, les préférences audio, la qualité native, les profils et les paramètres PTZ. Une mise à jour ou un redémarrage ne réinitialise pas les données, même si go2rtc a retiré un flux de son YAML. Le script d'installation lui-même n'écrit jamais dans les registres.

Le registre contient des URL potentiellement sensibles. Il est stocké sous le répertoire d'état systemd, avec des droits privés (fichier 0600, répertoire 0750), accessible au compte du service. Ne le publie pas et ne le partage pas. Les jetons existants et les paramètres actuels des deux environnements sont conservés lors d'une mise à jour.

Après installation, le jeton n'est jamais affiché automatiquement. Pour le récupérer volontairement (par exemple après un changement de navigateur ou un effacement du `localStorage`), ouvre un terminal sur le Raspberry Pi et exécute :

```bash
sudo go2rtc-control-show-token
sudo go2rtc-control-show-token --test
```

Sans option, la commande lit le jeton de production ; avec `--test`, elle lit celui de test. Elle ne régénère aucun jeton. Elle exige les droits root, vérifie le propriétaire et les permissions du fichier, et refuse d'afficher le secret si sa sortie n'est pas un terminal interactif. Traite le résultat comme un mot de passe : ne le partage pas et ne le laisse pas dans une capture d'écran ou un journal.

### Initialiser la clé de récupération sans jeton caméra

La première clé doit être créée **avant** de perdre le jeton caméra. Si elle n'a pas encore été créée, ou si le navigateur a déjà été entièrement nettoyé, utilise la commande d'administration locale depuis un terminal SSH sur le Raspberry Pi :

```bash
sudo go2rtc-control-recovery-key
```

La commande exige root et un terminal interactif. Elle génère la clé, stocke uniquement le vérificateur scrypt dans le répertoire privé de récupération, attribue le fichier et son répertoire au compte du service (droits 0600/0700), puis affiche la clé une seule fois. Conserve-la immédiatement hors du Raspberry Pi, par exemple dans ton gestionnaire de mots de passe. Elle n'est jamais écrite dans les journaux.

Pour l'environnement de test, utilise `sudo go2rtc-control-recovery-key --test`. Les deux environnements sont isolés.

Si une clé existe déjà, la commande refuse de l'écraser. Pour un renouvellement volontaire, utilise `sudo go2rtc-control-recovery-key --rotate` (ou ajoute `--test` pour l'environnement de test) et confirme en tapant exactement `ROTATE`. L'ancienne clé et toutes les sessions temporaires sont alors invalidées.

La commande lit uniquement la valeur `RECOVERY_KEY_FILE` du fichier d'environnement ; elle ne source ni n'exécute ce fichier. Elle n'utilise pas le jeton caméra, ne modifie pas les sauvegardes ni les registres caméra et n'expose aucune route HTTP supplémentaire.

Après la génération, saisis la clé dans le dialogue de récupération du tableau de bord. Si la clé est perdue, cette commande permet d'en générer une nouvelle uniquement depuis le Raspberry Pi ; elle ne permet pas de retrouver l'ancienne.


Après installation :

```bash
sudo systemctl status go2rtc.service go2rtc-control.service
sudo systemctl status go2rtc-test.service go2rtc-control-test.service
sudo journalctl -u go2rtc-control.service -u go2rtc-control-test.service -n 50 --no-pager
```

En cas d'échec d'une commande PTZ, le service consigne désormais l'opération concernée (connexion, `ContinuousMove` ou `Stop`), le type d'exception et le détail technique fourni par ONVIF. Les identifiants configurés sont masqués. Pour suivre les erreurs en direct :

```bash
sudo journalctl -u go2rtc-control.service -f
```

Après un échec de déplacement ou d'arrêt, la session ONVIF correspondante est retirée du cache ; la commande suivante établit donc une nouvelle session au lieu de réutiliser celle qui vient d'échouer.

## Passerelle de lecture vidéo (v96)

Le tableau de bord ne contacte plus directement l'interface HTTP de go2rtc. La lecture passe par une passerelle média intégrée au service de contrôle de production, sur son port habituel **1985** :

- Le tableau de bord demande un ticket à usage unique via `POST /api/media/ticket`, avec le jeton Bearer habituel.
- Le ticket expire après 45 secondes et est lié à une caméra ainsi qu'à son flux natif ou transcodé.
- Le premier chargement du lecteur échange le ticket contre un cookie de session HttpOnly, propre à la caméra, valable au plus 8 heures et renouvelé lors des requêtes média.
- La passerelle ne relaie que les fichiers du lecteur go2rtc nécessaires, la signalisation WebSocket `/api/ws` et les ressources HLS `/api/hls/`. Les autres chemins sont refusés.
- La signalisation WebRTC et les transports MSE/HLS passent par cette passerelle. Le média WebRTC (RTP/SRTP) reste une connexion directe du navigateur vers le port WebRTC go2rtc configuré, actuellement **8555 en TCP/UDP**.
- Les profils vidéo, les sessions de transcodage, les commandes PTZ et les préférences audio continuent d'utiliser les routes de contrôle existantes.

L'API go2rtc reste liée à `127.0.0.1:1984`. Aucun binaire, YAML go2rtc, port, registre caméra ni jeton existant n'est modifié par cette évolution. Le service de contrôle de test conserve son instance et son registre indépendants.

**Accès WAN :** cette évolution prépare la séparation entre signalisation HTTP et transport média, mais n'active aucune exposition Internet et ne modifie pas la box. Pour une étape WAN ultérieure, il faudra notamment décider de l'exposition HTTPS du service de contrôle/passerelle, renseigner les origines autorisées via `DASHBOARD_ORIGINS` (liste séparée par des virgules), configurer les candidats ICE annoncés par go2rtc et les redirections TCP/UDP nécessaires pour son port WebRTC. Le port d'administration go2rtc 1984 ne devra jamais être publié. Tant que cette configuration n'a pas été définie et sécurisée, conserver le port 1985 sur le réseau de confiance.

Le cookie est marqué `Secure; SameSite=None` lorsque le service reçoit `X-Forwarded-Proto: https` d'un reverse proxy ; en HTTP direct, il utilise `SameSite=Lax`.

## Commande audio par caméra

Chaque caméra conserve un état audio commun à tous les navigateurs, dans le registre privé /var/lib/go2rtc-control/cameras.json. Le bouton Audio activé / Audio coupé modifie la source du flux go2rtc unique :

Chaque caméra conserve également une résolution vidéo commune à tous les navigateurs dans ce même registre privé : **1080p** utilise le chemin RTSP `/stream1`, **720p** utilise `/stream2`. Le service remplace directement la source du flux go2rtc existant, sans transcodage, puis le lecteur se reconnecte. Le réglage est réappliqué après un arrêt global ou un redémarrage du service. Les sources RTSP dont le chemin ne se termine pas par `/stream1` ou `/stream2` restent utilisables en 1080p, mais ne peuvent pas être basculées en 720p.

- Audio activé : source RTSP originale, sans modification.
- Audio coupé : ajout de #media=video à la source afin que go2rtc ne récupère que la vidéo.
- Si le flux est en marche, le service le supprime puis le recrée avec la variante choisie ; le lecteur doit donc se reconnecter.
- Si le flux est arrêté globalement, le choix est simplement mémorisé et sera appliqué au prochain bouton Marche.
- Le réglage est partagé entre les navigateurs et survit aux redémarrages du service.

Lors de la mise à jour depuis l'ancienne version, les entrées existantes du registre conservent le comportement audio antérieur (audio activé). Aucun flux existant n'est silencieusement basculé pendant la migration. L'utilisateur peut ensuite désactiver l'audio depuis la carte caméra.

Le paramètre #media=video empêche go2rtc de récupérer le média audio ; il ne garantit pas que le microphone ou l'encodage audio soit physiquement désactivé dans la caméra.

## Pilotage PTZ ONVIF

Chaque caméra peut recevoir une configuration ONVIF indépendante depuis le panneau PTZ du tableau de bord. L'adresse, le port (80 par défaut), l'identifiant et le mot de passe sont stockés dans le registre privé `/var/lib/go2rtc-control/cameras.json`, avec les sources RTSP et la préférence audio. Les secrets ONVIF ne sont jamais renvoyés par l'API.

Le service utilise `onvif-zeep` pour sélectionner un profil média disposant d'une configuration PTZ et envoyer des déplacements physiques par petits pas `RelativeMove` (Pan/Tilt uniquement). Le navigateur répète ces déplacements finis tant que le joystick reste incliné ; au relâchement, il cesse immédiatement d'en envoyer de nouveaux. Le dernier petit déplacement déjà accepté par la caméra peut toutefois aller jusqu'à son terme. Le zoom ONVIF n'est pas utilisé : le zoom logiciel est appliqué localement à l'image dans le panneau PTZ, sans modifier le flux go2rtc. Les positions prédéfinies sont consultées (`GetPresets`), rappelées (`GotoPreset`) et de nouvelles positions peuvent être mémorisées (`SetPreset`). Le cache WSDL de Zeep est placé dans `/var/lib/go2rtc-control/cache` via `XDG_CACHE_HOME`, répertoire d'état accessible en écriture au service malgré les protections systemd `ProtectSystem=strict` et `ProtectHome=read-only`. Les sessions ONVIF sont mises en cache en mémoire pour éviter de refaire la découverte du profil à chaque mouvement du joystick. Les mouvements continus utilisent un délai ONVIF d'une seconde, renouvelé tant que l'utilisateur maintient la commande ; le navigateur envoie également `Stop` au relâchement et à la fermeture du panneau.

Routes authentifiées : `GET ptz-status`, `POST ptz-config`, `POST ptz-move` (un pas relatif Pan/Tilt), `POST ptz-stop` (conservée pour compatibilité), `GET ptz-presets`, `POST ptz-goto` et `POST ptz-save-preset`, sous `/api/cameras/{flux}/`.

Le port ONVIF est généralement 80, mais certaines caméras utilisent un port différent : renseigne celui qui fonctionne avec ton logiciel de pilotage habituel. La configuration ONVIF est distincte de l'URL RTSP et peut utiliser des identifiants différents.

## Récupération indépendante des sauvegardes

Le tableau de bord permet de créer une clé de récupération depuis Paramètres, avec le jeton Bearer habituel. La clé aléatoire (256 bits) est affichée une seule fois. Le service ne conserve que son vérificateur scrypt salé dans :

- production : `/var/lib/go2rtc-control/recovery/recovery-key.json` ;
- test : `/var/lib/go2rtc-control-test/recovery/recovery-key.json`.

Le sous-répertoire est créé avec le mode 0700 et le fichier avec le mode 0600. La clé ne doit jamais être copiée dans les sauvegardes de paramètres, dans un classeur IDX ou dans un journal.

Après effacement du stockage du navigateur, l'utilisateur saisit la clé dans le dialogue de sauvegarde. `POST /api/recovery/session` exige une origine présente dans `DASHBOARD_ORIGINS` et délivre un jeton aléatoire valable cinq minutes. Ce jeton, transmis dans `X-Recovery-Token`, autorise uniquement `GET /api/settings-backups` et la lecture d'un fichier de sauvegarde. Il ne permet ni écriture/suppression de sauvegarde, ni commande caméra, ni accès aux profils ou à la bibliothèque. Les sessions ne sont conservées qu'en mémoire et sont invalidées par un renouvellement de clé ou un redémarrage.

La création/rotation utilise `POST /api/recovery/key` et exige le jeton Bearer normal. Le renouvellement invalide l'ancienne clé et toutes les sessions existantes. Cinq tentatives invalides par adresse cliente sur cinq minutes entraînent une limitation temporaire.

**Perte de la clé :** récupérer le jeton normal sur le Raspberry Pi avec `sudo go2rtc-control-show-token`, le saisir dans les paramètres du tableau de bord, puis générer une nouvelle clé. La commande d'affichage existante ne modifie aucun jeton.

**Transport :** la clé et les sauvegardes transitent par HTTP si le service est utilisé en HTTP. Sur un réseau où le trafic peut être observé, un attaquant pourrait intercepter la clé ou le contenu des sauvegardes. Pour une protection contre l'écoute réseau, utiliser HTTPS avec un reverse proxy correctement configuré et inscrire l'origine du tableau de bord dans `DASHBOARD_ORIGINS`. Ne pas exposer le port 1985 directement à Internet.

## Sécurité

- Les identifiants RTSP et ONVIF restent sur le Raspberry Pi, dans le YAML go2rtc et le registre privé ; ils ne sont jamais renvoyés au navigateur par l'API auxiliaire.
- Le jeton Bearer et le contrôle strict de l'origine CORS sont tous deux utilisés.
- Les sources prises en charge sont les chaînes simples du YAML go2rtc. Les entrées multi-sources/complexes sont ignorées.
- Limite le port TCP 1985 au réseau local avec le pare-feu. N'expose pas les ports 1984 et 1985 à Internet.
- L'arrêt global affecte les autres clients utilisant le flux ; l'arrêt local ne concerne que la page courante.

## Diagnostic

```bash
sudo journalctl -u go2rtc-control -f
sudo systemctl restart go2rtc-control
```


## Modèle des profils vidéo par caméra

Le registre privé `/var/lib/go2rtc-control/cameras.json` accueille désormais un modèle de profils vidéo propre à chaque caméra. Le tableau de bord applique désormais le profil préféré à l'ouverture du lecteur. Les sessions de transcodage sont gérées par le service et non par le navigateur.

Chaque caméra possède obligatoirement le profil réservé `native` :
- nom fixe **Natif** ;
- type `native` ;
- profil par défaut, enregistré dans `default_profile_id` ;
- aucune résolution de sortie ni paramètre FFmpeg, car le flux original est utilisé sans transcodage.

Les profils personnalisés sont enregistrés dans l'objet `profiles`, avec un identifiant interne stable (32 caractères hexadécimaux) distinct de leur nom visible. Leur nom est unique, sans distinction de casse, dans la caméra concernée (64 caractères maximum). Deux caméras peuvent réutiliser le même nom.

Un profil de type `transcode` conserve :
- `width` et `height` : l'une des résolutions prises en charge (1920×1080, 1280×720, 854×480 ou 640×360), sans dépasser la résolution native actuellement choisie pour la caméra ;
- `fps` : l'une des cadences prises en charge par le moteur (15, 10, 5, 2, 1, 0,5 ou 0,2 image/s) ;
- `bitrate_kbps` : débit cible compris entre 50 et 2000 kbit/s.

La résolution native de la caméra (`quality`) et sa préférence audio (`audio_enabled`) restent des propriétés de la caméra, indépendantes des profils. Les identifiants et paramètres PTZ existants restent également dans leur emplacement actuel.

### Migration du registre existant

Au démarrage du service, les entrées caméra existantes sans modèle de profils reçoivent automatiquement le profil Natif et `default_profile_id: "native"`. La migration convertit les anciennes entrées sources textuelles en objets structurés et conserve la source RTSP, la préférence audio, la résolution native et les paramètres PTZ existants.

L'écriture reste atomique et le registre conserve ses permissions privées (fichier 0600). Un registre qui contient des profils personnalisés invalides est signalé comme invalide : les profils ne sont pas silencieusement supprimés ou remplacés. Les mises à jour ultérieures devront continuer à préserver les identifiants internes des profils.

## Moteur de transcodage H.264 à deux processus

Le moteur est piloté par le service Python : il n'utilise ni source `exec:` ni exécution de commande arbitraire dans go2rtc. Le service possède les deux processus FFmpeg et la destination go2rtc temporaire pour chaque caméra.

Lorsqu'une première session est acquise, le service crée dynamiquement la destination `{identifiant_logique}_transcode` dans go2rtc avec la source inerte `webrtc:`. Cette source d'attente ne contacte aucune caméra. Il démarre ensuite les deux processus dans cet ordre :

1. **Relais FFmpeg** : écoute un port UDP local propre à la caméra, reçoit le MPEG-TS, copie la vidéo H.264 sans la réencoder et publie le résultat en RTSP vers go2rtc.
2. **Encodeur FFmpeg** : lit le flux natif local go2rtc via `rtsp://127.0.0.1:8554/{identifiant_logique}?video`, écarte l'audio, applique la cadence demandée, encode en H.264 matériel avec `h264_v4l2m2m` et envoie le MPEG-TS sur le port UDP local du relais.

Le flux natif n'est jamais remplacé et FFmpeg ne se connecte jamais directement à l'URL RTSP de la caméra. Le relais est démarré avant l'encodeur afin que son récepteur UDP soit prêt avant l'arrivée des paquets. À l'arrêt, le service arrête d'abord l'encodeur, puis le relais et enfin supprime la destination temporaire.

### Résolution, cadence et débit

Le profil conserve la résolution native sélectionnée, la cadence et le débit cible. Lorsque la sortie demandée correspond exactement à la résolution native (1920×1080 pour `1080p`, 1280×720 pour `720p`), le filtre ne fait que régler la cadence : aucun redimensionnement logiciel n'est appliqué. Les autres dimensions restent possibles avec le filtre logiciel `scale/pad`, mais elles peuvent réduire fortement les performances sur un Raspberry Pi 3B.

Le débit cible est exprimé en kbit/s, avec plafond et tampon calculés à partir de cette valeur. Le débit réellement observé dépend du mouvement et de la complexité de la scène ; une scène presque immobile ne permet pas de prédire le débit d'une scène en mouvement. Le GOP est réglé à environ deux secondes.

### Transport local et disponibilité

Le port UDP est alloué dynamiquement sur l'interface de boucle locale ; il n'a pas besoin d'être ouvert sur le réseau local ni sur Internet. Chaque caméra active possède son propre port et son propre couple de processus. Le relais utilise `-c:v copy` : il ne consomme pas de ressources d'encodage supplémentaires.

La requête RTSP `?video` demande à go2rtc de ne transmettre à l'encodeur que la piste vidéo. Les options `-map 0:v:0` et `-an` constituent une seconde protection : le MPEG-TS et le flux RTSP publié ne contiennent aucune piste audio.

Le service attend l'apparition d'un véritable producteur RTSP dans go2rtc avant de confirmer l'acquisition. Le producteur WebRTC d'attente ne suffit pas. Si l'un des deux processus s'arrête pendant le démarrage, les processus déjà lancés, le port UDP réservé et la destination temporaire sont nettoyés.

Le binaire FFmpeg doit exposer l'encodeur `h264_v4l2m2m`. Cette vérification au démarrage ne remplace pas un test réel du matériel. Le port RTSP de go2rtc doit rester limité au réseau de confiance.

## API de sessions de transcodage

Les routes de session sont ajoutées sous /api/cameras/{identifiant_logique}/transcode/ :

- POST acquire : demande un profil et crée/rejoint une session ;
- POST heartbeat : renouvelle le bail de la session ;
- POST release : libère la session ;
- GET status : retourne l'état de coordination ;
- GET health : retourne l'état de santé du producteur.

Les appels utilisent le jeton Bearer du service ; heartbeat et release exigent en plus le jeton propre à la session. Les profils doivent utiliser la qualité native actuellement sélectionnée dans le registre. Toute modification de la source native (qualité, arrêt global ou bascule audio qui remplace la source) est refusée tant qu'une session réserve le transcodage.


## API de gestion des profils vidéo

Le tableau de bord ouvre la gestion des profils depuis chaque carte caméra. Les appels utilisent le jeton Bearer configuré dans les paramètres du tableau de bord :

- GET /api/cameras/{camera}/profiles : lire les profils et la préférence enregistrée ;
- POST /api/cameras/{camera}/profiles : créer un profil personnalisé ;
- PUT /api/cameras/{camera}/profiles/{id} : modifier ses paramètres ;
- DELETE /api/cameras/{camera}/profiles/{id} : supprimer un profil personnalisé ;
- PUT /api/cameras/{camera}/profiles/selected avec le champ profile_id : mémoriser le profil préféré de cette caméra.

L’interface protège le profil Natif et propose uniquement les résolutions qui ne dépassent pas la qualité native connue. Le lecteur applique directement la préférence enregistrée : profil Natif sur le flux original, ou profil personnalisé sur le flux transcodé dédié. Il acquiert une session avant d'ouvrir ce dernier, renouvelle le bail toutes les 10 secondes et libère sa session à l'arrêt ou à la fermeture de la page. Les règles de bail et de concurrence restent entièrement appliquées par le service Python.


## Sessions de transcodage pilotées par le lecteur

Lorsque la caméra utilise le profil **Natif**, le navigateur lit le flux go2rtc habituel. Lorsqu'un profil personnalisé est préféré, le tableau de bord demande au service une session de transcodage et lit le flux de sortie dédié, nommé `<nom_du_flux>_transcode`. Le moteur FFmpeg lit uniquement la vidéo de la source native (`?video`) et encode sans piste audio (`-an`), conformément à l'architecture A.

Routes authentifiées sous `/api/cameras/{flux}/transcode/` : `GET status` et `GET health` pour consulter l'état ; `POST acquire` avec le profil demandé pour démarrer ou rejoindre un producteur ; `POST heartbeat` pour renouveler le bail ; `POST release` pour libérer la session du navigateur.

Le service reste l'autorité sur le cycle de vie : heartbeat du navigateur toutes les **10 secondes**, bail expirant après **60 secondes** sans renouvellement, balayage des expirations toutes les **5 secondes**. Plusieurs lecteurs peuvent partager le même transcodage si leur profil est identique ; un profil différent reçoit un conflit. Le producteur s'arrête lorsque la dernière session est libérée ou expire.

Le tableau de bord libère sa session avant un arrêt global ou une modification de la source native, et tente une libération à la fermeture de l'onglet. Si le navigateur disparaît brutalement ou si la requête de libération échoue, le bail expire côté service. La modification de la résolution native reste refusée tant qu'une session de transcodage réserve la caméra.
