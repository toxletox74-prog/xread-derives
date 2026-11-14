"""Série de température réelle MétéoSuisse (Genève-Cointrin, tre200h0), figée pour une campagne reproductible.

Premier appel : les fichiers publics MétéoSuisse sont téléchargés (lecture seule, aucune donnée envoyée) et copiés
dans evaluation/sorties/cache_meteo/, avec la date de téléchargement. Appels suivants : lecture du cache seulement.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from vigie import meteo

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, "sorties", "cache_meteo")
META = os.path.join(CACHE, "meta.json")


def _nom(url):
    return url.rsplit("/", 1)[-1]


def _maintenant():
    """Date de référence de la campagne : celle du premier téléchargement (figée dans meta.json)."""
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(META):
        with open(META, encoding="utf-8") as f:
            return datetime.fromisoformat(json.load(f)["telecharge_le"])
    t = datetime.now(timezone.utc).replace(microsecond=0)
    with open(META, "w", encoding="utf-8") as f:
        json.dump({"telecharge_le": t.isoformat(), "station": meteo.STATION_DEFAUT, "colonne": meteo.COLONNE,
                   "source": meteo.BASE_URL}, f, ensure_ascii=False, indent=1)
    return t


def lire_url(url):
    """Contenu d'un fichier MétéoSuisse : depuis le cache, sinon téléchargé puis mis en cache."""
    chemin = os.path.join(CACHE, _nom(url))
    if not os.path.exists(chemin):
        texte = meteo.telecharger(url)
        with open(chemin, "w", encoding="utf-8", newline="") as f:
            f.write(texte)
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def maintenant():
    return _maintenant()


def serie_reelle(jours=130):
    """{datetime UTC naïf fin d'heure : °C} — mêmes règles que vigie.meteo.temperatures_reelles (heures manquantes absentes)."""
    return meteo.temperatures_reelles(jours=jours, telecharger_fn=lire_url, maintenant=_maintenant())


def serie_longue(annees=3):
    """Série horaire plus longue (fichier de la décennie + récent + maintenant) : climatologie et annualisation."""
    m = _maintenant()
    u = meteo.urls(meteo.STATION_DEFAUT, m)
    depuis = (m - timedelta(days=365 * annees)).replace(tzinfo=None)
    serie = {}
    for nom in ("historique", "recent", "now"):
        serie.update(meteo.convertir(lire_url(u[nom]), meteo.STATION_DEFAUT, depuis))
    return {datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"): v for ts, v in serie.items()}
