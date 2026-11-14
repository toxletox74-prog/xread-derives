"""Biais de l'attendu sur immeubles SAINS : consommation mesurée ÷ attendue − 1 sur les 14 derniers jours complets.

Un attendu juste donne ≈ 0 %. Un biais positif consomme la marge avant le seuil (fausses alertes possibles) et
gonfle le chiffrage. Relevés horaires, 12 mois d'historique, fin d'analyse au 15 de chaque mois d'octobre 2025 à avril
2026 (vraie température GVE) et fin fictive (météo fictive). Trois versions de l'attendu :
  avant       copie figée du moteur V0.2.0 (référence = toute la période avant la fenêtre, sans abaissement nocturne) ;
  anterieure  moteur actuel, référence = toute la période avant la fenêtre (repli) ;
  saison      moteur actuel, référence = même saison de l'an passé + 60 jours récents (choix par défaut).

  python -m evaluation.biais   ->  evaluation/sorties/biais_attendu.json
"""
import json
import os
from multiprocessing import Pool

import numpy as np
import pandas as pd

from vigie import moteur

from . import chiffrage, meteo_gve
from . import simulateur as S
from .campagne import SORTIES
from .reference import moteur_v0_2_0 as ref_moteur

P = {"fenetre_analyse_jours": 30}
GRAINES = range(200, 210)
_ETAT = {}


def _derniers(df, fin, jours=14):
    f = pd.Timestamp(fin).normalize()
    if "juge" in df:
        df = df[df["juge"]]
    return df[(df.index >= f - pd.Timedelta(days=jours)) & (df.index < f)]


def signature_avant(s, t, fin):
    d = ref_moteur.jour(s)
    df = pd.DataFrame({"q": d, "dj": ref_moteur.degres_jours(t).reindex(d.index)}).dropna()
    ref = df[df.index < fin - pd.Timedelta(days=30)]
    b, a = np.polyfit(ref["dj"], ref["q"], 1)
    df["att"] = a + b * df["dj"]
    return df


def pac_avant(e, flux, t, fin):
    h = pd.DataFrame({"e": e, "t": t, **flux}).dropna()
    ref = h[h.index < fin - pd.Timedelta(days=30)]
    if "totale" not in flux and "chauffage" not in flux and (ref["t"] < 14).sum() < ref_moteur.PAC_HEURES_CHAUFFE_MIN:
        return None
    coef, *_ = np.linalg.lstsq(ref_moteur._x_pac(ref, flux).to_numpy(), ref["e"].to_numpy(), rcond=None)
    h["e_att"] = (ref_moteur._x_pac(h, flux).to_numpy() @ coef).clip(min=0)
    return h.resample("D").agg({"e": "sum", "e_att": "sum"})


def _versions(fn_avant, fn_actuel):
    yield "avant", fn_avant()
    yield "anterieure", fn_actuel({**P, "reference_saison": False})
    yield "saison", fn_actuel(P)


def _init():
    _ETAT["reelle"] = pd.Series(meteo_gve.serie_longue(3)).sort_index()


def un(args):
    graine, met_nom, fin = args
    met = _ETAT["reelle"] if met_nom == "reelle" else "fictive"
    base = {"jours": chiffrage.HISTORIQUE_J, **({"fin": fin} if fin else {})}
    etiquette = fin.strftime("%Y-%m") if fin else "fictive"
    out = []
    brut, t, fin_s = S.simuler({"type": "chaufferie", **base}, graine, met)
    fin_s = pd.Timestamp(fin_s)
    s = brut["SIM_CHAL"]
    for version, df in _versions(lambda: signature_avant(s, t, fin_s),
                                 lambda p: moteur.signature_attendue(s, t, fin_s, p)):
        d = _derniers(df, fin_s)
        out.append({"modele": "chaleur_signature", "version": version, "meteo": met_nom, "fin": etiquette,
                    "graine": graine, "biais": float(d["q"].sum() / d["att"].sum() - 1),
                    "reference": (df.attrs or {}).get("reference")})
    for c in ("totale", "chauffage", "ecs", "aucune"):
        brut, t, fin_s = S.simuler({"type": "pac", "comptage": c, **base}, graine, met)
        fin_s = pd.Timestamp(fin_s)
        flux = {c: brut["SIM_" + S.POINTS_PAC[c][0]]} if c in S.POINTS_PAC else {}
        e = brut["SIM_PAC_ELEC"]
        for version, df in _versions(lambda: pac_avant(e, flux, t, fin_s),
                                     lambda p: moteur.pac_attendu(e, flux, t, fin_s, p)):
            ligne = {"modele": f"pac_{c}", "version": version, "meteo": met_nom, "fin": etiquette, "graine": graine}
            if df is None:
                out.append({**ligne, "biais": None, "reference": None})
                continue
            d = _derniers(df, fin_s)
            out.append({**ligne, "biais": float(d["e"].sum() / d["e_att"].sum() - 1),
                        "reference": (df.attrs or {}).get("reference")})
    return out


def _resume(vals):
    v = [b for b in vals if b is not None]
    out = {"n": len(vals), "sans_conclusion": len(vals) - len(v)}
    if v:
        out.update(moyenne=float(np.mean(v)), mediane=float(np.median(v)), min=float(min(v)), max=float(max(v)),
                   abs_moyen=float(np.mean(np.abs(v))))
    return out


def main():
    meteo_gve.serie_longue(3)
    taches = [(g, "reelle", f) for f in chiffrage.FINS for g in GRAINES] + [(g, "fictive", None) for g in GRAINES]
    with Pool(max(1, (os.cpu_count() or 2) - 1), initializer=_init) as pool:
        lignes = [x for r in pool.map(un, taches) for x in r]
    res, par_fin = {}, {}
    for x in lignes:
        res.setdefault(f"{x['modele']}|{x['meteo']}|{x['version']}", []).append(x["biais"])
        par_fin.setdefault(f"{x['modele']}|{x['fin']}|{x['version']}", []).append(x["biais"])
    resume = {k: _resume(v) for k, v in sorted(res.items())}
    with open(os.path.join(SORTIES, "biais_attendu.json"), "w", encoding="utf-8") as f:
        json.dump({"protocole": "relevés horaires, 12 mois d'historique, 14 derniers jours complets",
                   "fins": [x.isoformat() for x in chiffrage.FINS], "resume": resume,
                   "par_fin": {k: _resume(v) for k, v in sorted(par_fin.items())}, "lignes": lignes},
                  f, ensure_ascii=False, indent=1)
    for k, v in resume.items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})


if __name__ == "__main__":
    main()
