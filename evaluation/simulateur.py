"""Simulateur paramétrable pour la campagne d'évaluation (consommations FICTIVES).

Reprend les lois du générateur d'exemple (vigie/generer_demo.py) — profils d'eau, d'électricité, de chaleur et
de PAC, bruits — mais avec une dérive d'AMPLITUDE et de DATE DE DÉBUT réglables, des défauts de données et des
variantes de robustesse (bruit, lacunes, occupation, historique court). Chaque scénario est simulé deux fois avec
les MÊMES tirages aléatoires (avec et sans dérive) : la différence donne la vérité exacte de l'excès injecté.

Historique : 12 mois par défaut. Pas de relevé : HORAIRE par défaut (aucune donnée n'arrive plus finement que
l'heure). L'écoulement de l'eau et la présence (électricité) sont simulés par quart d'heure, puis RELEVÉS à l'heure
(index lu à l'heure pleine, électricité et PAC cumulées sur l'heure) ; la chaleur est simulée à l'heure. Variante
`pas=1440` : relevé journalier de tous les compteurs de consommation (la température reste horaire).

Le scénario passe ensuite par la chaîne réelle de Vigie : base SQLite temporaire (en mémoire) -> import CSV
(db.importer_mesures, contrôles de qualité compris) -> moteur.analyser() avec les règles par défaut.
"""
import io
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from vigie import db, generer_demo, moteur

MOTEUR = moteur  # moteur évalué (remplaçable par la copie figée « avant révision », voir campagne.py)

FIN_FICTIVE = generer_demo.FIN
JOURS = 365  # 12 mois d'historique
HORS_GEL = 0.12  # facteur de marche hors-gel du générateur (R41)
# Production de chaleur d'un immeuble non PAC (`chauffage` du scénario) : point simulé, fluide, unité, nature
CHAUFFAGES = {"chaleur": ("SIM_CHAL", "chaleur", "kWh", "intervalle"), "cad": ("SIM_CAD", "cad", "kWh", "intervalle"),
              "gaz": ("SIM_GAZ", "gaz", "m3", "index")}
PCS_GAZ = generer_demo.PCS_GAZ                    # kWh par m³ (valeur d'EXEMPLE du référentiel)
RENDEMENT_CHAUDIERE = generer_demo.RENDEMENT_CHAUDIERE

# Types d'immeubles simulés (tailles proches des immeubles de l'exemple)
TYPES = {
    "chaufferie": dict(logements=30, base_kw=3.2, jour_kw=10.0, profil="Habite"),   # comme OB
    "pac": dict(logements=32, profil="Habite"),                                      # comme G01
    "vide": dict(logements=20, base_kw=1.2, jour_kw=0.0, profil="Vide", talon=200.0),  # comme R41
}
POINTS_PAC = {"totale": ("PAC_CHAL", "pac_chaleur"), "chauffage": ("PAC_CHAUF", "pac_chaleur_chauffage"),
              "ecs": ("PAC_ECS", "pac_chaleur_ecs")}


def _point(pid, fluide, unite, nature, pas):
    return {"id": pid, "fluide": fluide, "libelle": pid, "unite": unite, "nature": nature, "pas_min": pas,
            "source": "simulation"}


def immeuble(sc):
    """Fiche d'immeuble (référentiel) du scénario."""
    t = TYPES[sc["type"]]
    pas = sc.get("pas", 60)
    pts = [_point("SIM_ELEC", "electricite", "kWh", "intervalle", pas), _point("SIM_EAU", "eau", "m3", "index", pas)]
    if sc["type"] == "pac":
        pts.append(_point("SIM_PAC_ELEC", "pac_electricite", "kWh", "intervalle", pas))
        if sc.get("comptage", "totale") in POINTS_PAC:
            suffixe, fluide = POINTS_PAC[sc["comptage"]]
            pts.append(_point("SIM_" + suffixe, fluide, "kWh", "intervalle", pas))
    else:
        pts.append(_point(*CHAUFFAGES[sc.get("chauffage", "chaleur")], pas))
    occ = sc.get("occ", 1.0)
    profil = sc.get("profil", t["profil"])
    return {"id": "SIM", "nom": "Immeuble simulé", "adresse": "Rue de la Simulation 1", "npa": "1200 Genève",
            "profil": profil, "taux_occupation": occ if profil == "Partiel" else None, "logements": t["logements"],
            "talon_horsgel_kwh_j": t.get("talon"), "points": pts}


# ---------------------------------------------------------------- température


