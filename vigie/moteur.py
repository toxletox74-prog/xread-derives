"""Moteur de détection Vigie : qualité -> attendu -> détecteurs -> impact -> priorisation -> consignes.

Principe : les chiffres (kWh, m3, CHF, CO2) sont TOUJOURS calculés ici, jamais générés par un LLM.
Données : au mieux horaires (un relevé journalier ne sert qu'aux règles journalières), un an d'historique.
Chiffrage : eau et électricité par an (dérive constante) ; chauffage et PAC = excès MESURÉ depuis le début de la
dérive, sans année extrapolée ; rythme par 30 jours pour tous, qui sert à prioriser.
L'attendu utilisé dans ce prototype est statistique et explicable (profil de nuit, signature
énergétique, régression du rendement PAC). Un modèle de prévision (Chronos-2) peut être branché
dans `attendu_chronos()` sans changer le reste du moteur.
"""
import math

import numpy as np
import pandas as pd

from . import calendrier, complements, historique, solaire
from .db import FLUIDES_METEO, PAS_MENSUEL

URGENCE = {"Critique": 3.0, "Élevée": 2.0, "Modérée": 1.0, "Données": 0.0}

# ---------------------------------------------------------------- chargement


PAS_HORAIRE = 60      # pas de temps de référence : les données arrivent au mieux à l'heure (CLAUDE.md §5)
PAS_JOURNALIER = 1440  # relevé journalier : seules les règles journalières peuvent s'en servir


def lire_brut(cx):
    """Points et mesures brutes (horodatage UTC naïf), lus une seule fois : sert à l'analyse et au rejeu."""
    pts = pd.read_sql("SELECT * FROM point_mesure", cx).set_index("id")
    raw = pd.read_sql("SELECT ts, point_id, valeur, qualite FROM mesure", cx)
    if not raw.empty:
        raw["ts"] = pd.to_datetime(raw["ts"], utc=True).dt.tz_localize(None)
    return pts, raw


def charger_series(cx, jusqua=None, brut=None):
    """Séries horaires (fin d'intervalle) des points au pas horaire ou plus fin, et séries journalières des points
    relevés une fois par jour. Retourne (points, horaires, qualité, fin, journalières)."""
    # `jusqua` : seules les mesures jusqu'à cette date sont vues (rejeu) ; `brut` = lire_brut(cx) déjà chargé
    pts, raw = brut if brut is not None else lire_brut(cx)
    if jusqua is not None and not raw.empty:
        raw = raw[raw["ts"] <= jusqua]
    if raw.empty:
        return pts, {}, {}, None, {}
    # Fin des données = dernier relevé d'un COMPTEUR : la météo, mise à jour toutes les 3 h, est souvent plus récente
    # que les relevés importés ; la prendre comme fin ferait paraître tous les compteurs muets.
    compteurs = raw[~raw["point_id"].isin(pts.index[pts["fluide"].isin(FLUIDES_METEO)])]
    fin = (compteurs if not compteurs.empty else raw)["ts"].max()
    series, qualite, journalieres = {}, {}, {}
    for pid, g in raw.groupby("point_id"):
        g = g.sort_values("ts").set_index("ts")
        nature = pts.loc[pid, "nature"]
        pas = float(pts.loc[pid, "pas_min"])
        v = g["valeur"].where(g["qualite"] == "valide")  # ni suspecte, ni estimée par le distributeur (règle 4)
        recul = 0
        if nature == "index":
            d = v.diff()
            recul = int((d < 0).sum())
            # Après un trou de relevés, l'écart d'index cumule toute la consommation du trou : on ne sait pas à
            # quelle heure elle a eu lieu. Elle n'est attribuée à aucune heure (règle 4 : jamais de décision sur
            # une valeur reconstituée). Sinon, une passerelle coupée la nuit simule une fuite.
            ecart = pd.Series(v.index, index=v.index).diff()
            v = d.where((d >= 0) & (ecart <= pd.Timedelta(minutes=1.5 * pas)))
        if nature == "instantane":
            series[pid] = v.resample("h", label="right", closed="right").mean()
        elif pas <= PAS_HORAIRE:
            r = v.resample("h", label="right", closed="right")
            # Heure incomplète (un relevé de l'heure manquant si le pas est plus fin que l'heure) = valeur inconnue,
            # pas une heure sous-estimée (règle 4). Au pas horaire : un relevé par heure.
            series[pid] = r.sum(min_count=1).where(r.count() >= max(1, round(PAS_HORAIRE / pas)))
        elif pas == PAS_JOURNALIER:
            # Relevé journalier : sa consommation couvre 24 heures, elle n'est attribuée à aucune heure (la fuite de
            # nuit, l'électricité de nuit et la PAC sont invisibles à ce pas). Jour = jour de fin d'intervalle - 1 s.
            v = v.dropna()
            journalieres[pid] = v.groupby((v.index - pd.Timedelta(seconds=1)).normalize()).sum(min_count=1)
        # autre pas plus grossier que l'heure : aucune règle ne peut s'en servir (signalé dans la fiche du compteur)
        debut30 = fin - pd.Timedelta(days=30)
        attendu = 30 * 24 * 60 / pas
        recus = (g.index > debut30).sum()
        if pas >= PAS_MENSUEL:  # relevé mensuel : complétude sur 12 mois, depuis le premier relevé du compteur
            debut12 = fin - pd.Timedelta(days=365)
            recus = (g.index > debut12).sum()
            # compteur relevé depuis moins d'un an : son premier relevé, puis un par mois CIVIL écoulé (un mois
            # « moyen » de 30,44 jours attendait un relevé de trop le 31 du mois, la veille de son arrivée)
            premier = g.index.min()
            attendu = 12 if premier <= debut12 else (fin.year - premier.year) * 12 + fin.month - premier.month + 1
        elif g.index.min() > debut30:  # série commencée il y a moins de 30 jours : jugée depuis son premier relevé
            debut_serie = g.index.min() - pd.Timedelta(minutes=pas)
            recus = (g.index > debut_serie).sum()
            attendu = max(1.0, (fin - debut_serie).total_seconds() / 60 / pas)
        qualite[pid] = {
            "derniere": g.index.max(),
            "nature": nature,
            "completude": min(1.0, recus / attendu),
            "index_recule": recul,
            "suspectes": int((g["qualite"] == "suspecte").sum()),
            "pas_min": pas,
        }
        if pts.loc[pid, "fluide"] == "solaire":  # production au-delà de la puissance crête : échelle ou unité fausse
            kwc = pts.loc[pid].get("puissance_crete_kwc")
            qualite[pid]["crete"] = (solaire.crete_depassee(series.get(pid), kwc, debut30), kwc)
            qualite[pid]["natif"] = v  # production au pas du compteur (quart d'heure…) : coupures de l'onduleur
    return pts, series, qualite, fin, journalieres


