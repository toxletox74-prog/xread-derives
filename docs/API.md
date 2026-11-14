# API de Xread Dérives (Vigie)

Deux accès programmatiques au même moteur :

1. l'**API JSON** du serveur local (`vigie/serveur.py`), celle qu'utilise l'interface web ;
2. le **serveur MCP** (`vigie/mcp.py`), qui expose le moteur de dérives à un assistant IA, en lecture seule.

Les deux sont ouverts aux **services tiers** par une clé API : chaque service a son espace, une base isolée où il
importe ses relevés et obtient l'analyse de ses dérives (section 3).

Un test (`tests/test_mcp.py`) vérifie que chaque route et chaque outil MCP figure dans ce document.

## 1. API JSON

### Généralités

| | |
|---|---|
| Adresse | `http://127.0.0.1:8765` (`python -m vigie interface [--demo] [--port=8765]`) |
| Format | JSON UTF-8 en entrée et en sortie, sauf les imports (corps = fichier brut) et les téléchargements |
| Horodatages | ISO 8601 en UTC (`2026-11-14T09:51:24Z`) ; les agrégats par jour, mois, année sont en heure de Zurich |
| Taille maximale d'un envoi | 50 Mo |

**Protections** (à respecter par tout client) :

- l'en-tête `Host` doit valoir `127.0.0.1` ou `localhost` (sinon `403`) ;
- toute requête autre que `GET` doit porter l'en-tête `X-Vigie: 1` (sinon `403`), sauf avec une clé API d'espace
  (section 3) ;
- **lecture seule sans identification** dès qu'un mot de passe est défini (variable `VIGIE_MOT_DE_PASSE`) ou que la
  requête arrive par un serveur frontal (en-têtes `X-Forwarded-*`) : toute écriture, ainsi que la lecture de
  `/api/reglages` et `/api/connecteur`, exigent alors une session (témoin `vigie_session`, 12 h) ; sinon `401`.

**Erreurs** : toujours `{"erreur": "message lisible"}`.

| Code | Sens |
|---|---|
| `400` | Saisie refusée (le message dit pourquoi) |
| `401` | Session nécessaire, ou mot de passe incorrect |
| `403` | En-tête `Host` ou `X-Vigie` refusé |
| `404` | Route inconnue |
| `500` | Erreur interne (détail dans la console du serveur) |

**Exemple**

```bash
curl http://127.0.0.1:8765/api/alertes?statut=ouverte
curl -X POST -H "X-Vigie: 1" http://127.0.0.1:8765/api/analyser
```

**Chiffres.** Tous les montants (kWh, m³, CHF, CO₂) sont calculés par le moteur (règle 5). Suffixes d'une alerte :
`_mois` = rythme par 30 jours, `_mesure` = excès déjà mesuré depuis le début de la dérive, `_proj` = projection sous
l'hypothèse décrite dans `projection`, `_an` = annualisation quand elle a un sens. `null` = non calculable : ne jamais
le remplacer par zéro (règle 4).

### État et session

| Route | Rôle |
|---|---|
| `GET /api/etat` | État général : base, fin des données, dernière analyse, nombre de compteurs, `kpis` (alertes, critiques, rythmes mensuels cumulés, bons ouverts, pertinence), météo, couverture des règles, droits d'accès |
| `POST /api/session` | Ouvre une session. Corps : `{"mot_de_passe": "…"}`. Pose le témoin `vigie_session` |
| `DELETE /api/session` | Ferme la session |

### Détection : analyse, alertes, règles, rejeu

| Route | Rôle |
|---|---|
| `POST /api/analyser` | Lance la détection sur les relevés en base, enregistre les alertes, prépare ou envoie les bons selon l'automatisation. Réponse : `{donnees_au, alertes (nombre), nouvelles [ids], bons {crees, envoyes, erreurs}}` |
| `GET /api/alertes` | Alertes, de la plus prioritaire à la moins prioritaire. Paramètre `statut` : `ouverte` (défaut), `sourdine`, `resolue`, `toutes` |
| `POST /api/alertes/{id}/retour` | Avis du gestionnaire. Corps : `{"retour": "pertinente" \| "deja_connue" \| "fausse_alerte"}` |
| `POST /api/alertes/{id}/bon` | Crée le bon de travaux de l'alerte (ou renvoie le bon ouvert). Corps : `{"prestataire_id": 3}` (facultatif). Réponse : `{bon, cree}` |
| `GET /api/regles` | Règles et réglages effectifs, seuils de qualité, couverture, matrice fluide × pas de relevé |
| `PUT /api/regles/{cause}` | Règle une règle. Champs : `active`, `profils`, `seuil`, `persistance`, `gravite`, `delai`, `metier`, `consigne` |
| `DELETE /api/regles/{cause}` | Remet la règle à ses valeurs par défaut |
| `GET /api/couts` | Tarifs et facteurs CO₂ par vecteur, enjeu minimal, seuils de qualité des données |
| `PUT /api/couts` | Corps : `{"tarifs": [{vecteur, chf_par_unite, statut, co2_kg_par_kwh}], "enjeu_min_chf_mois", "silence_max_heures", "completude_min"}` |
| `GET /api/rejeu` | Dernier rejeu (`python -m vigie rejouer`) : période, nombre d'analyses, épisodes |

