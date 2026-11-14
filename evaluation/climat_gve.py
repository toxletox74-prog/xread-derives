"""Climat de Genève (degrés-jours base 16 °C, définition du moteur) à partir des VRAIES données MétéoSuisse.

  python -m evaluation.climat_gve            calcule et affiche les valeurs par année
  python -m evaluation.climat_gve --ecrire   écrit la normale dans config/referentiel.json (parametres + climat_reference)

La normale (degrés-jours base 16 °C moyens des 10 dernières années complètes) sert uniquement à la PROJECTION « si rien
n'est fait » du chauffage, du CAD, du gaz et des PAC (vigie/chiffrage.py) : une hypothèse affichée comme telle, jamais
un déclencheur. La série 2016-2025 donne aussi, dans l'évaluation, l'excès « réalisé » de chaque année réelle.

Source : MétéoSuisse, données ouvertes SwissMetNet, station Genève-Cointrin (GVE), colonne tre200h0 (UTC, fin
d'intervalle), fichiers ogd-smn_gve_h_historical_2010-2019.csv et _2020-2029.csv (copies figées dans
evaluation/sorties/cache_meteo). Degrés-jours d'un jour = moyenne des heures mesurées de max(0 ; 16 − T) ; part de
nuit = heures de fin d'intervalle 22 h-5 h (moteur.NUIT_CHAUFFE). Seules les années complètes (≥ 99 % des heures)
sont retenues ; la normale est la moyenne des 10 dernières années complètes (climat récent).
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from vigie import meteo, moteur

from . import meteo_gve

ANNEES_NORMALE = 10
REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "referentiel.json")


def serie_historique():
    valeurs = {}
    for annee in (2015, 2025):  # fichiers des décennies 2010-2019 et 2020-2029
        url = meteo.urls("GVE", datetime(annee, 6, 1, tzinfo=timezone.utc))["historique"]
        for ts, v in meteo.convertir(meteo_gve.lire_url(url), "GVE"):
            valeurs[ts] = v
    t = pd.Series(valeurs)
    t.index = pd.to_datetime(t.index).tz_localize(None)
    return t.sort_index()


def par_annee(t):
    dh = (16.0 - t).clip(lower=0)
    nuit = moteur.heures_nuit_chauffe(dh.index)
    j = pd.DataFrame({"dj": dh.resample("D").mean(), "djn": dh.where(nuit, 0.0).resample("D").mean()})
    out = []
    for annee, g in j.groupby(j.index.year):
        attendues = (366 if pd.Timestamp(annee, 12, 31).day_of_year == 366 else 365) * 24
        heures = int((t.index.year == annee).sum())
        out.append({"annee": int(annee), "heures": heures, "complete": heures >= 0.99 * attendues,
                    "dj16": round(float(g["dj"].sum()), 1), "dj16_nuit": round(float(g["djn"].sum()), 1),
                    "t_moyenne": round(float(t[t.index.year == annee].mean()), 2)})
    return out


def normale(annees):
    completes = [a for a in annees if a["complete"]][-ANNEES_NORMALE:]
    n = len(completes)
    return {"dj16_annuel_normal": round(sum(a["dj16"] for a in completes) / n, 1),
            "dj16_nuit_annuel_normal": round(sum(a["dj16_nuit"] for a in completes) / n, 1),
            "periode": f"{completes[0]['annee']}-{completes[-1]['annee']}", "annees": n,
            "min": min(a["dj16"] for a in completes), "max": max(a["dj16"] for a in completes)}


def main(argv):
    annees = par_annee(serie_historique())
    for a in annees:
        print(a)
    nm = normale(annees)
    print("normale :", nm)
    if "--ecrire" in argv:
        ecrire(annees, nm)


def ecrire(annees, nm):
    with open(REF, encoding="utf-8") as f:
        ref = json.load(f)
    ref["parametres"]["dj16_annuel_normal"] = nm["dj16_annuel_normal"]
    ref["parametres"]["dj16_nuit_annuel_normal"] = nm["dj16_nuit_annuel_normal"]
    ref["climat_reference"] = {
        "_statut": "MESURÉ — données réelles MétéoSuisse",
        "usage": "PROJECTION seulement (« si rien n'est fait, sur 12 mois, au climat normal ») du chauffage, du CAD, du "
                 "gaz et des PAC. Jamais un déclencheur d'alerte, jamais dans le score ni la gravité. La dérive "
                 "constatée (mesurée) reste la base des actions.",
        "source": "MétéoSuisse, données ouvertes SwissMetNet, station Genève-Cointrin (GVE), colonne tre200h0 "
                  "(température de l'air à 2 m, moyenne horaire, UTC), fichiers ogd-smn_gve_h_historical_2010-2019 et "
                  "2020-2029 (data.geo.admin.ch/ch.meteoschweiz.ogd-smn/gve)",
        "definition": "degrés-jours base 16 °C = somme sur l'année des moyennes journalières de max(0 ; 16 − T horaire) ; "
                      "part de nuit = heures de fin d'intervalle 22 h-5 h UTC",
        "periode": nm["periode"], "annees_retenues": nm["annees"],
        "dj16_min_max_sur_la_periode": [nm["min"], nm["max"]],
        "par_annee": {str(a["annee"]): {"dj16": a["dj16"], "dj16_nuit": a["dj16_nuit"]}
                      for a in annees if a["complete"]},
        "calcule_par": "python -m evaluation.climat_gve --ecrire"}
    with open(REF, "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("écrit dans", REF)


if __name__ == "__main__":
    main(sys.argv)
