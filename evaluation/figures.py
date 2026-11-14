"""Figures de la campagne (PNG haute définition) : evaluation/sorties/figures/.

  python -m evaluation.figures   (après python -m evaluation.analyse --etiquette=horaire / --etiquette=horaire_avant)

Campagne principale « horaire » : relevés horaires, 12 mois d'historique, moteur actuel. « horaire_avant » : copie figée
du moteur V0.2.0 sur l'expérience de chiffrage seulement.
"""
import json
import os
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .campagne import AGE_DELAI, NOMINALE, ROBUSTE, SORTIES, UNITE_AMPLITUDE  # noqa: E402

FIG = os.path.join(SORTIES, "figures")
NUIT, BLEU, ORANGE, GRIS, GRIS_CLAIR, GRILLE = "#0F1B2D", "#1D4ED8", "#C2410C", "#64748B", "#CBD5E1", "#E5E7EB"
TEXTE, TEXTE_2 = "#0F1B2D", "#475569"
NOMS = {"eau_nuit": "Eau — fuite de nuit", "eau_vide": "Eau — immeuble vide",
        "chaleur_signature": "Chaleur — signature", "chaleur_vide": "Chaleur — immeuble vide",
        "elec_nuit": "Électricité — nuit", "pac_totale": "PAC — chaleur totale", "pac_chauffage": "PAC — chauffage seul",
        "pac_ecs": "PAC — eau chaude seule", "pac_aucune": "PAC — électricité seule",
        "cad_signature": "CAD — signature", "cad_vide": "CAD — immeuble vide", "gaz_signature": "Gaz — signature",
        "gaz_vide": "Gaz — immeuble vide"}
ORDRE = list(NOMS)
LIGNES = -(-len(ORDRE) // 3)  # grilles de 3 colonnes
MOIS_FR = {"01": "janv.", "02": "févr.", "03": "mars", "04": "avr.", "05": "mai", "06": "juin", "07": "juil.",
           "08": "août", "09": "sept.", "10": "oct.", "11": "nov.", "12": "déc."}


def _style():
    for f in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
        chemin = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", f)
        if os.path.exists(chemin):
            font_manager.fontManager.addfont(chemin)
    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 8.5, "axes.titlesize": 9, "axes.titleweight": "semibold",
        "axes.labelsize": 8, "axes.labelcolor": TEXTE_2, "axes.edgecolor": GRIS_CLAIR, "axes.linewidth": 0.8,
        "xtick.color": TEXTE_2, "ytick.color": TEXTE_2, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "axes.grid": True, "grid.color": GRILLE, "grid.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 7.5, "axes.titlecolor": TEXTE,
        "figure.dpi": 110, "savefig.dpi": 220, "axes.formatter.use_locale": False, "lines.linewidth": 1.8,
        "lines.solid_capstyle": "round", "axes.titlepad": 6, "axes.titlelocation": "left"})


def _fr(x, nd=0):
    return f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")


def _virgule(ax):
    for axe in (ax.xaxis, ax.yaxis):
        axe.set_major_formatter(FuncFormatter(lambda v, _: (f"{v:g}").replace(".", ",").replace("-", "−")))


