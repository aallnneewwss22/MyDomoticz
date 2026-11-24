# Accès distant à Domoticz avec WireGuard et Freebox

Ce guide décrit la configuration validée pour accéder au réseau domestique et au tableau de bord MyDomoticz depuis l'extérieur, sur un PC Windows ou un smartphone Android, sans exposer directement les services Domoticz ou go2rtc sur Internet.

## 1. Architecture retenue

- La Freebox Révolution héberge le serveur VPN WireGuard.
- Chaque appareil dispose de son propre profil WireGuard et de ses propres clés : un profil pour le PC et un autre pour le smartphone.
- Le tunnel est configuré en **tunnel fractionné** (*split tunnel*) : seul le trafic destiné aux réseaux domestiques passe par le VPN. Le trafic Internet ordinaire continue d'utiliser la connexion de l'appareil.
- Aucun port de l'API go2rtc-control (1985) ni de l'API go2rtc (1984) n'est exposé directement sur Internet pour cet accès distant.
- Aucun logiciel VPN supplémentaire n'est installé sur le Raspberry Pi : le serveur WireGuard de la Freebox assure l'accès distant.

Les plages `AllowedIPs` validées sur les profils PC et Android sont :

```ini
AllowedIPs = 192.168.27.64/27, 192.168.1.0/24
```

Elles correspondent respectivement au réseau WireGuard de la Freebox et au réseau local domestique de l'installation. **Ne pas ajouter `0.0.0.0/0`** dans cette architecture : cela ferait passer tout le trafic IPv4 dans le VPN et transformerait le tunnel fractionné en tunnel intégral.

Ces plages sont celles de l'installation testée ; elles doivent être adaptées si le plan d'adressage de la Freebox ou du réseau local change.

## 2. Accès depuis un PC extérieur (Windows)

### Préparation à domicile

1. Activer et configurer le serveur WireGuard dans Freebox OS.
2. Créer un profil WireGuard dédié au PC, nommé par exemple `PC-Domoticz`.
3. Exporter le fichier de configuration `.conf` correspondant.
4. Conserver ce fichier dans un emplacement sûr : il contient une clé privée et ne doit être transmis à personne.

### Configuration du PC

1. Installer le client officiel WireGuard pour Windows.
2. Importer le fichier `.conf` créé pour le PC (option d'importation d'un tunnel depuis un fichier).
3. Modifier le profil si nécessaire pour conserver uniquement les réseaux domestiques dans `AllowedIPs` :

   ```ini
   AllowedIPs = 192.168.27.64/27, 192.168.1.0/24
   ```

   Si le profil exporté contient également `0.0.0.0/0`, retirer cette seule entrée afin de garder le tunnel fractionné. Ne pas modifier les clés ni les autres paramètres sans raison.
4. Enregistrer le profil.

### Connexion depuis l'extérieur

1. Connecter le PC à Internet depuis un réseau extérieur (autre Wi-Fi ou partage de connexion du smartphone, par exemple).
2. Activer le tunnel `PC-Domoticz` dans WireGuard.
3. Ouvrir Domoticz avec son adresse habituelle sur le réseau local, en utilisant l'adresse IP privée du Raspberry Pi et le port configuré dans l'installation.
4. Ouvrir le tableau de bord personnalisé et vérifier les fonctions nécessaires, notamment les cartes caméra.

Le test réalisé depuis un partage de connexion mobile, avec PIA désactivé, a confirmé l'accès à Domoticz, au tableau de bord et aux fonctions caméra. PIA n'est pas nécessaire pour accéder au réseau domestique par WireGuard ; s'il perturbe les routes ou les tests, le désactiver temporairement pendant cet accès.

## 3. Accès depuis un smartphone Android

### Préparation à domicile

1. Dans Freebox OS, créer un profil WireGuard distinct pour le smartphone, par exemple `Smartphone-Domoticz`.
2. Afficher ou exporter le QR code de ce profil.
3. Ne pas réutiliser le profil du PC : chaque appareil doit avoir ses propres clés et son propre profil.

### Configuration du smartphone

1. Installer l'application officielle **WireGuard** depuis la boutique Android.
2. Ajouter un tunnel en scannant le QR code fourni par Freebox OS.
3. Vérifier que le profil utilise les réseaux domestiques dans `AllowedIPs` :

   ```ini
   AllowedIPs = 192.168.27.64/27, 192.168.1.0/24
   ```

