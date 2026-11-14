"""Coordonnées GPS des adresses du parc (géocodage officiel de la Confédération).

Service : api3.geo.admin.ch, « SearchServer » (type=locations, origine adresse), coordonnées WGS84 (sr=4326).
Seule l'ADRESSE de l'immeuble est envoyée : aucune donnée de consommation ne quitte le poste (règle 9).

Un résultat n'est retenu que si la rue, le numéro et le NPA correspondent EXACTEMENT : le service renvoie
volontiers une rue voisine pour une adresse inconnue, et un point faux sur la carte serait pire qu'aucun point.
Une adresse introuvable reste « non localisée » ; ses coordonnées peuvent être saisies à la main.

Site d'un jeu de données fictif (position x_km / y_km sur le plan du jeu, sans adresse réelle) : ses coordonnées
GPS sont CALCULÉES ici depuis le plan, enregistrées dans la base, et jamais demandées au géocodeur.
"""
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import db

URL = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
SOURCE = "geo.admin.ch"
BORNES_SUISSE = (45.8, 47.9, 5.9, 10.6)  # lat min, lat max, lon min, lon max
PAUSE_S = 0.15                            # politesse envers le service public entre deux requêtes
SOURCE_PLAN = "plan"                     # site d'un jeu fictif : position x_km / y_km sur le plan de son jeu
# Le plan d'un jeu fictif est reporté sur la carte du canton, son milieu placé ici (Carouge – Plainpalais, au sud de
# la rade : aucun site ne tombe dans le lac). Coordonnées GPS fictives, comme les sites eux-mêmes.
PLAN_CENTRE = (46.1860, 6.1350)
KM_PAR_DEGRE = (111.2, 77.05)            # kilomètres par degré de latitude et de longitude, à la latitude de Genève
LABEL_PLAN = "Position fictive : plan du jeu de données reporté sur la carte"
LABEL_RE = re.compile(r"^(.*?\d+\s*[a-zA-Z]?)\s+(\d{4}\b.*)$")  # « Rue du Rhône 41 1204 Genève »


class ErreurGeo(ValueError):
    pass


def _norm(texte):
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def decomposer(rue, npa_localite):
    """« Rue du Rhône 41 », « 1204 Genève » -> ("rue du rhone", "41", "1204") ; None si incomplet."""
    m = re.match(r"^\s*(.*?)\s+(\d+\s*[a-zA-Z]?)\s*$", str(rue or ""))
    npa = re.search(r"\b(\d{4})\b", str(npa_localite or ""))
    if not m or not npa:
        return None
    return _norm(m.group(1)), m.group(2).replace(" ", "").lower(), npa.group(1)


def dans_bornes(lat, lon):
    la0, la1, lo0, lo1 = BORNES_SUISSE
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


def valider_coordonnees(lat, lon):
    try:
        lat, lon = float(str(lat).replace(",", ".")), float(str(lon).replace(",", "."))
    except (TypeError, ValueError):
        raise ErreurGeo("Latitude et longitude doivent être des nombres (ex. 46,2038 et 6,1495).") from None
    if not dans_bornes(lat, lon):
        raise ErreurGeo("Coordonnées hors de Suisse : vérifiez la latitude (≈ 46,2 à Genève) et la longitude (≈ 6,1).")
    return round(lat, 6), round(lon, 6)