def _sauver(fig, nom):
    os.makedirs(FIG, exist_ok=True)
    fig.savefig(os.path.join(FIG, nom), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _lire(etiquette):
    chemin = os.path.join(SORTIES, etiquette, "resume.json")
    if not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def _echelle(det):
    return 100 if UNITE_AMPLITUDE[det].startswith("%") else 1


def _met(m):
    return "réelle" if m == "reelle" else m


# ---------------------------------------------------------------- données


def fig_meteo(donnees):
    from vigie import moteur
    r, f = donnees["meteo_reelle"], donnees["meteo_fictive_campagne"]
    jr = pd.Series({pd.Timestamp(d): v for d, v in r["journalier"]})
    jf = pd.Series({pd.Timestamp(d): v for d, v in f["journalier"]})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 4.4), gridspec_kw={"height_ratios": [2.2, 1]})
    fin = pd.Timestamp(r["fin"])
    limite = fin - timedelta(days=30)
    a1.axvspan(limite, fin, color="#DBEAFE", lw=0, zorder=0)
    a1.axvspan(limite - timedelta(days=moteur.RECENT_J), limite, color="#F1F5F9", lw=0, zorder=0)
    debut_saison = max(jr.index[0], limite - moteur.UN_AN - timedelta(days=moteur.SAISON_MARGE_J))
    a1.axvspan(debut_saison, fin - moteur.UN_AN + timedelta(days=moteur.SAISON_MARGE_J), color="#F1F5F9", lw=0, zorder=0)
    a1.text(fin - timedelta(days=15), 29, "fenêtre\nd'analyse", ha="center", va="top", fontsize=6.6, color=TEXTE_2)
    a1.text(limite - timedelta(days=moteur.RECENT_J / 2), 29, "référence :\n60 j récents", ha="center", va="top",
            fontsize=6.6, color=TEXTE_2)
    a1.text(debut_saison + timedelta(days=22), 29, "référence :\nmême saison\nl'an passé", ha="center", va="top",
            fontsize=6.6, color=TEXTE_2)
    a1.plot(jr.index, jr.values, color=BLEU, lw=1.3, label="Réelle — MétéoSuisse Genève-Cointrin (moyenne journalière)")
    a1.plot(jf.index + (fin - pd.Timestamp(f["fin"])), jf.values, color=GRIS, lw=1.0,
            label="Fictive — simulateur de la campagne (graine 0)")
    a1.axhline(16, color=ORANGE, lw=0.9)
    a1.set_ylabel("°C")
    a1.set_ylim(-6, 31)
    a1.legend(loc="lower center", fontsize=7)
    a1.set_title("Température extérieure sur les 12 mois simulés et périodes de référence du chauffage et de la PAC")
    _virgule(a1)
    djr = (16 - jr).clip(lower=0)
    a2.bar(jr.index, djr.values, width=0.9, color=BLEU, lw=0)
    a2.set_ylabel("DJ base 16 / jour")
    a2.set_title("Degrés-jours journaliers de la série réelle (approximation par la moyenne journalière)", fontsize=8)
    _virgule(a2)
    for a in (a1, a2):
        a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m.%Y"))
    fig.tight_layout()
    _sauver(fig, "meteo_gve.png")


def fig_annualisation(donnees):
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    mois = ["10", "11", "12", "1", "2", "3", "4"]
    noms = ["oct.", "nov.", "déc.", "janv.", "févr.", "mars", "avr."]
    couleurs = [GRIS_CLAIR, GRIS, BLEU, NUIT]
    ann = [a for a in donnees["annualisation"] if a["grandeur"] == "chaleur"]
    for i, a in enumerate(ann):
        v = [a["rapport_par_mois"][m] for m in mois]
        ax.plot(range(len(noms)), v, marker="o", ms=4, color=couleurs[i % len(couleurs)], label=f"saison {a['saison']}")
    ax.axhline(1, color=NUIT, lw=0.9)
    ax.set_ylim(0, 1.6)
    _virgule(ax)
    ax.set_xticks(range(len(noms)))
    ax.set_xticklabels(noms)
    ax.set_ylabel("chiffrage annuel ÷ réalité")
    ax.set_title("Ancienne annualisation « excès du jour × 210 jours » selon le mois (dérive proportionnelle)")
    ax.legend(loc="lower center", ncol=len(ann))
    fig.tight_layout()
    _sauver(fig, "annualisation.png")


# ---------------------------------------------------------------- détection


def _legende_commune(fig):
    from matplotlib.lines import Line2D
    poignees = [Line2D([], [], color=BLEU, marker="o", ms=3.5, label="météo fictive"),
                Line2D([], [], color=ORANGE, marker="s", ms=3.5, label="météo réelle GVE")]
    fig.legend(handles=poignees, loc="upper center", ncol=2, fontsize=7.2, bbox_to_anchor=(0.5, 1.0))


def fig_detection(res):
    fig, axes = plt.subplots(LIGNES, 3, figsize=(7.4, 1.9 * LIGNES))
    for ax in axes.flat[len(ORDRE):]:
        ax.set_visible(False)
    for ax, det in zip(axes.flat, ORDRE):
        k = _echelle(det)
        for met, coul, mk in (("fictive", BLEU, "o"), ("reelle", ORANGE, "s")):
            b = res["balayage"].get(f"{det}|{met}")
            if not b:
                continue
            x = [c["amplitude"] * k for c in b["courbe"]]
            ax.fill_between(x, [c["ic95"][0] for c in b["courbe"]], [c["ic95"][1] for c in b["courbe"]], color=coul,
                            alpha=0.10, lw=0)
            ax.plot(x, [c["p"] for c in b["courbe"]], color=coul, marker=mk, ms=3.5)
        ax.set_title(NOMS[det], fontsize=8.2)
        ax.set_ylim(-0.03, 1.05)
        ax.set_xlabel(UNITE_AMPLITUDE[det], fontsize=7)
        _virgule(ax)
    for a in axes[:, 0]:
        a.set_ylabel("probabilité de détection")
    _legende_commune(fig)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _sauver(fig, "detection_amplitude.png")