4. Dans le champ **DNS servers / Serveurs DNS** du profil, laisser le champ vide pour la configuration Android validée ici. La correction du problème DNS est détaillée à la section suivante.
5. Enregistrer le profil.

### Connexion depuis l'extérieur

1. Utiliser les données mobiles (4G/5G) ou un Wi-Fi extérieur.
2. Activer le tunnel `Smartphone-Domoticz` dans l'application WireGuard.
3. Ouvrir Domoticz avec son adresse IP privée habituelle.
4. Ouvrir le tableau de bord personnalisé et vérifier le chargement des classeurs IDX ainsi que les fonctions caméra.

Sur le Poco M4 Pro 5G testé, l'accès distant complet a été validé en données mobiles : Domoticz, page personnalisée, fichiers Excel IDX, import/restauration des paramètres et fonctions caméra.

## 4. Particularité DNS rencontrée sur Android

### Symptômes

Sur le Poco M4 Pro 5G connecté en données mobiles :

- WireGuard permettait d'ouvrir Domoticz et le tableau de bord personnalisé ;
- les fichiers Excel IDX étaient accessibles directement ;
- les noms de domaines Internet ne se résolvaient plus lorsque WireGuard était actif (Firefox : « Adresse introuvable » ; Chrome : `DNS_PROBE_FINISHED_BAD_CONFIG`) ;
- Google et les autres sites redevenaient accessibles dès la désactivation de WireGuard.

Le réglage Android **DNS privé** était sur « Automatique ». Le passer temporairement sur « Désactivé » n'a pas corrigé le problème.

### Cause identifiée

Le profil WireGuard Android exporté par la Freebox contenait le serveur DNS `212.27.38.253`. Avec le tunnel fractionné utilisé, ce DNS configuré dans le profil provoquait l'échec de la résolution des noms de domaines depuis le smartphone.

### Correction validée

Dans l'application WireGuard sur Android :

1. Ouvrir le profil du smartphone et choisir **Modifier** (icône crayon).
2. Dans le champ **DNS servers / Serveurs DNS**, supprimer uniquement l'adresse `212.27.38.253`.
3. Laisser le champ DNS vide.
4. Enregistrer le profil.
5. Conserver le DNS privé Android sur **Automatique**.
6. Conserver les `AllowedIPs` du tunnel fractionné.

Après cette correction, avec WireGuard activé, les sites Internet se sont ouverts normalement et les tests suivants ont tous réussi :

- accès à Domoticz et au tableau de bord personnalisé ;
- détection et chargement des classeurs IDX ;
- accès aux fonctions et aux flux des caméras.

La correction a été validée sur le smartphone Android décrit ci-dessus. Ne pas en déduire que tous les profils WireGuard ou toutes les versions Android nécessitent exactement le même réglage : vérifier le champ DNS et tester la résolution de noms sur chaque appareil concerné. La documentation ne recommande pas de supprimer un serveur DNS d'autres profils sans avoir vérifié leur comportement.

## 5. Contrôles en cas de problème

Avec WireGuard activé sur l'appareil :

1. Vérifier que l'adresse IP privée de Domoticz reste accessible.
2. Tester un site Internet connu par son nom de domaine.
3. Désactiver WireGuard et refaire le même test pour confirmer que la panne est liée au VPN.
4. Sur Android, examiner le champ DNS du profil WireGuard avant de modifier le réglage système **DNS privé**.
5. Vérifier que `AllowedIPs` ne contient pas `0.0.0.0/0` si l'objectif est de conserver le tunnel fractionné.
6. Ne modifier qu'un paramètre à la fois, puis refaire les tests d'accès local et Internet.

Ne pas partager les fichiers de configuration WireGuard, les QR codes ou les clés privées : chaque appareil doit conserver son profil personnel. Si un profil est compromis, le révoquer et en générer un nouveau depuis Freebox OS.

## 6. Périmètre et sécurité

Cette configuration concerne l'accès distant au réseau domestique par le serveur WireGuard intégré à la Freebox Révolution. Elle ne décrit pas une exposition publique des services ni une installation VPN sur le Raspberry Pi. Aucun changement du système Domoticz, du service go2rtc-control ou de go2rtc n'a été nécessaire pour corriger le problème DNS Android.

Le tunnel fractionné limite le trafic envoyé dans le VPN aux réseaux déclarés. Il ne remplace pas les protections d'authentification des services domestiques. Garder les profils WireGuard et leurs clés privées confidentiels.
