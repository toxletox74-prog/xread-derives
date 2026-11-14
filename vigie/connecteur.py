"""Connecteur API des relevés de compteurs : clé API, appel au fournisseur, import des valeurs.

Ce qui sort du poste, vers le seul fournisseur configuré : la clé, l'identifiant de chaque compteur relié et la
période demandée. Aucune consommation n'est envoyée (règle 9) : les valeurs ne font qu'entrer, avec les contrôles de
l'import CSV (compteur connu, horodatage ISO, valeur lisible, valeur négative marquée suspecte).

Format par défaut (réglable dans Réglages, car il dépend du fournisseur retenu) :
  GET {adresse}/points/{identifiant}/mesures?debut=2026-11-12T06:00:00Z&fin=2026-11-13T07:00:00Z
  en-tête  X-API-Key: <clé>
  réponse  {"mesures": [{"ts": "2026-11-12T07:00:00Z", "valeur": 4.385}, ...]}   (ts en UTC, fin d'intervalle)
"""
import csv
import io
import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from . import db, secret

SOURCE_API = "API du fournisseur"
ENV_CLE = "VIGIE_API_CLE"
PARAM, PARAM_CLE = "connecteur", "connecteur_cle"
TAILLE_MAX = 20 * 1024 * 1024
DELAI_S = 30
JOURS_PAR_APPEL = 31
JOURS_MAX = 400
FMT = "%Y-%m-%dT%H:%M:%SZ"
CHEMIN_DEFAUT = "/points/{identifiant}/mesures?debut={debut}&fin={fin}"
HOTES_LOCAUX = ("127.0.0.1", "localhost", "::1")
AUTHS = {"en_tete": "Clé dans un en-tête HTTP (ex. X-API-Key)", "bearer": "En-tête Authorization: Bearer <clé>",
         "parametre": "Clé dans l'adresse (ex. ?api_key=…)"}
FORMATS = {"json": "JSON", "csv": "CSV"}
DEMO_CLE = "DEMO-VIGIE-2026"
DEMO_CHEMIN = "/demo-fournisseur"
CONFIG_DEFAUT = {"actif": False, "fournisseur": "", "url_base": "", "auth": "en_tete", "auth_nom": "X-API-Key",
                 "chemin": CHEMIN_DEFAUT, "format": "json", "json_liste": "mesures", "json_ts": "ts",
                 "json_valeur": "valeur", "historique_j": 7, "recul_h": 2, "auto": False, "intervalle_h": 1,
                 "derniere_synchro": None, "statut": "jamais", "message": ""}
MESSAGES_HTTP = {
    400: "Demande refusée par le fournisseur (400) : vérifiez le chemin et le format des dates.",
    401: "Clé API refusée par le fournisseur (401) : vérifiez la clé.",
    403: "Accès refusé (403) : la clé n'a pas de droits sur ce compteur.",
    404: "Adresse ou compteur inconnu du fournisseur (404) : vérifiez l'adresse, le chemin et l'identifiant.",
    429: "Trop de demandes (429) : le fournisseur limite le rythme ; réessayez plus tard.",
}


class ErreurConnecteur(ValueError):
    pass


# ---------------------------------------------------------------- réglages et clé


def lire_config(cx):
    return {**CONFIG_DEFAUT, **(db.lire_parametre(cx, PARAM) or {})}


def cle(cx):
    """La clé en clair, pour l'appel seulement : variable d'environnement d'abord, sinon clé protégée du poste."""
    env = os.environ.get(ENV_CLE, "").strip()
    if env:
        return env
    protege = db.lire_parametre(cx, PARAM_CLE)
    return secret.relire(protege) if protege else ""


def points_api(cx):
    """Compteurs reliés à l'API : (code Vigie, identifiant chez le fournisseur, nature)."""
    return [(r[0], (r[1] or "").strip() or r[0], r[2]) for r in cx.execute(
        "SELECT id, identifiant, nature FROM point_mesure WHERE source = ? AND etat != 'inactif' ORDER BY id",
        (SOURCE_API,))]


