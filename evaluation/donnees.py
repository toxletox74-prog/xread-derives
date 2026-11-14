"""Description des données : température réelle (MétéoSuisse GVE, 12 mois de la campagne), températures fictives
(simulateur 12 mois et générateur d'exemple 120 jours), points de mesure des fluides (tous au pas horaire), et étude
de l'ancienne annualisation (excès d'un jour × 210 jours) sur les saisons de chauffe réelles : elle montre pourquoi
le chauffage et la PAC ne sont plus annualisés.

  python -m evaluation.donnees   ->  evaluation/sorties/donnees.json
"""
import json
import os
import tempfile
from datetime import timedelta

import numpy as np
import pandas as pd

from vigie import db, generer_demo, service

from . import meteo_gve
from .campagne import SORTIES


def _dj(t):
    """Degrés-jours base 16 °C du moteur : moyenne journalière de (16 - T horaire) écrêté à 0."""
    return (16.0 - t).clip(lower=0).resample("D").mean()


def stats_temperature(t, debut, fin):
    """t : série horaire (fin d'intervalle) des heures MESURÉES ; grille attendue (debut, fin]."""
    grille = pd.date_range(debut + timedelta(hours=1), fin, freq="h")
    t = t[(t.index > debut) & (t.index <= fin)]
    manquantes = grille.difference(t.index)
    trous, courant, prec = [], 0, None
    for h in manquantes:
        courant = courant + 1 if prec is not None and h - prec == timedelta(hours=1) else 1
        if courant == 1:
            trous.append([str(h), 1])
        else:
            trous[-1][1] = courant
        prec = h
    jour = t.resample("D").mean()
    dj = _dj(t)
    fenetre = pd.Timestamp(fin - timedelta(days=30))
    mois = t.groupby(t.index.to_period("M")).agg(["mean", "min", "max", "count"])
    return {
        "debut": str(debut), "fin": str(fin), "heures_attendues": len(grille), "heures_presentes": int(len(t)),
        "heures_manquantes": int(len(manquantes)), "plus_longs_trous": sorted(trous, key=lambda x: -x[1])[:5],
        "min": float(t.min()), "min_le": str(t.idxmin()), "max": float(t.max()), "max_le": str(t.idxmax()),
        "moyenne": float(t.mean()), "jour_min": float(jour.min()), "jour_max": float(jour.max()),
        "dj16_total": float(dj.sum()), "dj16_reference": float(dj[dj.index < fenetre.normalize()].sum()),
        "dj16_fenetre_30j": float(dj[dj.index >= fenetre.normalize()].sum()),
        "heures_sous_14_reference": int((t[t.index < fenetre] < 14).sum()),
        "jours_dj_positif": int((dj > 0.5).sum()),
        "mois": [{"mois": str(p), "moyenne": float(r["mean"]), "min": float(r["min"]), "max": float(r["max"]),
                  "heures": int(r["count"])} for p, r in mois.iterrows()],
        "journalier": [[str(d.date()), float(v)] for d, v in jour.items()],
    }


def annualisation(longue):
    """Rapport (excès estimé un mois donné × jours d'exposition) / excès réel sur l'année, pour une dérive
    proportionnelle (+x % de chaleur ou d'électricité PAC), sur les saisons réelles de Genève-Cointrin."""
    t = pd.Series(longue).sort_index()
    t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="h")).interpolate(limit=6)  # étude descriptive
    h = t.index.hour
    reduit = np.where((h >= 22) | (h < 5), 0.8, 1.0)
    L = 30
    q_ch = L * 0.22 * (16 - t).clip(lower=0) * reduit
    q_ecs = L * 0.12
    chaleur = (q_ch + q_ecs).resample("D").sum()
    e_pac = (q_ch / (3.4 + 0.04 * (t - 5)) + q_ecs / (2.6 + 0.03 * (t - 5))).resample("D").sum()
    out = []
    for annee in sorted(set(chaleur.index.year)):
        debut, fin = pd.Timestamp(annee, 7, 1), pd.Timestamp(annee + 1, 7, 1)
        if chaleur.index.min() > debut or chaleur.index.max() < fin - timedelta(days=2):
            continue
        for nom, serie, jours_an in (("chaleur", chaleur, 210), ("pac", e_pac, 210)):
            an = serie[(serie.index >= debut) & (serie.index < fin)]
            total = float(an.sum())
            par_mois = {}
            for m in (10, 11, 12, 1, 2, 3, 4):
                a = annee if m >= 7 else annee + 1
                mm = an[(an.index.month == m) & (an.index.year == a)]
                par_mois[m] = float(mm.mean() * jours_an / total)
            out.append({"saison": f"{annee}-{annee + 1}", "grandeur": nom, "jours_an": jours_an,
                        "rapport_par_mois": par_mois,
                        "jours_dj_positif": int((_dj(t[(t.index >= debut) & (t.index < fin)]) > 0.5).sum()),
                        "dj16_saison": float(_dj(t[(t.index >= debut) & (t.index < fin)]).sum())})
    return out


