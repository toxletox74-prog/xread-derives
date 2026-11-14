# Licences des composants et des données tiers

Le code de Xread Dérives (dossier `vigie/`, tests, scripts, documentation) est sous licence **MIT** : voir `LICENSE`.
La licence MIT ne couvre **pas** les éléments ci-dessous, qui gardent leur propre licence.

## Leaflet 1.9.4 — BSD 2-Clause

Fichiers : `vigie/web/leaflet.js`, `vigie/web/leaflet.css` (copie non modifiée, https://leafletjs.com).

```
BSD 2-Clause License

Copyright (c) 2010-2023, Volodymyr Agafonkin
Copyright (c) 2010-2011, CloudMade
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Jeu de données Rive-Claire — CC BY 4.0

Fichiers du dossier `donnees/` (et les valeurs qui en sont importées dans une base `vigie.db`).
Attribution : Energ-IA Transition, Energ-IACK 2026, Rive-Claire v2. Licence Creative Commons Attribution 4.0
International (https://creativecommons.org/licenses/by/4.0/deed.fr). Le fichier
`donnees/EIAK-RC-Fluides-PV_v2.xlsx` est une version modifiée du lot : production solaire seule, avec deux coupures
ajoutées à la main pour l'essai de la règle onduleur.

Le fichier `donnees/RC-Electricite-15min-2025-FICTIF.csv` ne fait pas partie du lot : ce sont des courbes de charge
SYNTHÉTIQUES, produites par `evaluation/generer_electricite_15min.py` à partir des relevés mensuels d'électricité du
lot (donc dérivées de données sous CC BY 4.0, même attribution). Elles ne décrivent aucun bâtiment réel.

## Données et services publics utilisés à l'exécution (non redistribués)

- **MétéoSuisse** : température et rayonnement horaires de la station choisie (données ouvertes, source à citer :
  « MétéoSuisse »).
- **swisstopo / geo.admin.ch** : fonds de carte et géocodage des adresses, selon les conditions d'utilisation des
  géoservices de la Confédération (mention « © swisstopo » affichée sur la carte).

## Dépendances Python (installées séparément, non redistribuées)

pandas et numpy : licence BSD 3-Clause.

## Valeurs d'exemple

Les tarifs livrés dans `config/` reprennent les tarifs publics SIG 2026, à titre indicatif ; les facteurs CO₂ et
le pouvoir calorifique du gaz sont des valeurs d'EXEMPLE. Tous sont à remplacer par les contrats et le
référentiel retenu. Les prestataires « Exemple SA » sont fictifs.