def jour(s):
    return s.resample("D").sum(min_count=1)


JOUR_HEURES_MIN = 18  # un jour n'est jugé que si au moins 18 heures sur 24 sont mesurées (75 %, comme les nuits)


def jours_mesures(s, fin, journalier=False):
    """Jours complets ou presque (>= JOUR_HEURES_MIN heures mesurées), jour en cours exclu.

    Retourne (somme des heures mesurées, nombre d'heures mesurées). Une heure manquante n'est jamais comblée
    (règle 4) : le seuil journalier est comparé au prorata des heures mesurées, au lieu de juger un jour tronqué
    comme un jour entier (ce qui cassait la persistance dès 2 % de relevés perdus).
    `journalier=True` : `s` est déjà une série de relevés journaliers (24 heures chacun).
    """
    if journalier:
        s = s[(s.index.normalize() < fin.normalize())].dropna()
        return s, pd.Series(24, index=s.index)
    somme, n = s.resample("D").sum(min_count=1), s.resample("D").count()
    garder = (somme.index.normalize() < fin.normalize()) & (n >= JOUR_HEURES_MIN) & somme.notna()
    return somme[garder], n[garder]


def serie_consecutive_fin(cond):
    """Nombre de True consécutifs en fin de série (persistance)."""
    n = 0
    for v in reversed(list(cond)):
        if v:
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------- détecteurs


def det_qualite(pid, q, fin, P):
    out = []
    silence_h = (fin - q["derniere"]).total_seconds() / 3600
    regulier = q.get("nature") != "livraison"  # un bon de livraison n'a pas de rythme : ni silence ni complétude
    # un compteur journalier ou mensuel n'est pas muet entre deux relevés : tolérance d'au moins deux pas de temps
    if regulier and silence_h > max(P["silence_max_heures"], 2 * q.get("pas_min", PAS_HORAIRE) / 60):
        out.append(("donnees_silence", f"Aucune donnée reçue depuis {silence_h / 24:.0f} jours.", silence_h / 24))
    if regulier and q["completude"] < P["completude_min"]:
        out.append(("donnees_completude", f"Seulement {q['completude']:.0%} des mesures attendues reçues sur 30 jours.", None))
    if q["index_recule"]:
        out.append(("donnees_index", f"L'index a reculé {q['index_recule']} fois sans changement de compteur déclaré.", None))
    if q["suspectes"]:
        out.append(("donnees_negatif", f"{q['suspectes']} valeurs négatives rejetées (défaut de décodage ou d'échelle).", None))
    n_crete, kwc = q.get("crete") or (0, None)
    if n_crete:
        crete = f"{kwc:g}".replace(".", ",")
        out.append(("donnees_crete", f"{n_crete} heures de production au-delà de la puissance crête ({crete} kWc) sur "
                                     "30 jours : défaut d'échelle ou d'unité.", None))
    return out


NUIT_HEURES_MIN = 0.75  # part minimale d'heures de nuit mesurées pour juger une nuit (eau)


def det_eau_nuit(s_m3h, P, seuil_l_h=20.0, persistance=3):
    h1, h2 = P["heures_nuit"]
    l_h = s_m3h * 1000
    nuit = l_h[(l_h.index.hour > h1) & (l_h.index.hour <= h2)]
    g = nuit.groupby(nuit.index.date)
    # Une nuit n'est jugée que si au moins 3 heures sur 4 sont mesurées : le minimum d'une nuit lacunaire
    # (ex. passerelle coupée) n'est pas représentatif et simulait une fuite.
    mins = g.min()[g.count() >= math.ceil(NUIT_HEURES_MIN * (h2 - h1))].dropna()
    n = serie_consecutive_fin(mins > seuil_l_h)
    if n < persistance:
        return None
    ref = mins.iloc[-(n + 30):-n].median() if len(mins) > n + 5 else 0.0
    exces_l_h = max(0.0, mins.iloc[-n:].median() - ref)
    return {"persistance": n, "unite": "nuits", "debut": str(mins.index[-n]),
            "mesure": f"{mins.iloc[-n:].median():.0f} l/h", "attendu": f"{ref:.0f} l/h",
            "m3_j": exces_l_h * 24 / 1000, "force": min(1.0, exces_l_h / 100),
            # constaté : la fuite coule en continu ; excès de débit constaté la nuit × heures mesurées depuis le début
            "m3_mesure": exces_l_h * heures_depuis(s_m3h, mins.index[-n]) / 1000,
            "heures_mesurees": heures_depuis(s_m3h, mins.index[-n])}


def det_eau_vide(s_m3h, P, seuil_l_j=50.0, persistance=2, fin=None, journalier=False):
    # Jour en cours exclu (6 h de fuite ne font pas 50 l : la persistance cassait) ; jours lacunaires au prorata
    fin = s_m3h.index.max() if fin is None else fin
    d, nh = jours_mesures(s_m3h * 1000, fin, journalier)
    n = serie_consecutive_fin(d > seuil_l_j * nh / 24)
    if n < persistance:
        return None
    l_j = (d * 24 / nh).iloc[-n:]  # litres par jour ramenés à 24 h (chiffrage)
    return {"persistance": n, "unite": "jours", "debut": str(d.index[-n].date()),
            "mesure": f"{l_j.mean():.0f} l/jour", "attendu": "≈ 0 l/jour",
            "m3_j": l_j.mean() / 1000, "force": 0.8,
            "m3_mesure": float(s_m3h[s_m3h.index >= d.index[-n]].sum()) if not journalier
            else float(s_m3h[(s_m3h.index >= d.index[-n]) & (s_m3h.index.normalize() < fin.normalize())].sum()),
            "heures_mesurees": heures_depuis(s_m3h, d.index[-n]) * (24 if journalier else 1)}


def degres_jours(text_h, base=16.0):
    return (base - text_h).clip(lower=0).resample("D").mean()


# ---------------------------------------------------------------- chiffrage (voir vigie/chiffrage.py)
from .chiffrage import (JOURS_AN, JOURS_MOIS, RYTHME_JOURS_MAX, champs_vides, chiffrage_mesure,  # noqa: E402,F401
                        chiffrer, climat_normal, heures_depuis, projection_par_dj, projection_proportionnelle,
                        seuil_enjeu_mois)
from .chiffrage import score as _score  # noqa: E402


