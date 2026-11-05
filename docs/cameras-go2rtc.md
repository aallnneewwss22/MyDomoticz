# Afficher des caméras RTSP avec go2rtc

Le navigateur ne lit généralement pas une URL RTSP directement. go2rtc reçoit le flux RTSP de la caméra et le rend lisible par le navigateur, en privilégiant WebRTC et en proposant MSE/HLS lorsque c'est possible.

## 1. Installer go2rtc

Téléchargez la version correspondant à l'architecture du Raspberry Pi depuis le [site officiel go2rtc](https://go2rtc.org/). Les versions Linux ARM 32 bits et ARM 64 bits sont proposées. Installez le binaire et configurez son lancement automatique (par exemple avec un service systemd), en veillant à ce que le service utilise le fichier YAML choisi.

Les valeurs habituelles des ports sont :
- TCP 1984 : interface web et API go2rtc ;
- TCP 8554 : serveur RTSP go2rtc (inutile au tableau de bord pour la lecture) ;
- TCP et UDP 8555 : transport WebRTC.

## 2. Déclarer les caméras

Utilisez [go2rtc.example.yaml](go2rtc.example.yaml) comme modèle. Remplacez les deux URL fictives par les URL RTSP connues et vérifiées dans VLC. Adaptez les noms « salon » et « entree » à vos besoins. Ce sont ces noms qui seront inscrits dans Excel.

Conservez le fichier réel, avec les identifiants, dans un répertoire de configuration local non publié par le serveur web Domoticz. Ne le placez pas dans www/templates et ne le commitez pas dans Git. L'exemple fourni dans le dépôt ne contient que des valeurs fictives.

## 3. Configurer les lignes Excel

Dans le classeur de la page (par exemple IDX2.xlsx), ajoutez une ligne comme suit :

| Colonne A | Colonne B | Colonne C |
|---|---|---|
| salon | Caméra du salon | caméra |

La colonne A est le nom du flux go2rtc, pas une URL RTSP. Les noms acceptés contiennent des lettres, chiffres, points, tirets et soulignements (80 caractères maximum). Les lignes vides conservent leur fonction de séparation de rangée. Les lignes caméra restent dans l'ordre défini par Excel.

## 4. Régler l'adresse go2rtc

Par défaut, le tableau de bord suppose que go2rtc fonctionne sur le même hôte que Domoticz, au port 1984. Si go2rtc est installé ailleurs ou utilise un autre port, ouvrez **Paramètres** et indiquez son adresse HTTP/HTTPS, par exemple http://192.168.1.21:1984. Le réglage est mémorisé dans le navigateur.

Le lecteur intégré utilise la page universelle /stream.html de go2rtc et demande les modes webrtc,mse,hls. La compatibilité réelle dépend des codecs de la caméra, du navigateur et du réseau. Pour WebRTC, le port 8555 doit aussi être joignable depuis les postes clients ; en cas d'échec, vérifiez les candidats ICE et les règles du pare-feu dans la documentation go2rtc.

## Sécurité

- Ne mettez jamais de mot de passe RTSP dans IDX*.xlsx : les classeurs sont téléchargés directement par le navigateur et peuvent être lus par les utilisateurs de la page.
- N'exposez pas le port 1984 à Internet. L'API go2rtc est puissante et doit rester limitée à un réseau de confiance ou être protégée par une configuration d'authentification/reverse proxy appropriée.
- Les personnes qui peuvent accéder au service de streaming peuvent potentiellement regarder les caméras, même si elles ne connaissent pas les identifiants RTSP.
- Si le tableau de bord est servi en HTTPS, go2rtc doit également être accessible en HTTPS : les navigateurs bloquent généralement les contenus HTTP chargés depuis une page HTTPS.

Références : [site officiel](https://go2rtc.org/), [lecteur web](https://github.com/AlexxIT/go2rtc/blob/master/www/README.md), [configuration WebRTC](https://go2rtc.org/internal/webrtc/).
