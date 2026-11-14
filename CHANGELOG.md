# Journal des versions de Xread Dérives (Vigie)

Ce fichier garde ce qui est historique : ce que chaque version a apporté, les résultats obtenus sur le lot
communal et les mesures de validation. La notice de la version courante est dans `README.md`.

Les textes ci-dessous sont ceux qui figuraient dans `README.md` à la publication de chaque version, repris tels
quels. Les chiffres (nombre de tests, durées, volumes, épisodes) sont donc ceux mesurés à ce moment-là : ils ne
sont pas remis à jour ici. Deux passages se contredisent dans le texte d'origine et sont laissés en l'état : la
durée du rejeu d'une année (« environ 7 minutes » dans l'exemple de commande, « environ 15 minutes (7 avant les
règles du même mois) » dans les limites), et le nombre de tests (224 pour la V0.3.0, 132 pour la validation de la
version précédente).

## Après la V0.3.0 (non publié)

- **Tarifs par défaut** : tarifs publics SIG 2026, indicatifs, hors abonnements et coûts fixes (électricité
  0,2707, gaz 0,0868, solaire perdu 0,1185 CHF/kWh, eau 5,10 CHF/m³ ; chaleur et CAD 0,1105 CHF/kWh, milieu de
  la fourchette 0,086 à 0,135). Ils restent marqués « valeur d'exemple » tant que ceux des contrats ne sont pas
  saisis ; une base où les coûts ont déjà été enregistrés garde les siens. Conséquence mesurée : sur le grand
  exemple en météo réelle, la coupure d'onduleur du G17 (7 CHF/mois) passe sous l'enjeu minimal et n'est plus
  levée (15 dérives sur 16) ; l'exemple standard et le grand exemple en météo fictive restent à 100 %.
- **Lecture seule sans identification** : derrière un serveur frontal ou dès que `VIGIE_MOT_DE_PASSE` est défini,
  la consultation est libre et toute modification exige une session (`vigie/acces.py`).
- **Analyse automatique** toutes les N heures et après un relevé API automatique ; avertissement quand le mot de
  passe SMTP manque pour l'envoi automatique (`vigie/planification.py`).
- **Périodes déclarées et sourdines** par immeuble : sourdine justifiée, travaux et vacance datés, changement de
  compteur ou de consigne (`vigie/declarations.py`, table `declaration`).
- **Cause commune à plusieurs immeubles** : alertes groupées marquées, confiance abaissée, pas de bon automatique
  (`vigie/recoupement.py`).
- **Fenêtres de nuit et abaissement nocturne à l'heure de Zurich** (moteur, exemple et simulateur de la campagne).
- **Rejeu accéléré** à résultats identiques : séries préparées une fois par rejeu (`vigie/series.py`).
- **Dépôt** : notice et journal des versions séparés, flux GitHub Actions, dépendances bornées
  (`pandas>=2.2,<4`, `numpy>=1.26,<3`), `requirements-evaluation.txt`.

## V0.3.0

### V0.3.0 : import d'un patrimoine complet (lot communal)

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

### Méthodes ajoutées pour compléter la matrice fluide × pas de relevé

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

### Comparaison à l'historique du même mois (gaz, PAC, chaleur, CAD, électricité, eau, solaire)

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

### Jours ouvrés et vacances dans la règle de chauffage

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

### Couverture des règles : l'alerte de granularité

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

### Rejeu de l'année 2025 sur le lot communal

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

### Limites, tests et corrections de la V0.3.0

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

## Avant la V0.3.0

### Nouveauté : production solaire (photovoltaïque)

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

### Révision précédente : pas horaire, dérive constatée et projection, CAD et gaz

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

### Validation de cette version (relevés horaires, 12 mois)

« Cette version » désigne ici la version qui précédait la V0.3.0 : cette section a été écrite avant elle.

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
