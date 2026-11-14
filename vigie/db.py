"""Stockage local : SQLite, même modèle que sql/schema_timescaledb.sql.

Le référentiel (adresses, immeubles, compteurs), les réglages (règles, tarifs, prestataires) et le suivi
(alertes, bons de travaux) vivent dans la base. `referentiel(cx)` reconstruit le dictionnaire attendu
par le moteur, qui ne lit donc plus directement config/referentiel.json.

Import CSV des mesures : ts (UTC ISO), point_id, valeur
Contrôles à l'import (règles de qualité) :
  - point inconnu du référentiel -> rejeté
  - horodatage illisible ou valeur non numérique -> rejeté
  - doublon (point, ts) -> la dernière valeur l'emporte
  - valeur négative sur un index ou une consommation -> marquée 'suspecte'
"""
import csv
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS adresse (
  id TEXT PRIMARY KEY, rue TEXT NOT NULL, npa_localite TEXT NOT NULL,
  lat REAL, lon REAL, geo_source TEXT, geo_label TEXT);
CREATE TABLE IF NOT EXISTS immeuble (
  id TEXT PRIMARY KEY, adresse_id TEXT NOT NULL REFERENCES adresse(id), nom TEXT NOT NULL,
  profil TEXT NOT NULL, taux_occupation REAL, logements INTEGER, sre_m2 REAL,
  talon_horsgel_kwh_j REAL, proprietaire TEXT, remarque TEXT);
CREATE TABLE IF NOT EXISTS point_mesure (
  id TEXT PRIMARY KEY, immeuble_id TEXT REFERENCES immeuble(id), fluide TEXT NOT NULL, libelle TEXT NOT NULL,
  unite TEXT NOT NULL, nature TEXT NOT NULL, pas_min INTEGER NOT NULL, source TEXT NOT NULL,
  identifiant TEXT, fournisseur TEXT, etat TEXT NOT NULL DEFAULT 'actif');
CREATE TABLE IF NOT EXISTS mesure (
  ts TEXT NOT NULL, point_id TEXT NOT NULL, valeur REAL NOT NULL,
  qualite TEXT NOT NULL DEFAULT 'valide', lot_import TEXT,
  PRIMARY KEY (point_id, ts));
