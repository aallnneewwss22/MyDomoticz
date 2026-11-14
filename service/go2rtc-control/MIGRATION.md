# Séparation des instances go2rtc production et test

Cette procédure est une migration manuelle, contrôlée et réversible. Elle ne doit être exécutée qu'après validation de la PR, sauvegarde vérifiée et lecture complète des étapes. La fusion de la PR ne modifie pas le Raspberry Pi.

**Ne pas exécuter cette procédure en bloc.** Chaque phase doit être vérifiée avant de poursuivre. Ne jamais publier les YAML, registres, fichiers d'environnement ou jetons : ils peuvent contenir des identifiants.

## 1. Architecture cible

| Élément | Production | Test |
| --- | --- | --- |
| Unité go2rtc | `go2rtc.service` | `go2rtc-test.service` |
| Configuration | `/etc/go2rtc/go2rtc.yaml` | `/home/pi/go2rtc-test/go2rtc.yaml` |
| Binaire | `/usr/local/bin/go2rtc` | `/home/pi/go2rtc-test/go2rtc` |
| API go2rtc | `127.0.0.1:1984` | `127.0.0.1:1987` |
| RTSP | `:8554` | `:8556` |
| WebRTC | `:8555` | `:8557` |
| API de contrôle | `:1985` | `127.0.0.1:1986` |
| Registre privé | `/var/lib/go2rtc-control/cameras.json` | `/var/lib/go2rtc-control-test/cameras.json` |

Les deux instances doivent avoir un binaire, un YAML, des ports et un registre indépendants. Aucun service de production ne doit dépendre de `go2rtc-test.service`, et aucun service de test ne doit utiliser l'instance de production.

Les ports de production restent ceux actuellement utilisés par le tableau de bord. Les ports de test sont déplacés pour libérer ces ports avant le démarrage de l'instance de production.

## 2. Préparation et sauvegarde

Ne pas arrêter ni redémarrer les services pendant cette phase.

La sauvegarde doit inclure au minimum :
- le YAML et le binaire go2rtc actuels ;
- les deux registres privés de caméras ;
- les deux fichiers d'environnement et **les fichiers réellement désignés par leurs variables `TOKEN_FILE`** ;
- les trois unités systemd actuelles ;
- tout fichier déjà présent sous `/etc/go2rtc`.

Exemple de sauvegarde locale protégée (à adapter si un chemin diffère) :

```bash
sudo install -d -o root -g root -m 0700 /root/go2rtc-separation-backup
sudo cp -a --parents /home/pi/go2rtc-test/go2rtc.yaml /root/go2rtc-separation-backup
sudo cp -a --parents /home/pi/go2rtc-test/go2rtc /root/go2rtc-separation-backup
sudo cp -a --parents /var/lib/go2rtc-control/cameras.json /root/go2rtc-separation-backup
sudo cp -a --parents /var/lib/go2rtc-control-test/cameras.json /root/go2rtc-separation-backup
sudo cp -a --parents /etc/go2rtc-control/go2rtc-control.env /root/go2rtc-separation-backup
sudo cp -a --parents /etc/go2rtc-control-test/go2rtc-control-test.env /root/go2rtc-separation-backup
sudo cp -a --parents /etc/systemd/system/go2rtc-test.service /root/go2rtc-separation-backup
sudo cp -a --parents /etc/systemd/system/go2rtc-control.service /root/go2rtc-separation-backup
sudo cp -a --parents /etc/systemd/system/go2rtc-control-test.service /root/go2rtc-separation-backup
```

Sauvegarder également les jetons désignés par les deux fichiers d'environnement. Lire uniquement la valeur locale de `TOKEN_FILE`, puis copier le fichier correspondant avec ses permissions ; ne jamais afficher son contenu. Si le chemin est relatif, absent ou ambigu, arrêter et résoudre ce point avant de continuer. Si `/etc/go2rtc` existe déjà, le sauvegarder intégralement avant toute modification.

Vérifier que les deux registres sont présents et distincts. Ne pas les fusionner, les remplacer ou les régénérer. Les registres existants contiennent les sources, profils vidéo, préférences audio et paramètres PTZ ; ils sont la source persistante de ces réglages.

Une copie indépendante hors du Raspberry et une vérification SHA-256 sont fortement recommandées.

## 3. Inventorier et répartir les flux YAML

Le YAML actuel peut ne contenir que `streams:` : l'absence des sections `api`, `rtsp` et `webrtc` est normale dans cette installation et ne doit pas conduire à supposer qu'elles existent déjà.

Avant édition, relever uniquement les **noms** des flux (pas leurs URL ni leurs identifiants) et décider de leur environnement. Chaque flux caméra réel doit appartenir à une seule instance. Ne pas recopier toutes les sources dans les deux YAML.

Pour l'installation auditée lors de la préparation de cette PR, les noms observés étaient :
- `camera_sejour` : flux de production attendu ;
- `camera_test` et `camera_test_rtsp_probe` : flux de test attendus.