def etat(cx):
    """Réglages pour l'interface : la clé n'en sort jamais, seulement ses 4 derniers caractères."""
    origine = "env" if os.environ.get(ENV_CLE, "").strip() else ("poste" if db.lire_parametre(cx, PARAM_CLE) else None)
    try:
        c = cle(cx)
    except secret.ErreurSecret:
        c, origine = "", "illisible"
    return {**lire_config(cx), "cle": {"presente": bool(c), "origine": origine, "masque": secret.masque(c) if c else None},
            "points": [{"id": p, "identifiant": i} for p, i, _ in points_api(cx)], "source_api": SOURCE_API,
            "auths": AUTHS, "formats": FORMATS, "protection_disponible": secret.DISPONIBLE, "env_cle": ENV_CLE}


def valider_url(url):
    u = urlsplit(url)
    if u.scheme not in ("https", "http") or not u.hostname:
        raise ErreurConnecteur("Adresse du fournisseur : elle commence par https:// (ex. https://api.fournisseur.ch/v1).")
    if u.username or u.password:
        raise ErreurConnecteur("Pas d'identifiant dans l'adresse : la clé se saisit dans le champ « Clé API ».")
    if u.scheme == "http" and u.hostname not in HOTES_LOCAUX:
        raise ErreurConnecteur("Adresse en http:// refusée : la clé circulerait en clair sur le réseau. Utilisez https://.")
    if u.query or u.fragment:
        raise ErreurConnecteur("Adresse de base sans « ? » ni « # » : les paramètres se mettent dans le chemin.")
    return url.rstrip("/")


def _texte(d, cle_champ, libelle, maxi):
    v = str(d.get(cle_champ) or "").strip()
    if len(v) > maxi or not v.isprintable():
        raise ErreurConnecteur(f"{libelle} : {maxi} caractères imprimables au plus.")
    return v


def _entier(d, cle_champ, libelle, mini, maxi):
    try:
        v = int(d.get(cle_champ))
    except (TypeError, ValueError):
        raise ErreurConnecteur(f"{libelle} : nombre entier attendu.") from None
    if not mini <= v <= maxi:
        raise ErreurConnecteur(f"{libelle} : entre {mini} et {maxi}.")
    return v


def enregistrer(cx, d):
    """Valide et enregistre les réglages ; une clé fournie est protégée par Windows avant d'être stockée."""
    cfg = lire_config(cx)
    for k, lib, maxi in (("fournisseur", "Fournisseur", 120), ("chemin", "Chemin", 300), ("json_liste", "Liste des valeurs", 120),
                         ("json_ts", "Champ horodatage", 60), ("json_valeur", "Champ valeur", 60), ("auth_nom", "Nom de la clé", 64)):
        if k in d:
            cfg[k] = _texte(d, k, lib, maxi)
    if "url_base" in d:
        cfg["url_base"] = valider_url(_texte(d, "url_base", "Adresse", 300)) if str(d["url_base"] or "").strip() else ""
    if "auth" in d:
        if d["auth"] not in AUTHS:
            raise ErreurConnecteur("Mode d'envoi de la clé inconnu.")
        cfg["auth"] = d["auth"]
    if "format" in d:
        if d["format"] not in FORMATS:
            raise ErreurConnecteur("Format de réponse : JSON ou CSV.")
        cfg["format"] = d["format"]
    for k, lib, mini, maxi in (("historique_j", "Historique au premier appel (jours)", 1, JOURS_MAX),
                               ("recul_h", "Recouvrement (heures)", 0, 168), ("intervalle_h", "Fréquence (heures)", 1, 24)):
        if k in d:
            cfg[k] = _entier(d, k, lib, mini, maxi)
    for k in ("actif", "auto"):
        if k in d:
            cfg[k] = bool(d[k])
    if cfg["auth"] != "bearer" and not all(c.isalnum() or c in "-_" for c in cfg["auth_nom"] or "-"):
        raise ErreurConnecteur("Nom de la clé : lettres, chiffres, - et _ seulement (ex. X-API-Key).")
    if not cfg["chemin"].startswith("/") or "{identifiant}" not in cfg["chemin"]:
        raise ErreurConnecteur("Chemin : commence par / et contient {identifiant} (ex. " + CHEMIN_DEFAUT + ").")
    if cfg["actif"] and not cfg["url_base"]:
        raise ErreurConnecteur("Indiquez l'adresse du fournisseur avant d'activer la connexion.")
    nouvelle = str(d.get("cle") or "").strip()
    if nouvelle:
        if len(nouvelle) > 1024 or not nouvelle.isprintable():
            raise ErreurConnecteur("Clé API invalide (trop longue ou caractères non imprimables).")
        db.ecrire_parametre(cx, PARAM_CLE, secret.proteger(nouvelle))
    db.ecrire_parametre(cx, PARAM, cfg)
    return etat(cx)


