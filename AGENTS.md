# AGENTS.md — Xread Dérives (Vigie)

Guide destiné aux agents de code (Codex, Claude Code…) et aux développeurs. Il décrit l'arborescence, le rôle de
chaque fichier et les règles à respecter. La documentation fonctionnelle complète est dans `README.md`.

## En bref

- **Quoi** : détecteur de dérives de consommation (électricité, gaz, chaleur, CAD, PAC, eau, solaire) d'un parc
  immobilier, avec interface web de gestion, alertes chiffrées et bons de travaux envoyés aux prestataires.
- **Stack** : Python ≥ 3.9 (3.12 en production). Dépendances : `pandas`, `numpy` uniquement (`requirements.txt`).
  Serveur HTTP de la bibliothèque standard, base SQLite, interface en HTML/CSS/JavaScript sans framework ni build.
- **Langue** : code, identifiants, commentaires, messages et commits sont en **français**. Garder cette convention.
- **Paquet principal** : `vigie/` (« Vigie » = nom interne de Xread Dérives).

## Commandes

```bash
pip install -r requirements.txt
python -m unittest discover -s tests        # 281 tests, ~120 s, doivent rester verts (2 ignorés hors DPAPI Windows)
python -m vigie interface                   # interface sur vigie.db → http://127.0.0.1:8765
python -m vigie interface --demo            # interface sur la base d'exemple vigie_demo.db
python -m vigie analyser                    # détection sur vigie.db, écrit sorties/
python -m vigie importer-patrimoine <classeur.xlsx> [--apercu]
python -m vigie importer-courbes <fichier.csv|.xlsx> [...] [--apercu]
python -m vigie mcp [--demo]                # serveur MCP en lecture seule (stdio) pour un assistant IA
```

Toutes les sous-commandes sont listées dans la docstring de `vigie/__main__.py`.
Les scripts de `evaluation/` demandent en plus `matplotlib` et `reportlab` (absents de `requirements.txt`).

## Arborescence