# ---------------------------------------------------------------- période de référence
# Avec un an d'historique, l'attendu du chauffage et de la PAC est appris sur la MÊME SAISON de l'année précédente
# (fenêtre d'analyse décalée d'un an, ± SAISON_MARGE_J jours) complétée par les RECENT_J jours qui précèdent la
# fenêtre (état récent de l'installation). Repli quand cette saison manque (moins d'un an de mesures) : toute la
# période antérieure à la fenêtre, comme avant.
UN_AN = pd.Timedelta(days=365)
SAISON_MARGE_J = 45
RECENT_J = 60
SIGNATURE_JOURS_MIN = 30  # jours jugés nécessaires pour apprendre une signature énergétique

# Abaissement nocturne du chauffage (heures de fin d'intervalle, UTC) : la chaleur par degré est plus faible la nuit.
# Une référence apprise en fin d'été (froid surtout la nuit) sous-estime alors le chauffage de plein hiver (froid
# aussi le jour) : biais mesuré +4 à +10 % sur immeuble sain (campagne d'évaluation). Le modèle sépare donc la part
# de nuit quand la référence contient assez d'heures froides de JOUR pour l'apprendre ; sinon, modèle simple.
NUIT_CHAUFFE = (22, 5)
HEURES_JOUR_FROIDES_MIN = 120  # heures de jour sous 14 °C dans la référence (moitié de PAC_HEURES_CHAUFFE_MIN)


def heures_nuit_chauffe(index):
    return (index.hour >= NUIT_CHAUFFE[0]) | (index.hour < NUIT_CHAUFFE[1])


def jour_froid_suffisant(text_h_ref):
    """La référence contient-elle assez d'heures froides de jour pour distinguer chauffage de jour et de nuit ?"""
    t = text_h_ref.dropna()
    return int(((t < 14) & ~heures_nuit_chauffe(t.index)).sum()) >= HEURES_JOUR_FROIDES_MIN


def limite_reference(fin, P, ref_avant=None):
    """Fin de la période de référence : avant la fenêtre d'analyse, ou avant le début d'une dérive déjà en alerte."""
    limite = fin - pd.Timedelta(days=P["fenetre_analyse_jours"])
    return min(limite, ref_avant) if ref_avant is not None else limite


def periode_reference(index, fin, P, ref_avant=None):
    """Masques (même saison l'an passé, saison + récent, toute la période antérieure) sur un index de jours ou d'heures."""
    limite = limite_reference(fin, P, ref_avant)
    avant = index < limite
    marge = pd.Timedelta(days=SAISON_MARGE_J)
    saison = avant & (index >= limite - UN_AN - marge) & (index <= fin - UN_AN + marge)
    recent = avant & (index >= limite - pd.Timedelta(days=RECENT_J))
    return saison, saison | recent, avant


def choisir_reference(index, fin, P, ref_avant, assez):
    """(masque de référence, mode) : « saison » si la même saison de l'an passé suffit (`assez`), sinon « antérieure »
    (repli). Une référence gelée (alerte ouverte) insuffisante laisse place à la référence habituelle."""
    for gel in ((ref_avant, None) if ref_avant is not None else (None,)):
        saison, saison_recent, avant = periode_reference(index, fin, P, gel)
        if P.get("reference_saison", True) and assez(saison):
            return saison_recent, "saison"
        if assez(avant):
            return avant, "antérieure"
    return None, None


# ---------------------------------------------------------------- chauffage


def _jours_signature(s_kwh, text_h, journalier=False):
    """Par jour : chaleur q, degrés-heures sommés dh / dh_nuit sur les heures où chaleur ET température sont mesurées,
    nombre de ces heures n, et degrés-jours du jour dj / dj_nuit (toutes les heures de température)."""
    dh = (16.0 - text_h).clip(lower=0)
    nuit = heures_nuit_chauffe(dh.index)
    jours_t = pd.DataFrame({"dj": dh.resample("D").mean(), "djn": dh.where(nuit, 0.0).resample("D").mean(),
                            "nt": dh.resample("D").count()})
    if journalier:  # relevé journalier : 24 heures de chaleur, température du jour (au moins JOUR_HEURES_MIN heures)
        j = pd.DataFrame({"q": s_kwh.dropna()}).join(jours_t, how="inner")
        j = j[j["nt"] >= JOUR_HEURES_MIN]
        j["n"], j["dh"], j["dhn"] = 24, 24 * j["dj"], 24 * j["djn"]
        return j
    h = pd.DataFrame({"q": s_kwh, "dh": dh, "dhn": dh.where(nuit, 0.0)}).dropna()
    j = h.resample("D").agg({"q": "sum", "dh": "sum", "dhn": "sum"})
    j["n"] = h["q"].resample("D").count()
    return j[j["n"] > 0].join(jours_t)


DJ_COMPARABLE = 2.0          # écart de degrés-jours toléré pour parler de « météo comparable »
JOURS_COMPARABLES_MIN = 10   # en dessous, la référence ne contient pas cette météo : le jour n'est pas jugé
COTES_MIN = 3                # jours comparables exigés de chaque côté (plus froids, plus doux) du jour jugé
JUGE_RECENT_MAX_J = 10       # dernier jour jugé plus ancien : l'alerte resterait figée sur un constat périmé


def _attendu_comparable(q24, dj_comparables, dj):
    """Attendu d'un jour d'après ses jours comparables, chacun ramené au degré-jour du jour jugé par la pente locale
    (moindres carrés sur ces mêmes jours), puis médiane. Sans cette correction, des comparables en majorité plus doux
    ou plus froids décalaient l'attendu de 5 à 10 % (mesuré : une dérive de +20 % lue +14 % ou +28 %)."""
    pente = 0.0
    if float(np.std(dj_comparables)) >= 0.3:  # degrés-jours assez étalés pour estimer une pente
        pente = max(0.0, float(np.polyfit(dj_comparables, q24, 1)[0]))
    return float(np.median(q24 + pente * (dj - dj_comparables)))


