"""Type de jour (ouvré, ouvré en vacances scolaires, non ouvré) pour comparer un jour à des jours semblables.

Mesuré sur les courbes du lot communal 2025, à météo égale : dans une crèche, une école, une bibliothèque, un bâtiment
administratif ou des ateliers, un jour ouvré consomme 9 à 17 % de plus que la droite météo et un jour non ouvré 18 à
25 % de moins ; des logements ou une piscine n'y sont pas sensibles (± 4 %). Avec un seuil de dérive de 10 %, comparer
un mardi à un dimanche fausse le jugement. La signature de chauffage compare donc chaque jour aux jours de MÊME TYPE,
mais seulement pour les immeubles où l'effet se voit dans leur propre référence (`sensible`).

Source : le calendrier du lot importé (table `reference` : jours ouvrés, vacances scolaires). Pour une date absente
du calendrier, lundi à vendredi = ouvré, samedi et dimanche = non ouvré (fériés et vacances alors inconnus).
"""
import sqlite3

import numpy as np
import pandas as pd

OUVRE, VACANCES, NON_OUVRE = "O", "V", "N"   # ouvré hors vacances, ouvré pendant les vacances scolaires, non ouvré
SERIES = ("jour_ouvre", "jour_vacances_scolaires")
ECART_MIN = 0.10      # écart de consommation entre jours ouvrés et non ouvrés qui rend l'immeuble « sensible »
JOURS_MIN = 10        # jours de chaque type exigés dans la référence pour en juger


def lire(cx):
    """{date: (ouvré, vacances scolaires)} du calendrier importé ; {} s'il n'y en a pas."""
    if cx is None:
        return {}
    try:
        lignes = cx.execute(f"SELECT serie, periode, valeur FROM reference WHERE serie IN {SERIES}").fetchall()
    except sqlite3.OperationalError:
        return {}
    par_jour = {}
    for serie, periode, valeur in lignes:
        par_jour.setdefault(periode, {})[serie] = bool(valeur)
    return {pd.Timestamp(jour): (v[SERIES[0]], v.get(SERIES[1], False))
            for jour, v in par_jour.items() if SERIES[0] in v}


def classes(jours, calendrier=None):
    """Type de chaque jour de l'index : calendrier importé, sinon jour de la semaine."""
    out = []
    for jour in pd.DatetimeIndex(jours).normalize():
        ouvre, vacances = (calendrier or {}).get(jour, (jour.dayofweek < 5, False))
        out.append(NON_OUVRE if not ouvre else VACANCES if vacances else OUVRE)
    return np.array(out)


def sensible(rapports, types):
    """Vrai si, dans la référence, les jours non ouvrés s'écartent des jours ouvrés de plus de ECART_MIN.

    `rapports` : consommation du jour ÷ attendu de la droite météo ; `types` : type de chaque jour."""
    rapports, types = np.asarray(rapports, dtype=float), np.asarray(types)
    connus = np.isfinite(rapports)
    ouvres, repos = rapports[connus & (types != NON_OUVRE)], rapports[connus & (types == NON_OUVRE)]
    if len(ouvres) < JOURS_MIN or len(repos) < JOURS_MIN:
        return False
    return abs(float(np.median(ouvres)) - float(np.median(repos))) >= ECART_MIN


def comparables(types_reference, type_du_jour):
    """Masques des jours de référence à essayer, du plus précis au plus large ; aucun repli vers un autre type de
    jour (un jour ouvré n'est jamais comparé à un week-end)."""
    meme = types_reference == type_du_jour
    if type_du_jour == NON_OUVRE:
        return [meme]
    return [meme, types_reference != NON_OUVRE]  # sans assez de jours du même type : tous les jours ouvrés
