"""Rejeu : la détection rejouée jour après jour sur une période passée.

Le moteur juge la situation à la FIN des relevés. Pour retrouver les dérives d'une année écoulée, on le fait tourner
comme s'il avait été lancé chaque jour : à la date J, il ne voit que les mesures jusqu'à J (aucune connaissance du
futur), avec les mêmes règles, la même persistance et la même référence qu'en exploitation. Tant qu'une dérive est en
alerte, sa référence reste gelée à son début, comme pour une alerte ouverte.

Les alertes successives sont regroupées en ÉPISODES : même immeuble et même cause, du premier jour d'alerte au dernier.
Une alerte absente au plus TOLERANCE_J jours puis revenue reste le même épisode (une dérive de +15 % qui repasse un
jour sous le seuil de 10 % doit ré-accumuler 7 jours de persistance : sans cette tolérance, elle serait découpée en
plusieurs épisodes). Les montants d'un épisode sont les plus grands constatés par le moteur pendant l'épisode (dérive
mesurée depuis son début) ; rien n'est recalculé ici.
"""
import csv
import os

import pandas as pd

from . import db, moteur

TOLERANCE_J = 10
MONTANTS = ("chf_mesure", "kwh_mesure", "m3_mesure", "co2_t_mesure", "chf_mois")
COLONNES = ("immeuble_id", "immeuble", "point_id", "cause", "gravite", "fluide", "titre", "debut", "detecte_le",
            "dernier_le", "disparu_le", "jours_en_alerte", "delai_detection_j", "chf_mesure", "kwh_mesure", "m3_mesure",
            "chf_mois", "mesure", "attendu", "metier", "constat", "consigne")


def _jour(t):
    return str(pd.Timestamp(t).date())


def _nouvel_episode(a, jour):
    debut = str(a["debut"])[:10] if a.get("debut") else _jour(jour)
    return {"id": a["id"], "immeuble_id": a["immeuble_id"], "immeuble": a["immeuble"], "point_id": a.get("point_id"),
            "cause": a["cause"], "debut": debut, "detecte_le": _jour(jour), "jours_en_alerte": 0,
            "delai_detection_j": (pd.Timestamp(_jour(jour)) - pd.Timestamp(debut)).days, "disparu_le": None,
            **{m: 0 for m in MONTANTS}}


def _mettre_a_jour(e, a, jour):
    e["jours_en_alerte"] += 1
    e["dernier_le"] = _jour(jour)
    e.pop("_absent", None)
    for cle in ("gravite", "fluide", "titre", "constat", "consigne", "metier", "mesure", "attendu", "persistance"):
        e[cle] = a.get(cle)
    for m in MONTANTS:
        e[m] = max(e[m], a.get(m) or 0)


def rejouer(cx, ref, debut, fin, pas_jours=1, progres=None):
    """Rejoue l'analyse de `debut` à `fin` (dates incluses), tous les `pas_jours`. Retourne le bilan et les épisodes."""
    brut = moteur.lire_brut(cx)
    ouverts, clos, gelees, alertes = {}, [], {}, []
    jour, dernier, analyses = pd.Timestamp(debut).normalize(), pd.Timestamp(fin).normalize(), 0
    while jour <= dernier:
        alertes, _fin = moteur.analyser(cx, ref, jusqua=jour, brut=brut, gelees=dict(gelees))
        analyses += 1
        presentes = {a["id"]: a for a in alertes}
        for aid, a in presentes.items():
            e = ouverts.setdefault(aid, _nouvel_episode(a, jour))
            _mettre_a_jour(e, a, jour)
            if a["gravite"] != "Données" and a.get("debut"):
                gelees.setdefault(aid, pd.Timestamp(str(a["debut"])[:10]))  # référence gelée au début de la dérive
        for aid in [x for x in ouverts if x not in presentes]:
            e = ouverts[aid]
            e.setdefault("_absent", jour)
            if (jour - e["_absent"]).days > TOLERANCE_J:  # disparue pour de bon : l'épisode est clos
                e["disparu_le"] = _jour(e.pop("_absent"))
                clos.append(ouverts.pop(aid))
                gelees.pop(aid, None)
        if progres:
            progres(jour, len(alertes))
        jour += pd.Timedelta(days=pas_jours)
    for e in ouverts.values():  # encore en alerte (ou absente depuis moins de TOLERANCE_J jours) à la fin du rejeu
        if "_absent" in e:
            e["disparu_le"] = _jour(e.pop("_absent"))
        clos.append(e)
    clos.sort(key=lambda e: (e["detecte_le"], e["immeuble_id"], e["cause"]))
    # alertes_finales : alertes de la dernière date rejouée (références gelées comprises), à ouvrir dans la base
    return {"debut": _jour(debut), "fin": _jour(fin), "pas_jours": pas_jours, "analyses": analyses, "episodes": clos,
            "alertes_finales": alertes}


def enregistrer(cx, resultat, dossier_sortie=None):
    """Garde le dernier rejeu en base (paramètre « rejeu ») et l'écrit en CSV (séparateur ;)."""
    db.ecrire_parametre(cx, "rejeu", {k: v for k, v in resultat.items() if k != "alertes_finales"})
    if not dossier_sortie:
        return None
    os.makedirs(dossier_sortie, exist_ok=True)
    chemin = os.path.join(dossier_sortie, "rejeu_episodes.csv")
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLONNES)
        w.writerows([["" if e.get(c) is None else e.get(c) for c in COLONNES] for e in resultat["episodes"]])
    return chemin