```
xread-derives/
├── AGENTS.md                  ce guide
├── README.md                  documentation fonctionnelle (méthodes, imports, écrans, validation)
├── LICENSE · LICENCES_TIERS.md  MIT ; licences des données et composants tiers (Leaflet, lot communal)
├── requirements.txt           pandas, numpy
├── lancer_vigie.py            lanceur utilisable depuis n'importe quel dossier (ajoute la racine au sys.path)
├── Lancer Vigie.bat           double-clic Windows → lancer_vigie.py interface
├── deploy.sh                  redéploiement sur le VPS de production (voir « Production »)
│
├── vigie/                     ─── APPLICATION ───
│   ├── __main__.py            ligne de commande : interface, demo, analyser, importer-*, meteo, rejouer…
│   ├── serveur.py             serveur HTTP local + API JSON (table `routes` dans Application.__init__)
│   ├── acces.py               lecture seule sans identification, session par mot de passe (VIGIE_MOT_DE_PASSE)
│   ├── planification.py       analyse automatique (toutes les N heures, après un relevé API)
│   ├── service.py             enchaînement partagé CLI/web : référentiel → moteur → sorties → alertes → bons
│   ├── mcp.py                 serveur MCP (stdio, JSON-RPC) : le moteur interrogé par un assistant IA, lecture seule
│   │
│   │   Détection (le cœur métier)
│   ├── moteur.py              qualité → attendu → détecteurs → impact → priorisation → consignes
│   ├── regles.py              textes et réglages par défaut des règles ; matrice fluide × pas de relevé
│   ├── complements.py         détecteurs V0.3 : eau au jour, retour du CAD, injection solaire
│   ├── historique.py          comparaison au même mois des années précédentes (tous fluides)
│   ├── solaire.py             production PV à ensoleillement égal : décote, panne, dégradation, arrêt
│   ├── calendrier.py          type de jour (ouvré, vacances, non ouvré) pour comparer des jours semblables
│   ├── chiffrage.py           dérive constatée, rythme mensuel, projection (kWh, m³, CHF, CO₂)
│   ├── rejeu.py               détection rejouée jour par jour sur une période passée
│   ├── series.py              lecture des mesures et séries par compteur, préparées une fois puis tronquées
│   ├── declarations.py        sourdines, travaux et vacance datés, changements déclarés par immeuble
│   ├── recoupement.py         cause commune à plusieurs immeubles (alertes groupées les mêmes jours)
│   │
│   │   Données et imports
│   ├── db.py                  SQLite (même modèle que sql/schema_timescaledb.sql), import CSV, référentiel
│   ├── parc.py                adresses, immeubles, compteurs, prestataires, règles ; validations `valider_*`
│   ├── patrimoine.py          import du classeur patrimoine (sites, bâtiments, compteurs, relevés mensuels)
│   ├── courbes.py             import des courbes fines (jour, heure, quart d'heure) et du calendrier
│   ├── excel.py               lecture/écriture .xlsx sans dépendance (zip + XML)
│   ├── connecteur.py          relevés par API d'un fournisseur (+ fournisseur de démonstration)
│   ├── meteo.py               température et rayonnement MétéoSuisse (Genève-Cointrin), mise à jour auto
│   ├── geo.py                 géocodage des adresses (api3.geo.admin.ch) et positions des sites fictifs
│   ├── secret.py              protection de la clé API (DPAPI Windows ; ailleurs : variable d'environnement)
│   │
│   │   Sorties et suivi
│   ├── bons.py                alertes ouvertes/résolues, choix du prestataire, bons de travaux, envoi SMTP/.eml
│   ├── rapport.py             sorties/rapport.html, alertes.json, alertes.csv
│   ├── generer_demo.py        jeu d'exemple fictif (12 mois horaires, dérives injectées)
│   │
│   └── web/                   interface (modules ES, servis tels quels, pas de build)
│       ├── index.html         page unique
│       ├── app.js             navigation entre écrans, bandeau d'état
│       ├── outils.js          appels API (en-tête X-Vigie), construction DOM `h()`, formats, dialogues
│       ├── pages_suivi.js     tableau de bord, alertes, bons de travaux
│       ├── pages_parc.js      adresses, immeubles, compteurs, imports
│       ├── pages_reglages.js  prestataires, règles et coûts, automatisation, messagerie
│       ├── fiche.js           fiche technique d'un immeuble
│       ├── carte.js           carte du parc (swisstopo + Leaflet)
│       ├── connecteur.js      réglages du connecteur API
│       ├── rejeu.js           écran du rejeu
│       ├── icones.js          pictogrammes SVG construits dans le DOM
│       ├── app.css            styles, jetons de couleur clair/sombre
│       └── leaflet.js · leaflet.css   Leaflet 1.9.4 (tiers, NE PAS MODIFIER)
│
├── tests/                     ─── TESTS (unittest, un fichier par domaine) ───
│   ├── commun.py              base d'exemple créée une fois puis copiée pour chaque test
│   └── test_*.py              bons, chiffrage, connecteur, fluides, geo, historique, historique_fluides,
│                              import_mesures, meteo, methodes_par_pas, onduleur, pac, parc, patrimoine,
│                              mcp, rejeu, serveur, solaire (aucun accès réseau, aucun courriel réel)
│
├── evaluation/                ─── CAMPAGNE D'ÉVALUATION ET DOCUMENTS PDF (hors application) ───
│   ├── campagne.py · analyse.py · figures.py   simulation → métriques → figures
│   ├── simulateur.py          consommations fictives à dérive d'ampleur et de date réglables
│   ├── biais.py · chiffrage.py · donnees.py · temps.py · validation.py   expériences ciblées
│   ├── climat_gve.py · meteo_gve.py   climat et météo réels de Genève (cache figé)
│   ├── generer_electricite_15min.py   courbes élec 15 min fictives du lot communal
│   ├── pdf*.py                → docs/*.pdf (reportlab)
│   ├── reference/moteur_v0_2_0.py   copie FIGÉE du moteur V0.2.0 (point de comparaison, ne pas modifier)
│   └── sorties/               résultats générés par la campagne (versionnés, ne pas éditer à la main)
│
├── config/
│   ├── referentiel.json       parc d'exemple et valeurs par défaut (paramètres, tarifs, facteurs CO₂)
│   └── exemple_grand.json     grand exemple (24 adresses, 15 dérives)
├── sql/schema_timescaledb.sql schéma cible PostgreSQL + TimescaleDB (le prototype utilise SQLite)
├── docs/                      API.md (API JSON et serveur MCP) ; PDF générés par evaluation/ (méthodes, évaluation…)
├── exemple de données fluides/  modèles et exemples de fichiers de relevés à importer (fictifs)
└── donnees/                   jeux de données du lot communal, déposés localement (NON versionnés)
```

**Non versionnés (`.gitignore`)** : `*.db` (`vigie.db`, `vigie_demo.db`), `sorties/` (régénéré à chaque analyse),
`donnees/*`, `.venv/`, `.env*`. `video-teaser/` (projet Remotion de vidéo promotionnelle, Node) est hors application.