def _recaler_sur_meteo_comparable(j, jours_ref, types=None):
    """Première année de suivi (pas de « même saison l'an passé ») : la droite apprise sur toute la période antérieure
    est fausse hors de la saison qui la domine (apprise de janvier à mai, elle prolonge le chauffage vers zéro et
    sous-estime de moitié la consommation de base de l'été). L'attendu de chaque jour devient donc la consommation des
    JOURNÉES COMPARABLES de la référence : médiane des jours à ± DJ_COMPARABLE degrés-jours, ramenée à 24 h. Il en
    faut de chaque côté (plus froids et plus doux) : à la lisière d'une saison, des comparables tous d'un seul côté
    faussent l'attendu. Sans assez de jours comparables, le jour n'est pas jugé. `types` (calendrier.py) : type de
    chaque jour ; si la référence de l'immeuble y est sensible, un jour n'est comparé qu'à des jours de même type."""
    ref = j.loc[jours_ref]
    q24 = (ref["q"] * 24 / ref["n"]).to_numpy()
    dj_ref = ref["dj"].to_numpy()
    types_ref = None
    if types is not None:
        types = pd.Series(types, index=j.index)
        chauffe = (ref["att"] > 0) & (ref["dj"] >= DJ_COMPARABLE)  # jours de chauffe : la droite météo y a un sens
        if calendrier.sensible((q24 / ref["att"].to_numpy())[chauffe.to_numpy()], types[jours_ref][chauffe].to_numpy()):
            types_ref = types[jours_ref].to_numpy()
    attendus = []
    for i, dj in enumerate(j["dj"].to_numpy()):
        proches = np.abs(dj_ref - dj) <= DJ_COMPARABLE
        masques = ([proches] if types_ref is None
                   else [proches & m for m in calendrier.comparables(types_ref, types.iloc[i])])
        # jamais d'extrapolation : il faut des jours comparables plus froids ET plus doux que le jour jugé. À l'entrée
        # de la saison de chauffe, des comparables tous plus doux sous-estimaient l'attendu (fausse dérive).
        choisi = next((m for m in masques if int(m.sum()) >= JOURS_COMPARABLES_MIN
                       and int((dj_ref[m] <= dj).sum()) >= COTES_MIN and int((dj_ref[m] >= dj).sum()) >= COTES_MIN), None)
        attendus.append(_attendu_comparable(q24[choisi], dj_ref[choisi], dj) if choisi is not None else np.nan)
    att = pd.Series(attendus, index=j.index)
    j["juge"] &= att.notna()
    j["att"] = att.fillna(j["att"])
    j["att_mesure"] = j["att"] * j["n"] / 24


def signature_attendue(s_kwh, text_h, fin, P, ref_avant=None, journalier=False):
    """Chaleur journalière mesurée et attendue à météo égale (signature énergétique apprise AVANT la fenêtre).

    Modèle q = a + b·DJ (+ c·DJ_nuit si la référence le permet), DJ = degrés-jours base 16 °C (moyenne horaire),
    DJ_nuit = part des degrés-jours tombant pendant l'abaissement nocturne. None si la référence est trop courte.
    Une ligne par jour mesuré (jour en cours compris) ; colonnes : q (chaleur des heures mesurées), att_mesure
    (attendu sur ces mêmes heures), att (attendu sur 24 h), n (heures mesurées), juge (jour assez complet et terminé).
    """
    j = _jours_signature(s_kwh, text_h, journalier)
    j["juge"] = (j["n"] >= JOUR_HEURES_MIN) & (j.index.normalize() < fin.normalize())
    juges = j[j["juge"]]
    masque, mode = choisir_reference(juges.index, fin, P, ref_avant, lambda m: int(m.sum()) >= SIGNATURE_JOURS_MIN)
    if masque is None:
        return None
    ref = juges[masque]
    # Ajustement sur les heures mesurées : chaleur(jour) = a·n/24 + b·Σdh/24 (+ c·Σdh_nuit/24) ; pour un jour complet
    # c'est exactement q = a + b·DJ (+ c·DJ_nuit), la signature énergétique habituelle.
    x1 = np.c_[ref["n"] / 24, ref["dh"] / 24]
    (a, b), *_ = np.linalg.lstsq(x1, ref["q"].to_numpy(), rcond=None)
    c = 0.0
    if jour_froid_suffisant(text_h[text_h.index.normalize().isin(ref.index)]):
        x = np.c_[x1, ref["dhn"] / 24]
        (a2, b2, c2), *_ = np.linalg.lstsq(x, ref["q"].to_numpy(), rcond=None)
        if b2 > 0 and -b2 <= c2 <= 0:  # physiquement plausible : la nuit chauffe moins par degré, jamais en négatif
            a, b, c = a2, b2, c2
    # attendu sur les heures mesurées (q = a + b·DJ + c·DJ_nuit, réparti heure par heure) et sur la journée entière
    j["att_mesure"] = (a * j["n"] + b * j["dh"] + c * j["dhn"]) / 24
    j["att"] = a + b * j["dj"] + c * j["djn"]
    if mode == "antérieure":
        _recaler_sur_meteo_comparable(j, ref.index, calendrier.classes(j.index, P.get("calendrier")))
    j.attrs["modele"] = (float(a), float(b), float(c))  # chaleur/jour = a + b·DJ + c·DJ_nuit
    j.attrs["reference"] = mode
    return j


def det_chaleur_signature(s_kwh, text_h, fin, P, seuil=1.10, persistance=7, ref_avant=None, journalier=False):
    """Signature énergétique (chaleur produite, chaleur livrée par le CAD ou énergie du gaz : même méthode)."""
    tout = signature_attendue(s_kwh, text_h, fin, P, ref_avant, journalier)
    if tout is None:
        return None
    df = tout[tout["juge"]]
    if df.empty or (fin.normalize() - df.index[-1]).days > JUGE_RECENT_MAX_J:
        return None  # plus aucun jour jugeable récemment (pas de météo comparable en référence) : pas de conclusion
    ratio = df["q"] / df["att_mesure"].clip(lower=df["n"] / 24)  # mesuré / attendu sur les mêmes heures
    n = serie_consecutive_fin(ratio > seuil)
    if n < persistance:
        return None
    der = df.iloc[-n:]
    exces_24h = (ratio.iloc[-n:] - 1) * der["att"]  # excès relatif × attendu d'une journée entière
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
            "mesure": f"{(ratio.iloc[-n:].mean() - 1) * 100:+.0f} %",
            "attendu": f"{der['att'].mean():.0f} kWh/jour à météo égale",
            "force": min(1.0, (ratio.iloc[-n:].mean() - 1) * 4), "reference": tout.attrs["reference"],
            **chiffrage_mesure(tout["q"] - tout["att_mesure"], tout["n"], der.index[0], exces_24h),
            # projection (hypothèse, jamais déclencheur) : excès relatif constaté × année normale du modèle appris
            "kwh_proj": projection_proportionnelle(der["q"].sum() / der["att_mesure"].sum() - 1, *tout.attrs["modele"], P)}