Cette répartition est à confirmer avec l'usage réel avant suppression d'une entrée d'un YAML. Si un de ces noms a changé de rôle, adapter la répartition en conséquence. Le flux `camera_test_rtsp_probe` est un flux technique de test et ne doit pas être ajouté au registre des caméras de production.

Créer deux fichiers de travail à partir du YAML sauvegardé. Les chemins sont explicites pour éviter toute édition directe du fichier actif pendant la préparation :

```bash
sudo install -d -o root -g root -m 0700 /root/go2rtc-separation-work
sudo cp -a /root/go2rtc-separation-backup/home/pi/go2rtc-test/go2rtc.yaml /root/go2rtc-separation-work/go2rtc-production.yaml
sudo cp -a /root/go2rtc-separation-backup/home/pi/go2rtc-test/go2rtc.yaml /root/go2rtc-separation-work/go2rtc-test.yaml
sudo nano /root/go2rtc-separation-work/go2rtc-production.yaml
sudo nano /root/go2rtc-separation-work/go2rtc-test.yaml
```

Après édition et vérification :
- `/root/go2rtc-separation-work/go2rtc-production.yaml` contient les flux de production uniquement ;
- `/root/go2rtc-separation-work/go2rtc-test.yaml` contient les flux de test uniquement.

Ne pas éditer les sources RTSP elles-mêmes. Préserver exactement leurs URL, options, identifiants et paramètres. Ne jamais envoyer leur contenu dans un ticket ou une conversation.

Dans chacun des deux YAML, créer ou mettre à jour une seule occurrence de chaque section de configuration :

Production :
```yaml
api:
  listen: 127.0.0.1:1984
rtsp:
  listen: :8554
webrtc:
  listen: :8555
```

Test :
```yaml
api:
  listen: 127.0.0.1:1987
rtsp:
  listen: :8556
webrtc:
  listen: :8557
```

Conserver les autres propriétés éventuellement présentes dans ces sections (par exemple les certificats ou paramètres WebRTC) ; ne remplacer que `listen`. Ne pas créer de clés YAML en double. Les sections doivent être au niveau racine, au même niveau que `streams`.

Vérifier visuellement que chaque nom de flux est présent dans un seul YAML et que les deux fichiers contiennent une section `streams` valide. Ne pas continuer en cas de doute sur l'affectation d'un flux.

## 4. Créer la copie indépendante de production

Le binaire de production doit être une copie indépendante du binaire de test :

```bash
sudo install -d -o root -g pi -m 0750 /etc/go2rtc
sudo install -o pi -g pi -m 0755 /home/pi/go2rtc-test/go2rtc /usr/local/bin/go2rtc
```

Créer `/etc/go2rtc/go2rtc.yaml` à partir du YAML de production préparé à l'étape 3. Ne pas écraser un fichier préexistant : s'il existe, l'examiner et le sauvegarder avant toute décision.

```bash
sudo install -o pi -g pi -m 0640 /root/go2rtc-separation-work/go2rtc-production.yaml /etc/go2rtc/go2rtc.yaml
```

Le fichier d'environnement `/etc/go2rtc/go2rtc.env` sera créé par l'installateur s'il est absent. S'il existe déjà, vérifier que son unique variable `GO2RTC_CONFIG` vaut exactement `/etc/go2rtc/go2rtc.yaml`. Ne pas écraser un environnement préexistant.

## 5. Reconfigurer les deux API de contrôle

Conserver dans chaque fichier les valeurs personnalisées non concernées, notamment `TOKEN_FILE`, `SOURCE_REGISTRY` et `DASHBOARD_ORIGIN`.

Dans `/etc/go2rtc-control/go2rtc-control.env`, vérifier :
```ini
GO2RTC_API=http://127.0.0.1:1984
GO2RTC_CONFIG=/etc/go2rtc/go2rtc.yaml
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8554
CONTROL_HOST=0.0.0.0
CONTROL_PORT=1985
SOURCE_REGISTRY=/var/lib/go2rtc-control/cameras.json
```

Dans `/etc/go2rtc-control-test/go2rtc-control-test.env`, vérifier :
```ini
GO2RTC_API=http://127.0.0.1:1987
GO2RTC_CONFIG=/home/pi/go2rtc-test/go2rtc.yaml
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8556
CONTROL_HOST=127.0.0.1
CONTROL_PORT=1986
SOURCE_REGISTRY=/var/lib/go2rtc-control-test/cameras.json
```

Les deux variables `SOURCE_REGISTRY` doivent rester différentes et pointer vers les registres existants. Ne pas copier un registre par-dessus l'autre. Ne pas changer les chemins `TOKEN_FILE` et ne pas générer de nouveaux jetons.

## 6. Basculer d'abord l'environnement de test

À ce stade, les fichiers doivent avoir été sauvegardés, les deux YAML préparés, les deux registres préservés et les fichiers d'environnement vérifiés.

