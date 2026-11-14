# Séparation des instances go2rtc production et test

Cette migration est volontairement distincte de l'installation logicielle. Elle ne doit être exécutée qu'après sauvegarde et validation de la configuration locale. Elle ne modifie pas le Raspberry Pi tant que les commandes ne sont pas lancées manuellement.

## Architecture cible

| Élément | Production | Test |
| --- | --- | --- |
| Unité go2rtc | `go2rtc.service` | `go2rtc-test.service` |
| Configuration | `/etc/go2rtc/go2rtc.yaml` | `/home/pi/go2rtc-test/go2rtc.yaml` |
| Binaire | `/usr/local/bin/go2rtc` | `/home/pi/go2rtc-test/go2rtc` |
| API go2rtc | `127.0.0.1:1984` | `127.0.0.1:1987` |
| RTSP | `:8554` | `:8556` |
| WebRTC | `:8555` | `:8557` |
| API de contrôle | `:1985` | `127.0.0.1:1986` |

Les ports de production restent identiques aux ports actuellement utilisés par le tableau de bord. Le service de contrôle de production dépend désormais de `go2rtc.service`, et non de `go2rtc-test.service`.

## 1. Sauvegarder l'état existant

Ne pas arrêter ni redémarrer les services à ce stade.

```bash
sudo install -d -o root -g root -m 0700 /root/go2rtc-separation-backup
sudo cp -a /home/pi/go2rtc-test/go2rtc.yaml /root/go2rtc-separation-backup/go2rtc-test.yaml
sudo cp -a /home/pi/go2rtc-test/go2rtc /root/go2rtc-separation-backup/go2rtc-test
sudo cp -a /etc/go2rtc-control/go2rtc-control.env /root/go2rtc-separation-backup/
sudo cp -a /etc/go2rtc-control-test/go2rtc-control-test.env /root/go2rtc-separation-backup/
sudo cp -a /var/lib/go2rtc-control/cameras.json /root/go2rtc-separation-backup/ 2>/dev/null || true
sudo cp -a /etc/systemd/system/go2rtc-test.service /root/go2rtc-separation-backup/
sudo cp -a /etc/systemd/system/go2rtc-control.service /root/go2rtc-separation-backup/
sudo cp -a /etc/systemd/system/go2rtc-control-test.service /root/go2rtc-separation-backup/
```

Vérifier que les fichiers de sauvegarde existent et que le registre `cameras.json`, s'il existe, est bien présent. Ce registre contient les sources et paramètres privés des caméras : ne pas le publier.

## 2. Créer une copie de production indépendante

Le binaire de production est une copie distincte : une mise à jour du binaire de test ne modifiera pas la production.

```bash
sudo install -d -o root -g pi -m 0750 /etc/go2rtc
sudo install -o pi -g pi -m 0755 /home/pi/go2rtc-test/go2rtc /usr/local/bin/go2rtc
sudo install -o pi -g pi -m 0640 /home/pi/go2rtc-test/go2rtc.yaml /etc/go2rtc/go2rtc.yaml
```

La copie du YAML conserve les sources et les réglages actuels. Vérifier ensuite que la configuration de production utilise les ports de production :

```yaml
api:
  listen: 127.0.0.1:1984
rtsp:
  listen: :8554
webrtc:
  listen: :8555
```

Ne pas remplacer le reste du fichier : en particulier, conserver les définitions de flux et tous les réglages spécifiques déjà présents.

## 3. Déplacer uniquement les ports de l'instance de test

Éditer `/home/pi/go2rtc-test/go2rtc.yaml` avec :

```bash
sudo nano /home/pi/go2rtc-test/go2rtc.yaml
```

Modifier les trois écoutes pour les valeurs de test :

```yaml
api:
  listen: 127.0.0.1:1987
rtsp:
  listen: :8556
webrtc:
  listen: :8557
```

Conserver toutes les définitions de flux et les autres options du fichier. Si ces sections existent déjà, modifier uniquement leur propriété `listen`. Ne pas créer de doublons YAML.

## 4. Reconfigurer le contrôle de test

Éditer `/etc/go2rtc-control-test/go2rtc-control-test.env` et vérifier les valeurs suivantes. Conserver les autres variables, notamment le jeton et le port d'écoute de l'API de contrôle :

```ini
GO2RTC_API=http://127.0.0.1:1987
GO2RTC_CONFIG=/home/pi/go2rtc-test/go2rtc.yaml
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8556
CONTROL_HOST=127.0.0.1
CONTROL_PORT=1986
```

Le service de contrôle de production doit pointer vers la configuration dédiée :

```bash
sudo nano /etc/go2rtc-control/go2rtc-control.env
```

Vérifier au minimum :

```ini
GO2RTC_API=http://127.0.0.1:1984
GO2RTC_CONFIG=/etc/go2rtc/go2rtc.yaml
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8554
CONTROL_HOST=0.0.0.0
CONTROL_PORT=1985
```

Ne pas modifier `TOKEN_FILE`, `SOURCE_REGISTRY`, `DASHBOARD_ORIGIN` ni les autres paramètres personnalisés. Le registre de production reste `/var/lib/go2rtc-control/cameras.json` : il ne doit surtout pas être supprimé ou réinitialisé.

## 5. Basculer les instances

Après vérification des sauvegardes, des YAML et des deux fichiers d'environnement :

```bash
sudo systemctl daemon-reload
sudo systemctl restart go2rtc-test.service
sudo systemctl restart go2rtc-control-test.service
```

Vérifier d'abord que le test écoute uniquement sur ses ports dédiés :

```bash
sudo systemctl --no-pager --full status go2rtc-test.service go2rtc-control-test.service
sudo ss -ltnp | grep -E ':(1984|1985|1986|1987|8554|8555|8556|8557)\\b'
```

Si le test fonctionne, installer ensuite la version du dépôt depuis `service/go2rtc-control`. Le script vérifie la présence du binaire et du YAML de production avant de poursuivre :

```bash
sudo bash install.sh
```

Le script installe `go2rtc.service`, fait dépendre `go2rtc-control.service` de cette instance et démarre les services de production. Il ne redémarre pas les services de test.

## 6. Vérifications après migration

```bash
sudo systemctl --no-pager --full status go2rtc.service go2rtc-control.service
sudo systemctl --no-pager --full status go2rtc-test.service go2rtc-control-test.service
sudo journalctl -u go2rtc.service -u go2rtc-control.service -n 80 --no-pager
sudo journalctl -u go2rtc-test.service -u go2rtc-control-test.service -n 80 --no-pager
```

Contrôler les ports et les URL d'API des deux environnements. Tester ensuite une caméra en production, puis séparément le service de test. Vérifier que les flux, les préférences audio/vidéo, les profils et les paramètres PTZ sont présents.

## Retour arrière

Ne pas supprimer les sauvegardes. En cas d'échec, arrêter les nouvelles unités de production, restaurer les fichiers sauvegardés, remettre les ports de test à leurs valeurs initiales (`1984`, `8554`, `8555`) et redémarrer les unités précédentes. Ne jamais fusionner les deux registres de caméras.

Cette procédure ne réalise aucun retour arrière automatique : chaque étape doit être vérifiée avant de passer à la suivante.