def supprimer_cle(cx):
    cx.execute("DELETE FROM parametre WHERE cle = ?", (PARAM_CLE,))
    cx.commit()
    return etat(cx)


# ---------------------------------------------------------------- appel au fournisseur


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Une redirection renverrait la clé vers une adresse non choisie : refusée."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ErreurConnecteur(f"Le fournisseur renvoie vers une autre adresse (code {code}) : refusé, la clé n'y est "
                               "pas envoyée. Vérifiez l'adresse.")


_OUVREUR = urllib.request.build_opener(_SansRedirection)


def telecharger(url, entetes):
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/csv;q=0.9",
                                               "User-Agent": "Vigie (releves de compteurs)", **entetes})
    try:
        with _OUVREUR.open(req, timeout=DELAI_S) as r:
            contenu = r.read(TAILLE_MAX + 1)
    except urllib.error.HTTPError as e:
        raise ErreurConnecteur(MESSAGES_HTTP.get(e.code, f"Le fournisseur a répondu par une erreur ({e.code}).")) from None
    except urllib.error.URLError as e:
        raise ErreurConnecteur(f"Fournisseur injoignable ({e.reason}).") from None
    except OSError:
        raise ErreurConnecteur("Fournisseur injoignable (délai dépassé ou réseau coupé).") from None
    if len(contenu) > TAILLE_MAX:
        raise ErreurConnecteur("Réponse trop volumineuse (plus de 20 Mo) : réduisez la période.")
    return contenu


def requete(cfg, cle_api, identifiant, debut, fin):
    """(adresse, en-têtes) d'un appel. La clé n'apparaît dans aucun message d'erreur."""
    chemin = (cfg["chemin"].replace("{identifiant}", quote(identifiant, safe=""))
              .replace("{debut}", quote(debut.strftime(FMT), safe="")).replace("{fin}", quote(fin.strftime(FMT), safe="")))
    url = cfg["url_base"].rstrip("/") + chemin
    entetes = {}
    if cfg["auth"] == "bearer":
        entetes["Authorization"] = "Bearer " + cle_api
    elif cfg["auth"] == "en_tete":
        entetes[cfg["auth_nom"] or "X-API-Key"] = cle_api
    else:
        u = urlsplit(url)
        url = urlunsplit(u._replace(query=urlencode(parse_qsl(u.query, keep_blank_values=True)
                                                   + [(cfg["auth_nom"] or "api_key", cle_api)])))
    return url, entetes


def _ts(v):
    """Horodatage du fournisseur : texte ISO tel quel (contrôlé à l'import) ou nombre de secondes / millisecondes."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc).strftime(FMT)
    return str(v)


def lire_reponse(cfg, contenu, identifiant):
    """Réponse du fournisseur -> [(ts, valeur)] bruts."""
    if cfg["format"] == "csv":
        texte = contenu.decode("utf-8-sig", errors="replace")
        sep = ";" if texte[:4096].count(";") > texte[:4096].count(",") else ","
        return [(r.get(cfg["json_ts"]), r.get(cfg["json_valeur"])) for r in csv.DictReader(io.StringIO(texte), delimiter=sep)
                if r.get("point_id") in (None, "", identifiant)]
    try:
        donnees = json.loads(contenu.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ErreurConnecteur("Réponse illisible : JSON attendu (réglage « Format de réponse »).") from None
    for morceau in [m for m in (cfg["json_liste"] or "").split(".") if m]:
        if not isinstance(donnees, dict) or morceau not in donnees:
            raise ErreurConnecteur(f"Réponse inattendue : champ « {morceau} » absent (réglage « Liste des valeurs »).")
        donnees = donnees[morceau]
    if not isinstance(donnees, list):
        raise ErreurConnecteur("Réponse inattendue : la liste des valeurs est introuvable (réglage « Liste des valeurs »).")
    return [(el.get(cfg["json_ts"]), el.get(cfg["json_valeur"])) if isinstance(el, dict) else (el[0], el[1])
            for el in donnees if isinstance(el, dict) or (isinstance(el, list) and len(el) >= 2)]


def _heure(maintenant=None):
    return (maintenant or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)


def collecter(cfg, cle_api, pid, identifiant, debut, fin, telecharger_fn):
    """Valeurs d'un compteur entre debut et fin, par tranches de 31 jours au plus."""
    lignes, t = [], debut
    while t < fin:
        t2 = min(fin, t + timedelta(days=JOURS_PAR_APPEL))
        url, entetes = requete(cfg, cle_api, identifiant, t, t2)
        for ts, v in lire_reponse(cfg, telecharger_fn(url, entetes), identifiant):
            try:
                ts = _ts(ts)
            except (ValueError, OverflowError, OSError):
                ts = str(ts)
            lignes.append({"ts": ts, "point_id": pid, "valeur": v})
        t = t2
    return lignes