def det_chaleur_vide(s_kwh, talon, fin, P=None, facteur=1.5, persistance=2, journalier=False, text_h=None):
    d, nh = jours_mesures(s_kwh, fin, journalier)
    n = serie_consecutive_fin(d > talon * facteur * nh / 24)
    if n < persistance:
        return None
    der = (d * 24 / nh).iloc[-n:]  # kWh par jour ramenés à 24 h (rythme)
    # Excès mesuré heure par heure au-dessus du talon hors-gel déclaré (talon / 24 par heure mesurée)
    if journalier:
        exces_jour, heures_jour = d - talon, nh
    else:
        h = s_kwh.dropna()
        exces_jour, heures_jour = (h - talon / 24).resample("D").sum(), h.resample("D").count()
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
            "mesure": f"{der.mean():.0f} kWh/jour", "attendu": f"{talon:.0f} kWh/jour au maximum en hors-gel",
            "force": 1.0, **chiffrage_mesure(exces_jour, heures_jour, der.index[0], der - talon),
            "kwh_proj": None if text_h is None else projection_par_dj(der - talon, degres_jours(text_h).reindex(der.index), P)}


# ---------------------------------------------------------------- électricité


def det_elec_nuit(s_kwh, fin, P, seuil=1.20, persistance=3, ref_avant=None, text_h=None):
    h1, h2 = P["heures_nuit"]
    kw = s_kwh  # kWh par heure = kW moyen
    detect = kw[(kw.index.hour > h1) & (kw.index.hour <= h2)]
    nuits = detect.groupby(detect.index.date).mean().dropna()
    large = kw[(kw.index.hour > 22) | (kw.index.hour <= 6)]
    cle = [(t - pd.Timedelta(hours=7)).date() for t in large.index]  # nuit 22h-6h rattachée à sa veille
    nuits_large = large.groupby(cle).mean()
    if text_h is not None:  # site dont la nuit suit le froid (PAC, chauffage électrique) : à température égale
        sensible, r = complements.elec_nuit_meteo(nuits, large, text_h, fin, P, seuil, persistance, ref_avant)
        if sensible:
            return r
    dates = pd.to_datetime(pd.Series(nuits.index))
    fin_ref, debut_ref = fin - pd.Timedelta(days=20), fin - pd.Timedelta(days=50)
    if ref_avant is not None and ref_avant < fin_ref:  # alerte ouverte : nuits de référence gelées avant la dérive
        fin_ref, debut_ref = ref_avant, ref_avant - pd.Timedelta(days=30)
        if not ((dates < fin_ref) & (dates >= debut_ref)).any():
            fin_ref, debut_ref = fin - pd.Timedelta(days=20), fin - pd.Timedelta(days=50)
    ref_mask = ((dates < fin_ref) & (dates >= debut_ref)).values
    ref = nuits[ref_mask].median()
    if not ref or np.isnan(ref):
        return None
    n = serie_consecutive_fin(nuits / ref > seuil)
    if n < persistance:
        return None
    nl = pd.Series(nuits_large.values, index=pd.to_datetime(nuits_large.index))
    ref_l = nl[(nl.index < fin_ref) & (nl.index >= debut_ref)].median()
    exces_kw = max(0.0, nl.iloc[-n:].mean() - ref_l)
    return {"persistance": n, "unite": "nuits", "debut": str(nuits.index[-n]),
            "mesure": f"{nuits.iloc[-n:].mean():.1f} kW".replace(".", ","), "attendu": f"{ref:.1f} kW".replace(".", ","),
            "kwh_j": exces_kw * 8, "delta_kw": exces_kw, "force": min(1.0, exces_kw / 2),
            "kwh_mesure": exces_kw * heures_depuis(large, pd.Timestamp(nuits.index[-n]) - pd.Timedelta(hours=2)),
            "heures_mesurees": heures_depuis(large, pd.Timestamp(nuits.index[-n]) - pd.Timedelta(hours=2))}


# ---------------------------------------------------------------- pompe à chaleur

PAC_HEURES_REF_MIN = 20 * 24   # au moins 20 jours d'heures de fonctionnement dans la référence


PAC_HEURES_CHAUFFE_MIN = 240   # heures froides (T < 14 °C) nécessaires pour apprendre une part chauffage non comptée
PAC_JOUR_MIN_KWH = 1.0         # jour sans fonctionnement significatif de la PAC : non jugé


def _x_pac(h, flux, nuit=False):
    """Variables explicatives de l'électricité horaire de la PAC, selon les compteurs de chaleur disponibles.

    L'électricité d'une PAC ≈ chaleur / rendement, et 1/rendement varie à peu près linéairement avec la
    température extérieure : chaque flux de chaleur MESURÉ q apporte les termes q et q·T. Une part non mesurée est
    représentée par ce qui la gouverne : un niveau de base pour l'eau chaude, les degrés-heures pour le chauffage.
    """
    t = h["t"]
    dh = (16.0 - t).clip(lower=0)  # degrés-heures, base 16 °C comme la signature énergétique
    x = {}
    for nom in flux:
        x[nom], x[nom + "·T"] = h[nom], h[nom] * t
    if "totale" not in flux and "ecs" not in flux:
        x["base eau chaude"] = pd.Series(1.0, index=h.index)
    if "totale" not in flux and "chauffage" not in flux:
        x["chauffage"], x["chauffage·T"] = dh, dh * t
        if nuit:  # abaissement nocturne : coefficient propre aux heures de nuit (voir NUIT_CHAUFFE)
            n = heures_nuit_chauffe(h.index).astype(float)
            x["chauffage nuit"], x["chauffage nuit·T"] = dh * n, dh * t * n
    return pd.DataFrame(x)


