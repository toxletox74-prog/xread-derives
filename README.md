# Xread Dérives (Vigie) — détecteur de dérives du parc immobilier (V0.3.0)

Interface de gestion pour le gestionnaire d'immeubles : parc (adresses, immeubles, compteurs et leur connexion),
règles réglables selon l'occupation, coûts de la dérive, imports, prestataires par métier et **bons de travaux
préparés et envoyés automatiquement** selon la dérive constatée.

Fluides suivis : électricité, gaz, chaleur de chaufferie, chauffage à distance (CAD), pompe à chaleur (PAC), eau et
production solaire. Le moteur applique à chaque compteur la méthode que son pas de relevé permet (quart d'heure,
heure, jour ou mois).

Aucune donnée de consommation n'est envoyée sur Internet : tout reste sur la machine qui fait tourner Vigie (le
poste du gestionnaire, ou le serveur qui l'héberge).

Code sous **licence MIT** (voir `LICENSE` ; données et composants tiers : `LICENCES_TIERS.md`).

Documents liés :

- `CHANGELOG.md` : ce que chaque version a apporté, résultats obtenus sur le lot communal, mesures de validation ;
- `AGENTS.md` : arborescence détaillée, rôle de chaque fichier, règles de développement, production ;
- `docs/Xread_Derives_methodes_par_pas_de_releve.pdf` : méthode, calcul, seuil et justification de la dérive pour
  chaque fluide et chaque pas (11 pages, régénéré par `python -m evaluation.pdf_methodes_par_pas`) ;
- `docs/Vigie_methodes_et_evaluation_derives.pdf` : méthodes, données, résultats détaillés, révisions.

## Installer et lancer

```powershell
pip install -r requirements.txt        # pandas et numpy : seules dépendances de l'application et des tests
```

La suite de tests est passée sous **Python 3.12**, avec pandas 2.2.3 et numpy 1.26.4 d'une part, pandas 3.1.1 et
numpy 2.5.4 d'autre part : ce sont les bornes de `requirements.txt`. Aucune version de Python antérieure à 3.12
n'est testée.

Les scripts du dossier `evaluation/` (figures et documents PDF) demandent en plus matplotlib et reportlab :
`pip install -r requirements-evaluation.txt`. L'application et les tests n'en ont pas besoin.

Sous Windows, double-cliquez sur **`Lancer Vigie.bat`** : la fenêtre de commande reste ouverte et le navigateur
s'ouvre sur http://127.0.0.1:8765. Fermer la fenêtre arrête Vigie.

En ligne de commande :

```powershell
python -m vigie interface              # votre parc (base vigie.db, vide au départ)
python -m vigie interface --demo       # parc fictif d'exemple (base vigie_demo.db)
python -m vigie demo                   # recrée l'exemple (24 adresses, 12 mois) : consommations simulées, météo réelle
python -m vigie demo --petit           # exemple réduit : 5 immeubles, 4 adresses
python -m vigie demo --meteo-fictive   # idem, température fictive (hors ligne)
python -m vigie evaluer                # précision / rappel (référence : météo fictive)
python -m vigie evaluer --meteo-reelle # précision / rappel avec la vraie météo de Genève
python -m vigie evaluer --grand        # précision / rappel sur le grand exemple (24 adresses, 15 dérives)
python -m vigie importer mesures.csv   # import de relevés dans vigie.db
python -m vigie analyser               # analyse de vigie.db
python -m vigie meteo                  # met à jour température et rayonnement MétéoSuisse (Genève-Cointrin)
python -m unittest discover -s tests   # plus de 270 tests, environ 2 minutes
```

Les commandes d'import d'un patrimoine, de courbes et de rejeu sont décrites plus bas ; la liste complète est dans
l'en-tête de `vigie/__main__.py`.

La base d'exemple et votre base sont séparées : `demo` ne touche jamais à `vigie.db`.
Si Vigie est déjà ouvert, un second lancement le signale au lieu de démarrer une deuxième instance.