def _preparer(cx):
    cfg = lire_config(cx)
    if not cfg["url_base"]:
        raise ErreurConnecteur("Indiquez d'abord l'adresse du fournisseur (Réglages > Connexion API).")
    try:
        cle_api = cle(cx)
    except secret.ErreurSecret as e:
        raise ErreurConnecteur(str(e)) from None
    if not cle_api:
        raise ErreurConnecteur("Aucune clé API : saisissez-la dans Réglages > Connexion API.")
    points = points_api(cx)
    if not points:
        raise ErreurConnecteur(f"Aucun compteur relié à l'API : dans Parc, choisissez la connexion « {SOURCE_API} » "
                               "et indiquez l'identifiant du compteur chez le fournisseur.")
    return cfg, cle_api, points


def tester(cx, telecharger_fn=None, maintenant=None):
    """Un appel pour le premier compteur relié, sur les dernières 24 h ; rien n'est importé."""
    cfg, cle_api, points = _preparer(cx)
    pid, ident, _ = points[0]
    fin = _heure(maintenant)
    lignes = collecter(cfg, cle_api, pid, ident, fin - timedelta(days=1), fin, telecharger_fn or telecharger)
    return {"compteur": pid, "identifiant": ident, "valeurs": len(lignes), "apercu": lignes[-3:],
            "compteurs_relies": len(points)}


def synchroniser(cx, telecharger_fn=None, maintenant=None):
    """Importe les nouvelles valeurs de chaque compteur relié (depuis sa dernière valeur, moins un recouvrement)."""
    cfg, cle_api, points = _preparer(cx)
    fin = _heure(maintenant)
    lignes, erreurs = [], []
    for pid, ident, _ in points:
        derniere = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = ?", (pid,)).fetchone()[0]
        debut = (datetime.strptime(derniere, FMT).replace(tzinfo=timezone.utc) - timedelta(hours=cfg["recul_h"])
                 if derniere else fin - timedelta(days=cfg["historique_j"]))
        if debut >= fin:
            continue
        try:
            lignes += collecter(cfg, cle_api, pid, ident, debut, fin, telecharger_fn or telecharger)
        except ErreurConnecteur as e:
            erreurs.append({"compteur": pid, "message": str(e)})
    ok, rejets, lot = db._importer_lignes(cx, enumerate(lignes, start=1))
    statut = "ok" if not erreurs else ("erreur" if len(erreurs) == len(points) else "partiel")
    message = (f"{ok} valeur(s) importée(s) pour {len(points) - len(erreurs)} compteur(s)"
               + (f", {len(rejets)} rejetée(s)" if rejets else "")
               + (f" ; {len(erreurs)} compteur(s) en échec — {erreurs[0]['message']}" if erreurs else "") + ".")
    db.ecrire_parametre(cx, PARAM, {**lire_config(cx), "statut": statut, "message": message,
                                    "derniere_synchro": (maintenant or datetime.now(timezone.utc)).strftime(FMT)})
    return {"compteurs": len(points), "importees": ok, "rejets": len(rejets), "erreurs": erreurs, "lot": lot,
            "statut": statut, "message": message,
            "detail_rejets": [{"ligne": n, "motif": m} for n, m in rejets[:20]]}


def a_synchroniser(cfg, maintenant=None):
    """Synchronisation automatique due ? (connexion active, automatique, intervalle écoulé)."""
    if not (cfg["actif"] and cfg["auto"] and cfg["url_base"]):
        return False
    if not cfg["derniere_synchro"]:
        return True
    derniere = datetime.strptime(cfg["derniere_synchro"], FMT).replace(tzinfo=timezone.utc)
    return (maintenant or datetime.now(timezone.utc)) - derniere >= timedelta(hours=cfg["intervalle_h"])