## Flux de données

```
fichiers (CSV, .xlsx) / API fournisseur / MétéoSuisse
        │  db.py · patrimoine.py · courbes.py · connecteur.py · meteo.py
        ▼
   vigie.db (SQLite) ──► db.referentiel(cx) ──► moteur.py (+ complements, historique, solaire, calendrier)
                                                     │  chiffrage.py
                                                     ▼
                                    service.analyser ──► rapport.py (sorties/) ──► bons.py (alertes, bons, e-mail)
                                                     ▲
                         serveur.py (API JSON) ◄──── vigie/web/ (interface)
```

## Où modifier quoi

| Besoin | Fichiers |
|---|---|
| Nouvelle règle de détection | `regles.py` (textes, réglages, matrice) + `moteur.py` ou un module dédié (`complements.py`, `historique.py`, `solaire.py`) + tests |
| Calcul des montants | `chiffrage.py` |
| Nouveau format d'import | `courbes.py` / `patrimoine.py` / `db.py`, anomalies tracées dans la table `anomalie_import` |
| Nouvelle route API | `serveur.py` (liste `self.routes`) + appel via `api()` de `web/outils.js` + `docs/API.md` (un test vérifie que chaque route y figure) |
| Nouvel outil MCP | `mcp.py` (liste `OUTILS`, lecture seule) + `docs/API.md` + `tests/test_mcp.py` |
| Nouvel écran | `web/pages_*.js` + navigation dans `web/app.js` |
| Schéma de base | `db.py` **et** `sql/schema_timescaledb.sql` (même modèle) |

## Règles à respecter

Les numéros sont ceux cités dans les commentaires du code.

1. **Règle 5 : tous les chiffres (kWh, m³, CHF, CO₂) sont calculés par le code**, jamais générés par un LLM.
2. **Règle 4 : aucune décision sur une donnée manquante, estimée ou reconstituée.** Rien n'est comblé, ni corrigé
   en silence ; les écarts sont tracés (`anomalie_import`).
3. **Règle 7 : persistance obligatoire** avant de lever une alerte ; la référence est apprise sur une période
   antérieure à celle jugée (aucune connaissance du futur).
4. **Règle 6 : une seule alerte par fluide et par immeuble** : la règle la plus fine l'emporte.
5. **Règle 3 : une donnée météo absente ou figée doit se voir** dans l'interface.
6. **Règle 9 : aucune donnée de consommation ne quitte le serveur.** Seuls accès sortants autorisés : MétéoSuisse,
   géocodeur fédéral, tuiles swisstopo, fournisseur API configuré (identifiants et période seulement).
7. **Pas de nouvelle dépendance** sans nécessité : bibliothèque standard + pandas/numpy (ex. `excel.py` lit le xlsx
   lui-même). Pas de framework ni d'étape de build côté web.
8. **Sécurité du serveur à préserver** : contrôle de l'en-tête `Host` (127.0.0.1/localhost), en-tête `X-Vigie` exigé
   pour toute écriture, CSP stricte sans ressource externe (hors tuiles swisstopo), SQL toujours paramétré.
9. **Interface** : texte inséré avec `textContent` / `h()`, jamais `innerHTML` ; couleurs via les jetons CSS de
   `app.css`.
10. Modules gardés autour de **800 lignes maximum** (d'où l'extraction de `regles.py` depuis `moteur.py`).
11. Toute modification de comportement s'accompagne de tests dans `tests/` ; la suite complète doit rester verte.

## Production

- Servie sur `https://xread-derive.brochardbenjamin.com` (VPS Ubuntu 24.04, `root@195.35.24.97`).
- Code dans `/var/www/xread-derive` (clone GitHub), venv `.venv`, service systemd `xread-derive` (utilisateur
  `xread`, port 127.0.0.1:8765), vhost nginx dédié qui réécrit `Host: 127.0.0.1` vers l'app.
- Secrets éventuels dans `/etc/xread-derive.env` (`VIGIE_MOT_DE_PASSE` : mot de passe des écritures, sans lui l'interface publiée reste en lecture seule ;
  `VIGIE_SMTP_MOT_DE_PASSE`, `VIGIE_API_CLE`).
- Redéployer : `git push` puis `./deploy.sh` (pull, dépendances, redémarrage, test de santé). La base `vigie.db`
  du serveur n'est jamais écrasée.
- Le VPS héberge d'autres services (technistargets, etc.) : ne jamais modifier leurs vhosts, conteneurs ou services.