**Tests.** La suite compte plus de 270 tests. Certains sont ignorés selon l'environnement : 7 tests du connecteur API
exigent la protection DPAPI de Windows et sont ignorés ailleurs ; 2 tests sont ignorés quand les fichiers qu'ils
relisent ne sont pas déposés sur la machine (relevés d'exemple, classeur patrimoine dans `donnees/`). Le flux
GitHub Actions `.github/workflows/tests.yml` lance la suite sous Ubuntu et sous Windows à chaque push sur `main` et
à chaque pull request.

**Deux façons de faire tourner Vigie.** Sur un poste, comme ci-dessus. Sur un serveur : la production est un
serveur Ubuntu où Vigie tourne comme service, toujours à l'écoute de `127.0.0.1:8765`, derrière un nginx qui le
publie en https ; `deploy.sh` le met à jour. Sur un serveur, définissez `VIGIE_MOT_DE_PASSE` : sans session,
l'interface est en lecture seule. Le détail est dans la section « Production » d'`AGENTS.md`.

## Les écrans

| Écran | Ce que le gestionnaire y fait |
|---|---|
| **Tableau de bord** | Indicateurs (rythme des dérives en CHF par mois, dont l'excès déjà mesuré du chauffage et des PAC, MWh et m³ par mois, CO₂, bons à valider), **carte du parc** (liste des adresses à gauche, carte swisstopo à droite, couleur selon la criticité), alertes à traiter par priorité (rythme mensuel en CHF × confiance × urgence). Bouton « Lancer l'analyse ». Bannière de couverture des règles. |
| **Parc** | Adresses → immeubles → fluides. Ajout et modification d'un immeuble (occupation Habité / Partiel / Vide / Travaux, taux d'occupation, logements, talon hors-gel, propriétaire). Export Excel. |
| **Fiche immeuble** | Compteurs et capteurs : fluide, connexion (M-Bus, wM-Bus/OMS, LoRaWAN, export DLMS du distributeur, Modbus, BACnet, CSV, relevé de facture), identifiant de l'appareil, fournisseur, pas de temps, état (actif / à connecter / inactif), dernière donnée, complétude sur 30 jours, courbe journalière. Règles appliquées selon l'occupation. Alertes et bons de l'immeuble. |
| **Fiche technique (immeuble)** | Gestionnaire et concierge (nom, e-mail, téléphone), données techniques (construction, rénovation, EGID, étages, production de chaleur et d'eau chaude, puissance, installation, frigorigène, local technique), **partenaires techniques par fluide**, **consommation par compteur en journalier (90 jours), mensuel ou annuel** avec total et moyenne, suivi horodaté de chaque alerte (**En attente → Bon envoyé → Retour d'incident → Clôturée**, destinataire du bon, retour), **historique horodaté** de toutes les étapes, compteurs et connexions. |
| **Alertes** | Ouvertes et résolues. Constat en langage simple, consigne, métier, délai, imputation. Avis du gestionnaire : *Pertinente / Déjà connue / Fausse alerte*, qui donne le taux de pertinence réel. |
| **Bons de travaux** | Bon adressé au prestataire du métier pour l'immeuble. Relecture et modification du message, envoi par e-mail ou fichier `.eml` à ouvrir dans Outlook, puis suivi (envoyé, en cours, terminé, annulé) avec historique. Indique si la dérive a disparu des mesures. |
| **Prestataires** | Entreprise, métier, contact, e-mail, téléphone, immeubles couverts (tout le parc ou certains). Signale les métiers demandés par les règles mais non couverts. |
| **Règles & coûts** | Tableau « surveillance selon l'occupation », matrice des méthodes par fluide et par pas de relevé, couverture des règles. Pour chaque règle : activation, occupations concernées, seuil, persistance, gravité, métier du prestataire, délai, consigne. Coûts : tarif par vecteur (exemple ou contrat), facteur CO₂, enjeu minimal (CHF par mois), seuils de qualité des données. |
| **Imports** | Parc depuis Excel avec **aperçu avant import** (nouveaux, modifiés, inchangés, lignes refusées avec leur motif). Relevés en CSV (séparateur , ou ;) ou en Excel .xlsx (feuille « mesures »), colonnes `ts,point_id,valeur` : format commenté et modèles vides dans le dossier `exemple de données fluides` (voir son `LISEZMOI.txt` ; les relevés d'exemple ne sont pas publiés dans le dépôt). Modèle Excel du parc téléchargeable. Classeur patrimoine et courbes, avec aperçu et liste des anomalies. |
| **Rejeu** | Épisodes retrouvés en rejouant la détection jour après jour sur une période passée. |
| **Réglages** | **Relevés des compteurs par API** : clé API du fournisseur de télérelève (sous Windows, chiffrée par le compte Windows ; ailleurs, elle n'est pas stockée et se donne par la variable `VIGIE_API_CLE` ; jamais réaffichée ni envoyée ailleurs qu'au fournisseur), adresse https, format réglable (en-tête, Bearer ou paramètre ; JSON ou CSV), « Tester la connexion », « Relever maintenant », relevé automatique toutes les N heures. Les compteurs concernés ont la connexion « API du fournisseur » et leur identifiant chez le fournisseur. Fournisseur de démonstration intégré pour la base d'exemple (clé `DEMO-VIGIE-2026`). Puis automatisation des bons (manuelle, préparation automatique, envoi automatique, gravité minimale, problèmes de données), messagerie (expéditeur, copie, signature, serveur SMTP) et température extérieure (station, mise à jour). |

## Imports

### Parc depuis Excel

Classeur `.xlsx` avec jusqu'à trois feuilles. Le bouton « Télécharger le modèle » en fournit un prêt à remplir,
avec une feuille « Aide » qui liste les valeurs possibles.

| Feuille | Colonnes |
|---|---|
| Immeubles | `immeuble_id, nom, rue, npa_localite, profil, taux_occupation, logements, sre_m2, talon_horsgel_kwh_j, proprietaire, remarque` ; facultatif : `latitude`, `longitude` |
| Compteurs | `point_id, immeuble_id, fluide, libelle, unite, nature, pas_min, connexion, identifiant, fournisseur, etat` ; solaire : `puissance_crete_kwc` (obligatoire), `production_prevue_kwh_an`, `mise_en_service`, `degradation_pct_an` |
| Prestataires | `nom, metier, contact, email, telephone, immeubles` (`*` = tout le parc) |

Les en-têtes sont tolérants (accents, majuscules, synonymes comme « Code », « Adresse », « N° de série »,
« Courriel »). Les valeurs aussi : « Habité », « vacant », « Eau froide », « chauffage », « à connecter ».
Les lignes sont **ajoutées ou mises à jour par code ; rien n'est jamais supprimé par un import**. Les lignes
invalides sont refusées une à une, avec leur numéro et le motif. Le reste s'importe.

### Relevés des compteurs

- **Fichier** : CSV ou Excel, colonnes `ts,point_id,valeur` (écran Imports, ou `python -m vigie importer`).
  L'horodatage est en UTC, fin d'intervalle ; le format est détaillé dans
  `exemple de données fluides/LISEZMOI.txt`.
- **API d'un fournisseur de télérelève** : réglée dans Réglages (voir le tableau des écrans).
- Il n'y a pas de connecteur direct (M-Bus, LoRaWAN, Modbus…) : hors API, les relevés s'importent par fichier.

### Patrimoine complet et courbes fines

Un classeur de patrimoine (sites, bâtiments, installations, compteurs, relevés mensuels, références) et des
fichiers de courbes (jour, heure, quart d'heure) s'importent depuis l'écran Imports (« Classeur patrimoine et
courbes », avec aperçu avant import) ou en ligne de commande :

```powershell
python -m vigie importer-patrimoine donnees\patrimoine.xlsx   # --apercu : contrôle sans écrire
python -m vigie importer-courbes donnees\courbes_jour.csv donnees\courbes_cad_heure.csv donnees\calendrier.xlsx donnees\courbes_pv.xlsx
python -m vigie reprendre-prestataires ..\Xread_Derives_V0_2_0\vigie.db           # prestataires d'une autre base Vigie
python -m vigie analyser
```

Ce format est celui du lot communal (ville suisse fictive, données sous CC BY 4.0). Ses fichiers se déposent dans
`donnees/` et ne sont pas publiés dans le dépôt. Les volumes importés, les anomalies relevées et la reprise des
prestataires pour ce lot sont dans `CHANGELOG.md`.

**Correspondance avec Vigie**

- Un **site** devient un immeuble, avec le même code (`S01`) ; ses bâtiments et ses installations figurent dans
  la fiche du site. Les **compteurs** gardent leur code, leur rôle (général, sous-compteur, production, livraison),
  leur compteur parent et leurs bornes de service ; un compteur retiré avant la fin des relevés est « inactif ».
- **Relevé mensuel** : pas de temps de 43 200 minutes. La valeur est stockée telle quelle, dans l'unité du
  compteur, horodatée à la fin du mois (janvier 2021 → `2021-02-01T00:00:00Z`).
- **Courbe fine** : elle devient un second compteur relié au premier (`S13-GZ` = relevé mensuel du distributeur,
  `S13-GZ-JOUR`, `S01-CAD-HEURE`, `S09-PV-15MIN` = courbes). Deux pas de temps ne sont jamais mélangés dans une
  série et rien n'est compté deux fois. Les horodatages des fichiers (début d'intervalle, heure légale suisse) sont
  convertis en UTC, fin d'intervalle. Le moteur analyse la série la plus fine de chaque fluide.
- **Coordonnées GPS** : les sites du lot n'ont pas d'adresse réelle. À l'import, chaque site reçoit des coordonnées
  calculées depuis le plan du jeu et enregistrées dans la base. Ces positions sont fictives : rien n'est envoyé au
  géocodeur, et une position saisie à la main n'est jamais remplacée.
- **Références** (table `reference`) : climat mensuel, facteurs de conversion, facteurs CO₂ du lot, calendrier.
  Les degrés-jours du mois et le calendrier servent aux règles ; les facteurs de conversion mensuels et les
  facteurs CO₂ du lot sont stockés sans être utilisés par le moteur.

Le détail (fluides repris, séries des sous-stations, placement des sites sur la carte) est dans `CHANGELOG.md`.

**Contrôles à l'import** : chaque écart est tracé dans la table `anomalie_import`, dans la page Imports et dans
`sorties/anomalies_import.csv`. Rien n'est corrigé ni comblé. Sont contrôlés : doublon, valeur négative (marquée
« suspecte »), relevé manquant, relevé estimé par le distributeur (marqué « estimée », affiché mais exclu des
décisions), compteur inconnu, valeur illisible, désaccord de site, de fluide ou d'unité avec le compteur, relevé
hors bornes de service, énergie incohérente avec valeur × facteur, mois ou pas de temps sans aucune ligne,
livraisons du même mois (additionnées), bilan thermique du chauffage à distance, et écart entre la courbe et le
relevé mensuel (tolérance 1 %, 3 % pour l'injection solaire).

## Méthodes de détection

### Une méthode par fluide et par pas de relevé

Le moteur applique à chaque compteur la méthode la plus fine que son relevé permet, et jamais une méthode horaire à
un relevé journalier. La matrice ci-dessous est codée une seule fois (`regles.PAS_REGLES`, `regles.matrice`) ; elle
alimente la page « Règles & coûts » et le document `docs/Xread_Derives_methodes_par_pas_de_releve.pdf`.

| Fluide | Quart d'heure et heure | Jour | Mois |
|---|---|---|---|
| Eau | fuite de nuit (débit minimum 1 h – 5 h) | niveau de base sur 7 jours | même mois des années précédentes |
| Électricité | puissance de nuit | jour comparé aux jours de même type | même mois, à climat égal |
| Gaz, chaleur, chauffage à distance | signature à météo égale ; retour du CAD | signature à météo égale | même mois, à climat égal |
| Pompe à chaleur | rendement heure par heure | électricité du jour à météo égale | même mois, à chaleur produite égale |
| Solaire | coupures de l'onduleur ; journées comparables | journées comparables | rendement du même mois |

Seuil, persistance, occupations concernées, gravité et prestataire de chaque règle se règlent dans « Règles &
coûts ». S'y ajoutent, pour un immeuble déclaré vide, les règles « immeuble vide » de l'eau et du chauffage
(chaleur, CAD, gaz), qui tournent au jour ou plus fin. Une seule alerte est levée par fluide et par immeuble : la
règle la plus fine l'emporte.

### Relevés à l'heure ou au quart d'heure

- `elec_nuit` — puissance de nuit comparée aux nuits de référence. Pour les sites dont la nuit suit le froid (PAC,
  chauffage électrique), la nuit est comparée aux nuits de même froid de la référence (± 2 degrés, jamais
  d'extrapolation) ; un site insensible au froid garde la comparaison aux nuits de 20 à 50 jours plus tôt.
- `cad_retour` — retour trop chaud d'une sous-station : température de retour au-dessus de l'attendu à température
  extérieure égale de plus de 5 °C pendant 7 jours. Non chiffrée en kWh, jamais masquée.
- `solaire_onduleur` — défaut de l'onduleur : entre le lever et le coucher du soleil, donnés par le rayonnement de
  la station météo (rayonnement > 0), la production tombe à zéro entre deux relevés producteurs. Jugé au pas du
  compteur sur les 7 derniers jours. La nuit, l'aube avant le premier relevé producteur et une journée entière à
  l'arrêt (règle `solaire_arret`) ne sont pas des coupures. Déclaré dès la première coupure ; la durée minimale (en
  relevés à zéro) et le nombre de jours avec coupure se règlent. La production non réalisée est estimée d'après les
  deux relevés qui encadrent chaque coupure.
- `donnees_injection` — défaut de données : injection nulle des jours entiers alors que le solaire produit plus que
  tous les jours sans injection de la référence.
- Une production horaire au-delà de 1,25 × la puissance crête est un défaut d'échelle ou d'unité (alerte
  « Données », aucune alerte énergie sur ce compteur).

### Relevés au jour

- `eau_talon` — le minimum de consommation sur 7 jours (qui contient toujours un week-end) dépasse de 100 % le
  niveau de base de référence, et d'au moins 480 l/jour (20 l/h en continu), pendant 3 jours. Une fuite relève ce
  minimum ; le remplissage d'un bassin ne le change pas.
- `elec_jour` — chaque jour comparé à la médiane des jours de même type (ouvré, vacances, non ouvré) des 8 semaines
  de référence ; +20 % pendant 5 jours.
- `pac_signature` — électricité de la PAC à météo égale (même signature que le chauffage) ; +15 % pendant 7 jours.
- Solaire : les règles arrêt, panne et dégradation tournent sur la production journalière et l'ensoleillement du
  jour (sans le détail matin / midi / après-midi du diagnostic).
- Un relevé journalier n'est attribué à aucune heure : les règles de nuit et le rendement horaire de la PAC ne
  tournent pas sur lui.

### Signature de chauffage (chaleur, CAD, gaz) et PAC

- **Référence d'un an** : l'attendu du chauffage, du CAD, du gaz et de la PAC est appris sur la même saison de
  l'année précédente plus les 60 jours récents ; si cette saison manque (moins d'un an de mesures), sur toute la
  période antérieure.