**Une alerte** (champs principaux) :

```json
{
  "id": "R41-chaleur_vide", "rang": 1, "gravite": "Critique", "cause": "chaleur_vide", "fluide": "Chaleur",
  "immeuble_id": "R41", "immeuble": "Immeuble Rhône 41", "adresse": "Rue du Rhône 41, 1204 Genève",
  "point_id": "R41_CHAL", "profil": "Vide",
  "titre": "Chauffage normal dans un immeuble déclaré vide",
  "constat": "L'immeuble est déclaré vide mais la chaufferie produit 867 kWh/jour depuis 9 jours…",
  "mesure": "867 kWh/jour", "attendu": "200 kWh/jour au maximum en hors-gel",
  "debut": "2026-11-02", "persistance": "9 jours", "confiance": 0.95,
  "kwh_mois": 20021, "chf_mois": 2403, "co2_t_mois": 4.6, "m3_mois": 0.0,
  "kwh_mesure": 6337, "chf_mesure": 760, "kwh_proj": 164915, "chf_proj": 19790,
  "periode": "depuis le 02.11.2026 (223 heures mesurées)",
  "projection": "sur 12 mois (hypothèse : climat normal de Genève…)",
  "consigne": "Repasser la chaufferie en mode hors-gel…", "metier": "Chauffagiste", "delai": "48 h",
  "payeur": "Propriétaire (immeuble vide)", "sinistre": false,
  "statut": "ouverte", "ouverte_le": "…", "derniere_detection": "…", "cloturee_le": null, "retour": null,
  "suivi": "en_attente", "bon": {"id": 1, "numero": "BT-2026-0001", "statut": "brouillon", "…": "…"}
}
```

`gravite` : `Critique`, `Élevée`, `Modérée`, ou `Données` (défaut de relevé, sans chiffrage). `suivi` : `en_attente`,
`bon_envoye`, `retour_incident`, `a_verifier`, `cloturee`, `sourdine`. Une alerte en sourdine porte un objet `sourdine`.

### Parc : adresses, immeubles, compteurs

| Route | Rôle |
|---|---|
| `GET /api/parc` | Arbre adresses → immeubles → compteurs (état des données, complétude, alertes), points météo, listes de choix |
| `POST /api/immeubles` | Crée ou modifie un immeuble. Champs : `id`, `nom`, `rue`, `npa_localite`, `profil` (`Habite`, `Partiel`, `Vide`, `Travaux`), `taux_occupation`, `logements`, `sre_m2`, `talon_horsgel_kwh_j`, `proprietaire`, `remarque`, `latitude`, `longitude`. Une nouvelle adresse est géocodée (adresse seule envoyée au géocodeur fédéral) |
| `DELETE /api/immeubles/{id}` | Supprime l'immeuble |
| `POST /api/compteurs` | Crée ou modifie un compteur. Champs : `id`, `immeuble_id`, `libelle`, `fluide`, `unite`, `nature` (`index`, `intervalle`, `instantane`, `livraison`), `pas_min`, `etat` (`actif`, `a_connecter`, `inactif`), `source`, `identifiant`, `fournisseur` ; solaire : `puissance_crete_kwc`, `production_prevue_kwh_an`, `mise_en_service`, `degradation_pct_an`. Réponse : `{compteur, avertissements}` |
| `DELETE /api/compteurs/{id}` | Supprime le compteur |
| `GET /api/serie/{id}` | Consommation par jour d'un compteur (affichage). Paramètre `jours` : 7 à 365, défaut 60 |
| `GET /api/consommation/{id}` | Consommation agrégée. Paramètre `echelle` : `jour` (90 derniers), `mois` (60), `annee` (10). Chaque valeur : `{periode, valeur, mesures, estimee}` |
| `GET /api/immeubles/{id}/fiche` | Fiche : contacts, technique, partenaires par fluide, bâtiments, installations, alertes, historique, déclarations |
| `PUT /api/immeubles/{id}/fiche` | Enregistre contacts (`gestionnaire`, `concierge`, e-mails, téléphones) et données `technique` |
| `GET /api/immeubles/{id}/declarations` | Sourdines, périodes de travaux ou de vacance, changements déclarés |
| `POST /api/immeubles/{id}/declarations` | Corps : `type` (`sourdine`, `travaux`, `vacance`, `changement`), `debut`, `fin`, `motif`, `auteur`, `cause` (sourdine), `point_id` (changement) |
| `DELETE /api/declarations/{id}` | Supprime la déclaration |
| `GET /api/carte` | Adresses avec coordonnées, immeubles, alertes ouvertes et état le plus grave ; adresse des tuiles swisstopo |
| `POST /api/geocoder` | Géocode les adresses sans coordonnées (géocodeur fédéral) |
| `PUT /api/adresses/{id}/coordonnees` | Corps : `{"lat": 46.2, "lon": 6.15}` (position saisie à la main) |