def temperature_fictive_annuelle(heures):
    """Température FICTIVE sur 12 mois (hors ligne) : cycle annuel (minimum mi-janvier, 2 à 19 °C en moyenne
    journalière), cycle journalier ±4 °C (maximum à 15 h UTC) et variation lente ±2,5 °C sur une douzaine de jours."""
    doy = heures.day_of_year.to_numpy()
    d = (heures - heures[0]).total_seconds().to_numpy() / 86400
    return (10.5 - 8.5 * np.cos(2 * math.pi * (doy - 20) / 365.25)
            + 4 * np.sin((heures.hour.to_numpy() - 9) / 24 * 2 * math.pi) + 2.5 * np.sin(d / 6.0))


def temperatures(meteo, graine, fin, jours, bruit=1.0, froid=None):
    """(T de simulation sur toute la grille horaire, T « mesurée » importée) ; réelle = MétéoSuisse GVE figée."""
    debut = fin - timedelta(days=jours)
    heures = pd.date_range(debut + timedelta(hours=1), periods=jours * 24, freq="h")
    if isinstance(meteo, str):  # "fictive"
        rng = np.random.default_rng([graine, 7])
        t = pd.Series(temperature_fictive_annuelle(heures) + rng.normal(0, 0.6 * bruit, len(heures)), index=heures)
        return _froid(t, fin, froid), _froid(t, fin, froid)
    reelle = meteo if isinstance(meteo, pd.Series) else pd.Series(meteo).sort_index()
    mesuree = reelle.reindex(heures).dropna()
    simul = reelle.reindex(heures).ffill().bfill()
    return _froid(simul, fin, froid), _froid(mesuree, fin, froid)


def _froid(t, fin, froid):
    """Vague de froid artificielle : `froid` = (écart °C, jours avant la fin)."""
    if not froid:
        return t
    ecart, jours = froid
    return t.where(t.index <= fin - timedelta(days=jours), t - ecart)


def fin_scenario(meteo, sc=None):
    """Fin de la série simulée : imposée par le scénario (`fin`), sinon fin fictive ou dernier 06:00 UTC réel."""
    if sc and sc.get("fin"):
        return sc["fin"]
    if isinstance(meteo, str):
        return FIN_FICTIVE
    return generer_demo.fin_reelle(meteo.index if isinstance(meteo, pd.Series) else meteo)


# ---------------------------------------------------------------- consommations


def _presence(hh):
    p = np.where((hh >= 6) & (hh <= 23), np.sin((hh - 6) / 17 * math.pi), 0.0)
    return np.maximum(p, 0.0)


def _occ(sc, idx, fin):
    """Taux d'occupation à chaque instant (changement d'occupation éventuel `occ_apres` à `occ_age_j` jours de la fin)."""
    occ = np.full(len(idx), float(sc.get("occ", 1.0)))
    if sc.get("occ_apres") is not None:
        occ[idx > fin - timedelta(days=sc["occ_age_j"])] = sc["occ_apres"]
    return occ


def _par_heure(valeurs_quart, heures):
    """Somme des 4 quarts d'heure (t-45, -30, -15, 0 min) de chaque heure : relevé horaire d'un compteur d'intervalle."""
    return pd.Series(valeurs_quart.reshape(-1, 4).sum(axis=1), index=heures)


def releve(s, nature, pas):
    """Relevé au pas `pas` d'une série horaire physique (intervalle : somme ; index : valeur lue en fin de pas)."""
    if pas == 60:
        return s
    if pas != 1440:
        raise ValueError("pas de relevé simulé : 60 ou 1440 minutes")
    debut = s.index[0] - timedelta(hours=1)
    premier = (debut + timedelta(days=1)).normalize() + timedelta(days=1)  # premier jour entier après le début
    if nature == "index":
        j = s[s.index.hour == 0]
    else:
        j = s.resample("D", label="right", closed="right").sum()
    return j[(j.index >= premier) & (j.index <= s.index[-1])]  # jours entiers seulement