- **Première année de suivi** : l'attendu d'un jour est la médiane des journées de référence de météo comparable
  (± 2 degrés-jours, au moins 10 jours), sinon le jour n'est pas jugé. Un jour n'est jugé que s'il a des jours
  comparables plus froids et plus doux que lui (3 de chaque côté) : jamais d'extrapolation. Les jours comparables
  sont ramenés au degré-jour du jour jugé (pente locale) avant d'en prendre la médiane. Tant que la référence ne
  contient aucun jour aussi froid, rien n'est conclu.
- **Jours ouvrés et vacances** (`vigie/calendrier.py`) : en première année de suivi, chaque jour est comparé aux
  jours de même type (ouvré, ouvré pendant les vacances scolaires, non ouvré), mais seulement pour les immeubles où
  l'écart se voit dans leur propre référence. Un jour ouvré n'est jamais comparé à un week-end. Source : le
  calendrier importé (jours ouvrés, fériés, vacances scolaires) ; pour une date qui n'y figure pas, lundi à
  vendredi = ouvré.
- Si plus aucun jour n'est jugeable depuis 10 jours (pas de météo comparable en référence, à l'intersaison), la
  règle ne conclut plus, au lieu de rester figée sur son dernier constat.
- Gaz en m³ : converti en kWh par le pouvoir calorifique supérieur du référentiel (`gaz_pcs_kwh_par_m3`,
  10,5 kWh/m³ par défaut, valeur d'EXEMPLE). CAD = chaleur livrée à la sous-station (kWh).
- Un compteur dont les relevés commencent il y a moins de 30 jours est jugé depuis son premier relevé.

### Relevés au mois : comparaison au même mois des années précédentes

Sept règles (`vigie/historique.py`) : `gaz_historique`, `pac_historique`, `chaleur_historique`, `cad_historique`,
`elec_historique`, `eau_historique` et `solaire_historique`. La valeur d'un mois est comparée à celle du **même mois
des années précédentes** (médiane des 3 dernières années connues). Un écart au-delà du pourcentage réglé, tenu
plusieurs mois de suite, est une dérive. C'est la seule règle des compteurs relevés une fois par mois.

| Règle | Écart toléré | Persistance | Correction |
|---|---|---|---|
| Gaz, chaleur, chauffage à distance | +20 % | 2 mois | climat du mois (degrés-jours) |
| Pompe à chaleur | +20 % | 2 mois | chaleur produite du mois si elle est comptée, sinon climat du mois |
| Électricité | +20 % | 3 mois | climat du mois (sans effet si le compteur n'y est pas sensible) |
| Eau | +20 % et au moins 480 l/jour de plus | 2 mois | aucune |
| Solaire | −15 % de rendement | 2 mois | ensoleillement du mois, décote des modules |

- **À climat égal** : l'attendu est `référence du même mois + pente × (degrés-jours du mois − degrés-jours de la
  référence)`, la pente étant apprise sur l'historique du compteur lui-même. Sans degrés-jours pour le mois, la
  comparaison se fait sans correction et le constat le dit.
- **PAC à chaleur produite égale** : quand la chaleur de la PAC est comptée, l'électricité du mois est comparée à
  `chaleur du mois × (électricité ÷ chaleur) du même mois des années précédentes`, c'est-à-dire au rendement.
- **Solaire à ensoleillement égal** : production du mois ÷ rayonnement du mois, comparée au même rendement des années
  précédentes, décote annuelle déduite. Les mois très peu ensoleillés (moins de 40 kWh/m² : décembre, janvier) ne
  sont pas jugés.
- **Deux garde-fous.** (1) Il faut **2 années de référence**, et avec 2 seulement la plus prudente des deux. (2) La
  référence ne remonte jamais avant le **dernier changement d'installation** du site (table `installation`) : une
  PAC qui remplace une chaudière ou du solaire posé rendent l'historique d'avant incomparable.
- **Quel compteur** : le relevé mensuel quand il existe, sinon la courbe ramenée aux mois complets. Un mois manquant
  ou estimé n'est ni comblé ni jugé.
- **Une seule alerte par cause** : si une règle plus fine du même fluide est déjà en alerte sur l'immeuble, la règle
  historique se tait.

### Production solaire

- Fluide « Solaire » : production brute de l'onduleur ou du compteur de production (kWh), avec les caractéristiques
  de l'installation saisies sur le compteur : **puissance crête (kWc, obligatoire)**, production brute prévue
  (kWh/an), année de mise en service et décote annuelle des modules (%/an, 0,5 si vide).
- **Production comparée à ensoleillement égal** : chaque jour ensoleillé (≥ 0,6 kWh/m²) est comparé aux journées
  comparables de l'historique : même saison (± 30 jours de la même date) et même ensoleillement (± 15 %, à défaut
  ± 25 ou ± 35 %). L'attendu est la médiane de leur rendement (kWh produits par kWh/m² reçu), corrigée de la décote
  prévue des modules entre leur date et le jour jugé : une baisse logique due à l'âge n'est jamais une alerte. Quand
  la référence gelée n'a pas la même saison, les journées comparables sont cherchées à ± 60 puis ± 90 jours. Sans
  historique (installation neuve), la référence est la production prévue, décotée selon l'âge, au prorata de
  l'ensoleillement du jour sur l'ensoleillement annuel normal de Genève (1 385,9 kWh/m², MétéoSuisse GVE 2016-2025).
- **Trois qualifications**, une seule alerte par immeuble à la fois ; une alerte ouverte garde sa qualification tant
  qu'elle persiste :
  - `solaire_arret` (Élevée, 2 jours ensoleillés) : production quasi nulle malgré le soleil (onduleur, disjoncteur,
    interrupteur DC) ;
  - `solaire_panne` (Élevée, 3 jours ensoleillés, −15 %) : chute brutale, l'essentiel de la baisse en quelques
    jours. Une perte répartie sur toute la journée oriente vers des cellules ou modules défectueux, une diode de
    dérivation ou une chaîne (string) hors service ; une perte surtout le matin ou l'après-midi, vers un ombrage
    ou une chaîne d'une orientation ; une perte surtout à midi, vers l'onduleur ;
  - `solaire_degradation` (Modérée, 7 jours ensoleillés, −10 %) : baisse progressive au-delà de la décote
    (encrassement, vieillissement anormal, ombrage).
- **Chiffrage** : production perdue = Σ (attendu − mesuré) depuis le début, sur les heures mesurées ; valeur du kWh
  solaire perdu 0,1185 CHF (rétribution publique 2026 de l'injection, indicative : un minimum, la part autoconsommée
  vaut le tarif de l'électricité) ; CO₂ = électricité du réseau
  achetée à la place (EXEMPLE). Projection 12 mois = perte relative × production prévue décotée (hypothèse).

### Ce que chiffre une alerte

- **Dérive constatée** (déclencheur des actions) : ce qui a été **mesuré** depuis le début de la dérive. Chauffage,
  CAD, gaz et PAC : Σ (mesuré − attendu) heure par heure sur les heures mesurées. Eau d'un immeuble vide : volume
  mesuré. Fuite de nuit et électricité de nuit : excès constaté la nuit × heures mesurées. Affichage : « Dérive
  constatée : ≈ X CHF », « 2 459 kWh depuis le 31.10.2026 (271 heures mesurées) ».
- **Rythme mensuel** (base de la priorité) : excès moyen par jour des 30 derniers jours de dérive au plus × 30.
- **Projection si rien n'est fait** (hypothèse, séparée) : coût sur 12 mois, dérive constante pour l'eau et
  l'électricité, **climat normal de Genève** pour le chauffage, le CAD, le gaz et les PAC (2 122 degrés-jours base
  16 °C par an, dont 761,3 la nuit : moyenne 2016-2025 des données MétéoSuisse Genève-Cointrin, bloc
  `climat_reference` du référentiel, `python -m evaluation.climat_gve --ecrire`). Elle ne déclenche jamais d'alerte,
  ne change jamais la gravité, n'entre pas dans le score et n'apparaît pas dans le bon envoyé au prestataire.
- **Priorisation** : score = rythme mensuel constaté en CHF × confiance × urgence (× 1,5 si risque de sinistre),
  même base pour tous les fluides. L'enjeu minimal se règle en CHF par mois (8,22 CHF par défaut).

### Couverture des règles : l'alerte de granularité

Une règle ne juge un compteur que s'il est relevé assez finement pour elle. L'interface le dit partout où une règle
est affichée :

- **Tableau de bord** : une bannière signale les règles actives qui ne tournent sur aucun compteur et les compteurs
  sans aucune règle.
- **Règles & coûts** : section « Couverture des règles » (règle sans effet, règle partielle, compteurs sans règle) ;
  chaque règle indique le relevé qu'elle exige et le nombre de compteurs du parc sur lesquels elle tourne.
- **Fiche immeuble** : « sans effet ici : demande un relevé … » à côté de chaque règle que le relevé de l'immeuble ne
  permet pas.

Une règle du relevé au jour n'est pas signalée quand le fluide a déjà des courbes plus fines : la règle fine s'en
charge. Un compteur plus grossier que l'heure est signalé avec ce qu'il fait perdre.

## Rejeu sur une période passée

Le moteur juge la situation à la fin des relevés. Pour retrouver les dérives réparties sur une période, il est
**rejoué jour après jour** : à chaque date, il ne voit que les mesures déjà reçues, avec les mêmes règles et la même
persistance qu'en exploitation. Les alertes successives sont regroupées en **épisodes** (même site, même cause ; une
alerte revenue dans les 10 jours reste le même épisode). Les alertes encore en cours à la dernière date sont ouvertes
dans la base, avec leur référence gelée à leur début.

```powershell
python -m vigie meteo-periode 2024-11-01 2025-12-31   # météo horaire réelle de Genève-Cointrin (température, rayonnement)
python -m vigie rejouer 2025-01-01 2026-01-01         # une analyse par jour ; --pas=N : une analyse tous les N jours
```

Résultat : page **Rejeu** de l'interface, paramètre `rejeu` de la base et `sorties/rejeu_episodes.csv`. Les épisodes
retrouvés sur l'année 2025 du lot communal sont dans `CHANGELOG.md`.

## Exemple : 24 adresses, 12 mois

L'exemple (`python -m vigie demo`, ou « Charger l'exemple » sur une base vide) compte **25 immeubles à 24
adresses** :
- les **5 immeubles d'origine**, sur 4 adresses ;
- **16 immeubles chauffés par PAC** et **4 immeubles au chauffage à distance ou au gaz**, placés à de vraies adresses
  genevoises (coordonnées du géocodeur fédéral, correspondance exacte) et décrits dans `config/exemple_grand.json`.

Les consommations sont toutes **fictives et simulées** sur **12 mois**, sur la vraie météo de Genève (ou une
température fictive à cycle annuel, hors ligne). Les compteurs suivent le nombre de logements et l'occupation, et
**tous sont relevés à l'heure** :
- électricité générale et électricité de la PAC cumulées sur l'heure ;
- chaleur, chaleur livrée par le CAD et chaleur de la PAC à l'heure ; gaz en index horaire (m³) ;
- index d'eau lu à l'heure pleine (l'écoulement, chasses d'eau comprises, est simulé par quart d'heure) ;
- production solaire à l'heure, simulée sur le **rayonnement réel** de Genève-Cointrin (ou un rayonnement fictif,
  hors ligne) : modules inclinés, pertes de température, décote de 0,5 %/an depuis la mise en service, onduleur
  limité à 90 % de la puissance crête.

Le comptage de la chaleur PAC varie d'un immeuble à l'autre : chaleur totale, chauffage seul, eau chaude seule, ou
électricité seule.

Installations solaires : immeubles T8 et A (immeubles d'origine, 30 kWc et 45 kWc) ;
G03, G06, G10, G14 et G17 dans les immeubles ajoutés.

**Dérive solaire injectée dans les immeubles d'origine** : T8 perd une chaîne de modules sur quatre (−25 % depuis
14 jours, panne). A est sain.

**Dérives injectées dans les immeubles ajoutés** (en fin de période), en plus des 7 d'origine :
- G02 : rendement PAC en baisse, avec la chaleur de chauffage seule comptée ;
- G05 : fuite d'eau de nuit ;
- G08 : électricité de nuit +30 % ;
- G18 (CAD) : chaleur livrée +18 % à météo égale depuis 12 jours ;
- G20 (gaz) : gaz +18 % à météo égale depuis 12 jours ;
- G06 (solaire 80 kWc) : une chaîne de modules hors service, −25 % depuis 14 jours (panne) ;
- G03 (solaire 60 kWc) : encrassement progressif jusqu'à −22 % sur 35 jours (dégradation) ;
- G14 (solaire 40 kWc) : onduleur à l'arrêt depuis 6 jours.

G17 (CAD) et G19 (gaz) sont sains, comme les installations solaires de G17 et de G10 (en travaux : règles d'énergie
suspendues). G12 a un compteur d'eau chaude « à connecter ». Les 15 autres immeubles ajoutés, dont 2 partiellement
occupés et 1 en travaux, ne doivent déclencher **aucune alerte**.

Dans l'exemple, chaque fluide a un partenaire fictif par secteur (rive droite, rive gauche, communes) : un
électricien, un frigoriste pour la PAC, une entreprise sanitaire pour l'eau, un chauffagiste et un installateur
solaire (sociétés fictives), plus un autre installateur solaire fictif.
Chaque immeuble a aussi un gestionnaire, un concierge et des données techniques fictifs. Deux adresses sont fictives :
elles sont placées au centre de leur commune et indiquées « position approximative ».

## Bons de travaux

1. Chaque règle désigne un **métier** (Sanitaire pour une fuite, Chauffagiste pour le chauffage, Frigoriste
   pour la PAC, Solaire pour une installation photovoltaïque, Télérelève pour un compteur muet…).
2. Après chaque analyse, selon les réglages, Vigie prépare un bon pour chaque **nouvelle** alerte dont la gravité
   atteint le seuil choisi. Le bon est adressé au prestataire de ce métier : celui dédié à l'immeuble passe avant
   celui de tout le parc. **Un seul bon ouvert par alerte** : une dérive qui dure ne crée pas un bon à chaque
   analyse.
3. Le message reprend le constat, la valeur mesurée et la valeur attendue, la consigne, le délai, et le risque de
   sinistre s'il y en a un. **Tous les chiffres viennent du moteur.** L'enjeu en CHF, la projection et l'imputation
   restent internes et ne figurent pas dans le message : le prestataire ne reçoit que la dérive constatée, en kWh
   ou en m³.
4. Envoi :
   - **avec un serveur SMTP** (Réglages › Messagerie), envoi direct, ou automatique si vous l'avez choisi ;
   - **sans serveur SMTP**, « Télécharger pour Outlook » produit un `.eml` qui s'ouvre prêt à envoyer.

   Le mot de passe SMTP est gardé **en mémoire** jusqu'à l'arrêt de Vigie, ou lu dans la variable
   d'environnement `VIGIE_SMTP_MOT_DE_PASSE`. Il n'est jamais écrit sur le disque.

**Concierge ou partenaire technique, retour d'incident**

- Un bon peut être adressé au **concierge de l'immeuble** ou au **partenaire technique** du métier. Le concierge est
  celui de la fiche ; s'il n'y en a pas, c'est le prestataire « Concierge » de l'immeuble.
- Par défaut, Vigie choisit le destinataire désigné par la règle. Quand il n'existe aucun partenaire du métier, le
  bon va au concierge et le journal du bon le signale.
- Tant que le bon est en brouillon, on peut changer de destinataire : le message est alors recomposé.
- Après l'envoi, on enregistre le **retour d'incident** (résolu, non résolu, à suivre, rien constaté) avec un
  compte rendu horodaté. On peut ensuite relancer une intervention ou clôturer le bon.
- Chaque étape est horodatée dans l'**historique** de l'immeuble : ouverture, réouverture et disparition de la
  dérive, création, envoi et retour du bon, avis du gestionnaire.

## Carte du parc (tableau de bord)

- **À gauche**, les adresses sont triées de la plus critique à la moins critique. Chacune a une pastille de couleur et
  indique son problème le plus grave. Un clic centre la carte sur l'adresse.
- **À droite**, la carte swisstopo propose trois fonds : plan couleur, plan gris et photo aérienne. **Six calques**
  peuvent être affichés ou masqués : Critique, Élevée, Modérée, Problème de données, Compteur à connecter, Sans
  dérive. Le **survol** d'un point affiche les immeubles de l'adresse et leurs problèmes, avec leur coût ; un clic
  ouvre les liens vers les fiches.
- **Coordonnées GPS** : les adresses sont localisées par le géocodeur officiel de la Confédération
  (api3.geo.admin.ch). Cela se fait à l'enregistrement d'un immeuble, puis en tâche de fond pour les adresses
  importées par Excel, et aussi avec le bouton « Localiser les adresses ». **Seule l'adresse est transmise.**
- Un résultat n'est retenu que si **rue, numéro et NPA correspondent exactement**. Sinon, l'adresse reste « non
  localisée ». Un clic sur elle permet de saisir sa position ; on peut aussi la renseigner dans les colonnes
  `latitude` / `longitude` de l'Excel ou dans la fiche de l'immeuble. Une position saisie à la main n'est jamais
  écrasée.
- La carte utilise Leaflet 1.9.4 (licence BSD-2), intégré dans `vigie/web/` et vérifié par son empreinte
  officielle. Seules les tuiles du fond de carte viennent d'Internet (wmts.geo.admin.ch).

## Température extérieure et ensoleillement : MétéoSuisse, automatique

Les règles « chauffage trop fort pour la météo » et « rendement PAC » comparent la consommation à la
température extérieure ; les règles solaires comparent la production à l'ensoleillement. Vigie utilise la **source
officielle de la Confédération** : MétéoSuisse, données ouvertes du réseau SwissMetNet, **station Genève-Cointrin
(GVE)**, colonnes `tre200h0` (température de l'air à 2 m) et `gre000h0` (rayonnement global, W/m²), moyennes
horaires, en UTC, fin d'intervalle, comme les mesures de Vigie. Le rayonnement est facultatif : une station qui ne
le mesure pas ne donne que la température.

- **Mise à jour automatique** au démarrage de Vigie puis toutes les 3 heures tant qu'il tourne. Elle peut aussi
  se lancer avec le bouton « Mettre à jour maintenant » (Réglages) ou la commande `python -m vigie meteo`.
- Au premier lancement, environ 400 jours d'historique sont chargés (le fichier de la décennie), puis seulement
  l'année en cours et les dernières heures.
- Heures manquantes laissées vides (jamais comblées), valeurs hors de −45 à 50 °C ou de 0 à 1 500 W/m² écartées.
- Base d'exemple sur météo réelle : la mise à jour n'ajoute que les heures nouvelles (température et rayonnement),
  sans réécrire celles qui ont servi à la simulation.
- Seul un fichier public est téléchargé : aucune donnée de consommation n'est envoyée.
- La station se change dans Réglages (code à 3 lettres). Un changement démarre une nouvelle série : on ne mélange
  jamais deux stations.
- La base d'exemple sur météo fictive garde ses températures fictives, cohérentes avec ses consommations simulées.
- Liens de la source (aussi affichés dans **Réglages › Température extérieure**) :
  [données ouvertes MétéoSuisse](https://www.meteoswiss.admin.ch/services-and-publications/service/open-data.html) ·
  [documentation](https://opendatadocs.meteoswiss.ch/general/download) ·
  [fichier horaire GVE](https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/gve/ogd-smn_gve_h_recent.csv).
  Conditions : utilisation libre, source à citer (MétéoSuisse).

## Sécurité

- Le serveur de Vigie n'écoute que sur `127.0.0.1` et vérifie l'en-tête `Host` (protection contre le « DNS
  rebinding »).
- Toute modification exige l'en-tête `X-Vigie`, ce qui bloque les formulaires venant d'autres sites, et, hors du
  poste local, une session ouverte (voir « Accès et identification »).
- Politique de sécurité du contenu stricte : aucun script ni style externe, aucune police chargée sur Internet ;
  seules les images du fond de carte swisstopo (wmts.geo.admin.ch) sont autorisées.
- Accès réseau sortants : température et rayonnement MétéoSuisse, géocodage des adresses, tuiles de la carte (tous
  en lecture de données publiques), et le fournisseur de télérelève quand la connexion API est réglée (identifiants
  des compteurs et période demandée seulement). Aucune donnée de consommation n'est envoyée.
- Tout texte est inséré sans interprétation HTML. Les fichiers servis sont limités au dossier `vigie/web`.
- Toutes les requêtes SQL sont paramétrées. Les fichiers Excel trop volumineux une fois décompressés sont refusés.
- La clé API du fournisseur est chiffrée par le compte Windows (DPAPI) ; hors Windows elle n'est pas stockée et se
  donne par la variable `VIGIE_API_CLE`. Le mot de passe SMTP n'est jamais écrit sur le disque.

### Accès et identification

- **Sur un poste** (accès direct à `127.0.0.1`, sans mot de passe défini), rien n'est demandé : tout est permis.
- **Lecture seule sans identification** dès qu'un mot de passe est défini par la variable d'environnement
  `VIGIE_MOT_DE_PASSE`, ou que la requête arrive par un serveur frontal (en-têtes `X-Forwarded-*`, `X-Real-IP`) :
  la consultation reste libre (tableau de bord, parc, alertes, carte, règles), mais toute modification exige une
  session ouverte avec le mot de passe (« Se connecter » dans le bandeau). La lecture des réglages de messagerie et
  du connecteur API est réservée elle aussi. Code : `vigie/acces.py`.
- Sans mot de passe défini, un accès par serveur frontal reste en lecture seule, sans connexion possible. Cette
  détection repose sur les en-têtes ajoutés par le serveur frontal : **en production, définissez toujours
  `VIGIE_MOT_DE_PASSE`** (dans `/etc/xread-derive.env`), sans quoi un frontal qui n'ajoute aucun de ces en-têtes
  laisserait les écritures ouvertes.
- Le mot de passe n'est jamais écrit sur le disque ; les sessions (témoin `HttpOnly`, `SameSite=Strict`, 12 heures)
  vivent en mémoire et sont perdues au redémarrage. Un seul mot de passe, sans comptes ni rôles : Vigie reste prévu
  pour un seul gestionnaire à la fois.

## Limites connues

### Automatisation, déclarations et recoupement

- **Analyse automatique.** Dans Réglages › Automatisation, l'option « Analyse automatique » (désactivée par défaut)
  lance l'analyse toutes les N heures (1 à 168, 6 par défaut) tant que Vigie tourne, et après chaque relevé API
  automatique qui apporte de nouvelles mesures. La date, le déclencheur et le résultat de la dernière analyse
  automatique y sont affichés. Un relevé lancé à la main ne déclenche pas d'analyse. Si l'envoi automatique des
  bons est choisi alors que le mot de passe de la messagerie n'est pas disponible (gardé en mémoire, perdu à chaque
  redémarrage), un avertissement apparaît sur le tableau de bord et dans les Réglages : sur un serveur, définissez
  `VIGIE_SMTP_MOT_DE_PASSE`.
- **Périodes déclarées et sourdines** (fiche d'un immeuble, `vigie/declarations.py`). Chaque déclaration a un motif
  obligatoire et est tracée dans l'historique. *Sourdine* : une règle d'un immeuble est mise en sourdine jusqu'à
  une date de fin obligatoire ; la dérive reste calculée et affichée « en sourdine jusqu'au … : motif », mais sort
  des alertes à traiter et aucun bon n'est préparé ; à l'échéance elle reprend seule. *Travaux, vacance* (début et
  fin) : les règles d'énergie sont suspendues comme pour l'occupation « Travaux » (fuites d'eau et défauts de
  données maintenus) et ces jours ne servent jamais de référence ensuite. *Changement* (compteur remplacé, consigne
  ou courbe de chauffe modifiée) : la référence ne remonte plus avant la date déclarée, et Vigie ne conclut pas tant
  que la référence postérieure est insuffisante (toute une intersaison après un changement en été, pour la
  signature de chauffage) ; un recul d'index le jour d'un changement déclaré sur le compteur n'est plus un défaut
  de données. Limites : les alertes « Données » ne se mettent pas en sourdine ; une vacance déclarée est traitée
  comme « Travaux », donc sans les règles « immeuble vide » ; les règles se règlent toujours pour tout le parc, par
  occupation (pas de seuil propre à un immeuble).
- **Cause commune à plusieurs immeubles** (`vigie/recoupement.py`). Quand au moins 4 immeubles, représentant au
  moins 10 % des immeubles jugés par la même famille de règles (signature de chauffage, PAC, électricité, solaire,
  règles du même mois à climat égal), entrent en alerte à 3 jours d'écart au plus, l'alerte porte la mention
  « Cause commune probable », sa confiance est divisée par deux et aucun bon automatique n'est préparé ; elle n'est
  jamais supprimée et le bon manuel reste possible. Seuils dans `config/referentiel.json` (`cause_commune_*`).
  Limites : un groupe de 2 ou 3 immeubles n'est pas marqué ; un immeuble détecté avant les autres peut recevoir son
  bon automatique avant d'être marqué ; le critère n'a pas été validé sur un cas réel (l'épisode de fin juin 2025
  du lot communal n'a pas pu être reproduit).
- **Fenêtres de nuit à l'heure de Zurich.** Les fenêtres de nuit (1 h – 5 h pour la fuite d'eau et l'électricité,
  22 h – 6 h pour le chiffrage de l'électricité de nuit) et l'abaissement nocturne du chauffage (22 h – 5 h) sont
  lus à l'heure de Zurich, été comme hiver ; les mesures restent stockées en UTC et les jours jugés restent des
  jours UTC. Aux changements d'heure, la nuit compte 3 relevés (fin mars) ou 5 (fin octobre) : elle reste jugée
  tant qu'au moins 3 heures sont mesurées. L'horaire d'abaissement est le même pour tous les immeubles. Les
  résultats versionnés de la campagne (`evaluation/sorties/`) et la valeur `dj16_nuit_annuel_normal` du référentiel
  (761,3, utilisée par la seule projection) ont été calculés avant ce changement, avec des fenêtres en UTC.
- **Durée du rejeu.** Les séries sont préparées une seule fois par rejeu puis tronquées à chaque date
  (`vigie/series.py`), à résultats identiques. Mesuré sur le grand exemple : rejeu de 60 jours en 64 s au lieu de
  111 s. Non remesuré sur la base du lot communal (environ 15 minutes pour une année à la V0.3.0) ; le reste du
  temps est dans les détecteurs (solaire, électricité de nuit, signature).

### Données, tarifs et connexions

- **Tarifs et facteurs CO₂ = valeurs d'exemple** tant qu'ils ne sont pas saisis comme « tarif de mon contrat ».
  Les tarifs par défaut reprennent les tarifs publics 2026, indicatifs, hors abonnements et coûts fixes
  (électricité 0,2707, gaz 0,0868, solaire 0,1185 CHF/kWh, eau 5,10 CHF/m³ ; chaleur et CAD 0,1105 CHF/kWh,
  milieu de la fourchette 0,086 à 0,135) : ils ne remplacent pas ceux de vos contrats.
- Solaire compté à 0,1185 CHF/kWh : une petite coupure d'onduleur passe sous l'enjeu minimal (8,22 CHF/mois) et
  n'est plus affichée. Sur le grand exemple en météo réelle, celle du G17 (58 kWh/mois, 7 CHF) est masquée :
  `python -m vigie evaluer --grand --meteo-reelle` lève 15 dérives sur 16 (16 sur 16 à 0,20 CHF/kWh).
  Les tarifs sont communs à tout le parc : pas encore de tarif par immeuble ou par contrat.
- CAD et gaz : PCS et tarifs d'exemple à remplacer par ceux des contrats. Le gaz en m³ est converti par un facteur
  unique (`gaz_pcs_kwh_par_m3`), pas par le facteur mensuel du distributeur ; un compteur de gaz en m³ sans PCS
  déclaré n'est pas analysé (qualité des données seulement).
- Connexion API générique : son format par défaut est une hypothèse, à aligner sur la documentation du fournisseur
  retenu (chemin, champs, envoi de la clé).
- L'envoi SMTP a été testé avec un serveur simulé seulement, pas avec un vrai serveur de messagerie.
- Compteurs sans règle de dérive : l'injection (hors défaut de données), les sous-compteurs électriques, la chaleur
  des PAC, le mazout et les granulés livrés.

### Chiffrage

- Chauffage et PAC : le montant est l'excès **mesuré** depuis le début détecté de la dérive. La part antérieure
  (dérive progressive, jours sous le seuil) et les heures sans mesure ne sont pas comptées : c'est un minimum. Le
  rythme mensuel vaut pour un mois au climat des derniers jours ; il s'écarte du mois suivant quand la saison
  change. L'ancienne annualisation « × 210 jours » sous-estimait en début de saison et surestimait en plein hiver.
- Immeuble vide chauffé : l'excès est compté au-dessus du talon hors-gel déclaré, donc sous-estimé si le hors-gel
  réel consomme moins que le talon.
- La projection est une hypothèse (climat normal, dérive maintenue 12 mois) : l'année réelle et la suite de la dérive
  s'en écartent. Elle n'est jamais un déclencheur.

### Méthodes

- Au pas journalier, les règles de nuit (fuite d'eau, électricité) et le rendement horaire de la PAC ne tournent
  pas : seules les méthodes « au jour » de la matrice s'appliquent.
- Règle du même mois : en été, l'écart d'une PAC ou d'une chaudière ne pèse que quelques francs par mois ; l'alerte
  passe alors sous l'enjeu minimal et revient à l'automne. Il faut 2 années de référence après le dernier
  changement d'installation : un site récemment transformé n'est pas jugé pendant deux ans.
- Première année de suivi (pas de « même saison l'an passé ») : les débuts de saison sont moins bien couverts, et
  en première saison de chauffe rien n'est conclu tant que la référence ne contient aucun jour aussi froid.
- Le modèle de la PAC et la signature de chauffage sont appris sur la même saison de l'an passé et les 60 jours
  qui précèdent la fenêtre d'analyse (sinon sur toute la période antérieure).
- **PAC sans compteur de chaleur chauffage** (électricité seule, ou eau chaude seule) : la part chauffage est
  estimée depuis la météo. Il faut au moins 240 heures froides (sous 14 °C) dans la période de référence ; sinon
  Vigie ne conclut pas, par exemple au tout début de la première saison de chauffe suivie. La dérive est aussi
  moins finement chiffrée qu'avec un compteur de chaleur.
- Règle d'eau au jour : peu sensible sur un gros consommateur (une fuite de 20 l/h ne double pas un niveau de base
  de 30 000 l/jour). Son « début » est le plus tôt possible, à quelques jours près.
- Les dérives qui ne se voient qu'en croisant plusieurs fluides ne sont pas recherchées. Quand la production et
  l'injection d'une installation solaire dérivent pour la même cause, seule la production a une règle.

### Solaire

- L'ensoleillement vient de la station MétéoSuisse (Genève-Cointrin), pas d'un capteur sur le toit ; un ombrage
  local ou une averse sur une seule commune ajoute du bruit, compensé par la persistance en jours ensoleillés. Les
  jours couverts (< 0,6 kWh/m²) et les jours de gel (neige possible sur les modules) ne sont pas jugés. Une
  installation suivie par son onduleur devient « compteur muet » (Données) quand l'onduleur s'arrête.
- La référence prend les journées comparables de même saison, l'an passé et juste avant la fenêtre d'analyse. Une
  baisse très lente commencée plus d'un mois avant la fenêtre est en partie apprise comme normale tant que la même
  saison de l'an passé manque (première année de suivi) ; elle est alors sous-estimée.
- Sans historique : la référence nominale (production prévue au prorata de l'ensoleillement horizontal) ne tient pas
  compte de l'orientation des modules saison par saison ; elle sert seulement en attendant l'historique.
- Règle de l'onduleur : déclarée dès la première coupure, sans la persistance habituelle des autres règles (une
  production à zéro entre deux relevés producteurs est un événement franc). Un compteur relevé à l'heure ne voit pas
  une coupure plus courte que l'heure.
- Un seul compteur de production analysé par immeuble (comme les autres fluides) ; une installation à plusieurs
  onduleurs se déclare en un compteur total. Sans jour ensoleillé jugé depuis 21 jours (rayonnement absent, ciel
  couvert durable), Vigie ne conclut pas. Une baisse brutale restée sous le seuil de panne est signalée comme baisse
  de production (règle « dégradation »), avec la mention « apparue d'un coup ».
- Le métier « Solaire » regroupe l'installateur photovoltaïque ; un défaut côté réseau du distributeur reste à
  signaler par l'installateur.

## Licence

Le code de Xread Dérives est publié sous **licence MIT** (fichier `LICENSE`) : utilisation, modification et
redistribution libres, y compris commerciales, à condition de conserver la mention de copyright et le texte de la
licence ; le logiciel est fourni sans garantie. `LICENCES_TIERS.md` liste ce que la licence MIT ne couvre pas :
Leaflet (BSD 2-Clause), le jeu de données communal (CC BY 4.0, attribution obligatoire), les données
MétéoSuisse et les fonds swisstopo.

Attribution des données du lot : voir `LICENCES_TIERS.md` (CC BY 4.0). Température et
rayonnement : données réelles MétéoSuisse, station Genève-Cointrin.

Avant une mise en ligne publique : ne publiez pas une base `vigie.db` ni un dossier `sorties/` contenant des
données réelles (relevés, adresses, prestataires, réglages de messagerie, clé de connexion chiffrée). Le nom du
titulaire dans `LICENSE` (« Xread Dérives (auteurs et contributeurs) ») est à remplacer par le vôtre.