def fig_delai(res):
    fig, axes = plt.subplots(LIGNES, 3, figsize=(7.4, 1.8 * LIGNES), sharex=True)
    for ax in axes.flat[len(ORDRE):]:
        ax.set_visible(False)
    for ax, det in zip(axes.flat, ORDRE):
        for met, coul in (("fictive", BLEU), ("reelle", ORANGE)):
            d = res["delai"].get(f"{det}|{met}")
            if d:
                ax.plot([p["age_j"] for p in d["profil"]], [p["p"] for p in d["profil"]], color=coul, lw=1.6)
        ax.set_title(NOMS[det], fontsize=8.2)
        ax.set_ylim(-0.03, 1.05)
        ax.set_xlim(0, AGE_DELAI)
        _virgule(ax)
    for a in axes.flat[len(ORDRE) - 3:len(ORDRE)]:
        a.set_xlabel("âge de la dérive à la date d'analyse (jours)")
        a.xaxis.set_tick_params(labelbottom=True)
    for a in axes[:, 0]:
        a.set_ylabel("part des graines en alerte")
    _legende_commune(fig)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _sauver(fig, "delai_detection.png")


# ---------------------------------------------------------------- chiffrage


def _barre(ax, e, y, coul, k=100):
    ax.plot([e["min"] * k, e["max"] * k], [y] * 2, color=coul, lw=0.8, alpha=0.6)
    ax.plot([e["q1"] * k, e["q3"] * k], [y] * 2, color=coul, lw=4.5, solid_capstyle="butt")
    ax.plot(e["mediane"] * k, y, "o", color="white", mec=coul, mew=1.4, ms=4.5)


def ecart_principal(r):
    """Écart du montant principal affiché : cumul mesuré (chauffage, PAC) ou annuel (eau, électricité, V0.2.0)."""
    return r.get("ecart_mesure") or r.get("ecart_annuel")


def fig_chiffrage(apres, avant):
    """V0.2.0 annualisé, dérive constatée et projection (÷ réalisé de chaque année réelle), vraie météo GVE."""
    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    ch_ap, ch_av = (apres or {}).get("chiffrage", {}), (avant or {}).get("chiffrage", {})
    y = np.arange(len(ORDRE))[::-1]
    borne = lambda e: {k: max(-1.0, min(v, 3.0)) if isinstance(v, float) else v for k, v in e.items()}  # noqa: E731
    for yi, det in zip(y, ORDRE):
        series = ((ch_av.get(f"{det}|reelle") or {}).get("ecart_annuel"), GRIS, 0.26),
        series += ((ch_ap.get(f"{det}|reelle") or {}).get("ecart_mesure"), BLEU, 0.0),
        series += ((ch_ap.get(f"{det}|reelle") or {}).get("ecart_proj_annees"), ORANGE, -0.26),
        for e, coul, dy in series:
            if e:
                _barre(ax, borne(e), yi + dy, coul)
    ax.axvline(0, color=NUIT, lw=0.9)
    ax.set_yticks(y)
    ax.set_yticklabels([NOMS[d] for d in ORDRE], fontsize=7.2)
    ax.set_xlabel("montant ÷ réalité − 1 (%) — médiane, quartiles, extrêmes (bornés à +300 %)")
    ax.set_title("Justesse des montants, fin d'analyse d'octobre à avril (vraie température GVE)")
    ax.plot([], [], color=GRIS, lw=4.5, label="V0.2.0 : CHF/an (× 210 ou × 365 jours) ÷ excès d'une année normale")
    ax.plot([], [], color=BLEU, lw=4.5, label="dérive constatée ÷ excès réel cumulé depuis le début réel")
    ax.plot([], [], color=ORANGE, lw=4.5, label="projection 12 mois ÷ excès réalisé de chaque année réelle 2016-2025")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.11), fontsize=6.8, ncol=1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−")))
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    _sauver(fig, "chiffrage.png")


