# Service de commande go2rtc

Service auxiliaire local permettant au tableau de bord MyDomoticz de commander les flux définis dans le YAML go2rtc.

## Les trois états

- **Marche** : le lecteur vidéo est affiché dans la page.
- **Arrêt local** : le lecteur est arrêté dans ce navigateur uniquement ; go2rtc continue de fournir le flux.
- **Arrêt global** : le flux est supprimé de go2rtc. Les autres clients qui l'utilisent peuvent être interrompus, mais le service go2rtc reste actif.

Après un arrêt global, le retour à Marche recrée le flux depuis sa source YAML locale. Seuls les flux déclarés avec une source textuelle simple sont pris en charge.

## Installation

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

Le script installe `python3-yaml`, déploie le programme dans `/opt/go2rtc-control`, crée un jeton aléatoire dans `/etc/go2rtc-control/token` et active le service systemd. Le jeton s'affiche à la fin : saisis-le dans les paramètres du tableau de bord et conserve-le en lieu sûr.

Le fichier `/etc/go2rtc-control/go2rtc-control.env` n'est créé qu'à la première installation. Après une modification de ce fichier :

```bash
sudo systemctl restart go2rtc-control
sudo systemctl status go2rtc-control
```

## Sécurité

- Les identifiants RTSP restent dans le YAML local go2rtc ; ils ne sont jamais transmis au navigateur ni renvoyés par l'API auxiliaire.
- Le jeton autorise l'arrêt et le redémarrage des flux déclarés. Le navigateur le mémorise pour les commandes.
- Le contrôle CORS de l'origine ne remplace pas le jeton Bearer : les deux protections sont utilisées.
- Limite le port TCP 1985 au réseau local avec le pare-feu. N'expose pas les ports 1984 et 1985 à Internet.
- L'arrêt global affecte les autres clients utilisant le flux ; l'arrêt local ne concerne que la page courante.

## Diagnostic

```bash
sudo journalctl -u go2rtc-control -f
sudo systemctl restart go2rtc-control
```
