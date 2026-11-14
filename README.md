# Xread Dérives (Vigie) — détecteur de dérives du parc immobilier (V0.3.0)

Interface de gestion pour le gestionnaire d'immeubles : parc (adresses, immeubles, compteurs et leur connexion),
règles réglables selon l'occupation, coûts de la dérive, imports, prestataires par métier et **bons de travaux
préparés et envoyés automatiquement** selon la dérive constatée.
Tout tourne en local sur le poste : aucune donnée de consommation ne part sur Internet.
Code sous **licence MIT** (voir `LICENSE` ; données et composants tiers : `LICENCES_TIERS.md`).

## V0.3.0 : import d'un patrimoine complet (lot communal)

La base `vigie.db` de cette version contient le **patrimoine d'une commune suisse fictive** (lot de
données sous CC BY 4.0) et la **liste des prestataires** de la base V0.2.

**Ce qui est importé** (fichiers dans `donnees/`)

| Fichier | Contenu | Résultat |
|---|---|---|
| `patrimoine.xlsx` | Bâtiments, installations, compteurs, relevés **mensuels** 2021-2025, références | 48 sites, 50 bâtiments, 64 installations, 172 compteurs, 9 433 relevés, 336 références |
| `courbes_jour.csv` | Gaz, eau et chaleur PAC **au jour**, 2025 | 16 courbes, 5 840 valeurs |
| `courbes_cad_heure.csv` | Chauffage à distance **à l'heure**, 2025 (énergie, débit, aller, retour) | 4 sous-stations, 16 séries, 140 160 valeurs |
| `courbes_pv.xlsx` | Production solaire **au quart d'heure**, 2025 (classeur, mêmes colonnes que le CSV ; deux coupures d'essai : S09 le 01.01, S26 le 31.12). L'injection au quart d'heure, chargée auparavant depuis `pv_15min.csv`, reste en base | 3 courbes, 105 120 valeurs |
| `RC-Electricite-15min-2025-FICTIF.csv` | Électricité soutirée **au quart d'heure**, 2025, des 48 sites. **Courbes synthétiques, hors lot** : générées par `python -m evaluation.generer_electricite_15min` à partir des relevés mensuels (le total de chaque mois est le relevé), de la typologie, du calendrier et du solaire de chaque site. Aucune dérive ajoutée. 72 Mo : trop de lignes pour un seul onglet Excel | 48 courbes, 1 681 920 valeurs |
| `calendrier.xlsx` | Mêmes courbes que les CSV ; seul son **calendrier 2025** est lu | 1 825 références (jour ouvré, férié, vacances, température et rayonnement du jour) |

**Correspondance avec Vigie**

- Un **site** devient un immeuble, avec le même code (`S01`). Ses **bâtiments** gardent leur identifiant
  (`S01-B1`, `S01-B2`) dans la fiche du site, avec année, rénovation, surface, niveaux, label et logements. Les
  **installations** (`S01-I1`…) y figurent aussi, avec leur mise en service et leur retrait.
- Les **compteurs** gardent leur code (`S01-EL`, `S04-PV`, `S13-GZ`…), leur rôle (général, sous-compteur,
  production, livraison), leur compteur parent et leurs bornes de service. Un compteur retiré avant la fin des
  relevés est « inactif » (son historique reste consultable).
- Fluides : électricité soutirée, **électricité injectée**, **sous-compteurs électriques**, électricité et chaleur de
  PAC, production solaire (puissance crête et année reprises de l'installation), gaz (m³), chauffage à distance, eau,
  et les **livraisons** de mazout (litres) et de **granulés** (kg).
- **Relevé mensuel** : nouveau pas de temps (43 200 minutes). La valeur est stockée telle quelle, dans l'unité du
  compteur, horodatée à la fin du mois (janvier 2021 → `2021-02-01T00:00:00Z`).
- **Courbe fine** : elle devient un second compteur relié au premier (`S13-GZ` = relevé mensuel du distributeur,
  `S13-GZ-JOUR`, `S01-CAD-HEURE`, `S09-PV-15MIN` = courbes). Deux pas de temps ne sont jamais mélangés dans une
  série et rien n'est compté deux fois. Les horodatages des fichiers (début d'intervalle, heure légale suisse) sont
  convertis en UTC, fin d'intervalle. Le débit et les températures des sous-stations ont leurs propres séries
  (`S01-CAD-DEBIT`, `-TALLER`, `-TRETOUR`). Le moteur analyse la série la plus fine de chaque fluide.
- **Carte et coordonnées GPS** : les sites n'ont pas d'adresse réelle, seulement une position en kilomètres sur le
  plan du jeu. À l'import, chaque site reçoit des coordonnées GPS (latitude, longitude) calculées depuis ce plan et
  enregistrées dans la base : le milieu du plan est posé sur Carouge – Plainpalais (au sud de la rade, aucun site
  dans le lac) et les distances entre sites sont conservées. La carte swisstopo du canton de Genève les affiche
  comme les autres adresses ; l'infobulle donne les coordonnées. Ces positions sont fictives, comme les sites :
  rien n'est envoyé au géocodeur, et une position saisie à la main n'est jamais remplacée.
- **Références** (table `reference`) : climat mensuel et normale 1991-2020, facteurs de conversion du gaz par mois,
  mazout, granulés, facteurs CO₂ du lot, calendrier 2025. Elles sont stockées, pas encore utilisées par le moteur.

**Contrôles à l'import** : chaque écart est tracé dans la table `anomalie_import`, dans la page Imports et dans
`sorties/anomalies_import.csv`. Rien n'est corrigé ni comblé.

- Relevés mensuels : 1 doublon (S03-EL, juin 2024), 1 valeur négative (S14-GZ, mars 2022, marquée « suspecte »),
  3 relevés manquants (S25-GZ, S44-EL, jamais comblés), 4 relevés estimés par le distributeur (S40-EL, marqués
  « estimée », affichés mais exclus des décisions).
- Autres contrôles prévus : compteur inconnu, valeur illisible, désaccord de site, de fluide ou d'unité avec le
  compteur, relevé hors bornes de service, énergie incohérente avec valeur × facteur, mois ou pas de temps sans
  aucune ligne, livraisons du même mois (additionnées), bilan thermique du chauffage à distance.