Installer le YAML de test préparé (après avoir vérifié qu'il ne contient que les flux de test) :

```bash
sudo install -o pi -g pi -m 0640 /root/go2rtc-separation-work/go2rtc-test.yaml /home/pi/go2rtc-test/go2rtc.yaml
```

Appliquer les nouveaux ports de test et redémarrer uniquement les services de test :

```bash
sudo systemctl daemon-reload
sudo systemctl restart go2rtc-test.service
sudo systemctl restart go2rtc-control-test.service
```

Contrôler immédiatement :

```bash
sudo systemctl --no-pager --full status go2rtc-test.service go2rtc-control-test.service
sudo ss -lntup | grep -E ':(1987|8556|8557)\b'
```

Les ports de test doivent être occupés par le processus go2rtc de test et l'API de contrôle doit rester sur `127.0.0.1:1986`. Les ports de production `1984/8554/8555` doivent être libérés par l'ancienne instance unique. Si le test ne fonctionne pas, ne pas installer ni démarrer la production : appliquer le retour arrière.

## 7. Installer et démarrer la production

Depuis le dossier `service/go2rtc-control` de la version validée du dépôt :

```bash
sudo bash install.sh
```

L'installateur vérifie le binaire et le YAML de production, installe les unités `go2rtc.service` et `go2rtc-control.service`, puis démarre uniquement les services de production. Il ne doit ni modifier ni redémarrer les unités de test.

L'installateur ne réinitialise pas le registre de production existant. Il ne doit pas remplacer le registre de test. Si l'installation s'arrête sur une vérification, ne pas contourner le contrôle : corriger la cause ou revenir en arrière.

## 8. Vérifications après bascule

```bash
sudo systemctl --no-pager --full status go2rtc.service go2rtc-control.service
sudo systemctl --no-pager --full status go2rtc-test.service go2rtc-control-test.service
sudo ss -lntup | grep -E ':(1984|1985|1986|1987|8554|8555|8556|8557)\b'
sudo journalctl -u go2rtc.service -u go2rtc-control.service -n 80 --no-pager
sudo journalctl -u go2rtc-test.service -u go2rtc-control-test.service -n 80 --no-pager
```

Résultat attendu :
- production : go2rtc sur API 1984, RTSP 8554, WebRTC 8555 ; contrôle sur 1985 ;
- test : go2rtc sur API 1987, RTSP 8556, WebRTC 8557 ; contrôle sur 127.0.0.1:1986 ;
- les deux registres restent distincts et inchangés ;
- les flux de production et de test ne sont pas chargés par l'autre instance.

Tester ensuite séparément une caméra de production et les flux de test. Vérifier les profils, préférences audio, résolutions natives et paramètres PTZ. Vérifier que le tableau de bord continue d'accéder à l'API de production sur le port 1985 et à go2rtc sur le port 1984.

## 9. Retour arrière détaillé

Effectuer le retour arrière si l'une des vérifications échoue. Ne pas supprimer les sauvegardes.

1. Arrêter et désactiver la nouvelle instance de production (si elle a été installée) :
   ```bash
   sudo systemctl disable --now go2rtc-control.service go2rtc.service
   ```
2. Restaurer les fichiers d'environnement de production et de test, les trois unités systemd, les deux registres et les deux jetons depuis la sauvegarde. Restaurer également le YAML d'origine dans `/home/pi/go2rtc-test/go2rtc.yaml`. Utiliser `cp -a` afin de préserver propriétaires et permissions. Ne jamais fusionner les registres.
3. Supprimer uniquement les nouveaux fichiers de production créés par cette migration (`/etc/go2rtc/go2rtc.yaml`, `/etc/go2rtc/go2rtc.env` et l'unité `go2rtc.service`) après avoir vérifié qu'ils n'existaient pas avant la migration. Le binaire `/usr/local/bin/go2rtc` peut être conservé ou retiré après vérification qu'aucun autre service ne l'utilise.
4. Recharger systemd et redémarrer l'ancienne instance et les contrôleurs :
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable go2rtc-test.service go2rtc-control.service go2rtc-control-test.service
   sudo systemctl restart go2rtc-test.service
   sudo systemctl restart go2rtc-control.service go2rtc-control-test.service
   ```
5. Vérifier que l'ancienne topologie est rétablie : une instance go2rtc sur 1984/8554/8555, API de production sur 0.0.0.0:1985, API de test sur 127.0.0.1:1986 ; les deux contrôleurs pointent à nouveau vers l'ancien YAML et leurs registres restent distincts.

Si la restauration d'un fichier échoue ou si les services ne reviennent pas à l'état attendu, arrêter les manipulations et conserver les journaux pour diagnostic. Ne pas supprimer les copies de sauvegarde.

Cette procédure de retour arrière est manuelle : vérifier chaque restauration avant de poursuivre. La migration n'est pas considérée comme terminée tant que les deux environnements n'ont pas été testés séparément.
