"""Température extérieure officielle : MétéoSuisse, données ouvertes (station Genève-Cointrin par défaut).

Source : réseau SwissMetNet, collection « ch.meteoschweiz.ogd-smn » sur data.geo.admin.ch.
Fichiers horaires d'une station (séparateur ;, horodatage « jj.mm.aaaa HH:MM » en UTC, FIN d'intervalle) :
  ogd-smn_<st>_h_now.csv                     hier 12 UTC -> maintenant, rafraîchi toutes les 10 min
  ogd-smn_<st>_h_recent.csv                  1er janvier -> hier, rafraîchi chaque jour
  ogd-smn_<st>_h_historical_<décennie>.csv   années précédentes
Colonnes utilisées : tre200h0 = température de l'air à 2 m, moyenne horaire (°C) ; gre000h0 = rayonnement global,
moyenne horaire (W/m², donc Wh/m² sur l'heure), qui sert à juger la production solaire à ensoleillement égal.
Le rayonnement est facultatif : une station qui ne le mesure pas ne donne que la température.

Seule une donnée publique est TÉLÉCHARGÉE : aucune donnée de consommation ne quitte le poste (règle 9).
Les heures manquantes restent manquantes (jamais interpolées, règle 4).
"""
import csv
import io
import math
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db

BASE_URL = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn"
LIENS = {
    "Données ouvertes MétéoSuisse": "https://www.meteoswiss.admin.ch/services-and-publications/service/open-data.html",
    "Documentation (format, horodatage UTC)": "https://opendatadocs.meteoswiss.ch/general/download",
    "Stations météorologiques automatiques": "https://opendatadocs.meteoswiss.ch/fr/a-data-groundbased/a1-automatic-weather-stations",
    "Jeu de données sur opendata.swiss": "https://opendata.swiss/fr/dataset/automatische-wetterstationen-messwerte",
}
STATION_DEFAUT = "GVE"
STATIONS_CONNUES = {"GVE": "Genève-Cointrin"}
COLONNE = "tre200h0"
JOURS_HISTORIQUE = 400       # recul conservé : une saison de chauffe + la période de référence
JOURS_MIN_RECUL = 60         # en dessous, l'historique de la décennie est aussi téléchargé
TAILLE_MAX = 60 * 1024 * 1024
INTERVALLE_AUTO_H = 3
CONFIG_DEFAUT = {"source": "meteosuisse", "station": STATION_DEFAUT, "auto": True, "point_id": None,
                 "point_rayonnement": None,
                 "derniere_maj": None, "derniere_mesure": None, "statut": "jamais", "message": ""}


class ErreurMeteo(ValueError):
    pass


def lire_config(cx):
    return {**CONFIG_DEFAUT, **(db.lire_parametre(cx, "meteo") or {})}


def exemple_fictif(cfg):
    """Base d'exemple sur températures FICTIVES : jamais de mise à jour MétéoSuisse (elles iraient avec rien)."""
    return cfg["source"] == "exemple" and cfg.get("point_id") != f"METEO_{cfg['station']}"