def pac_attendu(s_elec, flux, text_h, fin, P, ref_avant=None):
    """Électricité PAC journalière mesurée et attendue (modèle horaire appris avant la fenêtre). None = pas de conclusion.

    Une ligne par jour mesuré (jour en cours compris) ; juge = jour terminé où la PAC a fonctionné."""
    h = pd.DataFrame({"e": s_elec, "t": text_h, **flux}).dropna()
    h = h[h["e"] >= 0]
    chauffage_estime = "totale" not in flux and "chauffage" not in flux
    ok = lambda r: len(r) >= PAC_HEURES_REF_MIN and not (  # noqa: E731
        chauffage_estime and (r["t"] < 14).sum() < PAC_HEURES_CHAUFFE_MIN)
    masque, mode = choisir_reference(h.index, fin, P, ref_avant, lambda m: ok(h[m]))
    if masque is None:
        return None  # référence trop courte, ou trop peu d'heures froides pour apprendre le chauffage non compté
    ref = h[masque]
    nuit = chauffage_estime and jour_froid_suffisant(ref["t"])
    x_ref = _x_pac(ref, flux, nuit)
    coef, *_ = np.linalg.lstsq(x_ref.to_numpy(), ref["e"].to_numpy(), rcond=None)
    h["e_att"] = (_x_pac(h, flux, nuit).to_numpy() @ coef).clip(min=0)
    cols = {"e": "sum", "e_att": "sum", **{k: "sum" for k in flux}}
    d = h.resample("D").agg(cols)
    d["n"] = h["e"].resample("D").count()
    d = d[d["n"] > 0].copy()
    d["juge"] = (d["e_att"] > PAC_JOUR_MIN_KWH) & (d.index.normalize() < fin.normalize())  # jour en cours exclu
    d.attrs["reference"] = mode
    # Électricité attendue d'une PAC saine selon le climat (jours complets) : e_att(jour) ≈ u + v·DJ (projection)
    dj = (16.0 - h["t"]).clip(lower=0).resample("D").mean().reindex(d.index)
    complets = d["juge"] & (d["n"] == 24) & dj.notna()
    if int(complets.sum()) >= 30:
        (u, v), *_ = np.linalg.lstsq(np.c_[np.ones(int(complets.sum())), dj[complets]], d.loc[complets, "e_att"].to_numpy(),
                                     rcond=None)
        d.attrs["climat"] = (float(u), float(v))
    return d


def det_pac(s_elec, flux, text_h, fin, P, seuil=0.85, persistance=7, ref_avant=None):
    """Consommation électrique de la PAC comparée à l'attendu, heure par heure, à météo (et production) égales.

    `flux` = chaleurs mesurées disponibles parmi {"totale", "chauffage", "ecs"} (séries horaires, kWh). Selon le
    comptage de l'immeuble : chaleur totale, seulement le chauffage, seulement l'eau chaude, ou aucun compteur de
    chaleur (signature électrique selon la météo). Le modèle est appris sur la période de référence (même saison de
    l'an passé + récent, sinon période antérieure à la fenêtre d'analyse), au pas horaire : la température de l'heure
    où la chaleur est produite compte (une moyenne journalière mélangerait l'eau chaude d'été et le chauffage par
    temps froid et masquerait la dérive).
    Par jour : électricité attendue / électricité mesurée ; sous `seuil` pendant `persistance` jours = dérive.
    """
    tout = pac_attendu(s_elec, flux, text_h, fin, P, ref_avant)
    if tout is None:
        return None
    d = tout[tout["juge"]]
    ratio = d["e_att"] / d["e"]
    n = serie_consecutive_fin(ratio < seuil)
    if n < persistance:
        return None
    der = d.iloc[-n:]
    r = {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
         "force": min(1.0, (1 - ratio.iloc[-n:].mean()) * 3), "reference": tout.attrs["reference"],
         **chiffrage_mesure(tout["e"] - tout["e_att"], tout["n"], der.index[0],
                            (der["e"] - der["e_att"]) * 24 / der["n"]),
         "kwh_proj": projection_proportionnelle(der["e"].sum() / der["e_att"].sum() - 1, *tout.attrs["climat"], 0.0, P)
         if "climat" in tout.attrs else None}
    if "totale" in flux:  # chaleur totale comptée : le rendement réel se calcule
        q = der["totale"].sum()
        r.update(mesure=f"un rendement de {q / der['e'].sum():.1f}".replace(".", ","),
                 attendu=f"{q / der['e_att'].sum():.1f} à météo égale".replace(".", ","))
    else:
        base = "à météo et chaleur mesurée égales" if flux else "à météo égale"
        r.update(titre="PAC : consommation électrique en hausse",
                 mesure=f"{der['e'].mean():.0f} kWh d'électricité par jour",
                 attendu=f"{der['e_att'].mean():.0f} kWh par jour {base}")
    return r


def attendu_chronos(serie_horaire, horizon_h, covariables=None):
    """Point d'extension : prévision Chronos-2 (amazon/chronos-2, Apache 2.0).

    pip install chronos-forecasting  (puis téléchargement du modèle, hors ligne ensuite)
    Retourner un DataFrame indexé comme l'horizon avec les colonnes p05, p50, p95.
    Non utilisé par défaut : le prototype reste exécutable sans GPU ni téléchargement.
    """
    raise NotImplementedError


# Textes et réglages par défaut des règles : vigie/regles.py (réexportés ici)
from .regles import GRAVITES, METIER_DONNEES, METIERS, PROFILS, REGLES, TEXTES, TEXTES_DONNEES  # noqa: E402,F401

FLUIDES_CHAUFFAGE = ("chaleur", "cad", "gaz")  # fluide du point = préfixe des causes signature et immeuble vide
GAZ_PCS_DEFAUT = None  # sans pouvoir calorifique déclaré, un compteur de gaz en m³ n'est pas converti (pas d'alerte énergie)

# ---------------------------------------------------------------- moteur


def regles_effectives(ref):
    """Règles par défaut (REGLES + TEXTES) complétées par les réglages du gestionnaire (ref['regles'])."""
    reglages = ref.get("regles") or {}
    out = {}
    for cause, defaut in REGLES.items():
        r = {**TEXTES[cause], **defaut}
        r.update({k: v for k, v in (reglages.get(cause) or {}).items() if v is not None})
        r["profils"] = list(r["profils"])
        out[cause] = r
    return out


def references_gelees(cx):
    """Alertes OUVERTES (hors « fausse alerte » du gestionnaire) -> date de début de la dérive.

    Tant qu'une dérive est en alerte, sa référence reste celle d'AVANT son début : sinon, après 30 à 50 jours, la
    dérive entre dans la période de référence, devient « normale » et l'alerte passe à tort à « résolue » alors que
    rien n'a été réparé (mesuré : perte de l'alerte vers 33 à 37 jours). Une alerte jugée « fausse alerte » n'est
    pas gelée : le nouveau niveau est alors accepté comme référence. Le gel déjà appliqué (`reference_gelee`, porté
    par l'alerte) prime sur son début recalculé : la référence ne glisse pas vers une dérive qui a faibli puis repris.
    """
    import json
    import sqlite3
    try:
        lignes = cx.execute("SELECT id, donnees FROM alerte WHERE statut = 'ouverte' "
                            "AND (retour IS NULL OR retour != 'fausse_alerte')").fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for aid, donnees in lignes:
        try:
            alerte = json.loads(donnees)
            debut = alerte.get("reference_gelee") or alerte.get("debut")
            if debut:
                out[aid] = pd.Timestamp(str(debut)[:10])
        except (ValueError, TypeError):
            continue
    return out