- **La courbe retombe-t-elle sur le relevé mensuel ?** (tolérance 1 %, 3 % pour l'injection solaire). 18 mois
  s'en écartent nettement, sur 6 compteurs :

| Compteur | Mois 2025 | Écart de la courbe au relevé mensuel |
|---|---|---|
| S26-GZ (gaz, centre sportif) | octobre à décembre | +9 %, +18 %, +19 % |
| S05-EAU (eau, école des Crêts) | juillet et août | +146 %, +82 % |
| S37-CAD (chaleur, immeuble Bois-Joli 23) | novembre et décembre | +18 %, +19 % |
| S32-PV (solaire, voirie) | mai à septembre | −13 % à −42 % |
| S32-EL-INJ (injection, voirie) | mai à septembre | −18 % à −52 % |
| S26-EL-INJ (injection, centre sportif) | août | −72 % |

**Prestataires** : les 20 prestataires de la base V0.2 sont repris (`python -m vigie reprendre-prestataires`). Les
6 prestataires « tout le parc » sont inchangés. Les 14 qui étaient rattachés à des immeubles de l'ancien exemple
(12 partenaires de secteur et 2 conciergeries), immeubles qui n'existent plus ici, sont répartis sur les
**quartiers** de la commune, à tour de rôle par métier ; la répartition se modifie dans l'écran Prestataires.
« Solaire Exemple SA » est ajouté pour couvrir le métier Solaire (12 installations photovoltaïques).

**Commandes**

```powershell
python -m vigie importer-patrimoine donnees\patrimoine.xlsx   # --apercu : contrôle sans écrire
python -m vigie reprendre-prestataires ..\Xread_Derives_V0_2_0\vigie.db
python -m vigie importer-courbes donnees\courbes_jour.csv donnees\courbes_cad_heure.csv donnees\calendrier.xlsx donnees\courbes_pv.xlsx
python -m vigie analyser
```

Dans l'interface : Imports › « Classeur patrimoine et courbes », avec aperçu avant import.

## Une méthode par fluide et par pas de relevé

**Les règles sont dynamiques** : le moteur applique à chaque compteur la méthode la plus fine que son relevé
permet, et jamais une méthode horaire à un relevé journalier. La matrice ci-dessous est codée une seule fois
(`regles.PAS_REGLES`, `regles.matrice`) ; elle alimente la page « Règles & coûts » et le document
**`docs/Xread_Derives_methodes_par_pas_de_releve.pdf`** (11 pages : méthode, calcul, seuil et justification de la dérive
pour chaque fluide et chaque pas ; régénéré par `python -m evaluation.pdf_methodes_par_pas`).

| Fluide | Quart d'heure et heure | Jour | Mois |
|---|---|---|---|
| Eau | fuite de nuit (débit minimum 1 h – 5 h) | niveau de base sur 7 jours | même mois des années précédentes |
| Électricité | puissance de nuit | jour comparé aux jours de même type | même mois, à climat égal |
| Gaz, chaleur, chauffage à distance | signature à météo égale ; retour du CAD | signature à météo égale | même mois, à climat égal |
| Pompe à chaleur | rendement heure par heure | électricité du jour à météo égale | même mois, à chaleur produite égale |
| Solaire | coupures de l'onduleur ; journées comparables | journées comparables | rendement du même mois |

Méthodes ajoutées pour compléter la matrice :

- `elec_nuit` **à température extérieure égale** pour les sites dont la nuit suit le froid (PAC, chauffage
  électrique) : la nuit est comparée aux nuits de même froid de la référence (± 2 degrés, jamais d'extrapolation), au
  lieu des nuits de 20 à 50 jours plus tôt. Mesuré sur les 48 courbes d'électricité au quart d'heure (synthétiques) :
  14 alertes de nuit en décembre sans la température, 3 avec. Un site insensible au froid garde la règle d'origine.

- `elec_jour` — électricité relevée au jour : chaque jour comparé à la médiane des jours de même type (ouvré,
  vacances, non ouvré) des 8 semaines de référence ; +20 % pendant 5 jours.
- `pac_signature` — PAC relevée au jour : électricité à météo égale (même signature que le chauffage) ; +15 % pendant
  7 jours.
- Solaire relevé au jour : les règles arrêt, panne et dégradation tournent sur la production journalière et
  l'ensoleillement du jour (sans le détail matin / midi / après-midi du diagnostic).
- PAC au mois **à chaleur produite égale** : quand la chaleur de la PAC est comptée, l'électricité du mois est
  comparée à `chaleur du mois × (électricité ÷ chaleur) du même mois des années précédentes`, c'est-à-dire au
  rendement. Mesuré sur S09 : rendement de 3,0 au lieu de 4,2, soit +39 %.
- `chaleur_historique` — chaleur de chaufferie au mois, comme le gaz et le chauffage à distance.

Le lot communal n'a ni électricité, ni PAC, ni solaire relevés au jour : ces trois méthodes sont validées par leurs
tests sur des séries construites, pas sur des données du lot.

## Comparaison à l'historique du même mois (gaz, PAC, chaleur, CAD, électricité, eau, solaire)

Sept règles (`vigie/historique.py`) : `gaz_historique`, `pac_historique`, `chaleur_historique`, `cad_historique`,
`elec_historique`,
`eau_historique` et `solaire_historique`. La valeur d'un mois est comparée à celle du **même mois des années
précédentes** (médiane des 3 dernières années connues). Un écart au-delà du **pourcentage réglé**, tenu plusieurs mois
de suite, est une dérive. Seuil, persistance, types d'immeuble, gravité et prestataire se règlent dans « Règles &
coûts ». C'est la seule règle des compteurs relevés une fois par mois : elle en couvre 153 sur 172 dans le lot.

| Règle | Écart toléré | Persistance | Correction |
|---|---|---|---|
| Gaz, chaleur, chauffage à distance | +20 % | 2 mois | climat du mois (degrés-jours) |
| Pompe à chaleur | +20 % | 2 mois | chaleur produite du mois si elle est comptée, sinon climat du mois |
| Électricité | +20 % | 3 mois | climat du mois (sans effet si le compteur n'y est pas sensible) |
| Eau | +20 % et au moins 480 l/jour de plus | 2 mois | aucune |
| Solaire | −15 % de rendement | 2 mois | ensoleillement du mois, décote des modules |

- **À climat égal.** Mesuré sur 2022-2025 : une comparaison brute lèverait 44 épisodes de gaz et de PAC sur 25
  compteurs, presque tous dus à un mois plus froid que ses homologues (octobre 2025 : 180 degrés-jours contre 60).
  L'attendu est donc `référence du même mois + pente × (degrés-jours du mois − degrés-jours de la référence)`, la
  pente étant apprise sur l'historique du compteur lui-même. Sans degrés-jours pour le mois, la comparaison se fait
  sans correction et le constat le dit.
- **Solaire à ensoleillement égal** : production du mois ÷ rayonnement du mois, comparée au même rendement des années
  précédentes, décote annuelle déduite. Les mois très peu ensoleillés (moins de 40 kWh/m² : décembre, janvier) ne
  sont pas jugés. C'est la référence de plusieurs années qui manque aux courbes fines en première année de suivi.
- **Deux garde-fous**, tirés des mêmes relevés. (1) Il faut **2 années de référence**, et avec 2 seulement la plus
  prudente des deux : les sites fermés début 2021 faisaient paraître 2022 à +60 %. (2) La référence ne remonte jamais
  avant le **dernier changement d'installation** du site (table `installation`) : une PAC qui remplace une chaudière
  ou du solaire posé rendent l'historique d'avant incomparable.
- **Résultat sur 2022-2025**, garde-fous compris : chauffage à distance 0 épisode ; gaz 1 (S22, +26 %) ; PAC 2 (S09,
  +38 % toute l'année 2025, environ 11 600 kWh) ; eau 1 (S35, +30 % pendant 8 mois, 1 053 m³) ; solaire 1 (S26, deux
  mois sans production en 2023, 42 000 kWh) ; électricité 13 à 2 mois de persistance, dont plusieurs groupés sur les
  mêmes mois d'intersaison, d'où ses 3 mois par défaut.
- **Quel compteur** : le relevé mensuel quand il existe, sinon la courbe ramenée aux mois complets. Un mois manquant
  ou estimé n'est ni comblé ni jugé. Gaz en m³ : converti par le pouvoir calorifique du référentiel.
- **Une seule alerte par cause** : si une règle plus fine du même fluide est déjà en alerte sur l'immeuble, la règle
  historique se tait.
- **Exemples de 12 mois** : aucun « même mois » d'une année précédente, la règle reste muette (précision et rappel
  inchangés). Elle est validée par ses tests et sur les 5 ans de relevés du lot.

## Jours ouvrés et vacances dans la règle de chauffage

`vigie/calendrier.py`. Mesuré sur les courbes 2025, à météo égale : dans une crèche, une école, une bibliothèque, un
bâtiment administratif ou des ateliers, un jour ouvré consomme 9 à 17 % de plus que la droite météo et un jour non
ouvré 18 à 25 % de moins, alors que le seuil de dérive est de 10 %. Les logements et les installations sportives n'y
sont pas sensibles. En première année de suivi, la signature de chauffage (chaleur, CAD, gaz) compare donc chaque jour
aux jours de **même type** (ouvré, ouvré pendant les vacances scolaires, non ouvré), mais seulement pour les immeubles
où l'écart se voit dans leur propre référence. Un jour ouvré n'est jamais comparé à un week-end.

- Source : le calendrier du lot (jours ouvrés, fériés, vacances scolaires) ; pour une date qui n'y figure pas, lundi à
  vendredi = ouvré.
- Effet mesuré au rejeu : dans l'école S06 et la crèche S13, la dérive de mars n'était vue que 1 ou 2 jours ; elle
  est maintenant tenue (S06 : 34 jours en alerte, +28 %, environ 2 570 CHF).
- Garde ajoutée : si plus aucun jour n'est jugeable depuis 10 jours (pas de météo comparable en référence, à
  l'intersaison), la règle ne conclut plus, au lieu de rester figée sur son dernier constat.
- **Jamais d'extrapolation** : un jour n'est jugé que s'il a des jours comparables plus froids ET plus doux que
  lui (3 de chaque côté). À l'entrée de la saison de chauffe, des comparables tous plus doux sous-estimaient
  l'attendu et levaient de fausses dérives.
- **Jours comparables ramenés au degré-jour du jour jugé** (pente locale) avant d'en prendre la médiane : une
  dérive réelle de +20 % était lue +14 % ou +28 % selon la répartition des jours comparables ; elle est lue
  +19 à +20 %.
- Conséquence assumée : en première saison de chauffe, tant que la référence ne contient aucun jour aussi froid,
  rien n'est conclu (120 à 180 jours de données commencés en été ne suffisent pas ; 210 jours suffisent).

## Couverture des règles : l'alerte de granularité

Une règle ne juge un compteur que s'il est relevé assez finement pour elle : la fuite de nuit (1 h – 5 h) demande un
relevé à l'heure, le niveau de base de l'eau un relevé au jour, la règle du même mois se contente d'un relevé mensuel.
L'interface le dit partout où une règle est affichée :

- **Tableau de bord** : une bannière signale les règles actives qui ne tournent sur aucun compteur et les compteurs
  sans aucune règle.
- **Règles & coûts** : section « Couverture des règles » (règle sans effet, règle partielle, compteurs sans règle) ;
  chaque règle indique le relevé qu'elle exige et le nombre de compteurs du parc sur lesquels elle tourne.
- **Fiche immeuble** : « sans effet ici : demande un relevé … » à côté de chaque règle que le relevé de l'immeuble ne
  permet pas.

Dans la base du lot, courbes d'électricité au quart d'heure comprises : 3 règles sans effet (fuite de nuit de l'eau,
rendement et signature de la PAC : l'eau y est relevée au jour ou au mois, les PAC au mois), 11 règles partielles et
26 compteurs sans règle (injection, sous-compteurs, mazout et granulés livrés). Une règle du relevé au jour n'est pas
signalée quand le fluide a déjà des courbes plus fines : la règle fine s'en charge.

Le moteur juge la situation à la fin des relevés. Pour retrouver les dérives réparties sur l'année, il est **rejoué
jour après jour** : à chaque date, il ne voit que les mesures déjà reçues, avec les mêmes règles et la même
persistance qu'en exploitation. Les alertes successives sont regroupées en **épisodes** (même site, même cause ; une
alerte revenue dans les 10 jours reste le même épisode). Les alertes encore en cours à la dernière date sont ouvertes
dans la base, avec leur référence gelée à leur début.

```powershell
python -m vigie meteo-periode 2024-11-01 2025-12-31   # météo horaire réelle de Genève-Cointrin (température, rayonnement)
python -m vigie rejouer 2025-01-01 2026-01-01         # 366 analyses, environ 7 minutes
```

Résultat : page **Rejeu** de l'interface, paramètre `rejeu` de la base et `sorties/rejeu_episodes.csv`.

**Épisodes sur 2025.** Le nombre dépend des réglages (voir la page Rejeu). Aux réglages par défaut, le rejeu retrouve
les écarts du contrôle d'import, les deux coupures d'onduleur ajoutées pour l'essai (S09 le 01.01, S26 le 31.12), et,
par les règles du même mois, la PAC de S09 (détectée le 01.03, masquée en été sous l'enjeu minimal, revenue le 01.10)
et l'électricité du parking S47 (+37 %, depuis juillet 2024). Les épisodes qui durent :
| Détecté le | Compteur | Épisode | Du … au … |
|---|---|---|---|
| 27.05 | S32-PV (solaire, voirie) | Chute brutale de production, −35 % à ensoleillement égal | 24.05 au 05.09 (86 jours en alerte) |
| 16.07 | S05-EAU (école des Crêts) | Niveau de base de l'eau : 3 410 l/jour au lieu de 530 (155 m³ constatés) | 07.07 au 31.08 |
| 07.08 | S26-EL-INJ (centre sportif) | Défaut de données : injection nulle alors que l'installation produit | 07.08 au 26.08 |
| 27.10 | S06-CAD (école de Bois-Joli) | Retour de la sous-station à 57,9 °C au lieu de 48,8 °C | depuis le 20.10, en cours fin décembre |
| 08.11 | S26-GZ (centre sportif) | Gaz +22 % à météo égale | depuis le 01.11, en cours fin décembre |
| 18.11 et 16.12 | S37-CAD (immeuble Bois-Joli 23) | Chaleur livrée +18 % à météo égale | depuis le 03.11 (deux épisodes), en cours fin décembre |
| toute l'année | S14-GZ | Défaut de données : valeur négative du relevé mensuel de mars 2022 | en cours |

Les neuf autres épisodes sont **brefs (1 à 8 jours en alerte)** et à vérifier avant d'agir : chauffage à distance de
S06 (mars, juin), gaz de S13 (avril, octobre), de S31 (juin, septembre) et de S34 (novembre), solaire de S09 (juin) et
de S32 (novembre). Ils tombent surtout aux changements de saison, là où une première année de suivi a peu de jours
comparables.

**Règles ajoutées pour ces données** (`vigie/complements.py`, `vigie/solaire.py`, réglables dans « Règles & coûts ») :

- `eau_talon` — **eau relevée au jour** : le minimum de consommation sur 7 jours (qui contient toujours un week-end)
  dépasse de 100 % le niveau de base de référence, et d'au moins 480 l/jour (20 l/h en continu), pendant 3 jours.
  Une fuite relève ce minimum ; le remplissage d'un bassin ne le change pas.
- `cad_retour` — **retour trop chaud d'une sous-station** : température de retour au-dessus de l'attendu à
  température extérieure égale de plus de 5 °C pendant 7 jours. Non chiffrée en kWh, jamais masquée.
- `donnees_injection` — **défaut de données** : injection nulle des jours entiers alors que le solaire produit plus
  que tous les jours sans injection de la référence.
- `solaire_onduleur` — **défaut de l'onduleur** : entre le lever et le coucher du soleil, donnés par le rayonnement
  de la station météo (rayonnement > 0), la production tombe à **zéro entre deux relevés producteurs**. Jugé au pas
  du compteur (quart d'heure ou heure) sur les 7 derniers jours. La nuit, l'aube avant le premier relevé producteur
  et une journée entière à l'arrêt (règle `solaire_arret`) ne sont pas des coupures. **Déclaré dès la première
  coupure** ; la durée minimale (en relevés à zéro) et le nombre de jours avec coupure se règlent. La production
  non réalisée est estimée d'après les deux relevés qui encadrent chaque coupure. Les courbes solaires d'origine du
  lot n'ont aucune coupure de ce type ; le classeur `courbes_pv.xlsx` en contient deux, mises à la main
  pour l'essai (S09 le 01.01.2025 de 14:00 à 15:15, S26 le 31.12.2025 de 11:00 à 11:45), toutes deux relevées ; le
  grand exemple en injecte une sur G17.
- **Signature de chauffage en première année de suivi** (pas de « même saison l'an passé ») : l'attendu d'un jour est
  la médiane des journées de référence de météo comparable (± 2 degrés-jours, au moins 10 jours), sinon le jour
  n'est pas jugé. Le mode habituel, avec un an d'historique, est inchangé.
- Solaire : une alerte ouverte garde sa qualification (panne ou dégradation) tant qu'elle persiste ; quand la
  référence gelée n'a pas la même saison, les journées comparables sont cherchées à ± 60 puis ± 90 jours.
- Un compteur dont les relevés commencent il y a moins de 30 jours est jugé depuis son premier relevé (plus de
  « données incomplètes » à tort).

**Limites de la V0.3.0**

- **Relevés mensuels** : gaz, PAC, chauffage à distance, électricité, eau et solaire ont la règle du même mois ;
  l'injection, les sous-compteurs, la chaleur des PAC, le mazout et les granulés n'ont aucune règle de dérive.
- Règle du même mois : en été, l'écart d'une PAC ou d'une chaudière ne pèse que quelques francs par mois ; l'alerte
  passe alors sous l'enjeu minimal et revient à l'automne. Un changement d'usage non déclaré (horaires, surface
  chauffée, saison d'une patinoire) ressort comme une dérive. Il faut 2 années de référence après le dernier
  changement d'installation : un site récemment transformé n'est pas jugé pendant deux ans.
- Signature de chauffage : plusieurs immeubles en alerte les mêmes jours (fin juin 2025 : S01, S06, S24, S31) signalent
  plutôt un effet de météo ou de calendrier qu'une dérive ; ces épisodes brefs restent à vérifier.
- Le rejeu d'une année dure environ 15 minutes (7 avant les règles du même mois).
- Rejeu : une seule année de courbes, donc pas de « même saison l'an passé ». Les débuts de saison sont moins bien
  couverts, et une dérive d'octobre sous le seuil de 10 % (S26-GZ : +9 %) n'est vue qu'en novembre. Les deux dérives
  de S32 (production et injection) viennent de la même cause : seule la production a une règle.
- La chaleur de la PAC de S09 (au jour) n'a pas de règle : elle demande l'électricité de la PAC à l'heure. La courbe
  électrique au quart d'heure du lot (soutirage) n'a pas été fournie ; les dérives qui ne se voient qu'en croisant
  les fluides et l'électricité ne sont donc pas recherchées.
- Règle d'eau au jour : peu sensible sur un gros consommateur (une fuite de 20 l/h ne double pas un niveau de base
  de 30 000 l/jour). Son « début » est le plus tôt possible, à quelques jours près.
- Règle de l'onduleur : déclarée dès la première coupure, à la demande, sans la persistance habituelle des autres
  règles (une production à zéro entre deux relevés producteurs est un événement franc). Un compteur relevé à l'heure
  ne voit pas une coupure plus courte que l'heure.
- Les tarifs et facteurs CO₂ restent ceux d'EXEMPLE de Vigie ; ceux du lot (émissions directes) sont dans la table
  des références.
- Le gaz en m³ est converti par un facteur unique, réglé pour cette base à 11,1 kWh/m³ (moyenne indiquée par le
  lot), pas par le facteur mensuel du distributeur. Les montants en CHF utilisent les tarifs d'exemple.
- Attribution des données du lot : voir `LICENCES_TIERS.md` (CC BY 4.0). Température et
  rayonnement : données réelles MétéoSuisse, station Genève-Cointrin.
- 224 tests unitaires (132 de la V0.2, 16 pour les imports et la carte, 14 pour le rejeu et les règles
  complémentaires, 6 pour l'onduleur, 35 pour les règles du même mois, le calendrier et la couverture, 21 pour les
  méthodes par pas de relevé et leur matrice).
- Base du lot : les 48 courbes d'électricité au quart d'heure (synthétiques) y sont importées ; elle passe de 386 000
  à 2 068 000 mesures (252 Mo) et l'analyse dure environ 12 secondes.
- Interface : enregistrer une règle lui retirait tous ses types d'immeuble (elle ne s'appliquait plus nulle part),
  et un prestataire limité à « certains immeubles » perdait sa liste. Corrigé ; une règle sans aucun type
  d'immeuble est désormais refusée.

## Nouveauté : production solaire (photovoltaïque)

- **Nouveau fluide « Solaire »** : production brute de l'onduleur ou du compteur de production (kWh, au pas horaire),
  avec les caractéristiques de l'installation saisies sur le compteur : **puissance crête (kWc, obligatoire)**,
  **production brute prévue (kWh/an)**, **année de mise en service** et **décote annuelle des modules** (%/an, 0,5 si
  vide). Colonnes Excel `puissance_crete_kwc`, `production_prevue_kwh_an`, `mise_en_service`, `degradation_pct_an`.
- **Ensoleillement mesuré** : la mise à jour MétéoSuisse relève aussi le **rayonnement global** de Genève-Cointrin
  (`gre000h0`, W/m², moyenne horaire) dans le point `RAYON_GVE`.
- **Production comparée à ensoleillement égal** : chaque jour ensoleillé (≥ 0,6 kWh/m²) est comparé aux **journées
  comparables** de l'historique : même saison (± 30 jours de la même date) et même ensoleillement (± 15 %, à défaut
  ± 25 ou ± 35 %). L'attendu est la médiane de leur rendement (kWh produits par kWh/m² reçu), **corrigée de la décote
  prévue des modules** entre leur date et le jour jugé : une baisse logique due à l'âge n'est jamais une alerte. Sans
  historique (installation neuve), la référence est la **production prévue**, décotée selon l'âge, au prorata de
  l'ensoleillement du jour sur l'ensoleillement annuel normal de Genève (1 385,9 kWh/m², MétéoSuisse GVE 2016-2025).
- **Trois qualifications**, une seule alerte par immeuble à la fois :
  - `solaire_arret` (Élevée, 2 jours ensoleillés) : production quasi nulle malgré le soleil (onduleur, disjoncteur,
    interrupteur DC) ;
  - `solaire_panne` (Élevée, 3 jours ensoleillés, −15 %) : **chute brutale**, l'essentiel de la baisse en quelques
    jours. Une perte répartie sur toute la journée oriente vers des **cellules ou modules défectueux, une diode de
    dérivation ou une chaîne (string) hors service** ; une perte surtout le matin ou l'après-midi, vers un ombrage
    ou une chaîne d'une orientation ; une perte surtout à midi, vers l'onduleur ;
  - `solaire_degradation` (Modérée, 7 jours ensoleillés, −10 %) : **baisse progressive** au-delà de la décote
    (encrassement, vieillissement anormal, ombrage).
- **Chiffrage** : production perdue = Σ (attendu − mesuré) depuis le début, sur les heures mesurées ; valeur du kWh
  solaire perdu 0,20 CHF (EXEMPLE, autoconsommation évitée et reprise du surplus) ; CO₂ = électricité du réseau achetée
  à la place (EXEMPLE). Projection 12 mois = perte relative × production prévue décotée (hypothèse).
- **Qualité des données** : une production horaire au-delà de 1,25 × la puissance crête est un défaut d'échelle ou
  d'unité (alerte « Données », aucune alerte énergie sur ce compteur).
- **Partenaires solaires** : nouveau métier « Solaire » (installateur photovoltaïque) ; dans l'exemple, un partenaire
  par secteur (Soleil Rive Droite Sàrl, Photovolta Rive Gauche SA, Solaire Communes Sàrl) et Solaire Exemple SA.
- Interface : pictogramme et couleur du solaire, bloc « Installation solaire » dans la fiche du compteur, kWc et
  production prévue dans la liste des compteurs, trois règles réglables dans « Règles & coûts », tarif « Production
  solaire perdue » dans les coûts.

## Révision précédente : pas horaire, dérive constatée et projection, CAD et gaz

- **Toutes les données sont au maximum horaires.** Les compteurs sont déclarés à 60 minutes par défaut, pour tous
  les fluides. Un compteur plus grossier que l'heure est signalé « pas trop grossier » avec ce qu'il fait perdre. Un
  relevé **journalier** n'est attribué à aucune heure : il ne sert qu'aux règles journalières (eau et chauffage d'un
  immeuble vide, signature de chauffage). Au pas journalier, la fuite de nuit, l'électricité de nuit et la PAC ne
  sont pas surveillées.
- **Dérive constatée** (déclencheur des actions) : chaque alerte chiffre ce qui a été **mesuré** depuis le début de la
  dérive. Chauffage, CAD, gaz et PAC : Σ (mesuré − attendu) heure par heure sur les heures mesurées. Eau d'un immeuble
  vide : volume mesuré. Fuite de nuit et électricité de nuit : excès constaté la nuit × heures mesurées. Affichage :
  « Dérive constatée : ≈ X CHF », « 2 459 kWh depuis le 31.10.2026 (271 heures mesurées) ».
- **Rythme mensuel** (base de la priorité) : excès moyen par jour des 30 derniers jours de dérive au plus × 30.
- **Projection si rien n'est fait** (hypothèse, séparée) : coût sur 12 mois, dérive constante pour l'eau et
  l'électricité, **climat normal de Genève** pour le chauffage, le CAD, le gaz et les PAC (2 122 degrés-jours base
  16 °C par an, dont 761,3 la nuit : moyenne 2016-2025 des vraies données MétéoSuisse Genève-Cointrin, bloc
  `climat_reference` du référentiel, `python -m evaluation.climat_gve --ecrire`). Elle ne déclenche jamais d'alerte,
  ne change jamais la gravité, n'entre pas dans le score et n'apparaît pas dans le bon envoyé au prestataire (qui
  ne reçoit que la dérive constatée, en kWh ou m³).
- **Priorisation sur la mesure** : score = rythme mensuel constaté en CHF × confiance × urgence (× 1,5 si risque de
  sinistre), même base pour tous les fluides. L'enjeu minimal se règle en CHF par mois (8,22 CHF, équivalent exact
  de l'ancien 100 CHF/an pour l'eau et l'électricité).
- **Référence d'un an** : l'attendu du chauffage, du CAD, du gaz et de la PAC est appris sur la même saison de l'année
  précédente plus les 60 jours récents ; si cette saison manque (moins d'un an de mesures), sur toute la période
  antérieure.
- **Nouveaux fluides : chauffage à distance (CAD) et gaz.** CAD = chaleur livrée à la sous-station (kWh) ; gaz = énergie
  de la chaudière, en kWh ou en m³ convertis par le pouvoir calorifique supérieur du référentiel
  (`gaz_pcs_kwh_par_m3` = 10,5 kWh/m³, valeur d'EXEMPLE). Règles « signature » et « immeuble vide » reprises de la
  chaleur (causes `cad_signature`, `cad_vide`, `gaz_signature`, `gaz_vide`), métier Chauffagiste, tarifs et facteurs
  CO₂ d'EXEMPLE.
- **Exemple sur 12 mois** de relevés horaires pour tous les compteurs (cycle été / hiver visible dans les graphiques
  mois et année de la fiche).
- Champs d'alerte : `*_mesure` et `periode` (constaté), `*_mois` (rythme), `*_proj` et `projection` (hypothèse),
  `*_an` (eau, électricité, = projection), `chiffrage` (« annuel » : dérive constante, « mesure » : liée au climat),
  `heures_mesurees`, `reference`.
- Méthodes, données et résultats détaillés : `docs/Vigie_methodes_et_evaluation_derives.pdf`.

## Lancer

```powershell
pip install -r requirements.txt        # pandas, numpy uniquement
```

Puis double-cliquez sur **`Lancer Vigie.bat`** : la fenêtre de commande reste ouverte et le navigateur s'ouvre
sur http://127.0.0.1:8765. Fermer la fenêtre arrête Vigie.

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
python -m unittest discover -s tests   # 132 tests
```

La base d'exemple et votre base sont séparées : `demo` ne touche jamais à `vigie.db`.
Si Vigie est déjà ouvert, un second lancement le signale au lieu de démarrer une deuxième instance.

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

Installations solaires : T8 Les Tilleuls (30 kWc, 2019) et Ormeaux A (45 kWc, 2016) dans les immeubles d'origine ;
G03, G06, G10, G14 et G17 dans les immeubles ajoutés.

**Dérive solaire injectée dans les immeubles d'origine** : T8 perd une chaîne de modules sur quatre (−25 % depuis
14 jours, panne). Ormeaux A est sain.

**Dérives injectées dans les immeubles ajoutés** (en fin de période), en plus des 7 d'origine :
- G02 Carl-Vogt 65 : rendement PAC en baisse, avec la chaleur de chauffage seule comptée ;
- G05 Wendt 30 : fuite d'eau de nuit ;
- G08 France 20 : électricité de nuit +30 % ;
- G18 Vaudagne 13 (Meyrin, CAD) : chaleur livrée +18 % à météo égale depuis 12 jours ;
- G20 Servette 40 (gaz) : gaz +18 % à météo égale depuis 12 jours ;
- G06 Petit-Lancy 30 (solaire 80 kWc) : une chaîne de modules hors service, −25 % depuis 14 jours (panne) ;
- G03 Lyon 87 (solaire 60 kWc) : encrassement progressif jusqu'à −22 % sur 35 jours (dégradation) ;
- G14 Bel-Air 50 (solaire 40 kWc) : onduleur à l'arrêt depuis 6 jours.

G17 Lignon 40 (CAD) et G19 Vollandes 23 (gaz) sont sains, comme les installations solaires de G17 et de G10 (en
travaux : règles d'énergie suspendues). G12 La Montagne 50 a un compteur d'eau chaude « à
connecter ». Les 15 autres immeubles ajoutés, dont 2 partiellement occupés et 1 en travaux, ne doivent déclencher
**aucune alerte**.

## Bons : concierge ou partenaire technique, retour d'incident

- Un bon peut être adressé au **concierge de l'immeuble** ou au **partenaire technique** du métier. Le concierge est
  celui de la fiche ; s'il n'y en a pas, c'est le prestataire « Concierge » de l'immeuble.
- Par défaut, Vigie choisit le destinataire désigné par la règle. Quand il n'existe aucun partenaire du métier, le
  bon va au concierge et le journal du bon le signale.
- Tant que le bon est en brouillon, on peut changer de destinataire : le message est alors recomposé.
- Après l'envoi, on enregistre le **retour d'incident** (résolu, non résolu, à suivre, rien constaté) avec un
  compte rendu horodaté. On peut ensuite relancer une intervention ou clôturer le bon.
- Chaque étape est horodatée dans l'**historique** de l'immeuble : ouverture, réouverture et disparition de la
  dérive, création, envoi et retour du bon, avis du gestionnaire.
- Dans l'exemple, chaque fluide a un partenaire fictif par secteur : rive droite, rive gauche et communes. On y
  trouve un électricien, un frigoriste pour la PAC, une entreprise sanitaire pour l'eau, un chauffagiste et un
  installateur solaire (métier « Solaire »). Chaque
  immeuble a aussi un gestionnaire, un concierge et des données techniques fictifs.

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
- Dans l'exemple, deux adresses sont fictives (Chemin des Tilleuls 8 à Onex, Avenue des Ormeaux 15 au
  Grand-Lancy). Elles sont placées au centre de leur commune et indiquées « position approximative ».
- La carte utilise Leaflet 1.9.4 (licence BSD-2), intégré dans `vigie/web/` et vérifié par son empreinte
  officielle. Seules les tuiles du fond de carte viennent d'Internet (wmts.geo.admin.ch).

## Température extérieure et ensoleillement : MétéoSuisse, automatique

Les règles « chauffage trop fort pour la météo » et « rendement PAC » comparent la consommation à la
température extérieure ; les règles solaires comparent la production à l'ensoleillement. Vigie utilise la **source
officielle de la Confédération** : MétéoSuisse, données ouvertes du réseau SwissMetNet, **station Genève-Cointrin
(GVE)**, colonnes `tre200h0` (température de l'air à 2 m) et `gre000h0` (rayonnement global, W/m²), moyennes
horaires, en UTC, fin d'intervalle, comme les mesures de Vigie. Le rayonnement est facultatif : une station qui ne
le mesure pas ne donne que la température.

- **Mise à jour automatique** au démarrage de Vigie puis toutes les 3 heures tant qu'il est ouvert. Elle peut aussi
  se lancer avec le bouton « Mettre à jour maintenant » (Réglages) ou la commande `python -m vigie meteo`.
- Au premier lancement, environ 400 jours d'historique sont chargés (le fichier de la décennie), puis seulement
  l'année en cours et les dernières heures.
- Heures manquantes laissées vides (jamais comblées), valeurs hors de −45 à 50 °C ou de 0 à 1 500 W/m² écartées.
- Base d'exemple sur météo réelle : la mise à jour n'ajoute que les heures nouvelles (température et rayonnement),
  sans réécrire celles qui ont servi à la simulation.
- Seul un fichier public est téléchargé : aucune donnée de consommation ne quitte le poste.
- La station se change dans Réglages (code à 3 lettres). Un changement démarre une nouvelle série : on ne mélange
  jamais deux stations.
- La base d'exemple garde ses températures fictives, cohérentes avec ses consommations simulées.
- Liens de la source (aussi affichés dans **Réglages › Température extérieure**) :
  [données ouvertes MétéoSuisse](https://www.meteoswiss.admin.ch/services-and-publications/service/open-data.html) ·
  [documentation](https://opendatadocs.meteoswiss.ch/general/download) ·
  [fichier horaire GVE](https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/gve/ogd-smn_gve_h_recent.csv).
  Conditions : utilisation libre, source à citer (MétéoSuisse).

## Les écrans

| Écran | Ce que le gestionnaire y fait |
|---|---|
| **Tableau de bord** | Indicateurs (rythme des dérives en CHF par mois, dont l'excès déjà mesuré du chauffage et des PAC, MWh et m³ par mois, CO₂, bons à valider), **carte du parc** (liste des adresses à gauche, carte swisstopo à droite, couleur selon la criticité), alertes à traiter par priorité (rythme mensuel en CHF × confiance × urgence). Bouton « Lancer l'analyse ». |
| **Parc** | Adresses → immeubles → fluides. Ajout et modification d'un immeuble (occupation Habité / Partiel / Vide / Travaux, taux d'occupation, logements, talon hors-gel, propriétaire). Export Excel. |
| **Fiche immeuble** | Compteurs et capteurs : fluide, connexion (M-Bus, wM-Bus/OMS, LoRaWAN, export DLMS du distributeur, Modbus, BACnet, CSV, relevé de facture), identifiant de l'appareil, fournisseur, pas de temps, état (actif / à connecter / inactif), dernière donnée, complétude sur 30 jours, courbe journalière. Règles appliquées selon l'occupation. Alertes et bons de l'immeuble. |
| **Fiche technique (immeuble)** | Gestionnaire et concierge (nom, e-mail, téléphone), données techniques (construction, rénovation, EGID, étages, production de chaleur et d'eau chaude, puissance, installation, frigorigène, local technique), **partenaires techniques par fluide**, **consommation par compteur en journalier (90 jours), mensuel ou annuel** avec total et moyenne, suivi horodaté de chaque alerte (**En attente → Bon envoyé → Retour d'incident → Clôturée**, destinataire du bon, retour), **historique horodaté** de toutes les étapes, compteurs et connexions. |
| **Alertes** | Ouvertes et résolues. Constat en langage simple, consigne, métier, délai, imputation. Avis du gestionnaire : *Pertinente / Déjà connue / Fausse alerte*, qui donne le taux de pertinence réel. |
| **Bons de travaux** | Bon adressé au prestataire du métier pour l'immeuble. Relecture et modification du message, envoi par e-mail ou fichier `.eml` à ouvrir dans Outlook, puis suivi (envoyé, en cours, terminé, annulé) avec historique. Indique si la dérive a disparu des mesures. |
| **Prestataires** | Entreprise, métier, contact, e-mail, téléphone, immeubles couverts (tout le parc ou certains). Signale les métiers demandés par les règles mais non couverts. |
| **Règles & coûts** | Tableau « surveillance selon l'occupation ». Pour chaque règle : activation, occupations concernées, seuil, persistance, gravité, métier du prestataire, délai, consigne. Coûts : tarif par vecteur (exemple ou contrat), facteur CO₂, enjeu minimal (CHF par mois), seuils de qualité des données. |
| **Imports** | Parc depuis Excel avec **aperçu avant import** (nouveaux, modifiés, inchangés, lignes refusées avec leur motif). Relevés en CSV (séparateur , ou ;) ou en Excel .xlsx (feuille « mesures »), colonnes `ts,point_id,valeur` : format commenté et modèles vides dans le dossier `exemple de données fluides` (voir son `LISEZMOI.txt` ; les relevés d'exemple ne sont pas publiés dans le dépôt). Modèle Excel du parc téléchargeable. |
| **Réglages** | **Relevés des compteurs par API** : clé API du fournisseur de télérelève (chiffrée par le compte Windows, jamais réaffichée ni envoyée ailleurs qu'au fournisseur ; ou variable `VIGIE_API_CLE`), adresse https, format réglable (en-tête, Bearer ou paramètre ; JSON ou CSV), « Tester la connexion », « Relever maintenant », relevé automatique toutes les N heures. Les compteurs concernés ont la connexion « API du fournisseur » et leur identifiant chez le fournisseur. Fournisseur de démonstration intégré pour la base d'exemple (clé `DEMO-VIGIE-2026`). Puis automatisation des bons (manuelle, préparation automatique, envoi automatique, gravité minimale, problèmes de données) et messagerie (expéditeur, copie, signature, serveur SMTP). |

## Import Excel du parc

Classeur `.xlsx` avec jusqu'à trois feuilles. Le bouton « Télécharger le modèle » en fournit un prêt à remplir,
avec une feuille « Aide » qui liste les valeurs possibles.

| Feuille | Colonnes |
|---|---|
| Immeubles | `immeuble_id, nom, rue, npa_localite, profil, taux_occupation, logements, sre_m2, talon_horsgel_kwh_j, proprietaire, remarque` |
| Compteurs | `point_id, immeuble_id, fluide, libelle, unite, nature, pas_min, connexion, identifiant, fournisseur, etat` ; solaire : `puissance_crete_kwc` (obligatoire), `production_prevue_kwh_an`, `mise_en_service`, `degradation_pct_an` |
| Prestataires | `nom, metier, contact, email, telephone, immeubles` (`*` = tout le parc) |

Les en-têtes sont tolérants (accents, majuscules, synonymes comme « Code », « Adresse », « N° de série »,
« Courriel »). Les valeurs aussi : « Habité », « vacant », « Eau froide », « chauffage », « à connecter ».
Les lignes sont **ajoutées ou mises à jour par code ; rien n'est jamais supprimé par un import**. Les lignes
invalides sont refusées une à une, avec leur numéro et le motif. Le reste s'importe.

## Bons de travaux : comment ça marche

1. Chaque règle désigne un **métier** (Sanitaire pour une fuite, Chauffagiste pour le chauffage, Frigoriste
   pour la PAC, Solaire pour une installation photovoltaïque, Télérelève pour un compteur muet…).
2. Après chaque analyse, selon les réglages, Vigie prépare un bon pour chaque **nouvelle** alerte dont la gravité
   atteint le seuil choisi. Le bon est adressé au prestataire de ce métier : celui dédié à l'immeuble passe avant
   celui de tout le parc. **Un seul bon ouvert par alerte** : une dérive qui dure ne crée pas un bon à chaque
   analyse.
3. Le message reprend le constat, la valeur mesurée et la valeur attendue, la consigne, le délai, et le risque de
   sinistre s'il y en a un. **Tous les chiffres viennent du moteur.** L'enjeu en CHF et l'imputation restent
   internes et ne figurent pas dans le message.
4. Envoi :
   - **avec un serveur SMTP** (Réglages › Messagerie), envoi direct, ou automatique si vous l'avez choisi ;
   - **sans serveur SMTP**, « Télécharger pour Outlook » produit un `.eml` qui s'ouvre prêt à envoyer.

   Le mot de passe SMTP est gardé **en mémoire** jusqu'à la fermeture de Vigie, ou lu dans la variable
   d'environnement `VIGIE_SMTP_MOT_DE_PASSE`. Il n'est jamais écrit sur le disque.

## Sécurité

- Le serveur n'écoute que sur `127.0.0.1` et vérifie l'en-tête `Host` (protection contre le « DNS rebinding »).
- Toute modification exige l'en-tête `X-Vigie`, ce qui bloque les formulaires venant d'autres sites.
- Politique de sécurité du contenu stricte : aucun script ni style externe, aucune police chargée sur Internet ;
  seules les images du fond de carte swisstopo (wmts.geo.admin.ch) sont autorisées.
- Accès réseau sortants, tous en lecture de données publiques : température MétéoSuisse, géocodage des
  adresses, tuiles de la carte. Aucune donnée de consommation n'est envoyée.
- Tout texte est inséré sans interprétation HTML. Les fichiers servis sont limités au dossier `vigie/web`.
- Toutes les requêtes SQL sont paramétrées. Les fichiers Excel trop volumineux une fois décompressés sont refusés.

## Organisation

```
Lancer Vigie.bat · lancer_vigie.py   démarrage par double-clic
config/referentiel.json   parc d'exemple et valeurs par défaut (paramètres, tarifs et facteurs CO₂ d'EXEMPLE)
sql/schema_timescaledb.sql schéma cible PostgreSQL + TimescaleDB (y compris prestataires et bons)
vigie/db.py               stockage SQLite, import CSV / Excel des mesures, référentiel construit depuis la base
vigie/moteur.py           qualité → attendu → détecteurs → impact → priorisation ; REGLES réglables
vigie/solaire.py          production solaire à ensoleillement égal : attendu, décote, arrêt / panne / dégradation
vigie/parc.py             parc, prestataires, règles, coûts ; contrôles de saisie ; import et export Excel
vigie/excel.py            lecture et écriture .xlsx sans dépendance externe
vigie/meteo.py            température et rayonnement officiels MétéoSuisse (Genève-Cointrin), mise à jour automatique
vigie/geo.py              coordonnées GPS des adresses (géocodeur fédéral, correspondance exacte)
vigie/bons.py             suivi des alertes, choix du prestataire, bons, e-mail, automatisation
vigie/service.py          enchaînement analyse → sorties → alertes → bons ; chargement de l'exemple
vigie/serveur.py          serveur local et API JSON
vigie/web/                interface (HTML, CSS, JavaScript sans framework) ; carte.js + Leaflet 1.9.4 intégré
vigie/rapport.py          sorties rapport.html / alertes.json / alertes.csv
vigie/generer_demo.py     12 mois de données fictives relevées à l'heure (dont le solaire), avec dérives injectées
evaluation/               campagne d'évaluation (simulateur 12 mois horaire, analyse, figures, document PDF)
docs/                     Vigie_methodes_et_evaluation_derives.pdf (méthodes, données, résultats, révisions)
tests/                    tests unitaires (unittest)
```

## Validation de cette version (relevés horaires, 12 mois)

- Les 4 évaluations officielles : `python -m vigie evaluer`, `--meteo-reelle`, `--grand`, `--grand --meteo-reelle` :
  **précision 100 %, rappel 100 %** (7/7 et 15/15 dérives, aucune fausse alerte).
- Solaire, graines 1, 7, 42, 123 et 2026, petit et grand exemple : arrêt, panne et dégradation trouvés et
  correctement qualifiés à chaque fois ; **aucune alerte solaire** sur les mêmes parcs sans dérive solaire injectée
  (décote normale de 0,5 %/an comprise). Grand exemple sur rayonnement réel de Genève : 3/3.
- Temps mesurés (exemple 12 mois, météo fictive) : standard 166 222 mesures, génération 1,3 s, génération + import
  2,7 s, analyse 0,6 s ; grand 805 702 mesures, génération 5,9 s, génération + import 13,3 s, analyse 3,1 s.
- Campagne d'évaluation (`evaluation/`, 9 764 scénarios simulés, 12 mois relevés à l'heure, vraie météo de Genève
  et météo fictive, 40 minutes) :
  - exemples officiels régénérés (80) : **0 fausse alerte, 0 dérive manquée** ;
  - immeubles sains : **0 fausse alerte sur 7 920 analyses** (dont CAD et gaz, habités et vides) ;
  - CAD et gaz : seuil effectif 50 % de 11 % (signature, règle 10 %), délai médian 8 jours ; immeuble vide détecté
    à partir d'un facteur de marche de 0,28 (météo fictive) ;
  - **dérive constatée** (fin d'analyse d'octobre 2025 à avril 2026, vraie météo) : écart médian au réel cumulé de
    −0,8 % à +0,9 % pour les signatures (chaleur, CAD, gaz) et les PAC, contre −25 % à −23 % avec l'ancienne
    annualisation × 210 ; immeuble vide chauffé −14 % à −11 % (talon déclaré) ; eau et électricité −5,3 % à +7,1 % ;
  - **projection 12 mois** (signatures, PAC) : −4 % à −2 % de l'excès d'une année normale en médiane, −15 % à +8 % du
    réalisé de chaque année réelle 2016-2025 ;
  - priorisation : la base du score valait de 5,7 à 12,2 fois le coût réel du mois suivant selon le fluide ; le
    rythme mensuel constaté vaut de 0,81 à 1,05 fois ce coût ;
  - **pas journalier** : fuite de nuit, électricité de nuit et PAC 0 détection ; signatures et immeubles vides
    détectés comme au pas horaire ; aucune fausse alerte.
- 132 tests unitaires verts (dont 15 pour le solaire).
- Interface et rapport HTML vérifiés : « Dérive constatée : ≈ X CHF », quantités et période mesurées, rythme
  mensuel, « Projection si rien n'est fait : … (hypothèse : …) » ; le bon envoyé au prestataire ne contient que la
  dérive constatée (kWh ou m³, sans CHF).
- Détail des méthodes et des résultats : `docs/Vigie_methodes_et_evaluation_derives.pdf`.

## Licence

Le code de Xread Dérives est publié sous **licence MIT** (fichier `LICENSE`) : utilisation, modification et
redistribution libres, y compris commerciales, à condition de conserver la mention de copyright et le texte de la
licence ; le logiciel est fourni sans garantie. `LICENCES_TIERS.md` liste ce que la licence MIT ne couvre pas :
Leaflet (BSD 2-Clause), le jeu de données communal (CC BY 4.0, attribution obligatoire), les données
MétéoSuisse et les fonds swisstopo.

Avant une mise en ligne publique : ne publiez pas une base `vigie.db` ni un dossier `sorties/` contenant des
données réelles (relevés, adresses, prestataires, réglages de messagerie, clé de connexion chiffrée). Le nom du
titulaire dans `LICENSE` (« Xread Dérives (auteurs et contributeurs) ») est à remplacer par le vôtre.

## Limites connues

- **Tarifs et facteurs CO₂ = valeurs d'exemple** tant qu'ils ne sont pas saisis comme « tarif de mon contrat ».
  Les tarifs sont communs à tout le parc : pas encore de tarif par immeuble ou par contrat.
- Connexion API générique : son format par défaut est une hypothèse, à aligner sur la documentation du fournisseur
  retenu (chemin, champs, envoi de la clé). Après un relevé, l'analyse se lance à la main. Pas de connecteurs directs
  (M-Bus, LoRaWAN, Modbus…) : hors API, les relevés s'importent en CSV ou Excel.
- Les règles se règlent pour tout le parc, par occupation. Pas encore de réglage propre à un immeuble ni de
  sourdine justifiée.
- Pas de gestion des changements de compteur ni des périodes déclarées (travaux datés, vacance).
- L'analyse se lance à la main (bouton ou ligne de commande) : pas encore de planification automatique.
- L'envoi SMTP a été testé avec un serveur simulé seulement, pas avec un vrai serveur de messagerie.
- Chauffage et PAC : le montant est l'excès **mesuré** depuis le début détecté de la dérive. La part antérieure
  (dérive progressive, jours sous le seuil) et les heures sans mesure ne sont pas comptées : c'est un minimum. Le
  rythme mensuel vaut pour un mois au climat des derniers jours ; il s'écarte du mois suivant quand la saison
  change. L'ancienne annualisation « × 210 jours » sous-estimait en début de saison et surestimait en plein hiver.
- Immeuble vide chauffé : l'excès est compté au-dessus du talon hors-gel déclaré, donc sous-estimé si le hors-gel
  réel consomme moins que le talon.
- Au pas journalier, la fuite de nuit, l'électricité de nuit et la PAC ne sont pas surveillées.
- La projection est une hypothèse (climat normal, dérive maintenue 12 mois) : l'année réelle et la suite de la dérive
  s'en écartent. Elle n'est jamais un déclencheur.
- CAD et gaz : PCS et tarifs d'exemple à remplacer par ceux des contrats ; un compteur de gaz en m³ sans PCS déclaré
  n'est pas analysé (qualité des données seulement).
- Les fenêtres de nuit et d'abaissement nocturne sont en heures UTC (décalage d'une heure entre hiver et été).
- **PAC sans compteur de chaleur chauffage** (électricité seule, ou eau chaude seule) : la part chauffage est
  estimée depuis la météo. Il faut au moins 240 heures froides (sous 14 °C) dans la période de référence ; sinon
  Vigie ne conclut pas, par exemple au tout début de la première saison de chauffe suivie. La dérive est aussi
  moins finement chiffrée qu'avec un compteur de chaleur.
- Le modèle de la PAC et la signature de chauffage sont appris sur la même saison de l'an passé et les 60 jours
  qui précèdent la fenêtre d'analyse (sinon sur toute la période antérieure). Un changement de réglage voulu
  (consigne d'eau chaude, courbe de chauffe) peut donc ressembler à une dérive tant qu'il n'est pas déclaré : les
  périodes déclarées manquent encore.
- Un seul utilisateur à la fois, sans identification (outil de poste local).
- **Solaire** : l'ensoleillement vient de la station MétéoSuisse (Genève-Cointrin), pas d'un capteur sur le toit ;
  un ombrage local ou une averse sur une seule commune ajoute du bruit, compensé par la persistance en jours
  ensoleillés. Les jours couverts (< 0,6 kWh/m²) et les jours de gel (neige possible sur les modules) ne sont pas
  jugés. Une installation suivie par son onduleur devient « compteur muet » (Données) quand l'onduleur s'arrête.
- Solaire : la référence prend les journées comparables de même saison, l'an passé et juste avant la fenêtre
  d'analyse. Une baisse très lente commencée plus d'un mois avant la fenêtre est en partie apprise comme normale
  tant que la même saison de l'an passé manque (première année de suivi) ; elle est alors sous-estimée.
- Solaire sans historique : la référence nominale (production prévue au prorata de l'ensoleillement horizontal) ne
  tient pas compte de l'orientation des modules saison par saison ; elle sert seulement en attendant l'historique.
- Le métier « Solaire » regroupe l'installateur photovoltaïque ; un défaut côté réseau du distributeur reste à
  signaler par l'installateur.
- Solaire : un seul compteur de production analysé par immeuble (comme les autres fluides) ; une installation à
  plusieurs onduleurs se déclare en un compteur total. Sans jour ensoleillé jugé depuis 21 jours (rayonnement absent,
  ciel couvert durable), Vigie ne conclut pas. Une baisse brutale restée sous le seuil de panne est signalée comme
  baisse de production (règle « dégradation »), avec la mention « apparue d'un coup ».