def requete(texte):
    """GET public du géocodeur fédéral ; renvoie la liste brute des résultats."""
    q = urllib.parse.urlencode({"searchText": texte, "type": "locations", "origins": "address", "sr": "4326",
                                "limit": 5})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "Vigie/0.2 (logiciel local)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as rep:
            return json.loads(rep.read(2_000_000)).get("results", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ErreurGeo(f"Géocodeur fédéral injoignable (connexion Internet ?) : {e}") from e


def geocoder(rue, npa_localite, requete_fn=None):
    """(lat, lon, libellé officiel) si l'adresse EXACTE est trouvée, sinon None."""
    cherchee = decomposer(rue, npa_localite)
    if not cherchee:
        return None
    for r in (requete_fn or requete)(f"{rue} {npa_localite}"):
        a = r.get("attrs", {})
        label = re.sub(r"<[^>]+>", "", a.get("label", "")).strip()
        m = LABEL_RE.match(label)
        if not m or decomposer(m.group(1), m.group(2)) != cherchee:
            continue
        lat, lon = a.get("lat"), a.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and dans_bornes(lat, lon):
            return round(lat, 6), round(lon, 6), label
    return None


def enregistrer(cx, adresse_id, lat, lon, source, label=None):
    n = cx.execute("UPDATE adresse SET lat = ?, lon = ?, geo_source = ?, geo_label = ? WHERE id = ?",
                   (lat, lon, source, label, adresse_id)).rowcount
    cx.commit()
    if not n:
        raise ErreurGeo("Adresse introuvable.")


def plan_vers_gps(x_km, y_km, milieu_x, milieu_y):
    """Position du plan (km, x vers l'est, y vers le nord) -> (latitude, longitude) WGS84."""
    return (round(PLAN_CENTRE[0] + (y_km - milieu_y) / KM_PAR_DEGRE[0], 6),
            round(PLAN_CENTRE[1] + (x_km - milieu_x) / KM_PAR_DEGRE[1], 6))


def placer_plan(cx):
    """Donne des coordonnées GPS aux sites d'un jeu fictif qui n'en ont pas encore (position x_km / y_km connue).

    Le milieu du plan (toutes les positions du jeu) est posé sur PLAN_CENTRE ; les distances du plan sont
    conservées. Une position saisie à la main n'est jamais remplacée. Retourne le nombre de sites placés ; la
    validation (commit) revient à l'appelant."""
    plan = db.lignes(cx, "SELECT id, x_km, y_km, lat FROM adresse WHERE x_km IS NOT NULL AND y_km IS NOT NULL")
    a_placer = [a for a in plan if a["lat"] is None]
    if not a_placer:
        return 0
    milieu_x = (min(a["x_km"] for a in plan) + max(a["x_km"] for a in plan)) / 2
    milieu_y = (min(a["y_km"] for a in plan) + max(a["y_km"] for a in plan)) / 2
    for a in a_placer:
        lat, lon = plan_vers_gps(a["x_km"], a["y_km"], milieu_x, milieu_y)
        cx.execute("UPDATE adresse SET lat = ?, lon = ?, geo_source = ?, geo_label = ? WHERE id = ?",
                   (lat, lon, SOURCE_PLAN, LABEL_PLAN, a["id"]))
    return len(a_placer)


def geocoder_parc(cx, requete_fn=None, pause_s=PAUSE_S, reessayer=False):
    """Localise les adresses sans coordonnées. Jamais celles saisies à la main ; les introuvables seulement si
    `reessayer` (bouton de l'interface). Retourne un bilan ; une panne réseau lève ErreurGeo."""
    # jamais les adresses saisies à la main, ni les sites d'un jeu fictif (placés depuis leur plan : placer_plan)
    condition = "lat IS NULL AND coalesce(geo_source, '') NOT IN ('manuel', 'plan')"
    if not reessayer:
        condition += " AND coalesce(geo_source, '') != 'introuvable'"
    a_faire = db.lignes(cx, f"SELECT id, rue, npa_localite FROM adresse WHERE {condition} ORDER BY rue")
    bilan = {"traitees": len(a_faire), "localisees": [], "introuvables": []}
    for i, ad in enumerate(a_faire):
        if i and pause_s:
            time.sleep(pause_s)
        r = geocoder(ad["rue"], ad["npa_localite"], requete_fn)
        if r:
            enregistrer(cx, ad["id"], r[0], r[1], SOURCE, r[2])
            bilan["localisees"].append(f"{ad['rue']}, {ad['npa_localite']}")
        else:
            cx.execute("UPDATE adresse SET geo_source = 'introuvable' WHERE id = ?", (ad["id"],))
            cx.commit()
            bilan["introuvables"].append(f"{ad['rue']}, {ad['npa_localite']}")
    return bilan