def fig_chiffrage_mois(apres, avant):
    """Écart médian par mois de fin d'analyse : V0.2.0 annualisé, dérive constatée, projection (÷ année normale)."""
    dets = ["chaleur_signature", "chaleur_vide", "cad_signature", "gaz_signature", "pac_totale"]
    fig, axes = plt.subplots(1, len(dets), figsize=(7.4, 2.7), sharey=True)
    for ax, det in zip(axes, dets):
        for res, cle, coul, lib in ((avant, "par_mois", GRIS, "V0.2.0 (annuel)"),
                                    (apres, "par_mois", BLEU, "dérive constatée"),
                                    (apres, "par_mois_proj", ORANGE, "projection 12 mois")):
            pm = (((res or {}).get("chiffrage") or {}).get(f"{det}|reelle") or {}).get(cle) or {}
            if pm:
                mois = sorted(pm)
                ax.plot(range(len(mois)), [pm[m] * 100 for m in mois], marker="o", ms=3.2, color=coul, label=lib)
                ax.set_xticks(range(len(mois)))
                ax.set_xticklabels([MOIS_FR[m[5:]] for m in mois], fontsize=6.2, rotation=90)
        ax.axhline(0, color=NUIT, lw=0.8)
        ax.set_title(NOMS[det].replace(" — ", "\n"), fontsize=7.4)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−")))
    axes[0].set_ylabel("écart médian au réel (%)")
    poignees, libelles = [], []
    for ax in axes:
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            if ll not in libelles:
                poignees.append(hh)
                libelles.append(ll)
    fig.legend(poignees, libelles, loc="upper center", ncol=3, fontsize=7, bbox_to_anchor=(0.5, 1.04))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    _sauver(fig, "chiffrage_mois.png")


def fig_pas(res):
    """Part des dérives détectées au pas horaire et au pas journalier (ampleurs « robustesse » et nominale)."""
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    y = np.arange(len(ORDRE))[::-1]
    for yi, det in zip(y, ORDRE):
        for p, coul, dy in ((60, BLEU, 0.2), (1440, ORANGE, -0.2)):
            k = n = 0
            for a in (ROBUSTE[det], NOMINALE[det]):
                for met in ("fictive", "reelle"):
                    r = (res.get("pas") or {}).get(f"{det}|{met}|{p}|{a}")
                    if r:
                        k, n = k + r["detectees"], n + r["n"]
            if n:
                ax.barh(yi + dy, 100 * k / n, height=0.36, color=coul, lw=0)
                ax.text(100 * k / n + 1, yi + dy, f"{_fr(100 * k / n)} %", va="center", fontsize=6.5, color=TEXTE_2)
    ax.set_yticks(y)
    ax.set_yticklabels([NOMS[d] for d in ORDRE], fontsize=7.2)
    ax.set_xlim(0, 112)
    ax.set_xlabel("dérives détectées (%)")
    ax.set_title("Ce que l'on perd au pas journalier : même dérive relevée à l'heure et une fois par jour")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLEU, label="relevé horaire"), Patch(color=ORANGE, label="relevé journalier")],
              loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=7)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    _sauver(fig, "pas_journalier.png")


def fig_confiance(res):
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    seuils = {"eau_nuit": 20, "eau_vide": 50, "chaleur_signature": 0.10, "elec_nuit": 0.20, "pac_totale": 0.15,
              "pac_chauffage": 0.15, "pac_ecs": 0.15, "pac_aucune": 0.15}
    coul = {"eau_nuit": BLEU, "eau_vide": "#60A5FA", "chaleur_signature": ORANGE, "elec_nuit": NUIT,
            "pac_totale": GRIS, "pac_chauffage": GRIS, "pac_ecs": GRIS, "pac_aucune": GRIS}
    for det, s in seuils.items():
        b = res["balayage"].get(f"{det}|fictive")
        if not b:
            continue
        pts = [(c["amplitude"] / s, c["confiance_moy"]) for c in b["courbe"] if c["confiance_moy"] and c["amplitude"]]
        if pts:
            ax.plot(*zip(*pts), marker="o", ms=3, color=coul[det], lw=1.2,
                    label=NOMS[det] if not det.startswith("pac") or det == "pac_totale" else None)
    ax.set_xlabel("ampleur de la dérive ÷ seuil de la règle")
    ax.set_ylabel("confiance moyenne")
    ax.set_title("Confiance attribuée par le moteur aux alertes levées (météo fictive ; PAC : 4 comptages en gris)")
    ax.legend(ncol=3, loc="lower right", fontsize=6.8)
    ax.set_ylim(0.5, 1.0)
    _virgule(ax)
    fig.tight_layout()
    _sauver(fig, "confiance.png")