def simuler(sc, graine, meteo, avec_derive=True):
    """Mesures relevées {point_id: pd.Series} + température. Les tirages ne dépendent ni de la dérive ni du pas."""
    fin = fin_scenario(meteo, sc)
    jours = sc.get("jours", JOURS)
    bruit = sc.get("bruit", 1.0)
    debut = fin - timedelta(days=jours)
    t_sim, t_mes = temperatures(meteo, graine, fin, jours, bruit if sc.get("bruit_meteo") else 1.0, sc.get("froid"))
    rng = np.random.default_rng([graine, 11])
    heures = t_sim.index
    quarts = pd.date_range(debut + timedelta(minutes=15), periods=jours * 96, freq="15min")
    hq = quarts.hour.to_numpy() + quarts.minute.to_numpy() / 60
    hh = heures.hour.to_numpy()
    T = t_sim.to_numpy()
    typ, spec = sc["type"], TYPES[sc["type"]]
    L = spec["logements"]
    der = sc.get("derive") if avec_derive else None
    amp = sc.get("amplitude", 0.0)
    onset = fin - timedelta(days=sc.get("age_j", 14))
    actif_q = (quarts > onset) if der else np.zeros(len(quarts), bool)
    actif_h = (heures > onset) if der else np.zeros(len(heures), bool)
    occ_q, occ_h = _occ(sc, quarts, fin), _occ(sc, heures, fin)
    travaux = sc.get("profil") == "Travaux"
    out = {}

    # tirages (ordre fixe, indépendant de la dérive et du pas de relevé)
    u_elec = rng.uniform(1 - 0.07 * bruit, 1 + 0.07 * bruit, len(quarts))
    u_chal = rng.uniform(1 - 0.05 * bruit, 1 + 0.05 * bruit, len(heures))
    u_pac = rng.uniform(1 - 0.03 * bruit, 1 + 0.03 * bruit, len(quarts))
    u_eau = rng.uniform(1 - 0.15 * bruit, 1 + 0.15 * bruit, len(quarts))
    chasse = rng.random(len(quarts)) < 0.15 * sc.get("chasses", 1.0)
    v_chasse = rng.uniform(0, 40, len(quarts))
    index0 = (2000.0 if typ == "pac" else 1000.0) + rng.uniform(0, 800 if typ == "pac" else 500)

    # électricité générale (présence simulée par 15 min, relevé horaire)
    # quart d'heure repéré par sa FIN (convention des relevés) : la nuit 22 h-6 h = quarts finissant de 22:15 à 06:00
    nuit_q = (hq > 22) | (hq <= 6)
    if typ == "pac":
        base, jour_kw = 0.10 * L * occ_q, 0.30 * L * occ_q * (0.4 if travaux else 1.0)
    else:
        base, jour_kw = spec["base_kw"] * occ_q, spec["jour_kw"] * occ_q
    pres = _presence(hq)
    p = base + jour_kw * pres
    if der == "elec_nuit":
        p = p + np.where(actif_q & nuit_q, amp * base, 0.0)
    out["SIM_ELEC"] = _par_heure(p * 0.25 * u_elec, heures)

    # chaleur (horaire)
    reduit = np.where((hh >= 22) | (hh < 5), 0.8, 1.0)
    dh = np.maximum(0.0, 16 - T)
    if typ == "pac":
        k, ecs = L * 0.22 * (0.6 + 0.4 * occ_h), L * 0.12 * occ_h * (0.15 if travaux else 1.0)
        q_ch, q_ecs = k * dh * reduit * u_chal, ecs * u_chal
        comptage = sc.get("comptage", "totale")
        valeurs = {"totale": q_ch + q_ecs, "chauffage": q_ch, "ecs": q_ecs}
        if comptage in POINTS_PAC:
            out["SIM_" + POINTS_PAC[comptage][0]] = pd.Series(valeurs[comptage], index=heures)
        deg = np.ones(len(heures))
        if der == "pac":
            deg = np.where(actif_h, 1 - amp, 1.0)
        elif der == "pac_rampe":
            age = (fin - heures).total_seconds().to_numpy() / 86400
            d0 = sc.get("age_j", 24)
            deg = np.where(actif_h, 1 - amp * (d0 - age) / d0, 1.0)
        e = q_ch / ((3.4 + 0.04 * (T - 5)) * deg) + q_ecs / ((2.6 + 0.03 * (T - 5)) * deg)
        out["SIM_PAC_ELEC"] = _par_heure(np.repeat(e / 4, 4) * u_pac, heures)  # électricité cumulée sur l'heure
    else:
        f = u_chal.copy()
        k, ecs = L * 0.22 * (0.6 + 0.4 * occ_h), L * 0.12 * occ_h
        if typ == "vide":
            f = f * HORS_GEL
            if der == "chaleur_vide":
                f = np.where(actif_h, u_chal * amp, f)
        if der == "signature":
            f = np.where(actif_h, f * (1 + amp), f)
        q = pd.Series(k * dh * reduit * f + ecs * f, index=heures)
        pid = CHAUFFAGES[sc.get("chauffage", "chaleur")][0]
        if pid == "SIM_GAZ":  # chaudière : gaz = chaleur ÷ rendement, index en m³ (PCS)
            out[pid] = 5000.0 + (q / RENDEMENT_CHAUDIERE / PCS_GAZ).cumsum()
        else:
            out[pid] = q

    # eau froide (écoulement simulé par 15 min, index lu à l'heure pleine)
    prof = 0.02 + 1.2 * np.exp(-((hq - 7.5) ** 2) / 2) + np.exp(-((hq - 19.5) ** 2) / 3) + 0.4
    nuit_eau = (hq > 1) & (hq <= 5)  # 1 h-5 h : quarts finissant de 01:15 à 05:00
    prof = np.where(nuit_eau, 0.0, prof)
    fac_eau = 0.0 if typ == "vide" else 1.0
    l_h = L * 12.5 * prof * occ_q * fac_eau * (0.15 if travaux else 1.0) * u_eau
    l_h = np.where(nuit_eau & chasse, v_chasse, l_h)
    if der == "fuite":
        l_h = l_h + np.where(actif_q, amp, 0.0)
    if der == "eau_vide":
        l_h = l_h + np.where(actif_q, amp / 24.0, 0.0)
    index = index0 + np.cumsum(l_h / 4 / 1000)
    out["SIM_EAU"] = pd.Series(index[3::4], index=heures)

    pas = sc.get("pas", 60)
    out = {pid: releve(s, "index" if pid in ("SIM_EAU", "SIM_GAZ") else "intervalle", pas) for pid, s in out.items()}
    return out, t_mes, fin


