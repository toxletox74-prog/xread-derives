# Xread Dérives — teaser produit de 60 secondes

Projet Remotion autonome : il ne modifie aucune route, règle métier ou base de l'application Python.
React / TypeScript, 30 images/s, 1 800 images, sortie H.264 en 16:9 et composition verticale dédiée.
Les textes suffisent à comprendre le film sans voix off.

## Lire et exporter

Depuis ce dossier, avec Node.js 22 ou ultérieur, Python 3 et FFmpeg dans le PATH :

```powershell
npm ci
npm run assets
npm run studio
```

Dans Remotion Studio, sélectionner `EnergyTeaser1080`, `EnergyTeaser4K` ou `EnergyTeaserVertical`.

```powershell
npm run check
npm run qa
npm run render:1080
npm run render:4k
npm run render:vertical
```

Fichiers produits dans `out/` :

- `energy-software-teaser-1080p.mp4` : 1920 × 1080.
- `energy-software-teaser.mp4` : 3840 × 2160, master 4K.
- `energy-software-teaser-vertical.mp4` : 1080 × 1920, mise en page spécifique.

Le premier rendu télécharge le navigateur Chromium de Remotion. Les rendus suivants utilisent le cache local.
Les fichiers volumineux et les dépendances ne sont pas versionnés. Consulter les conditions de licence de
Remotion selon l'organisation qui exploite les exports.

## Parcours des services

| Temps | Séquence | Fonctions présentées |
| --- | --- | --- |
| 0–8 s | Le problème | Courbes et apparition de la surconsommation |
| 8–16 s | Les services | Imports CSV/Excel, connexion API fournisseur, suivi multi-fluides, interventions |
| 16–26 s | Le parc | Véritable frontend du tableau de bord, alertes et indicateurs |
| 26–38 s | L'analyse | Comparaison pédagogique réel/référence, météo, degrés-jours, calendrier |
| 38–51 s | La décision | Écart énergétique, coût estimé, priorité et préparation du bon de travaux |
| 51–60 s | La marque | Signature et appel à découvrir la plateforme |

## Modifier le film

- **Marque, CTA, URL, audio** : `src/config/branding.ts`. L'URL est vide par défaut ; renseigner `url` pour l'afficher.
- **Textes** : composants dans `src/scenes/`.
- **Couleurs, tailles et dispositions** : `src/style.css` (règles `.vertical` pour le portrait).
- **Logo** : `public/assets/logo.svg`, extrait du SVG présent dans `vigie/web/index.html` par `npm run assets`.
- **Durées** : `src/config/timeline.ts`, en images. Maintenir des segments contigus totalisant 1 800 images pour une minute.
  L'ordre des composants correspondant est dans `src/compositions/EnergyTeaser.tsx`.
- **Données** : `src/data/demoData.ts`. Les totaux du cas d'analyse sont calculés :
  référence de 1 000 kWh/jour × 30 jours ; 15 derniers jours à 1 400 kWh/jour ;
  total de 36 000 kWh, écart de 6 000 kWh (+20 % du mois), soit 1 080 CHF à 0,18 CHF/kWh.
- **Animations** : exclusivement pilotées par les images Remotion ; aucune minuterie ou animation CSS autonome.

Les tarifs sont des exemples. Les montants représentent des impacts estimés, jamais des économies réalisées.
L'écran comparatif et les cartes latérales sont une mise en scène pédagogique de fonctions existantes,
et non la promesse d'une interface identique dans le produit en construction.
Le dashboard capturé et le cas École des Cèdres sont deux jeux fictifs distincts : les chiffres du parc
ne sont pas les totaux des cartes de la mise en scène.

## Captures du logiciel en construction

Les captures incluses sont figées et n'exigent aucun serveur métier pour rendre le film.
Pour les renouveler, installer les dépendances Python indiquées dans le README du projet parent, puis :

```powershell
# Terminal 1, depuis video-teaser : base strictement fictive, isolée dans .cache.
python scripts/demo-server.py

# Terminal 2 : capture dans Edge en mode headless.
node scripts/capture.mjs
```

Le serveur de démonstration utilise `127.0.0.1:8876`, sans lecture de `vigie.db`.
La capture masque certains blocs pour concentrer la présentation sur les indicateurs et alertes ;
les tuiles cartographiques externes sont bloquées et ne sont pas redistribuées.
Le contournement CSP est limité au navigateur headless de capture pour appliquer ces styles ;
aucune politique de sécurité de l'application n'est modifiée.
Les générations initiales utilisent la date du jour du générateur métier : conserver les PNG fournis
pour reproduire exactement la version livrée.

## Musique et voix off

`scripts/prepare.py` synthétise une partition électronique originale et des ponctuations aux transitions,
dans `public/audio/score.wav`. Aucun morceau tiers n'a été téléchargé. Ce fichier est régénérable.

Pour une voix off française, déposer un enregistrement autorisé dans `public/audio/`,
puis renseigner `branding.voiceover`, par exemple `audio/voix-off-fr.wav`.
Le montage livré est sans voix off. Mettre `branding.music` à `false` pour supprimer la bande-son.
Après toute modification des durées, ajuster les accents sonores dans `scripts/prepare.py` et régénérer.
Le script de rendu appelle `scripts/finaliser.py` pour normaliser l'audio à −20 LUFS (plafond −1,5 dBTP)
et fixer le conteneur à 60 secondes, sans réencoder la piste vidéo. Il prend aussi en charge un export muet.

## Validation

`npm run qa` produit des images clés des formats paysage et portrait dans `out/qa`.
`scripts/verifier.py` contrôle les caractéristiques des MP4 et les décode intégralement via FFmpeg.
FFmpeg et FFprobe doivent être disponibles dans le PATH pour cette vérification :

```powershell
python scripts/verifier.py out/energy-software-teaser-1080p.mp4 out/energy-software-teaser.mp4 out/energy-software-teaser-vertical.mp4
```

La validation visuelle porte sur le cadrage, les textes, les courbes et les états d'animation.
Il reste possible d'actualiser les captures à mesure que le logiciel évolue, sans modifier le montage.