def fig_robustesse(res):
    from .campagne import VARIANTES
    variantes = list(VARIANTES)
    m = np.full((len(variantes), len(ORDRE)), np.nan)
    for i, v in enumerate(variantes):
        for j, det in enumerate(ORDRE):
            r = res["robustesse"].get(f"{v}|{det}|derive")
            if r:
                m[i, j] = r["detectees"] / r["n"]
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("bleu", ["#FFFFFF", "#BFDBFE", BLEU, NUIT])
    ax.imshow(m, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if not np.isnan(m[i, j]):
                ax.text(j, i, f"{m[i, j]:.0%}".replace("%", ""), ha="center", va="center", fontsize=6.0,
                        color="white" if m[i, j] > 0.6 else TEXTE)
    ax.set_xticks(range(len(ORDRE)))
    ax.set_xticklabels([NOMS[d].replace(" — ", "\n") for d in ORDRE], fontsize=5.6, rotation=90)
    ax.set_yticks(range(len(variantes)))
    ax.set_yticklabels(variantes, fontsize=7)
    ax.grid(False)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Robustesse au pas horaire : % des dérives détectées (≈ 1,5 à 2,5 × le seuil, 10 graines)")
    fig.tight_layout()
    _sauver(fig, "robustesse.png")


def fig_qualite(res):
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6))
    for ax, (defaut, unite, x_k, seuil) in zip(axes, (("silence", "heures sans donnée (compteur d'eau)", 1, 24),
                                                     ("completude", "relevés perdus sur 30 jours (%)", 100, 10))):
        pts = sorted((v["niveau"], v["alerte_donnees"] / v["n"], v["alerte_energie"] / v["n"])
                     for v in res["qualite"].values() if v["defaut"] == defaut)
        x = [p[0] * x_k for p in pts]
        ax.plot(x, [p[1] for p in pts], color=BLEU, marker="o", ms=3.5, label="alerte « Données »")
        ax.plot(x, [p[2] for p in pts], color=ORANGE, marker="s", ms=3.5, label="alerte énergie sur ce point")
        ax.axvline(seuil, color=GRIS, lw=0.9)
        ax.set_xlabel(unite)
        ax.set_ylim(-0.03, 1.05)
        _virgule(ax)
        ax.legend(loc="center right", fontsize=6.8)
    axes[0].set_title("Compteur muet (dérive de fuite active)")
    axes[1].set_title("Complétude (dérive électrique active)")
    axes[0].set_ylabel("part des graines")
    fig.tight_layout()
    _sauver(fig, "qualite_donnees.png")


