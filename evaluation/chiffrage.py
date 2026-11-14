"""Expérience « chiffrage » : justesse des montants avant (V0.2.0) et après (excès mesuré, rythme mensuel).

Pour chaque détecteur, une dérive d'ampleur nominale commence 14 jours avant la fin d'analyse ; la fin d'analyse est
placée au 15 de chaque mois d'octobre 2025 à avril 2026 (vraie température GVE, 12 mois d'historique), plus la fin
fictive en météo fictive. La série est simulée 30 jours AU-DELÀ de la fin d'analyse pour connaître le mois suivant.

Vérités (mêmes tirages, simulation sans dérive, relevé horaire) :
  cumul   excès réel heure par heure, du début réel de la dérive à la fin d'analyse ;
  mois    excès réel des 30 jours qui suivent la fin d'analyse (ce qu'annonce le rythme mensuel) ;
  annuel  excès qu'aurait la même dérive sur une année de Genève : lois du simulateur appliquées heure par heure à la
          vraie température GVE de 2016 à 2025 (moyenne des 10 années). Vérité du « par an » de V0.2.0 (× 210 ou 365
          jours) et du « par an » de l'eau et de l'électricité.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

FINS = [datetime(a, m, 15, 6) for a, m in ((2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3),
                                          (2026, 4))]
GRAINES = range(7000, 7006)
AGE_J = 14        # âge de la dérive à la fin d'analyse
APRES_J = 30      # jours simulés après la fin d'analyse (vérité du rythme mensuel)
HISTORIQUE_J = 365
ANNEES = range(2016, 2026)
VECTEUR = {"eau_nuit": "eau", "eau_vide": "eau", "chaleur_signature": "chaleur", "chaleur_vide": "chaleur",
           "cad_signature": "cad", "cad_vide": "cad", "gaz_signature": "gaz", "gaz_vide": "gaz"}  # sinon électricité


def taches(scenario, detecteurs, nominale, fictive_fin, n_graines=None):
    out = []
    graines = list(GRAINES)[:n_graines] if n_graines else GRAINES
    for det in detecteurs:
        for fin, met in [(f, "reelle") for f in FINS] + [(fictive_fin, "fictive")]:
            for g in graines:
                sc = scenario(det, nominale[det], AGE_J + APRES_J,
                              {"fin": fin + timedelta(days=APRES_J), "jours": HISTORIQUE_J + APRES_J})
                out.append({"exp": "chiffrage", "det": det, "amplitude": nominale[det], "meteo": met, "graine": g,
                            "fin_analyse": fin.isoformat(), "sc": sc, "coupes": [24 * APRES_J]})
    return out


def verites(h, fin_sim):
    """h = excès réel horaire (fin d'intervalle) ; retourne cumul (début réel -> fin d'analyse) et mois suivant."""
    fin_a = fin_sim - timedelta(days=APRES_J)
    debut = fin_a - timedelta(days=AGE_J)
    return {"verite_cumul": float(h[(h.index > debut) & (h.index <= fin_a)].sum()),
            "verite_mois": float(h[h.index > fin_a].sum()),
            "verite_j": float(h[(h.index > debut) & (h.index <= fin_a)].sum()) / AGE_J}


def serie_climat():
    """Température horaire réelle GVE 2016-2025 (fichiers historiques MétéoSuisse en cache)."""
    from . import climat_gve
    t = climat_gve.serie_historique()
    return t[(t.index.year >= ANNEES[0]) & (t.index.year <= ANNEES[-1])]


def _par_annee(t):
    """Excès annuels unitaires (lois du simulateur, heure de fin d'intervalle) pour chaque année de la série `t`."""
    reduit = np.where((t.index.hour >= 22) | (t.index.hour < 5), 0.8, 1.0)
    dh = (16 - t).clip(lower=0).to_numpy()
    T = t.to_numpy()
    an = lambda x: pd.Series(x, index=t.index).groupby(t.index.year).sum()  # noqa: E731
    chaleur = lambda L: an(L * 0.22 * dh * reduit + L * 0.12)  # noqa: E731
    pac = an(32 * 0.22 * dh * reduit / (3.4 + 0.04 * (T - 5)) + 32 * 0.12 / (2.6 + 0.03 * (T - 5)))
    df = pd.DataFrame({"chaleur_30": chaleur(30), "chaleur_20": chaleur(20), "pac_32": pac})
    return {int(y): r.to_dict() for y, r in df.iterrows()}


def verite_annuelle_unitaire(t=None):
    """{"moyenne": excès unitaires moyens 2016-2025, "annees": {année: excès unitaires}} : l'excès « réalisé » d'une
    dérive maintenue une année, chaque année réelle de Genève, et sa moyenne (le climat normal de la projection)."""
    annees = _par_annee(serie_climat() if t is None else t)
    moyenne = {k: float(np.mean([v[k] for v in annees.values()])) for k in next(iter(annees.values()))}
    return {"moyenne": moyenne, "annees": annees}


def verite_annuelle(det, a, V):
    """Excès annuel d'une dérive d'ampleur `a` maintenue toute l'année (m³ pour l'eau, kWh sinon ; gaz en kWh PCS)."""
    from . import simulateur
    if det == "eau_nuit":
        return a * 24 * 365 / 1000
    if det == "eau_vide":
        return a * 365 / 1000
    if det == "elec_nuit":
        return a * 3.2 * 8 * 365  # base de nuit 3,2 kW de l'immeuble « chaufferie », 22 h-6 h
    gaz = 1 / simulateur.RENDEMENT_CHAUDIERE if det.startswith("gaz") else 1.0
    if det.endswith("_signature"):
        return a * V["chaleur_30"] * gaz
    if det.endswith("_vide"):
        return (a - 0.12) * V["chaleur_20"] * gaz
    return (1 / (1 - a) - 1) * V["pac_32"]


def _q(xs):
    xs = sorted(x for x in xs if x is not None and np.isfinite(x))
    if not xs:
        return None
    return {"n": len(xs), "mediane": float(np.median(xs)), "min": xs[0], "max": xs[-1],
            "q1": float(np.percentile(xs, 25)), "q3": float(np.percentile(xs, 75))}


def resume(lignes, V):
    """Écarts (estimé ÷ réel − 1) par détecteur et par météo.

    mesure      dérive constatée ÷ excès réel cumulé depuis le début RÉEL de la dérive (moteur actuel) ;
    annuel      montant annuel ÷ excès d'une année au climat normal (moteur V0.2.0) ;
    proj        projection 12 mois ÷ excès d'une année au climat normal (moteur actuel) ;
    proj_annees projection ÷ excès réalisé chaque année réelle 2016-2025 (dispersion due au climat de l'année) ;
    mois        rythme mensuel ÷ excès réel des 30 jours suivants ; base_score : base du score ÷ coût réel du mois suivant.
    """
    from vigie import service

    from .campagne import CAUSE, DETECTEURS
    tarifs = service.defauts()["tarifs"]
    out = {}
    for det in DETECTEURS:
        for groupe in ("reelle", "fictive"):
            ls = [r for r in lignes if r["ok"] and r["det"] == det and r["meteo"] == groupe]
            if not ls:
                continue
            a = ls[0]["amplitude"]
            vrai_an = verite_annuelle(det, a, V["moyenne"])
            vrais_annees = [verite_annuelle(det, a, v) for v in V["annees"].values()]
            u = "m3" if det.startswith("eau") else "kwh"
            e = {"mesure": [], "annuel": [], "proj": [], "proj_annees": [], "mois": [], "base_score": []}
            par_mois, par_mois_proj, detectees = {}, {}, 0
            for r in ls:
                al = r["coupes"][0]["alerte"]
                if not al:
                    continue
                detectees += 1
                mois = r["fin_analyse"][:7]
                if al.get("chiffrage") is None:  # moteur V0.2.0 : montant annuel
                    if al.get(f"{u}_an") is not None:
                        e["annuel"].append(al[f"{u}_an"] / vrai_an - 1)
                        par_mois.setdefault(mois, []).append(e["annuel"][-1])
                else:
                    if al.get(f"{u}_mesure") is not None and r.get("verite_cumul"):
                        e["mesure"].append(al[f"{u}_mesure"] / r["verite_cumul"] - 1)
                        par_mois.setdefault(mois, []).append(e["mesure"][-1])
                    if al.get(f"{u}_proj") is not None:
                        e["proj"].append(al[f"{u}_proj"] / vrai_an - 1)
                        e["proj_annees"] += [al[f"{u}_proj"] / x - 1 for x in vrais_annees]
                        par_mois_proj.setdefault(mois, []).append(e["proj"][-1])
                if al.get(f"{u}_mois") is not None and r.get("verite_mois"):
                    e["mois"].append(al[f"{u}_mois"] / r["verite_mois"] - 1)
                # base du score ÷ coût réel des 30 jours suivants (même unité CHF) : comparable entre fluides si ≈ 1
                base = al.get("chf_mois") if al.get("chf_mois") is not None else al.get("chf_an")
                tarif = tarifs[VECTEUR.get(det, "electricite")]["chf_par_unite"]
                if base is not None and r.get("verite_mois"):
                    e["base_score"].append(base / (r["verite_mois"] * tarif))
            med = lambda d: {m: float(np.median(v)) for m, v in sorted(d.items()) if v}  # noqa: E731
            out[f"{det}|{groupe}"] = {
                "det": det, "cause": CAUSE[det], "meteo": groupe, "n": len(ls), "detectees": detectees,
                "verite_annuelle": vrai_an, "verite_annuelle_min_max": [min(vrais_annees), max(vrais_annees)],
                **{f"ecart_{k}": _q(v) for k, v in e.items()}, "par_mois": med(par_mois),
                "par_mois_proj": med(par_mois_proj)}
    return out