# ---------------------------------------------------------------- démonstration (base d'exemple)


def activer_demo(cx, port):
    """Branche la base d'exemple sur le fournisseur de démonstration servi par Vigie lui-même."""
    enregistrer(cx, {"actif": True, "fournisseur": "Fournisseur de démonstration (servi par Vigie)",
                     "url_base": f"http://127.0.0.1:{int(port)}{DEMO_CHEMIN}", "auth": "en_tete",
                     "auth_nom": "X-API-Key", "chemin": CHEMIN_DEFAUT, "format": "json",
                     "json_liste": "mesures", "json_ts": "ts", "json_valeur": "valeur", "cle": DEMO_CLE})
    n = cx.execute("UPDATE point_mesure SET source = ?, identifiant = COALESCE(NULLIF(identifiant, ''), id) "
                   f"WHERE immeuble_id IS NOT NULL AND fluide NOT IN {db.SQL_METEO} AND etat != 'inactif'",
                   (SOURCE_API,)).rowcount
    cx.commit()
    return {**etat(cx), "relies": n}


def _date(texte):
    return datetime.strptime(db.normaliser_ts(texte), FMT).replace(tzinfo=timezone.utc)


class FournisseurDemo:
    """Faux fournisseur, pour essayer la connexion sans vrai fournisseur (réunion, formation).

    Il prolonge les relevés de chaque compteur au-delà de leur fin par le profil moyen heure par heure des 7 derniers
    jours (pour un index : la consommation moyenne de chaque heure s'ajoute à l'index). Le point de départ est figé
    au premier appel : les réponses restent cohérentes d'un appel à l'autre.
    """

    def __init__(self):
        self._profils = {}
        self._verrou = threading.Lock()

    def _profil(self, cx, pid, nature):
        with self._verrou:
            if pid not in self._profils:
                lignes = cx.execute("SELECT ts, valeur FROM mesure WHERE point_id = ? AND qualite = 'valide' "
                                    "ORDER BY ts DESC LIMIT 193", (pid,)).fetchall()[::-1]
                self._profils[pid] = self._calculer(lignes, nature) if lignes else None
            return self._profils[pid]

    @staticmethod
    def _calculer(lignes, nature):
        dates = [_date(ts) for ts, _ in lignes]
        valeurs = [v for _, v in lignes]
        par_heure = {}
        if nature == "index":
            for i in range(1, len(valeurs)):
                if dates[i] - dates[i - 1] == timedelta(hours=1) and valeurs[i] >= valeurs[i - 1]:
                    par_heure.setdefault(dates[i].hour, []).append(valeurs[i] - valeurs[i - 1])
        else:
            for t, v in zip(dates[-168:], valeurs[-168:]):
                par_heure.setdefault(t.hour, []).append(v)
        profil = {h: sum(v) / len(v) for h, v in par_heure.items()}
        moyenne = sum(profil.values()) / len(profil) if profil else 0.0
        return dates[-1], valeurs[-1], {h: profil.get(h, moyenne) for h in range(24)}

    def mesures(self, cx, identifiant, debut, fin, maintenant=None):
        r = cx.execute("SELECT id, nature, unite FROM point_mesure WHERE (identifiant = ? OR id = ?) "
                       f"AND fluide NOT IN {db.SQL_METEO}", (identifiant, identifiant)).fetchone()
        if not r:
            return None
        pid, nature, unite = r
        fin = min(fin, _heure(maintenant))
        profil = self._profil(cx, pid, nature)
        t0 = profil[0] if profil else fin
        sortie = [{"ts": ts, "valeur": v} for ts, v in cx.execute(
            "SELECT ts, valeur FROM mesure WHERE point_id = ? AND ts > ? AND ts <= ? ORDER BY ts",
            (pid, debut.strftime(FMT), min(fin, t0).strftime(FMT)))]
        if profil:
            _, base, par_heure = profil
            t, valeur = t0, base
            while t < fin:
                t += timedelta(hours=1)
                valeur = valeur + par_heure[t.hour] if nature == "index" else par_heure[t.hour]
                if t > debut:
                    sortie.append({"ts": t.strftime(FMT), "valeur": round(valeur, 3)})
        return {"point": identifiant, "unite": unite, "mesures": sortie}
