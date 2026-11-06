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

Le script installe `python3-yaml`, déploie le programme dans `/opt/go2rtc-control`, crée le jeton dans `/etc/go2rtc-control/token` lors de la première installation, puis redémarre le service.

**Migration automatique de l'installation existante :** si le registre indépendant n'existe pas encore, le premier démarrage de cette version copie les sources textuelles actuellement présentes dans le YAML go2rtc vers `/var/lib/go2rtc-control/cameras.json`. Dans ton cas, comme tu as restauré le YAML avant cette mise à jour, cette copie récupérera les sources restaurées. Le registre est ensuite conservé tel quel : une mise à jour ou un redémarrage ne l'écrase pas, même si go2rtc a retiré un flux du YAML.

Le registre contient des URL potentiellement sensibles. Il est stocké sous le répertoire d'état systemd, avec des droits privés (fichier 0600, répertoire 0750), accessible au compte du service. Ne le publie pas et ne le partage pas. Le jeton existant et les paramètres actuels sont conservés lors d'une mise à jour.

Après installation :

```bash
sudo systemctl status go2rtc-control
sudo journalctl -u go2rtc-control -n 50 --no-pager
```

## Commande audio par caméra

Chaque caméra conserve un état audio commun à tous les navigateurs, dans le registre privé /var/lib/go2rtc-control/cameras.json. Le bouton Audio activé / Audio coupé modifie la source du flux go2rtc unique :

- Audio activé : source RTSP originale, sans modification.
- Audio coupé : ajout de #media=video à la source afin que go2rtc ne récupère que la vidéo.
- Si le flux est en marche, le service le supprime puis le recrée avec la variante choisie ; le lecteur doit donc se reconnecter.
- Si le flux est arrêté globalement, le choix est simplement mémorisé et sera appliqué au prochain bouton Marche.
- Le réglage est partagé entre les navigateurs et survit aux redémarrages du service.

Lors de la mise à jour depuis l'ancienne version, les entrées existantes du registre conservent le comportement audio antérieur (audio activé). Aucun flux existant n'est silencieusement basculé pendant la migration. L'utilisateur peut ensuite désactiver l'audio depuis la carte caméra.

Le paramètre #media=video empêche go2rtc de récupérer le média audio ; il ne garantit pas que le microphone ou l'encodage audio soit physiquement désactivé dans la caméra.

## Sécurité

- Les identifiants RTSP restent sur le Raspberry Pi, dans le YAML go2rtc et le registre privé ; ils ne sont jamais renvoyés au navigateur par l'API auxiliaire.
- Le jeton Bearer et le contrôle strict de l'origine CORS sont tous deux utilisés.
- Les sources prises en charge sont les chaînes simples du YAML go2rtc. Les entrées multi-sources/complexes sont ignorées.
- Limite le port TCP 1985 au réseau local avec le pare-feu. N'expose pas les ports 1984 et 1985 à Internet.
- L'arrêt global affecte les autres clients utilisant le flux ; l'arrêt local ne concerne que la page courante.

## Diagnostic

```bash
sudo journalctl -u go2rtc-control -f
sudo systemctl restart go2rtc-control
```
