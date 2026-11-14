"""Chargement des mesures : lecture brute, préparation par compteur, séries horaires et journalières à une date.

Ce qui ne dépend que du passé d'un compteur (tri des relevés, valeurs valides, écarts d'index, seaux horaires) est
préparé UNE fois par lecture de la base, puis tronqué à la date vue (`jusqua`) : un rejeu ne refait plus ce travail
à chaque date. Le résultat est celui d'une base qui ne contiendrait que les mesures jusqu'à cette date : aucune
valeur postérieure n'y entre (règles 4 et 7), et tout ce qui se mesure par rapport à la fin des relevés (complétude,
silence) est recalculé à chaque date.
"""
import numpy as np
import pandas as pd

from . import solaire
from .db import FLUIDES_METEO, PAS_MENSUEL

PAS_HORAIRE = 60      # pas de temps de référence : les données arrivent au mieux à l'heure (CLAUDE.md §5)
PAS_JOURNALIER = 1440  # relevé journalier : seules les règles journalières peuvent s'en servir


class Brut(tuple):
    """(points, mesures) lus en base : se déballe comme un couple, et garde ce qui en est préparé une seule fois."""

    def __new__(cls, pts, raw):
        brut = super().__new__(cls, (pts, raw))
        brut.prepare = {}
        return brut


def une_fois(brut, cle, fonction):
    """`fonction(points, mesures)`, calculée une seule fois par lecture de la base (à chaque appel pour un simple
    couple (points, mesures), qui ne garde rien)."""
    if not isinstance(brut, Brut):
        return fonction(*brut)
    if cle not in brut.prepare:
        brut.prepare[cle] = fonction(*brut)
    return brut.prepare[cle]


def lire_brut(cx):
    """Points et mesures brutes (horodatage UTC naïf), lus une seule fois : sert à l'analyse et au rejeu."""
    pts = pd.read_sql("SELECT * FROM point_mesure", cx).set_index("id")
    raw = pd.read_sql("SELECT ts, point_id, valeur, qualite FROM mesure", cx)
    if not raw.empty:
        raw["ts"] = pd.to_datetime(raw["ts"], utc=True).dt.tz_localize(None)
    return Brut(pts, raw)


def _par_compteur(pts, raw):
    """{compteur: relevés triés et grandeurs qui ne dépendent que de son passé}, quelle que soit la date vue."""
    out = {}
    for pid, g in raw.groupby("point_id"):
        g = g.sort_values("ts").set_index("ts")
        nature = pts.loc[pid, "nature"]
        pas = float(pts.loc[pid, "pas_min"])
        v = g["valeur"].where(g["qualite"] == "valide")  # ni suspecte, ni estimée par le distributeur (règle 4)
        recule = None
        if nature == "index":
            d = v.diff()
            recule = (d < 0).to_numpy()
            # Après un trou de relevés, l'écart d'index cumule toute la consommation du trou : on ne sait pas à
            # quelle heure elle a eu lieu. Elle n'est attribuée à aucune heure (règle 4 : jamais de décision sur
            # une valeur reconstituée). Sinon, une passerelle coupée la nuit simule une fuite.
            ecart = pd.Series(v.index, index=v.index).diff()
            v = d.where((d >= 0) & (ecart <= pd.Timedelta(minutes=1.5 * pas)))
        out[pid] = {"ts": g.index, "v": v, "nature": nature, "pas": pas, "recule": recule,
                    "suspecte": (g["qualite"] == "suspecte").to_numpy(), "horaire": None}
    return out


def points_releves(brut):
    """Compteurs qui ont au moins un relevé en base, toutes dates confondues."""
    return set(une_fois(brut, "compteurs", _par_compteur))


def _seaux_horaires(v, nature, pas):
    if nature == "instantane":
        return v.resample("h", label="right", closed="right").mean()
    r = v.resample("h", label="right", closed="right")
    # Heure incomplète (un relevé de l'heure manquant si le pas est plus fin que l'heure) = valeur inconnue,
    # pas une heure sous-estimée (règle 4). Au pas horaire : un relevé par heure.
    return r.sum(min_count=1).where(r.count() >= max(1, round(PAS_HORAIRE / pas)))


def _horaire(c, k):
    """Série horaire (fin d'intervalle) des `k` premiers relevés du compteur."""
    if c["horaire"] is None:
        c["horaire"] = _seaux_horaires(c["v"], c["nature"], c["pas"])
    ts = c["ts"]
    if k == len(ts):
        return c["horaire"]
    limite = ts[k - 1].ceil("h")  # dernière heure vue
    if ts[k] <= limite:  # la date vue coupe cette heure : son seau est refait avec les seuls relevés vus
        return _seaux_horaires(c["v"].iloc[:k], c["nature"], c["pas"])
    return c["horaire"].loc[:limite]