def convertir_gaz(pts, series, journ, P):
    """Compteurs de gaz en m³ -> kWh (PCS du référentiel, `gaz_pcs_kwh_par_m3`). Sans PCS : série retirée (aucune
    alerte énergie sur une unité non convertie ; la qualité des données reste contrôlée)."""
    pcs = P.get("gaz_pcs_kwh_par_m3", GAZ_PCS_DEFAUT)
    for pid in pts.index[(pts["fluide"] == "gaz") & (pts["unite"] == "m3")]:
        for d in (series, journ):
            if pid in d:
                if pcs:
                    d[pid] = d[pid] * float(pcs)
                else:
                    d.pop(pid)


def analyser(cx, ref, jusqua=None, brut=None, gelees=None):
    """Analyse à la fin des relevés. Rejeu : `jusqua` (date vue comme « aujourd'hui »), `brut` (mesures déjà lues)
    et `gelees` (débuts des dérives en alerte à cette date, à la place des alertes ouvertes de la base)."""
    P = {**ref["parametres"], "calendrier": calendrier.lire(cx)}  # jours ouvrés et vacances du lot, s'il y en a
    tarifs, co2 = ref["tarifs"], ref["facteurs_co2_kg_par_kwh"]
    R = regles_effectives(ref)
    brut = brut if brut is not None else lire_brut(cx)
    pts, series, qualite, fin, journ = charger_series(cx, jusqua, brut)
    # Rejeu : un compteur dont le premier relevé est postérieur à la date rejouée n'était pas encore relevé ce
    # jour-là. Il n'est pas « muet » (aucune alerte Données), et aucune règle ne tourne sur lui faute de mesures.
    pas_encore_releves = set(brut[1]["point_id"].unique()) - set(qualite) if jusqua is not None else set()
    if fin is None:
        return [], None
    gelees = references_gelees(cx) if gelees is None else gelees
    convertir_gaz(pts, series, journ, P)
    meteo_id = (ref.get("meteo") or {}).get("id")
    text_h = series.get(meteo_id)
    ray_h = series.get((ref.get("rayonnement") or {}).get("id"))  # rayonnement global (W/m²) : solaire
    mensuelles = historique.series_mensuelles(*brut, jusqua)  # gaz et PAC par mois civil (historique du même mois)
    dj_mois = historique.contexte(cx, text_h, ray_h)  # degrés-jours, rayonnement et changements d'installation
    alertes, points_en_defaut = [], set()

    # 1. Qualité des données d'abord : un point défaillant ne produit pas d'alerte énergie
    for im in ref["immeubles"]:
        for p in im["points"]:
            q = qualite.get(p["id"])
            if q is None and p["id"] in pas_encore_releves:
                continue
            if q is None:
                alertes.append(_alerte_donnees(im, p, "donnees_silence", "Aucune donnée reçue.", fin))
                points_en_defaut.add(p["id"])
                continue
            defauts = det_qualite(p["id"], q, fin, P)
            if defauts:  # une seule alerte par point, tous les constats regroupés
                constat = " ".join(c for _, c, _ in defauts)
                alertes.append(_alerte_donnees(im, p, defauts[0][0], constat, fin))
                points_en_defaut.add(p["id"])

    # 2. Détecteurs métier, selon le profil du lieu et les règles réglées par le gestionnaire.
    # Point horaire : toutes les règles. Point journalier : seulement les règles journalières (eau et chauffage d'un
    # immeuble vide, signature de chauffage) ; fuite de nuit, électricité de nuit et PAC demandent le pas horaire.
    for im in ref["immeubles"]:
        # un fluide relevé à deux pas (registre mensuel et courbe fine) : la série la plus fine est analysée
        ids = {p["fluide"]: p["id"] for p in sorted(im["points"], key=lambda p: -p["pas_min"])}
        valide = lambda f: f in ids and ids[f] not in points_en_defaut  # noqa: E731
        ok = lambda f: valide(f) and ids[f] in series  # noqa: E731
        jour_ok = lambda f: ok(f) or (valide(f) and ids[f] in journ)  # noqa: E731
        serie_j = lambda f: (series[ids[f]], False) if ok(f) else (journ[ids[f]], True)  # noqa: E731
        actif = lambda c: R[c]["active"] and im["profil"] in R[c]["profils"]  # noqa: E731
        gel = lambda c: gelees.get(f"{im['id']}-{c}")  # noqa: E731  début d'une dérive déjà en alerte (référence gelée)
        cand = []
        if ok("eau") and actif("eau_nuit"):
            r = R["eau_nuit"]
            cand.append(("eau_nuit", ids["eau"], det_eau_nuit(series[ids["eau"]], P, r["seuil"], r["persistance"])))
        if jour_ok("eau") and actif("eau_vide"):
            r, (s, jr) = R["eau_vide"], serie_j("eau")
            cand.append(("eau_vide", ids["eau"], det_eau_vide(s, P, r["seuil"], r["persistance"], fin, jr)))
        for fl in FLUIDES_CHAUFFAGE:  # chaleur produite, chaleur livrée par le CAD, énergie du gaz
            cv, cs = f"{fl}_vide", f"{fl}_signature"
            # Sans talon hors-gel déclaré, pas de seuil inventé : la règle ne tourne pas (signalé dans la fiche immeuble)
            if jour_ok(fl) and actif(cv) and im.get("talon_horsgel_kwh_j"):
                r, (s, jr) = R[cv], serie_j(fl)
                cand.append((cv, ids[fl], det_chaleur_vide(
                    s, im["talon_horsgel_kwh_j"], fin, P, r["seuil"], r["persistance"], jr, text_h)))
            if jour_ok(fl) and actif(cs) and text_h is not None:
                r, (s, jr) = R[cs], serie_j(fl)
                cand.append((cs, ids[fl], det_chaleur_signature(
                    s, text_h, fin, P, 1 + r["seuil"] / 100, r["persistance"], gel(cs), jr)))
        if ok("electricite") and actif("elec_nuit"):
            r = R["elec_nuit"]
            cand.append(("elec_nuit", ids["electricite"], det_elec_nuit(
                series[ids["electricite"]], fin, P, 1 + r["seuil"] / 100, r["persistance"], gel("elec_nuit"), text_h)))
        if ok("pac_electricite") and actif("pac_cop") and text_h is not None:
            # Chaleurs PAC disponibles et fiables : totale, ou seulement chauffage et/ou eau chaude, ou aucune
            flux = {nom: series[ids[f]] for nom, f in (("totale", "pac_chaleur"), ("chauffage", "pac_chaleur_chauffage"),
                                                       ("ecs", "pac_chaleur_ecs")) if ok(f)}
            if "totale" in flux:
                flux = {"totale": flux["totale"]}  # la totale contient déjà chauffage et eau chaude
            r = R["pac_cop"]
            cand.append(("pac_cop", ids["pac_electricite"], det_pac(
                series[ids["pac_electricite"]], flux, text_h, fin, P, 1 - r["seuil"] / 100, r["persistance"], gel("pac_cop"))))
        regles_pv = {c: R[c] for c in solaire.CAUSES if actif(c)}
        if jour_ok("solaire") and regles_pv and ray_h is not None:
            # Production solaire à ensoleillement égal ; référence gelée au début d'une alerte solaire encore ouverte
            point = next(p for p in im["points"] if p["id"] == ids["solaire"])
            gels = [g for g in (gel(c) for c in solaire.CAUSES) if g is not None]
            # une alerte solaire déjà ouverte garde sa qualification (panne ou dégradation) tant qu'elle persiste
            ouverte = next((c for c in solaire.CAUSES if gel(c) is not None), None)
            res = solaire.det_solaire(serie_j("solaire")[0], ray_h, text_h, fin, P, point, regles_pv,
                                      min(gels) if gels else None, ouverte, serie_j("solaire")[1])
            if res:
                cand.append((res[0], ids["solaire"], res[1]))
        if ok("solaire") and actif(solaire.CAUSE_ONDULEUR) and ray_h is not None:
            # Onduleur : production à zéro entre deux relevés producteurs, du lever au coucher du soleil (station météo)
            r, point = R[solaire.CAUSE_ONDULEUR], next(p for p in im["points"] if p["id"] == ids["solaire"])
            cand.append((solaire.CAUSE_ONDULEUR, ids["solaire"], solaire.det_onduleur(
                qualite[ids["solaire"]].get("natif", series[ids["solaire"]]), ray_h, fin, point, r["seuil"], r["persistance"])))
        if valide("eau") and not ok("eau") and ids["eau"] in journ and actif("eau_talon"):  # eau relevée au jour seulement
            r = R["eau_talon"]
            cand.append(("eau_talon", ids["eau"], complements.det_eau_talon(
                journ[ids["eau"]], fin, P, r["seuil"], r["persistance"], True, gel("eau_talon"))))
        if ok("cad_temperature_retour") and ok("cad_temperature_aller") and actif("cad_retour") and text_h is not None:
            r = R["cad_retour"]
            cand.append(("cad_retour", ids["cad_temperature_retour"], complements.det_cad_retour(
                series[ids["cad_temperature_aller"]], series[ids["cad_temperature_retour"]], text_h, fin, P,
                r["seuil"], r["persistance"], gel("cad_retour"))))
        if ok("solaire") and ok("electricite_injection"):  # défaut de données : injection nulle malgré la production
            constat = complements.det_injection_nulle(series[ids["solaire"]], series[ids["electricite_injection"]], fin, P)
            if constat:
                point = next(p for p in im["points"] if p["id"] == ids["electricite_injection"])
                alertes.append(_alerte_donnees(im, point, "donnees_injection", constat, fin))
        cand += complements.regles_au_jour(ids, journ, series, text_h, fin, P, R, actif, gel, valide)
        for fl, cause in historique.FLUIDES.items():  # même mois des années précédentes (relevé mensuel)
            if actif(cause):
                cand.append((cause, *historique.candidat(im, fl, mensuelles, points_en_defaut, dj_mois, fin, P,
                                                         R[cause], gel(cause))))
        trouvees = {cause for cause, _pid, res in cand if res}
        for cause, pid, res in cand:
            if res and not historique.doublon(cause, trouvees):
                a = _alerte_metier(im, pid, cause, res, qualite[pid], R[cause], tarifs, co2, P)
                if gel(cause) is not None:  # gel appliqué : gardé tel quel par les analyses suivantes
                    a["reference_gelee"] = str(pd.Timestamp(gel(cause)).date())
                alertes.append(a)

    # 3. Filtre d'enjeu minimal sur le rythme mensuel (sauf sinistre et données), puis priorisation
    seuil = seuil_enjeu_mois(P)
    alertes = [a for a in alertes if a["gravite"] == "Données" or a["sinistre"] or a["chf_mois"] >= seuil
               or TEXTES.get(a["cause"], {}).get("non_chiffre")]  # dérive sans kWh (retour du CAD) : jamais masquée
    for a in alertes:
        a["score"] = _score(a, URGENCE)
    alertes.sort(key=lambda a: (a["gravite"] == "Données", -a["score"]))
    for i, a in enumerate(alertes, 1):
        a["rang"] = i
    return alertes, fin


