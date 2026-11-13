# Service de commande go2rtc

Service auxiliaire local permettant au tableau de bord MyDomoticz de commander les flux définis dans go2rtc.

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

Valeurs par défaut : utilisateur Linux `pi`, YAML `/home/pi/go2rtc-test/go2rtc.yaml`, API go2rtc `http://127.0.0.1:1984`, origine Domoticz `http://192.168.1.21:8080`.

Pour adapter le chemin YAML ou l'origine du tableau de bord :

```bash
sudo GO2RTC_CONFIG=/chemin/go2rtc.yaml DASHBOARD_ORIGIN=http://192.168.1.21:8080 bash install.sh
```

Le script installe `python3-yaml`, `python3-zeep` et `python3-pip`, place le client `onvif-zeep` dans un répertoire privé de l'application, déploie le programme dans `/opt/go2rtc-control`, crée le jeton dans `/etc/go2rtc-control/token` lors de la première installation, puis redémarre le service.

**Migration automatique de l'installation existante :** si le registre indépendant n'existe pas encore, le premier démarrage de cette version copie les sources textuelles actuellement présentes dans le YAML go2rtc vers `/var/lib/go2rtc-control/cameras.json`. Dans ton cas, comme tu as restauré le YAML avant cette mise à jour, cette copie récupérera les sources restaurées. Le registre est ensuite conservé tel quel : une mise à jour ou un redémarrage ne l'écrase pas, même si go2rtc a retiré un flux du YAML.

Le registre contient des URL potentiellement sensibles. Il est stocké sous le répertoire d'état systemd, avec des droits privés (fichier 0600, répertoire 0750), accessible au compte du service. Ne le publie pas et ne le partage pas. Le jeton existant et les paramètres actuels sont conservés lors d'une mise à jour.

Après installation :

```bash
sudo systemctl status go2rtc-control
sudo journalctl -u go2rtc-control -n 50 --no-pager
```

En cas d'échec d'une commande PTZ, le service consigne désormais l'opération concernée (connexion, `ContinuousMove` ou `Stop`), le type d'exception et le détail technique fourni par ONVIF. Les identifiants configurés sont masqués. Pour suivre les erreurs en direct :

```bash
sudo journalctl -u go2rtc-control -f
```

Après un échec de déplacement ou d'arrêt, la session ONVIF correspondante est retirée du cache ; la commande suivante établit donc une nouvelle session au lieu de réutiliser celle qui vient d'échouer.

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