# ---------------------------------------------------------------- défauts de données


def appliquer_defauts(brut, t_mes, fin, defauts, graine):
    """Retire ou altère des mesures (après simulation) : silence, lacunes, blocs de nuit, recul d'index, négatifs."""
    rng = np.random.default_rng([graine, 23])
    brut = dict(brut)
    for d in defauts or ():
        if d.get("point") == "METEO":
            continue  # lacunes de la température : traitées plus bas
        cibles = list(brut) if d.get("point") == "*" else [d["point"]]
        for pid in cibles:
            s = brut[pid]
            if d["type"] == "silence":
                s = s[s.index <= fin - timedelta(hours=d["heures"])]
            elif d["type"] == "lacunes":  # fraction de relevés perdus au hasard sur `jours` jours
                zone = s.index > fin - timedelta(days=d.get("jours", 400))
                perdu = zone & (rng.random(len(s)) < d["taux"])
                s = s[~perdu]
            elif d["type"] == "bloc":  # passerelle hors service de h1 à h2 (UTC) pendant `nuits` nuits
                h = s.index.hour + s.index.minute / 60
                age = (fin - s.index).total_seconds() / 86400
                dans = (age <= d["nuits"]) & ((h > d["h1"]) | (h <= d["h2"]))
                s = s[~dans]
            elif d["type"] == "recul":  # remplacement d'index non déclaré : l'index repart plus bas
                s = s.copy()
                for _ in range(d["n"]):
                    i = rng.integers(len(s) // 4, len(s) - 10)
                    s.iloc[i:] = s.iloc[i:] - d.get("m3", 5.0)
            elif d["type"] == "negatifs":  # valeurs de signe inversé (défaut de décodage)
                s = s.copy()
                pos = rng.choice(np.arange(len(s) // 2, len(s)), size=d["n"], replace=False)
                s.iloc[pos] = -s.iloc[pos].abs() - 0.01
            brut[pid] = s
    for d in defauts or ():
        if d.get("point") == "METEO" and d["type"] == "lacunes":
            zone = t_mes.index > fin - timedelta(days=d.get("jours", 400))
            t_mes = t_mes[~(zone & (rng.random(len(t_mes)) < d["taux"]))]
    return brut, t_mes


# ---------------------------------------------------------------- passage dans Vigie


def _ts(idx):
    return idx.strftime("%Y-%m-%dT%H:%M:%SZ")


def base_temporaire(sc, brut, t_mes, defauts_ref):
    """Base SQLite EN MÉMOIRE (temporaire) : référentiel du scénario + import CSV de toutes les mesures."""
    cx = db.connecter(":memory:")
    ref = {**defauts_ref, "immeubles": [immeuble(sc)]}
    db.charger_referentiel(cx, ref)
    meteo_id = defauts_ref["meteo"]["id"]
    lignes = ["ts,point_id,valeur"]
    for pid, s in list(brut.items()) + [(meteo_id, t_mes)]:
        lignes += [f"{t},{pid},{v:.5f}" for t, v in zip(_ts(s.index), s.to_numpy())]
    ok, rejets, _ = db.importer_mesures(cx, io.StringIO("\n".join(lignes) + "\n"))
    if rejets:
        raise RuntimeError(f"rejets à l'import : {rejets[:3]}")
    return cx


def analyser_base(cx, defauts_ref):
    alertes, fin = MOTEUR.analyser(cx, db.referentiel(cx, defauts_ref))
    return alertes, fin


CHAMPS_ALERTE = ("id", "cause", "gravite", "debut", "persistance", "chiffrage", "periode", "projection",
                 *(f"{g}_{p}" for g in ("kwh", "m3", "chf", "co2_t") for p in ("an", "mois", "mesure", "proj")),
                 "heures_mesurees", "jours_rythme", "reference", "confiance", "mesure", "attendu", "score")


def resume_alerte(a):
    return {k: a.get(k) for k in CHAMPS_ALERTE}


def verite_horaire(sc, graine, meteo, cible):
    """Excès réel heure par heure sur le point visé (fin d'intervalle) : simulation avec dérive − sans dérive, mêmes
    tirages, relevé horaire et sans défaut de données (la vérité ne dépend ni du pas ni des lacunes)."""
    propre = {**sc, "pas": 60, "defauts": None}
    avec, _, fin = simuler(propre, graine, meteo, avec_derive=True)
    sans, _, _ = simuler(propre, graine, meteo, avec_derive=False)
    a, b = avec[cible], sans[cible]
    if cible in ("SIM_EAU", "SIM_GAZ"):  # index : consommation = différence
        a, b = a.diff(), b.diff()
    if cible == "SIM_GAZ":  # le moteur chiffre le gaz en kWh (PCS du référentiel)
        a, b = a * PCS_GAZ, b * PCS_GAZ
    return (a - b).fillna(0.0), fin


def verite_journaliere(sc, graine, meteo, brut_derive=None, cible="SIM_EAU"):
    """Excès réel par jour (étiquettes [J 00:00, J+1 00:00) des heures de fin d'intervalle, comme le moteur)."""
    h, fin = verite_horaire(sc, graine, meteo, cible)
    return h.resample("D").sum(), fin


def executer(sc, graine, meteo, coupes_h=(0,), defauts_ref=None, suivi=False):
    """Simule, importe, puis analyse à plusieurs dates de fin (coupes = heures avant la fin de la série).

    suivi=False : analyses indépendantes (la fin recule). suivi=True : exploitation au fil des jours — les coupes sont
    analysées de la plus ancienne à la plus récente, les mesures arrivent au fur et à mesure et le suivi des alertes
    (bons.synchroniser_alertes) est tenu après chaque analyse, comme dans Vigie.
    Retourne ([{coupe_h, fin, alertes:[...]}], mesures brutes)."""
    from vigie import bons
    brut, t_mes, fin = simuler(sc, graine, meteo)
    brut, t_mes = appliquer_defauts(brut, t_mes, fin, sc.get("defauts"), graine)
    cx = base_temporaire(sc, brut, t_mes, defauts_ref)
    limite = lambda c: (fin - timedelta(hours=c)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    res = []
    try:
        if suivi:
            ordre = sorted(coupes_h, reverse=True)
            cx.execute("CREATE TEMP TABLE stock AS SELECT * FROM mesure")
            cx.execute("DELETE FROM mesure WHERE ts > ?", (limite(ordre[0]),))
            precedente = limite(ordre[0])
            for c in ordre:
                cx.execute("INSERT OR REPLACE INTO mesure SELECT * FROM stock WHERE ts > ? AND ts <= ?",
                           (precedente, limite(c)))
                precedente = limite(c)
                alertes, fin_a = analyser_base(cx, defauts_ref)
                bons.synchroniser_alertes(cx, alertes)
                res.append({"coupe_h": c, "fin": str(fin_a), "alertes": [resume_alerte(a) for a in alertes]})
            res.sort(key=lambda r: r["coupe_h"])
        else:
            for c in sorted(coupes_h):
                if c:
                    cx.execute("DELETE FROM mesure WHERE ts > ?", (limite(c),))
                alertes, fin_a = analyser_base(cx, defauts_ref)
                res.append({"coupe_h": c, "fin": str(fin_a), "alertes": [resume_alerte(a) for a in alertes]})
    finally:
        cx.close()
    return res, brut


def jour_civil(ts):
    return datetime.fromisoformat(str(ts)[:10])