def charger_series(cx, jusqua=None, brut=None):
    """Séries horaires (fin d'intervalle) des points au pas horaire ou plus fin, et séries journalières des points
    relevés une fois par jour. Retourne (points, horaires, qualité, fin, journalières)."""
    # `jusqua` : seules les mesures jusqu'à cette date sont vues (rejeu) ; `brut` = lire_brut(cx) déjà chargé
    brut = brut if brut is not None else lire_brut(cx)
    pts = brut[0]
    vus = {}  # compteur -> (préparation, nombre de relevés vus à cette date), compteurs sans relevé vu écartés
    for pid, c in une_fois(brut, "compteurs", _par_compteur).items():
        k = np.int64(len(c["ts"])) if jusqua is None else c["ts"].searchsorted(pd.Timestamp(jusqua), side="right")
        if k:
            vus[pid] = (c, k)
    if not vus:
        return pts, {}, {}, None, {}
    # Fin des données = dernier relevé d'un COMPTEUR : la météo, mise à jour toutes les 3 h, est souvent plus récente
    # que les relevés importés ; la prendre comme fin ferait paraître tous les compteurs muets.
    meteo = set(pts.index[pts["fluide"].isin(FLUIDES_METEO)])
    fin = max([c["ts"][k - 1] for pid, (c, k) in vus.items() if pid not in meteo]
              or [c["ts"][k - 1] for c, k in vus.values()])
    series, qualite, journalieres = {}, {}, {}
    for pid, (c, k) in vus.items():
        ts, v, nature, pas = c["ts"][:k], c["v"].iloc[:k], c["nature"], c["pas"]
        if nature == "instantane" or pas <= PAS_HORAIRE:
            series[pid] = _horaire(c, k)
        elif pas == PAS_JOURNALIER:
            # Relevé journalier : sa consommation couvre 24 heures, elle n'est attribuée à aucune heure (la fuite de
            # nuit, l'électricité de nuit et la PAC sont invisibles à ce pas). Jour = jour de fin d'intervalle - 1 s.
            v = v.dropna()
            journalieres[pid] = v.groupby((v.index - pd.Timedelta(seconds=1)).normalize()).sum(min_count=1)
        # autre pas plus grossier que l'heure : aucune règle ne peut s'en servir (signalé dans la fiche du compteur)
        recus_depuis = lambda debut: k - ts.searchsorted(debut, side="right")  # noqa: E731  relevés après `debut`
        debut30 = fin - pd.Timedelta(days=30)
        attendu = 30 * 24 * 60 / pas
        recus = recus_depuis(debut30)
        if pas >= PAS_MENSUEL:  # relevé mensuel : complétude sur 12 mois, depuis le premier relevé du compteur
            debut12 = fin - pd.Timedelta(days=365)
            recus = recus_depuis(debut12)
            # compteur relevé depuis moins d'un an : son premier relevé, puis un par mois CIVIL écoulé (un mois
            # « moyen » de 30,44 jours attendait un relevé de trop le 31 du mois, la veille de son arrivée)
            premier = ts[0]
            attendu = 12 if premier <= debut12 else (fin.year - premier.year) * 12 + fin.month - premier.month + 1
        elif ts[0] > debut30:  # série commencée il y a moins de 30 jours : jugée depuis son premier relevé
            debut_serie = ts[0] - pd.Timedelta(minutes=pas)
            recus = recus_depuis(debut_serie)
            attendu = max(1.0, (fin - debut_serie).total_seconds() / 60 / pas)
        qualite[pid] = {
            "derniere": ts[-1],
            "nature": nature,
            "completude": min(1.0, recus / attendu),
            "index_recule": 0 if c["recule"] is None else int(np.count_nonzero(c["recule"][:k])),
            "suspectes": int(np.count_nonzero(c["suspecte"][:k])),
            "pas_min": pas,
        }
        if pts.loc[pid, "fluide"] == "solaire":  # production au-delà de la puissance crête : échelle ou unité fausse
            kwc = pts.loc[pid].get("puissance_crete_kwc")
            qualite[pid]["crete"] = (solaire.crete_depassee(series.get(pid), kwc, debut30), kwc)
            qualite[pid]["natif"] = v  # production au pas du compteur (quart d'heure…) : coupures de l'onduleur
    return pts, series, qualite, fin, journalieres
