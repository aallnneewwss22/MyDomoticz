# Accès distant à Domoticz avec WireGuard et Freebox

Ce document décrit la configuration validée pour accéder au réseau domestique et au tableau de bord MyDomoticz depuis l'extérieur, sans exposer directement les services Domoticz ou go2rtc sur Internet.

## Architecture retenue

- La Freebox Révolution héberge le serveur VPN WireGuard.
- Chaque appareil dispose de son propre profil WireGuard et de ses propres clés : par exemple un profil pour le PC et un autre pour le smartphone.
- Le tunnel est configuré en **split tunnel** : seul le trafic destiné aux réseaux domestiques passe par le VPN. Le trafic Internet ordinaire continue d'utiliser la connexion de l'appareil.
- Aucun port de l'API go2rtc-control (1985) ni de l'API go2rtc (1984) n'est exposé directement sur Internet pour cet accès distant.

Pour le profil Android validé, le champ `AllowedIPs` contient :

```ini
AllowedIPs = 192.168.27.64/27, 192.168.1.0/24
```

Ces réseaux correspondent respectivement au réseau WireGuard de la Freebox et au réseau local domestique de l'installation. **Ne pas ajouter `0.0.0.0/0`** pour cette architecture : cela ferait passer tout le trafic IPv4 dans le VPN et changerait le fonctionnement du tunnel fractionné.

Les plages ci-dessus sont celles de l'installation testée ; elles doivent être adaptées si le plan d'adressage de la Freebox ou du réseau local change.

## Particularité DNS sur Android

### Symptômes rencontrés

Sur un Poco M4 Pro 5G connecté en données mobiles :

- WireGuard permettait d'ouvrir Domoticz et le tableau de bord personnalisé ;
- les fichiers Excel IDX étaient accessibles directement ;
- en revanche, les noms de domaines Internet ne se résolvaient plus lorsque WireGuard était actif (Firefox : « Adresse introuvable » ; Chrome : `DNS_PROBE_FINISHED_BAD_CONFIG`) ;
- Google et d'autres sites redevenaient accessibles dès la désactivation de WireGuard.

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

La correction a été validée sur le smartphone Android décrit ci-dessus. Ne pas en déduire que tous les profils WireGuard ou toutes les versions Android nécessitent exactement le même réglage : vérifier le champ DNS et tester la résolution de noms sur chaque appareil concerné.

## Contrôles en cas de problème similaire

Avec WireGuard activé sur l'appareil :

1. Vérifier que les adresses des services domestiques restent accessibles.
2. Tester un site Internet connu par son nom de domaine.
3. Désactiver WireGuard et refaire le même test pour confirmer que la panne est liée au VPN.
4. Sur Android, examiner le champ DNS du profil WireGuard avant de modifier le réglage système **DNS privé**.
5. Si le champ DNS contient un serveur imposé par le profil et que la résolution échoue, tester sa suppression dans le profil concerné, sans modifier simultanément les routes `AllowedIPs`.

Ne pas partager les fichiers de configuration WireGuard, les QR codes ou les clés privées : chaque appareil doit conserver son profil personnel.

## Périmètre de cette configuration

Cette documentation concerne l'accès distant au réseau domestique par le serveur WireGuard intégré à la Freebox Révolution. Elle ne décrit pas une exposition publique des services ni une installation VPN sur le Raspberry Pi. Aucun changement du système Domoticz, du service go2rtc-control ou de go2rtc n'a été nécessaire pour corriger le problème DNS Android.