### Bons de travaux et prestataires

| Route | Rôle |
|---|---|
| `GET /api/bons` | Tous les bons, du plus récent au plus ancien |
| `GET /api/bons/{id}` | Un bon : objet, corps, destinataire, statut, journal, résumé de l'alerte, destinataires possibles |
| `PUT /api/bons/{id}` | Modifie un brouillon (`objet`, `corps`, `destinataire`, `prestataire_id`) ou change le `statut` (`brouillon`, `envoye`, `en_cours`, `retour`, `termine`, `annule`), avec `commentaire` facultatif |
| `PUT /api/bons/{id}/destinataire` | Corps : `{"destinataire_type": "concierge" \| "partenaire"}` (brouillon seulement) |
| `POST /api/bons/{id}/envoyer` | Envoie le bon par courriel (SMTP réglé dans Réglages) |
| `GET /api/bons/{id}/eml` | Télécharge le bon au format `.eml` |
| `POST /api/bons/{id}/retour` | Retour d'intervention. Corps : `resultat` (`resolu`, `non_resolu`, `a_suivre`, …), `texte`, `le` (facultatif) |
| `GET /api/prestataires` | Prestataires, métiers, métiers requis par les règles actives |
| `POST /api/prestataires` | Crée un prestataire. Champs : `nom`, `metier`, `contact`, `email`, `telephone`, `perimetre` (identifiants d'immeubles séparés par des virgules), `actif` |
| `PUT /api/prestataires/{id}` | Modifie le prestataire (mêmes champs) |
| `DELETE /api/prestataires/{id}` | Supprime le prestataire, ou le désactive s'il a des bons |

### Imports et exports

Le corps de la requête est le fichier lui-même. Sans `appliquer=1`, la réponse est un **aperçu** : rien n'est écrit.

| Route | Rôle |
|---|---|
| `POST /api/import/mesures` | Relevés `ts,point_id,valeur` en CSV ou `.xlsx`. Réponse : `{importees, rejets, lot, detail_rejets}` |
| `POST /api/import/parc` | Classeur du parc (`.xlsx`). Paramètre `appliquer` |
| `GET /api/export/parc` | Télécharge le parc en `.xlsx` |
| `POST /api/import/patrimoine` | Classeur patrimoine (sites, bâtiments, compteurs, relevés mensuels). Paramètre `appliquer` |
| `GET /api/import/patrimoine` | Dernier import patrimoine et anomalies d'import conservées en base |
| `POST /api/import/courbes` | Courbes au jour, à l'heure ou au quart d'heure (CSV), ou calendrier d'un classeur. Paramètres `appliquer`, `nom` (nom du fichier) |
| `POST /api/exemple` | Charge le parc d'exemple fictif dans une base vide, puis analyse |

### Réglages, météo, connecteur

| Route | Rôle |
|---|---|
| `GET /api/reglages` | Automatisation des bons, messagerie, analyse automatique (lecture réservée) |
| `PUT /api/reglages` | Corps : `automatisation` (`mode` : `manuel`, `brouillon`, `envoi` ; `gravite_min` ; `inclure_donnees` ; `analyse_auto`, `analyse_intervalle_h`), `messagerie` (`expediteur_nom`, `expediteur_email`, `copie_a`, `signature`, `smtp_hote`, `smtp_port`, `smtp_securite`, `smtp_utilisateur`), `mot_de_passe` (SMTP, gardé en mémoire seulement) |
| `GET /api/meteo` | Source, station, dernière mise à jour, statut de la météo |
| `PUT /api/meteo` | Règle la météo (`station`, `auto`) |
| `POST /api/meteo/maj` | Met à jour température et rayonnement depuis MétéoSuisse |
| `GET /api/connecteur` | Réglages du connecteur API du fournisseur de télérelève (lecture réservée ; la clé n'est jamais renvoyée) |
| `PUT /api/connecteur` | Règle le connecteur : `actif`, `fournisseur`, `url_base`, `auth`, `auth_nom`, `chemin`, `format`, `json_liste`, `json_ts`, `json_valeur`, `historique_j`, `recul_h`, `auto`, `intervalle_h`, `cle` |
| `DELETE /api/connecteur/cle` | Efface la clé API enregistrée |
| `POST /api/connecteur/tester` | Appel d'essai au fournisseur, sans rien écrire |
| `POST /api/connecteur/synchroniser` | Relève les compteurs dont la source est « API du fournisseur » |
| `POST /api/connecteur/demo` | Branche le fournisseur de démonstration (base d'exemple seulement) |
| `GET /demo-fournisseur/points/{identifiant}/mesures` | Fournisseur de démonstration. Paramètres `debut`, `fin` (UTC) ; en-tête `X-API-Key` |

## 2. Serveur MCP du moteur de dérives

Le serveur MCP (Model Context Protocol) permet à un assistant IA (Claude Code, Claude Desktop, tout client MCP)
d'interroger le moteur : « quelles dérives coûtent le plus ce mois ? », « que s'est-il passé à Rhône 41 ? ».

```bash
python -m vigie mcp --demo    # base d'exemple (données fictives)
python -m vigie mcp           # vigie.db
```

- **Transport stdio**, JSON-RPC 2.0, un message par ligne. Aucun port ouvert, aucun appel réseau, aucune dépendance.
  Également servi sur HTTP (`POST /mcp`) aux services tiers munis d'une clé, sur leur espace (section 3).
- **Lecture seule.** Aucun outil ne modifie la base, n'envoie de bon, ne change un réglage. Les décisions (valider un
  bon, mettre une alerte en sourdine, régler un seuil) restent dans l'interface.
- **Règle 5.** Les chiffres renvoyés sont ceux du moteur ; les consignes du serveur demandent à l'assistant de les
  citer tels quels et de signaler une valeur manquante au lieu de la combler.
- **Règle 9, à lire avant de brancher un vrai parc.** Le serveur n'émet rien lui-même, mais ce que les outils renvoient
  est lu par l'assistant. Avec un modèle hébergé, les alertes et leurs chiffres quittent donc le poste. À utiliser sur
  la base d'exemple, ou sur un parc dont le détenteur des données l'a accepté. Les courbes de consommation ne sont
  pas exposées.

### Outils

| Outil | Paramètres | Renvoie |
|---|---|---|
| `etat` | — | Comme `GET /api/etat`, sans les droits d'accès |
| `lister_alertes` | `statut` (`ouverte` par défaut, `sourdine`, `resolue`, `toutes`), `immeuble_id`, `gravite` | Résumé des alertes, par priorité : immeuble, fluide, gravité, constat, début, rythme mensuel, suivi |
| `lire_alerte` | `id` (obligatoire) | L'alerte complète (voir « Une alerte ») |
| `lire_parc` | — | Adresses, immeubles, compteurs : fluide, pas de relevé, état, dernier relevé, complétude |
| `lire_immeuble` | `id` (obligatoire) | Comme `GET /api/immeubles/{id}/fiche`, sans les listes de choix |
| `lister_regles` | — | Règles et réglages effectifs, seuils de qualité, couverture |
| `analyser_a_blanc` | — | Détection calculée sur les relevés actuels **sans rien enregistrer**, et l'écart avec les alertes ouvertes en base (`absentes_de_la_base`, `plus_detectees`) |
| `lister_bons` | — | Comme `GET /api/bons` |
| `lire_rejeu` | — | Comme `GET /api/rejeu` |

Une saisie refusée (identifiant inconnu, paramètre en trop) revient comme résultat d'outil `isError: true` avec
`{"erreur": "…"}`, pour que l'assistant se corrige.

### Branchement

Claude Code, depuis la racine du dépôt :

```bash
claude mcp add xread-derives -- python -m vigie mcp --demo
```

Claude Desktop ou tout autre client (fichier de configuration MCP) :

```json
{
  "mcpServers": {
    "xread-derives": {
      "command": "python",
      "args": ["C:/chemin/vers/xread-derives/lancer_vigie.py", "mcp", "--demo"]
    }
  }
}
```

`lancer_vigie.py` fonctionne depuis n'importe quel dossier ; avec un environnement virtuel, donner le chemin de son
interpréteur Python à la place de `python`.

Client MCP distant (transport HTTP, section 3) :

```json
{
  "mcpServers": {
    "xread-derives": {
      "type": "http",
      "url": "https://xread-derive.brochardbenjamin.com/mcp",
      "headers": {"Authorization": "Bearer vgk_…"}
    }
  }
}
```

## 3. Services tiers : espaces et clés API

Un service tiers (application, plateforme de télérelève, assistant IA hébergé) utilise le moteur sur **ses propres
données**. Il reçoit une clé API liée à un **espace** : une base Vigie isolée (`espaces/<id>/vigie.db`, sorties dans
`espaces/<id>/sorties/`). Il y importe son parc et ses relevés, lance l'analyse et lit ses dérives. Il ne voit jamais
la base principale ni l'espace d'un autre service.

### Clés

Sur le serveur :

```bash
python -m vigie espace creer acme --nom="ACME Énergie"   # crée l'espace et affiche une nouvelle clé (une seule fois)
python -m vigie espace lister                            # espaces et clés actives ou révoquées
python -m vigie espace revoquer acme                     # révoque les clés de l'espace (la base est gardée)
```

La clé (`vgk_…`) n'est affichée qu'à sa création ; le registre (`espaces/registre.db`) ne garde que son empreinte
SHA-256. Pour changer de clé : `creer` sur le même espace (nouvelle clé, mêmes données), puis `revoquer` l'ancienne
si besoin (`revoquer` les révoque toutes).

### Appels

Toute requête qui porte `Authorization: Bearer <clé>` travaille sur l'espace de la clé, en lecture **et** en écriture :
mêmes routes et mêmes réponses que la section 1, sans session ni en-tête `X-Vigie`. Clé absente, inconnue ou
révoquée : `401`.

```bash
CLE="vgk_…" ; URL="https://xread-derive.brochardbenjamin.com"
curl -H "Authorization: Bearer $CLE" --data-binary @parc.xlsx "$URL/api/import/parc?appliquer=1"
curl -H "Authorization: Bearer $CLE" --data-binary @releves.csv "$URL/api/import/mesures"
curl -H "Authorization: Bearer $CLE" -X POST "$URL/api/meteo/maj"     # température MétéoSuisse de l'espace
curl -H "Authorization: Bearer $CLE" -X POST "$URL/api/analyser"
curl -H "Authorization: Bearer $CLE" "$URL/api/alertes"
```

Parcours type : parc (`/api/import/parc` ou `/api/import/patrimoine`), relevés (`/api/import/mesures` ou
`/api/import/courbes`), météo (`POST /api/meteo/maj` : la mise à jour automatique toutes les 3 h et l'analyse
planifiée ne tournent que pour la base principale), analyse (`POST /api/analyser`), puis alertes et bons.

**Routes interdites aux espaces** (`403`) : `/api/session`, `/api/reglages` (messagerie), `/api/mcp…`, `/api/connecteur…`
(fournisseur de télérelève), `/api/exemple`, `POST /api/bons/{id}/envoyer` et `/demo-fournisseur/…`. Rien ne sort
du serveur au nom d'un espace : ni courriel, ni appel à un fournisseur. Les bons se préparent et se lisent
(`GET /api/bons/{id}/eml`), le service les transmet lui-même.

### Claude (MCP) sur la base principale

Une personne connectée à l'interface (bouton « Claude (MCP) » du bandeau) génère une clé qui ouvre `/mcp` sur la
**base principale**, et rien d'autre (toute route de l'API : `403`). Une seule clé active : en générer une nouvelle
révoque la précédente. Routes réservées (session, ou poste local) :

| Route | Rôle |
|---|---|
| `GET /api/mcp` | `{chemin: "/mcp", cle_creee}` : date de création de la clé active, ou `null` |
| `POST /api/mcp/cle` | Nouvelle clé (`{chemin, cle}`), affichée une seule fois ; l'ancienne cesse de fonctionner |
| `DELETE /api/mcp/cle` | Révoque la clé (`{revoquees}`) |

### MCP sur HTTP

`POST /mcp` avec la clé : un message JSON-RPC (ou un lot) par requête, réponse `application/json` ; `202` sans corps
pour une notification. Transport « Streamable HTTP » sans flux SSE ni session (`GET /mcp` : `405`). Mêmes outils en
lecture seule que la section 2, sur la base de l'espace de la clé.

```bash
curl -H "Authorization: Bearer $CLE" -H "Content-Type: application/json"      -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"lister_alertes","arguments":{}}}' "$URL/mcp"
```

**Règle 9.** Les données d'un espace sont celles que le service a lui-même envoyées ; elles ne sont rendues qu'à qui
présente sa clé. La base principale n'est jamais exposée par une clé.