def ecrire_config(cx, d):
    cfg = lire_config(cx)
    if cfg["source"] == "exemple" and str(d.get("station") or cfg["station"]).strip().upper() != cfg["station"]:
        raise ErreurMeteo("Base d'exemple : la station reste Genève-Cointrin (GVE), celle des consommations simulées.")
    if exemple_fictif(cfg) and "auto" in d:
        raise ErreurMeteo("Base d'exemple à températures fictives : pas de mise à jour MétéoSuisse.")
    if "station" in d:
        st = str(d["station"] or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", st):
            raise ErreurMeteo("Code de station : 3 lettres (ex. GVE pour Genève-Cointrin).")
        if st != cfg["station"]:  # nouvelle station = nouvelles séries (on ne mélange jamais deux stations)
            cfg["point_id"] = cfg["point_rayonnement"] = None
        cfg["station"] = st
    if "auto" in d:
        cfg["auto"] = bool(d["auto"])
    db.ecrire_parametre(cx, "meteo", cfg)
    return cfg


def urls(station, maintenant=None):
    st = station.lower()
    annee = (maintenant or datetime.now(timezone.utc)).year
    decennie = annee - annee % 10
    return {
        "now": f"{BASE_URL}/{st}/ogd-smn_{st}_h_now.csv",
        "recent": f"{BASE_URL}/{st}/ogd-smn_{st}_h_recent.csv",
        "historique": f"{BASE_URL}/{st}/ogd-smn_{st}_h_historical_{decennie}-{decennie + 9}.csv",
    }


def telecharger(url):
    """GET d'un fichier public MétéoSuisse. Aucune donnée du poste n'est envoyée."""
    req = urllib.request.Request(url, headers={"User-Agent": "Vigie/0.2 (logiciel local)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as rep:
            contenu = rep.read(TAILLE_MAX + 1)
    except urllib.error.HTTPError as e:
        raise ErreurMeteo(f"MétéoSuisse a répondu {e.code} pour {url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise ErreurMeteo(f"MétéoSuisse injoignable (connexion Internet ?) : {e}") from e
    if len(contenu) > TAILLE_MAX:
        raise ErreurMeteo("Fichier MétéoSuisse anormalement volumineux : ignoré.")
    return contenu.decode("utf-8-sig", errors="replace")


COLONNE_RAYONNEMENT = "gre000h0"
# fluide du point -> (colonne MétéoSuisse, bornes plausibles, préfixe du point, unité, libellé, clé de la configuration)
GRANDEURS = {
    "meteo": (COLONNE, -45, 50, "METEO", "degC", "Température extérieure", "point_id"),
    "rayonnement": (COLONNE_RAYONNEMENT, 0, 1500, "RAYON", "W/m2", "Rayonnement solaire global", "point_rayonnement"),
}


def lire_csv(texte, station, depuis=None):
    """CSV MétéoSuisse -> {fluide: [(ts ISO UTC fin d'intervalle, valeur)]}. Valeurs absentes ou implausibles écartées.

    La température est obligatoire ; le rayonnement n'est lu que si la colonne existe (liste vide sinon)."""
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=";")
    if not lecteur.fieldnames or COLONNE not in lecteur.fieldnames or "reference_timestamp" not in lecteur.fieldnames:
        raise ErreurMeteo(f"Format MétéoSuisse inattendu : colonne {COLONNE} introuvable.")
    out = {f: [] for f in GRANDEURS}
    for ligne in lecteur:
        if (ligne.get("station_abbr") or "").upper() != station.upper():
            continue
        try:
            t = datetime.strptime(ligne["reference_timestamp"].strip(), "%d.%m.%Y %H:%M")
        except (ValueError, KeyError, AttributeError):
            continue
        if depuis and t < depuis:
            continue
        for fluide, (colonne, mini, maxi, *_r) in GRANDEURS.items():
            brut = (ligne.get(colonne) or "").strip()
            if not brut:
                continue  # heure manquante : jamais comblée
            try:
                v = float(brut)
            except ValueError:
                continue
            if math.isfinite(v) and mini <= v <= maxi:
                out[fluide].append((t.strftime("%Y-%m-%dT%H:%M:%SZ"), v))
    return out


def convertir(texte, station, depuis=None):
    """CSV MétéoSuisse -> [(ts ISO UTC fin d'intervalle, °C)]. Valeurs absentes ou implausibles écartées."""
    return lire_csv(texte, station, depuis)["meteo"]


def point_meteo(cx, station, fluide="meteo"):
    """Point de mesure de la température extérieure (ou du rayonnement solaire) du parc ; créé s'il n'existe pas."""
    colonne, _mini, _maxi, prefixe, unite, libelle, cle = GRANDEURS[fluide]
    cfg = lire_config(cx)
    if cfg.get(cle) and cx.execute("SELECT 1 FROM point_mesure WHERE id = ?", (cfg[cle],)).fetchone():
        return cfg[cle]
    pid = f"{prefixe}_{station}"
    nom = STATIONS_CONNUES.get(station, station)
    cx.execute("INSERT OR IGNORE INTO point_mesure (id, immeuble_id, fluide, libelle, unite, nature, pas_min, source, "
               "identifiant, fournisseur, etat) VALUES (?, NULL, ?, ?, ?, 'instantane', 60, ?, ?, ?, 'actif')",
               (pid, fluide, f"{libelle} — {nom}", unite, f"MétéoSuisse open data · station {station}",
                f"SwissMetNet {station} · {colonne}", "Office fédéral de météorologie et de climatologie MétéoSuisse"))
    # Ce point devient LA référence du parc pour cette grandeur : les autres points sont mis hors service
    cx.execute("UPDATE point_mesure SET etat = 'actif' WHERE id = ?", (pid,))
    cx.execute("UPDATE point_mesure SET etat = 'inactif' WHERE fluide = ? AND id != ?", (fluide, pid))
    cfg[cle] = pid
    db.ecrire_parametre(cx, "meteo", cfg)
    return pid


def mettre_a_jour(cx, telecharger_fn=None, maintenant=None):
    """Télécharge et importe la température horaire de la station configurée. Retourne un bilan."""
    fetch = telecharger_fn or telecharger
    maintenant = maintenant or datetime.now(timezone.utc)
    horodatage = maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = lire_config(cx)
    if exemple_fictif(cfg):
        raise ErreurMeteo("Base d'exemple : ses températures fictives vont avec les consommations simulées. "
                          "La mise à jour MétéoSuisse ne s'applique qu'à votre parc réel.")
    station = cfg["station"]
    depuis = (maintenant - timedelta(days=JOURS_HISTORIQUE)).replace(tzinfo=None)
    try:
        # 1. Lecture seule, puis téléchargements : la base n'est pas verrouillée pendant l'accès réseau
        # Historique de la décennie si la température OU le rayonnement manque de recul (rayonnement ajouté après coup ;
        # sauf base d'exemple, qui ne reçoit jamais d'historique de rayonnement)
        recul = min(cx.execute("SELECT julianday(max(ts)) - julianday(min(ts)) FROM mesure WHERE point_id = ?",
                               (cfg.get(g[6]) or f"{g[3]}_{station}",)).fetchone()[0] or 0
                    for g in GRANDEURS.values() if g[6] == "point_id" or cfg["source"] != "exemple")
        u = urls(station, maintenant)
        fichiers = ["historique"] if recul < JOURS_MIN_RECUL else []
        fichiers += ["recent", "now"]  # ordre : le plus récent l'emporte en cas de recouvrement
        lu, lus = {f: {} for f in GRANDEURS}, []
        for nom in fichiers:
            try:
                for fluide, serie in lire_csv(fetch(u[nom]), station, depuis).items():
                    lu[fluide].update(serie)
                lus.append(nom)
            except ErreurMeteo:
                if nom == "historique":
                    continue  # facultatif : en début de décennie le fichier peut ne pas encore exister
                raise
        if not lu["meteo"]:
            raise ErreurMeteo(f"Aucune température exploitable pour la station {station}.")
        if cfg["source"] == "exemple":
            # Exemple sur météo réelle : on AJOUTE les heures nouvelles, sans jamais réécrire celles qui ont servi à
            # simuler les consommations et la production solaire (MétéoSuisse corrige parfois les jours passés).
            # Un exemple simulé sans rayonnement réel (production solaire sur rayonnement fictif) n'en reçoit jamais.
            for fluide, valeurs in lu.items():
                cle = GRANDEURS[fluide][6]
                if not cfg.get(cle):
                    lu[fluide] = {}
                    continue
                deja = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = ?", (cfg[cle],)).fetchone()[0] or ""
                lu[fluide] = {ts: v for ts, v in valeurs.items() if ts > deja}
            if not lu["meteo"]:
                derniere = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = ?", (cfg["point_id"],)).fetchone()[0]
                db.ecrire_parametre(cx, "meteo", {**lire_config(cx), "derniere_maj": horodatage, "statut": "ok",
                                                  "derniere_mesure": derniere, "message": "Déjà à jour."})
                return {"heures": 0, "derniere_mesure": derniere, "point_id": cfg["point_id"], "fichiers": lus,
                        "heures_rayonnement": 0}
        # 2. Écriture, courte et en une transaction
        lot = "meteo-" + maintenant.strftime("%Y%m%d%H%M")
        points = {}
        for fluide, valeurs in lu.items():
            if valeurs:
                points[fluide] = point_meteo(cx, station, fluide)
                cx.executemany("INSERT OR REPLACE INTO mesure VALUES (?,?,?, 'valide', ?)",
                               [(ts, points[fluide], v, lot) for ts, v in sorted(valeurs.items())])
        cx.commit()
        pid, valeurs = points["meteo"], lu["meteo"]
        derniere = max(valeurs)
        ray = len(lu["rayonnement"])
        db.ecrire_parametre(cx, "meteo", {**lire_config(cx), "point_id": pid, "derniere_maj": horodatage,
                                          "derniere_mesure": derniere, "statut": "ok",
                                          "message": f"{len(valeurs)} heures lues ({', '.join(lus)})"
                                                     + (f", dont {ray} de rayonnement solaire." if ray else ".")})
        return {"heures": len(valeurs), "derniere_mesure": derniere, "point_id": pid, "fichiers": lus,
                "heures_rayonnement": ray}
    except ErreurMeteo as e:
        cx.rollback()
        db.ecrire_parametre(cx, "meteo", {**lire_config(cx), "derniere_maj": horodatage, "statut": "erreur",
                                          "message": str(e)})
        raise


def charger_periode(cx, debut, fin, telecharger_fn=None, maintenant=None):
    """Température et rayonnement horaires de la station pour une période passée (`debut` et `fin` : dates UTC
    naïves), pour rejouer la détection. Seuls des fichiers publics sont téléchargés. Retourne un bilan."""
    fetch = telecharger_fn or telecharger
    maintenant = maintenant or datetime.now(timezone.utc)
    station = lire_config(cx)["station"]
    st = station.lower()
    adresses = [f"{BASE_URL}/{st}/ogd-smn_{st}_h_historical_{d}-{d + 9}.csv"
                for d in sorted({a - a % 10 for a in range(debut.year, fin.year + 1)})]
    if fin.year >= maintenant.year:
        adresses.append(urls(station, maintenant)["recent"])
    borne = fin.strftime("%Y-%m-%dT%H:%M:%SZ")
    lu = {f: {} for f in GRANDEURS}
    for adresse in adresses:
        for fluide, serie in lire_csv(fetch(adresse), station, debut).items():
            lu[fluide].update((ts, v) for ts, v in serie if ts <= borne)
    if not lu["meteo"]:
        raise ErreurMeteo(f"Aucune température de la station {station} entre {debut:%d.%m.%Y} et {fin:%d.%m.%Y}.")
    lot = "meteo-periode-" + maintenant.strftime("%Y%m%d%H%M")
    bilan = {"station": station}
    for fluide, valeurs in lu.items():
        if valeurs:
            pid = point_meteo(cx, station, fluide)
            cx.executemany("INSERT OR REPLACE INTO mesure VALUES (?,?,?, 'valide', ?)",
                           [(ts, pid, v, lot) for ts, v in sorted(valeurs.items())])
        bilan[fluide] = len(valeurs)
    cx.commit()
    db.ecrire_parametre(cx, "meteo", {**lire_config(cx), "statut": "ok", "derniere_mesure": max(lu["meteo"]),
                                      "derniere_maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                      "message": f"Période {debut:%d.%m.%Y} - {fin:%d.%m.%Y} chargée : {len(lu['meteo'])} "
                                                 f"heures de température, {len(lu['rayonnement'])} de rayonnement."})
    return bilan


def meteo_reelle(station=STATION_DEFAUT, jours=130, telecharger_fn=None, maintenant=None):
    """Séries horaires réelles {datetime UTC naïf : valeur} des `jours` derniers jours (servent à simuler l'exemple) :
    (températures °C, rayonnement global W/m² — vide si la station ne le fournit pas)."""
    fetch = telecharger_fn or telecharger
    maintenant = maintenant or datetime.now(timezone.utc)
    depuis = (maintenant - timedelta(days=jours)).replace(tzinfo=None)
    u = urls(station, maintenant)
    fichiers = (["historique"] if depuis.year < maintenant.year else []) + ["recent", "now"]
    lu = {f: {} for f in GRANDEURS}
    for nom in fichiers:
        for fluide, serie in lire_csv(fetch(u[nom]), station, depuis).items():
            lu[fluide].update(serie)
    if not lu["meteo"]:
        raise ErreurMeteo(f"Aucune température exploitable pour la station {station}.")
    lire = lambda s: {datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"): v for ts, v in s.items()}  # noqa: E731
    return lire(lu["meteo"]), lire(lu["rayonnement"])


def temperatures_reelles(station=STATION_DEFAUT, jours=130, telecharger_fn=None, maintenant=None):
    """Série horaire réelle {datetime UTC naïf : °C} des `jours` derniers jours."""
    return meteo_reelle(station, jours, telecharger_fn, maintenant)[0]


def etat(cx):
    cfg = lire_config(cx)
    station = cfg["station"]
    return {**cfg, "exemple_fictif": exemple_fictif(cfg), "exemple_reel": cfg["source"] == "exemple" and not exemple_fictif(cfg),
            "nom_station": STATIONS_CONNUES.get(station, station), "liens": LIENS,
            "fichiers": urls(station), "intervalle_auto_h": INTERVALLE_AUTO_H, "colonne": COLONNE,
            "colonne_rayonnement": COLONNE_RAYONNEMENT}