def points_fluides():
    """Inventaire des points de mesure du grand exemple (21 immeubles) : natures, pas, volumes de mesures."""
    dossier = tempfile.mkdtemp(prefix="vigie-donnees-")
    ancien, service.SORTIE = service.SORTIE, dossier
    try:
        cx = db.connecter(":memory:")
        info = service.charger_exemple(cx, graine=42, taille="grand")
        lignes = db.lignes(cx, "SELECT p.fluide, p.nature, p.pas_min, p.unite, p.etat, count(DISTINCT p.id) AS points, "
                               "count(m.ts) AS mesures, min(m.valeur) AS vmin, max(m.valeur) AS vmax "
                               "FROM point_mesure p LEFT JOIN mesure m ON m.point_id = p.id "
                               "GROUP BY p.fluide, p.nature, p.pas_min, p.unite, p.etat ORDER BY p.fluide")
        total = cx.execute("SELECT count(*) FROM mesure").fetchone()[0]
        suspectes = cx.execute("SELECT count(*) FROM mesure WHERE qualite = 'suspecte'").fetchone()[0]
        immeubles = db.lignes(cx, "SELECT profil, count(*) AS n, sum(logements) AS logements FROM immeuble GROUP BY profil")
        cx.close()
    finally:
        service.SORTIE = ancien
    return {"lignes": lignes, "mesures": total, "suspectes": suspectes, "importees": info["importees"],
            "rejets": info["rejets"], "immeubles": immeubles}


def main():
    from . import simulateur
    longue = meteo_gve.serie_longue(3)
    fin = generer_demo.fin_reelle(longue)
    t = pd.Series(longue).sort_index()
    res = {"meteo_reelle": stats_temperature(t, fin - timedelta(days=simulateur.JOURS), fin),
           "telecharge_le": meteo_gve.maintenant().isoformat(), "historique_jours": simulateur.JOURS}
    # température fictive du simulateur de la campagne (12 mois, graine 0)
    tf_sim, _ = simulateur.temperatures("fictive", 0, simulateur.FIN_FICTIVE, simulateur.JOURS)
    res["meteo_fictive_campagne"] = stats_temperature(tf_sim, simulateur.FIN_FICTIVE - timedelta(days=simulateur.JOURS),
                                                      simulateur.FIN_FICTIVE)
    # température fictive du générateur d'exemple (graine 42, 120 jours), même calcul
    import random
    rnd = random.Random(42)
    debut = generer_demo.FIN - timedelta(days=generer_demo.JOURS)
    heures = [debut + timedelta(hours=h) for h in range(1, generer_demo.JOURS * 24 + 1)]
    tf = pd.Series([generer_demo.temperature_fictive(x, debut) + rnd.gauss(0, 0.6) for x in heures], index=heures)
    res["meteo_fictive"] = stats_temperature(tf, debut, generer_demo.FIN)
    tl = t
    res["meteo_longue"] = {"debut": str(tl.index.min()), "fin": str(tl.index.max()), "heures": int(len(tl)),
                           "heures_attendues": int((tl.index.max() - tl.index.min()) / timedelta(hours=1)) + 1}
    res["annualisation"] = annualisation(longue)
    res["points"] = points_fluides()
    with open(os.path.join(SORTIES, "donnees.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("donnees.json écrit")
    return res


if __name__ == "__main__":
    main()