def fig_methodes():
    """Illustration des méthodes sur un scénario simulé (12 mois, horaire) : signature énergétique et minimum de nuit."""
    from vigie import moteur

    from . import simulateur as S
    sc = {"type": "chaufferie", "derive": "signature", "amplitude": 0.15, "age_j": 14}
    brut, t, fin = S.simuler(sc, 7, "fictive")
    q = brut["SIM_CHAL"].resample("D").sum()
    dj = moteur.degres_jours(t).reindex(q.index)
    _, ref_masque, _ = moteur.periode_reference(q.index, pd.Timestamp(fin), {"fenetre_analyse_jours": 30})
    ref = np.asarray(ref_masque)
    der = q.index >= pd.Timestamp(fin - timedelta(days=14)).normalize()
    fen = (q.index >= pd.Timestamp(fin - timedelta(days=30))) & ~der
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.9))
    a1.scatter(dj[ref], q[ref], s=8, color=GRIS, lw=0, label="référence (même saison + 60 j)")
    a1.scatter(dj[fen], q[fen], s=9, color="#93C5FD", lw=0, label="fenêtre, avant la dérive")
    a1.scatter(dj[der][:-1], q[der][:-1], s=12, color=ORANGE, lw=0, label="dérive +15 %")
    b, a = np.polyfit(dj[ref], q[ref], 1)
    xx = np.linspace(0, dj[ref | der].max() * 1.05, 10)
    a1.plot(xx, a + b * xx, color=NUIT, lw=1.3, label="signature apprise")
    a1.plot(xx, (a + b * xx) * 1.10, color=NUIT, lw=0.8, alpha=0.6)
    a1.text(xx[-1], (a + b * xx[-1]) * 1.10, " seuil +10 %", fontsize=6.8, va="bottom", ha="right", color=TEXTE_2)
    a1.set_xlabel("degrés-jours base 16 °C")
    a1.set_ylabel("chaleur (kWh/jour)")
    a1.set_title("Signature énergétique (chaleur)")
    a1.legend(fontsize=6.3, loc="upper left")
    sc2 = {"type": "chaufferie", "derive": "fuite", "amplitude": 35, "age_j": 6}
    brut2, _, _ = S.simuler(sc2, 7, "fictive")
    s = brut2["SIM_EAU"].diff() * 1000  # relevé horaire : débit de l'heure (l/h)
    nuit = s[(s.index.hour > 1) & (s.index.hour <= 5)]
    mins = nuit.groupby(nuit.index.date).min()[-40:]
    a2.bar(range(len(mins)), mins.values, color=[ORANGE if v > 20 else BLEU for v in mins.values], width=0.75, lw=0)
    a2.axhline(20, color=NUIT, lw=0.9)
    a2.text(0, 21.5, "seuil 20 l/h", fontsize=6.8, color=TEXTE_2)
    a2.set_xticks([0, len(mins) - 1])
    a2.set_ylabel("débit horaire minimum 1 h–5 h (l/h)")
    a2.set_title("Minimum de nuit (eau, relevé horaire) — fuite de 35 l/h")
    for ax in (a1, a2):
        _virgule(ax)
    a2.xaxis.set_major_formatter(matplotlib.ticker.FixedFormatter(
        [str(mins.index[0])[8:] + "." + str(mins.index[0])[5:7], str(mins.index[-1])[8:] + "." + str(mins.index[-1])[5:7]]))
    fig.tight_layout()
    _sauver(fig, "methodes_illustration.png")


def fig_biais():
    chemin = os.path.join(SORTIES, "biais_attendu.json")
    if not os.path.exists(chemin):
        return
    with open(chemin, encoding="utf-8") as f:
        r = json.load(f)["resume"]
    modeles = [("chaleur_signature", "Signature chaleur"), ("pac_totale", "PAC chaleur totale"),
               ("pac_chauffage", "PAC chauffage seul"), ("pac_ecs", "PAC eau chaude seule"),
               ("pac_aucune", "PAC électricité seule")]
    versions = (("avant", GRIS, "V0.2.0"), ("anterieure", "#93C5FD", "actuel, référence antérieure (repli)"),
                ("saison", BLEU, "actuel, même saison + 60 j (défaut)"))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
    for ax, met in zip(axes, ("fictive", "reelle")):
        y = np.arange(len(modeles))[::-1]
        for dy, (version, coul, _) in zip((0.26, 0, -0.26), versions):
            for yi, (m, _) in zip(y, modeles):
                v = r.get(f"{m}|{met}|{version}") or {}
                if "moyenne" not in v:
                    continue
                ax.barh(yi + dy, v["moyenne"] * 100, height=0.24, color=coul, lw=0)
                ax.plot([v["min"] * 100, v["max"] * 100], [yi + dy] * 2, color=NUIT, lw=0.7)
        ax.axvline(0, color=NUIT, lw=0.8)
        ax.set_yticks(y)
        ax.set_yticklabels([n for _, n in modeles], fontsize=7.2)
        ax.set_title("météo fictive" if met == "fictive" else "météo réelle GVE (oct. à avr.)", fontsize=8.2)
        ax.set_xlabel("mesuré ÷ attendu − 1 (%)")
        ax.grid(axis="y", visible=False)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−")))
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=c, label=lib) for _, c, lib in versions], loc="lower center", ncol=3, fontsize=6.8,
               bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    _sauver(fig, "biais_attendu.png")


def main():
    _style()
    with open(os.path.join(SORTIES, "donnees.json"), encoding="utf-8") as f:
        donnees = json.load(f)
    res, avant = _lire("horaire"), _lire("horaire_avant")
    fig_meteo(donnees)
    fig_annualisation(donnees)
    fig_methodes()
    fig_detection(res)
    fig_delai(res)
    fig_chiffrage(res, avant)
    fig_chiffrage_mois(res, avant)
    fig_pas(res)
    fig_confiance(res)
    fig_robustesse(res)
    fig_qualite(res)
    fig_biais()
    print("figures écrites dans", FIG)


if __name__ == "__main__":
    main()
