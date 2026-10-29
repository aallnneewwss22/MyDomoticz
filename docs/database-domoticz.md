# Repères sur `domoticz.db`

Le schéma de la base SQLite peut varier selon la version de Domoticz. Commencer par examiner la structure locale :

```sql
PRAGMA table_info(DeviceStatus);
```

Sur de nombreuses versions, `DeviceStatus.ID` correspond à l'identifiant `idx` exposé par l'API et `DeviceStatus.Name` contient le nom de l'équipement. À vérifier sur la base réellement utilisée.

```sql
SELECT ID AS idx, Name
FROM DeviceStatus
ORDER BY ID;
```

Effectuer les requêtes sur une copie de la base ou en lecture seule. Ne pas modifier directement la base Domoticz en fonctionnement et ne jamais ajouter de copie de la base au dépôt Git.