def _base(im):
    return {"immeuble_id": im["id"], "immeuble": im["nom"], "adresse": f"{im['adresse']}, {im['npa']}", "profil": im["profil"]}


def _alerte_donnees(im, p, cause, constat, fin):
    a = _base(im)
    # Identifiant stable par compteur : un compteur muet qui devient incomplet reste UNE alerte (règle 6)
    a.update(id=f"{im['id']}-donnees-{p['id']}", point_id=p["id"], cause=cause, fluide=p["libelle"], gravite="Données",
             titre=TEXTES_DONNEES[cause] + " — " + p["libelle"], constat=constat,
             consigne=f"Contrôler la chaîne de mesure ({p['source']}). Aucune alerte énergie n'est calculée sur ce point tant que les données manquent.",
             prestataire="Prestataire de télérelève", metier=METIER_DONNEES, delai="1 semaine", payeur="—", sinistre=False,
             persistance=None, debut=None, confiance=1.0, chiffrage=None, periode=None, projection=None,
             **champs_vides(0))
    return a


def _alerte_metier(im, pid, cause, r, q, t, tarifs, co2, P):
    a = _base(im)
    duree_j = r.get("persistance_jours", r["persistance"])  # règle mensuelle : persistance comptée en jours ici
    conf = 0.6 + min(0.2, 0.04 * (duree_j - P["persistance_min_jours"])) + 0.15 * r["force"]
    conf = min(0.97, conf) * min(1.0, q["completude"] / 0.97)
    a.update(id=f"{im['id']}-{cause}", point_id=pid, cause=cause, fluide=t["fluide"], gravite=t["gravite"],
             titre=r.get("titre", t["titre"]), constat=t["constat"].format(**r), consigne=t["consigne"],
             prestataire=t["prestataire"], metier=t["metier"], delai=t["delai"], payeur=t["payeur"],
             sinistre=t["sinistre"],
             persistance=f"{r['persistance']} {r['unite']}", debut=r["debut"],
             confiance=round(conf, 2), mesure=r["mesure"], attendu=r["attendu"], reference=r.get("reference"),
             **chiffrer(cause, r, tarifs, co2))
    return a