CREATE TABLE IF NOT EXISTS parametre (
  cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS regle (
  id TEXT PRIMARY KEY, active INTEGER, profils TEXT, seuil REAL, persistance INTEGER,
  gravite TEXT, delai TEXT, metier TEXT, consigne TEXT);
CREATE TABLE IF NOT EXISTS prestataire (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, metier TEXT NOT NULL, contact TEXT,
  email TEXT NOT NULL, telephone TEXT, perimetre TEXT NOT NULL DEFAULT '*', actif INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS alerte (
  id TEXT PRIMARY KEY, immeuble_id TEXT NOT NULL, point_id TEXT, cause TEXT NOT NULL, gravite TEXT NOT NULL,
  statut TEXT NOT NULL DEFAULT 'ouverte', ouverte_le TEXT NOT NULL, derniere_detection TEXT NOT NULL,
  cloturee_le TEXT, retour TEXT, retour_le TEXT, donnees TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evenement (
  id INTEGER PRIMARY KEY AUTOINCREMENT, le TEXT NOT NULL, immeuble_id TEXT NOT NULL, alerte_id TEXT, bon_id INTEGER,
  type TEXT NOT NULL, texte TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS evenement_immeuble ON evenement (immeuble_id, le);
CREATE TABLE IF NOT EXISTS declaration (
  id INTEGER PRIMARY KEY AUTOINCREMENT, immeuble_id TEXT NOT NULL, type TEXT NOT NULL, cause TEXT, point_id TEXT,
  debut TEXT NOT NULL, fin TEXT, motif TEXT NOT NULL, auteur TEXT, cree_le TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS declaration_immeuble ON declaration (immeuble_id);
CREATE TABLE IF NOT EXISTS bon (
  id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL, alerte_id TEXT NOT NULL,
  immeuble_id TEXT NOT NULL, prestataire_id INTEGER REFERENCES prestataire(id), statut TEXT NOT NULL,
  cree_le TEXT NOT NULL, envoye_le TEXT, cloture_le TEXT, destinataire TEXT, objet TEXT NOT NULL,
  corps TEXT NOT NULL, mode TEXT NOT NULL, journal TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS batiment (
  id TEXT PRIMARY KEY, immeuble_id TEXT NOT NULL REFERENCES immeuble(id), nom TEXT NOT NULL,
  annee_construction INTEGER, annee_renovation INTEGER, sre_m2 REAL, niveaux INTEGER, label TEXT,
  logements INTEGER, ouverture TEXT, remarque TEXT);
CREATE TABLE IF NOT EXISTS installation (
  id TEXT PRIMARY KEY, immeuble_id TEXT NOT NULL REFERENCES immeuble(id), type TEXT NOT NULL, libelle TEXT NOT NULL,
  vecteur TEXT, puissance_kw REAL, mise_en_service TEXT, retrait TEXT, remarque TEXT);
CREATE TABLE IF NOT EXISTS reference (
  serie TEXT NOT NULL, periode TEXT NOT NULL, valeur REAL NOT NULL, unite TEXT, source TEXT,
  PRIMARY KEY (serie, periode));
CREATE TABLE IF NOT EXISTS anomalie_import (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lot TEXT NOT NULL, type TEXT NOT NULL, feuille TEXT, ligne INTEGER,
  objet TEXT, periode TEXT, detail TEXT NOT NULL, traitement TEXT NOT NULL);
"""

NATURES = ("index", "intervalle", "instantane", "livraison")  # livraison : quantité livrée (bon de livraison, irrégulier)
PAS_MENSUEL = 43200  # relevé mensuel (30 jours nominaux) ; ts = fin du mois, soit le 1er du mois suivant à 00:00 UTC
QUALITES_MESURE = ("valide", "estimee", "suspecte")  # estimée par le distributeur : affichée, exclue des décisions
FLUIDES = {
    "electricite": ("Électricité", "kWh", "intervalle"),
    "chaleur": ("Chaleur", "kWh", "intervalle"),
    "cad": ("Chauffage à distance (CAD)", "kWh", "intervalle"),
    "eau": ("Eau froide", "m3", "index"),
    "eau_chaude": ("Eau chaude sanitaire", "m3", "intervalle"),
    "pac_electricite": ("PAC — électricité", "kWh", "intervalle"),
    "pac_chaleur": ("PAC — chaleur produite (totale)", "kWh", "intervalle"),
    "pac_chaleur_chauffage": ("PAC — chaleur chauffage", "kWh", "intervalle"),
    "pac_chaleur_ecs": ("PAC — chaleur eau chaude", "kWh", "intervalle"),
    "gaz": ("Gaz", "kWh", "index"),
    "electricite_injection": ("Électricité injectée dans le réseau", "kWh", "intervalle"),
    "electricite_sous_compteur": ("Électricité — sous-compteur", "kWh", "intervalle"),
    "mazout": ("Mazout", "l", "instantane"),
    "granules": ("Bois (granulés)", "kg", "livraison"),
    "cad_debit": ("CAD — débit de la sous-station", "m3/h", "instantane"),
    "cad_temperature_aller": ("CAD — température aller", "degC", "instantane"),
    "cad_temperature_retour": ("CAD — température retour", "degC", "instantane"),
    "solaire": ("Production solaire (photovoltaïque)", "kWh", "intervalle"),
    "meteo": ("Température extérieure", "degC", "instantane"),
    "rayonnement": ("Rayonnement solaire global", "W/m2", "instantane"),
}
# Grandeurs météo du parc (sans immeuble) : jamais prises pour la fin des relevés des compteurs ni reliées à l'API
FLUIDES_METEO = ("meteo", "rayonnement")
SQL_METEO = "('meteo', 'rayonnement')"
# Caractéristiques d'une installation solaire (colonnes du point de mesure de fluide « solaire »)
SOLAIRE_CHAMPS = ("puissance_crete_kwc", "production_prevue_kwh_an", "mise_en_service", "degradation_pct_an")
DEGRADATION_DEFAUT = 0.5  # % de production perdue par an d'utilisation (garantie usuelle des modules : 0,4 à 0,8 %/an)
ETATS_POINT = ("actif", "a_connecter", "inactif")
PROFILS_LIBELLES = {
    "Habite": "Occupation normale. Eau quasi nulle la nuit, chauffage selon la météo.",
    "Vide": "Aucun occupant. Eau ≈ 0, électricité = talon technique, chauffage hors-gel.",
    "Partiel": "Occupation partielle : attendus pondérés par le taux d'occupation.",
    "Travaux": "Alertes énergie suspendues, fuites et défauts de données maintenus.",
}


# Colonnes ajoutées après la création de bases existantes : ajoutées à l'ouverture, sans perte de données
MIGRATIONS = {
    "adresse": [("lat", "REAL"), ("lon", "REAL"), ("geo_source", "TEXT"), ("geo_label", "TEXT"),
                ("x_km", "REAL"), ("y_km", "REAL")],  # position sur le plan d'un jeu fictif (km) : sert à calculer lat / lon
    "immeuble": [("gestionnaire", "TEXT"), ("gestionnaire_email", "TEXT"), ("gestionnaire_tel", "TEXT"),
                 ("concierge", "TEXT"), ("concierge_email", "TEXT"), ("concierge_tel", "TEXT"), ("technique", "TEXT"),
                 ("typologie", "TEXT"), ("quartier", "TEXT")],
    "bon": [("destinataire_type", "TEXT"), ("destinataire_nom", "TEXT"), ("retour_resultat", "TEXT"),
            ("retour_texte", "TEXT"), ("retour_le", "TEXT")],
    "point_mesure": [("puissance_crete_kwc", "REAL"), ("production_prevue_kwh_an", "REAL"), ("mise_en_service", "INTEGER"),
                     ("degradation_pct_an", "REAL"),
                     # rôle du compteur dans le site et bornes de service (mois inclusifs AAAA-MM)
                     ("niveau", "TEXT"), ("parent_id", "TEXT"), ("service_debut", "TEXT"), ("service_fin", "TEXT"),
                     ("releve", "TEXT")],
}


def connecter(chemin):
    cx = sqlite3.connect(chemin, check_same_thread=False)
    cx.execute("PRAGMA foreign_keys = ON")
    cx.executescript(SCHEMA)
    for table, colonnes in MIGRATIONS.items():
        existantes = {r[1] for r in cx.execute(f"PRAGMA table_info({table})")}
        for nom, type_sql in colonnes:
            if nom not in existantes:
                cx.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {type_sql}")
    cx.commit()
    return cx


def lignes(cx, sql, args=()):
    cur = cx.execute(sql, args)
    noms = [d[0] for d in cur.description]
    return [dict(zip(noms, r)) for r in cur.fetchall()]


def id_adresse(rue, npa_localite):
    """Identifiant stable d'une adresse, dérivé de la rue et de la localité."""
    brut = f"{rue}-{npa_localite}".lower()
    for a, b in (("éèêë", "e"), ("àâä", "a"), ("ôö", "o"), ("ûüù", "u"), ("îï", "i"), ("ç", "c")):
        for c in a:
            brut = brut.replace(c, b)
    return re.sub(r"[^a-z0-9]+", "-", brut).strip("-")[:60]


# ---------------------------------------------------------------- paramètres


def lire_parametre(cx, cle, defaut=None):
    r = cx.execute("SELECT valeur FROM parametre WHERE cle = ?", (cle,)).fetchone()
    return json.loads(r[0]) if r else defaut


def ecrire_parametre(cx, cle, valeur):
    cx.execute("INSERT OR REPLACE INTO parametre VALUES (?, ?)", (cle, json.dumps(valeur, ensure_ascii=False)))
    cx.commit()


# ---------------------------------------------------------------- référentiel


def charger_referentiel(cx, ref, prestataires=None):
    """Remplace le parc par celui du fichier JSON (données d'exemple) et pose les paramètres par défaut."""
    cx.execute("DELETE FROM point_mesure")
    cx.execute("DELETE FROM batiment")
    cx.execute("DELETE FROM installation")
    cx.execute("DELETE FROM immeuble")
    cx.execute("DELETE FROM adresse")
    for im in ref["immeubles"]:
        aid = id_adresse(im["adresse"], im["npa"])
        cx.execute("INSERT OR IGNORE INTO adresse (id, rue, npa_localite, lat, lon, geo_source, geo_label) "
                   "VALUES (?,?,?,?,?,?,?)", (aid, im["adresse"], im["npa"], im.get("lat"), im.get("lon"),
                                               im.get("geo_source"), im.get("geo_label")))
        cx.execute("INSERT INTO immeuble (id, adresse_id, nom, profil, taux_occupation, logements, talon_horsgel_kwh_j)"
                   " VALUES (?,?,?,?,?,?,?)", (im["id"], aid, im["nom"], im["profil"], im.get("taux_occupation"),
                                                im.get("logements"), im.get("talon_horsgel_kwh_j")))
        for p in im["points"]:
            cx.execute("INSERT INTO point_mesure (id, immeuble_id, fluide, libelle, unite, nature, pas_min, source, etat, "
                       f"{', '.join(SOLAIRE_CHAMPS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (p["id"], im["id"], p["fluide"], p["libelle"], p["unite"], p["nature"], p["pas_min"], p["source"],
                        p.get("etat", "actif"), *(p.get(c) for c in SOLAIRE_CHAMPS)))
    for m in (ref["meteo"], ref.get("rayonnement")):
        if m:
            cx.execute("INSERT INTO point_mesure (id, immeuble_id, fluide, libelle, unite, nature, pas_min, source, etat)"
                       " VALUES (?,?,?,?,?,?,?,?, 'actif')", (m["id"], None, m["fluide"], m["libelle"], m["unite"],
                                                              m["nature"], m["pas_min"], m["source"]))
    for cle in ("parametres", "tarifs", "facteurs_co2_kg_par_kwh"):
        if lire_parametre(cx, cle) is None:
            ecrire_parametre(cx, cle, ref[cle])
    if prestataires is not None:
        cx.execute("DELETE FROM prestataire")
        for p in prestataires:
            cx.execute("INSERT INTO prestataire (nom, metier, contact, email, telephone, perimetre) VALUES (?,?,?,?,?,?)",
                       (p["nom"], p["metier"], p.get("contact"), p["email"], p.get("telephone"), p.get("perimetre", "*")))
    cx.commit()


def referentiel(cx, defauts):
    """Dictionnaire attendu par moteur.analyser(), construit depuis la base.

    `defauts` = contenu de config/referentiel.json (paramètres, tarifs et facteurs de repli).
    Seuls les points à l'état 'actif' sont analysés ; 'a_connecter' et 'inactif' sont ignorés.
    """
    ref = {
        "parametres": {**defauts["parametres"], **(lire_parametre(cx, "parametres") or {})},
        # vecteurs ajoutés depuis l'enregistrement des coûts (ex. CAD, gaz) : valeurs du référentiel
        "tarifs": {**defauts.get("tarifs", {}), **(lire_parametre(cx, "tarifs") or {})},
        "facteurs_co2_kg_par_kwh": {**defauts.get("facteurs_co2_kg_par_kwh", {}),
                                    **(lire_parametre(cx, "facteurs_co2_kg_par_kwh") or {})},
        "profils": PROFILS_LIBELLES,
        "immeubles": [],
        "meteo": None,
        "rayonnement": None,
        "regles": lire_regles(cx),
    }
    for im in lignes(cx, "SELECT i.*, a.rue AS adresse, a.npa_localite AS npa FROM immeuble i "
                         "JOIN adresse a ON a.id = i.adresse_id ORDER BY a.rue, i.nom"):
        im["points"] = lignes(cx, "SELECT * FROM point_mesure WHERE immeuble_id = ? AND etat = 'actif' ORDER BY id",
                              (im["id"],))
        ref["immeubles"].append(im)
    for fluide in FLUIDES_METEO:  # température extérieure et rayonnement solaire de référence du parc
        m = lignes(cx, "SELECT * FROM point_mesure WHERE fluide = ? AND etat = 'actif' ORDER BY id LIMIT 1", (fluide,))
        ref[fluide] = m[0] if m else None
    return ref


def lire_regles(cx):
    out = {}
    for r in lignes(cx, "SELECT * FROM regle"):
        rid = r.pop("id")
        if r.get("profils") is not None:
            r["profils"] = [p for p in r["profils"].split(",") if p]
        if r.get("active") is not None:
            r["active"] = bool(r["active"])
        out[rid] = {k: v for k, v in r.items() if v is not None}
    return out


# ---------------------------------------------------------------- mesures


def normaliser_ts(texte):
    """Horodatage ISO -> 'AAAA-MM-JJTHH:MM:SSZ' en UTC. Sans fuseau, il est lu en UTC (format d'import documenté).

    Un format non ISO (ex. 01.11.2026 00:00) est refusé : il ne doit jamais entrer en base et bloquer l'analyse.
    """
    t = str(texte).strip()
    if len(t) < 19 or t[4] != "-" or t[10] not in "T ":
        raise ValueError(t)
    d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def importer_csv(cx, chemin):
    with open(chemin, encoding="utf-8-sig") as f:
        return importer_mesures(cx, f)


def importer_mesures(cx, flux):
    """Importe des mesures depuis un flux texte CSV (séparateur , ou ;). Retourne (ok, rejets, lot)."""
    debut = flux.read(4096)
    flux.seek(0)
    sep = ";" if debut.count(";") > debut.count(",") else ","
    return _importer_lignes(cx, enumerate(csv.DictReader(flux, delimiter=sep), start=2))


EXCEL_ORIGINE = datetime(1899, 12, 30)  # jour 0 des dates Excel (système 1900)


def _ts_excel(v):
    """Cellule ts d'un classeur : texte ISO tel quel, ou date Excel (nombre de jours) lue en UTC, à la seconde près."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (EXCEL_ORIGINE + timedelta(seconds=round(v * 86400))).strftime("%Y-%m-%dT%H:%M:%SZ")
    return v


def importer_xlsx(cx, contenu):
    """Importe la feuille « mesures » (sinon la première) d'un classeur .xlsx : colonnes ts, point_id, valeur."""
    from . import excel
    feuilles = excel.lire_xlsx(contenu)
    if not feuilles:
        raise excel.ErreurExcel("Le classeur ne contient aucune feuille.")
    nom = next((f for f in feuilles if f.strip().lower() == "mesures"), next(iter(feuilles)))
    lignes = feuilles[nom]
    entetes = [str(c or "").strip().lower() for c in (lignes[0] if lignes else [])]
    if not {"ts", "point_id", "valeur"} <= set(entetes):
        raise excel.ErreurExcel(f"Feuille « {nom} » : la première ligne doit contenir les colonnes ts, point_id, valeur.")

    def dicts():
        for n, ligne in enumerate(lignes[1:], start=2):
            if not any(c not in (None, "") for c in ligne):
                continue
            d = {k: (ligne[i] if i < len(ligne) else None) for i, k in enumerate(entetes)}
            yield n, {"ts": _ts_excel(d["ts"]), "point_id": str(d["point_id"] or "").strip(), "valeur": d["valeur"]}
    return _importer_lignes(cx, dicts())


def _importer_lignes(cx, lignes):
    """Cœur commun CSV / Excel : `lignes` = (n° de ligne, {ts, point_id, valeur})."""
    points = {r[0]: r[1] for r in cx.execute("SELECT id, nature FROM point_mesure")}
    lot = "lot-" + uuid.uuid4().hex[:8]
    ok, rejets, lots, vus = 0, [], [], set()
    for n, ligne in lignes:
        pid = (ligne.get("point_id") or "").strip()
        if pid not in points:
            rejets.append((n, "point inconnu : " + pid))
            continue
        try:
            v = float(str(ligne["valeur"]).replace(",", "."))
            if not math.isfinite(v):
                raise ValueError
            ts = normaliser_ts(ligne["ts"])
        except (ValueError, KeyError, AttributeError, TypeError):
            rejets.append((n, "valeur ou horodatage illisible (attendu : 2026-11-11T06:00:00Z)"))
            continue
        qualite = "suspecte" if (v < 0 and points[pid] != "instantane") else "valide"
        lots.append((ts, pid, v, qualite, lot))
        vus.add(pid)
        ok += 1
    cx.executemany("INSERT OR REPLACE INTO mesure VALUES (?,?,?,?,?)", lots)
    # Un compteur « à connecter » qui reçoit ses premières données devient actif
    cx.executemany("UPDATE point_mesure SET etat = 'actif' WHERE id = ? AND etat = 'a_connecter'", [(p,) for p in vus])
    cx.commit()
    return ok, rejets, lot


def mois_attendus(premiere, fin):
    """Relevés mensuels attendus sur les 12 derniers mois, depuis le premier relevé du compteur (au moins 1)."""
    d0, d1 = datetime.strptime(premiere[:10], "%Y-%m-%d"), datetime.strptime(fin[:10], "%Y-%m-%d")
    return max(1, min(12, (d1.year - d0.year) * 12 + d1.month - d0.month + 1))


def etat_points(cx):
    """Première et dernière mesure, nombre de mesures sur 30 jours et sur 12 mois, par point."""
    # Dernier relevé d'un compteur (la météo, plus fraîche, ne doit pas faire paraître les compteurs muets)
    fin = cx.execute("SELECT max(m.ts) FROM mesure m JOIN point_mesure p ON p.id = m.point_id "
                     f"WHERE p.fluide NOT IN {SQL_METEO}").fetchone()[0] or cx.execute("SELECT max(ts) FROM mesure").fetchone()[0]
    if not fin:
        return {}, None
    out = {}
    for pid, derniere, premiere, n30, n12m in cx.execute(
            "SELECT point_id, max(ts), min(ts), sum(CASE WHEN julianday(?) - julianday(ts) <= 30 THEN 1 ELSE 0 END), "
            "sum(CASE WHEN julianday(?) - julianday(ts) < 365 THEN 1 ELSE 0 END) FROM mesure GROUP BY point_id",
            (fin, fin)):
        out[pid] = {"derniere": derniere, "premiere": premiere, "mesures_30j": n30, "mesures_12m": n12m}
    return out, fin
