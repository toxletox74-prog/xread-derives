"""Gestion du parc : adresses, immeubles, compteurs, prestataires, règles et coûts.

Toutes les saisies (interface ou Excel) passent par les fonctions `valider_*` : une saisie invalide lève
ErreurSaisie avec un message compréhensible par le gestionnaire. Rien n'est supprimé par un import Excel :
les lignes sont ajoutées ou mises à jour, jamais effacées.
"""
import json
import math
import re
import unicodedata

from . import db, excel, geo, moteur, regles

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[A-Za-z]{2,}$")
UNITES = ("kWh", "m3", "degC", "kW", "l", "W/m2", "kg", "m3/h")
PAS = (1, 5, 10, 15, 30, 60, 1440, db.PAS_MENSUEL)
MOIS_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Rôle du compteur dans le site et bornes de service : colonnes conservées quand la saisie ne les fournit pas
POINT_SERVICE = ("niveau", "parent_id", "service_debut", "service_fin", "releve")
SOURCES = ["M-Bus (passerelle filaire)", "wM-Bus / OMS (radio)", "LoRaWAN", "Export DLMS du GRD (CSV)",
           "Modbus TCP", "BACnet", "Import CSV manuel", "Relevé manuel / facture",
           "API du fournisseur"]  # = connecteur.SOURCE_API : relevés tirés par la connexion API (Réglages)
# Pas de temps : les données arrivent au mieux à l'heure (CLAUDE.md §5). Toutes les règles fonctionnent au pas horaire ;
# au-delà, ce qui est perdu dépend du fluide (mesuré par la campagne d'évaluation).
PAS_DEFAUT = 60
PAS_MAX = {f: 60 for f in ("electricite", "pac_electricite", "eau", "chaleur", "cad", "gaz", "pac_chaleur",
                           "pac_chaleur_chauffage", "pac_chaleur_ecs", "solaire", "meteo", "rayonnement")}
PERTE_PAS_GROSSIER = {
    "eau": "La fuite de nuit (1 h – 5 h) ne peut pas être jugée au pas journalier : c'est le niveau de base "
           "(minimum sur 7 jours) qui est surveillé, avec l'eau d'un immeuble vide.",
    "electricite": "L'électricité de nuit n'est pas surveillée au-delà du pas horaire.",
    "pac_electricite": "La PAC n'est pas surveillée au-delà du pas horaire (rendement jugé heure par heure).",
    "pac_chaleur": "La PAC n'est pas surveillée au-delà du pas horaire (rendement jugé heure par heure).",
    "pac_chaleur_chauffage": "La PAC n'est pas surveillée au-delà du pas horaire (rendement jugé heure par heure).",
    "pac_chaleur_ecs": "La PAC n'est pas surveillée au-delà du pas horaire (rendement jugé heure par heure).",
    "chaleur": "Au pas journalier, seules la signature et le chauffage d'un immeuble vide restent surveillés "
               "(sans abaissement nocturne visible).",
    "cad": "Au pas journalier, seules la signature et le chauffage d'un immeuble vide restent surveillés.",
    "gaz": "Au pas journalier, seules la signature et le chauffage d'un immeuble vide restent surveillés.",
    "meteo": "La signature de chauffage et la PAC demandent la température horaire.",
    "solaire": "Au-delà du pas horaire, la production solaire n'est pas surveillée (comparée heure par heure au "
               "rayonnement).",
    "rayonnement": "La surveillance de la production solaire demande le rayonnement horaire.",
}


class ErreurSaisie(ValueError):
    pass


# ---------------------------------------------------------------- normalisation


def _cle(texte):
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _texte(v, champ, obligatoire=False, maxi=200):
    t = "" if v is None else str(v).strip()
    if obligatoire and not t:
        raise ErreurSaisie(f"« {champ} » est obligatoire.")
    if len(t) > maxi:
        raise ErreurSaisie(f"« {champ} » est trop long ({maxi} caractères au maximum).")
    return t or None


def _nombre(v, champ, mini=None, maxi=None, entier=False):
    if v is None or str(v).strip() == "":
        return None
    try:
        n = float(str(v).replace(",", ".").replace("'", "").replace(" ", ""))
        if not math.isfinite(n):
            raise ValueError
    except ValueError:
        raise ErreurSaisie(f"« {champ} » doit être un nombre.") from None
    if (mini is not None and n < mini) or (maxi is not None and n > maxi):
        raise ErreurSaisie(f"« {champ} » doit être compris entre {mini} et {maxi}.")
    return int(n) if entier else n


def _identifiant(v, champ):
    t = _texte(v, champ, obligatoire=True, maxi=40)
    if not ID_RE.match(t):
        raise ErreurSaisie(f"« {champ} » ne doit contenir que des lettres sans accent, des chiffres, - ou _ (ex. T8_EAU).")
    return t


PROFILS_SYNONYMES = {"habite": "Habite", "occupe": "Habite", "habitation": "Habite", "vide": "Vide", "vacant": "Vide",
                     "inoccupe": "Vide", "partiel": "Partiel", "partiellement_occupe": "Partiel", "travaux": "Travaux",
                     "renovation": "Travaux", "chantier": "Travaux"}
FLUIDES_SYNONYMES = {_cle(lib): k for k, (lib, _, _) in db.FLUIDES.items()}
FLUIDES_SYNONYMES.update({k: k for k in db.FLUIDES})
FLUIDES_SYNONYMES.update({
    "elec": "electricite", "electricite_generale": "electricite", "courant": "electricite",
    "chauffage": "chaleur", "cad": "cad", "chauffage_a_distance": "cad", "chauffage_a_distance_cad": "cad",
    "gaz_naturel": "gaz",
    "eau_froide": "eau", "ef": "eau", "ecs": "eau_chaude",
    "pac_elec": "pac_electricite", "pac_electricite": "pac_electricite", "pac_chaleur": "pac_chaleur",
    "pac_chaleur_totale": "pac_chaleur", "pac_chauffage": "pac_chaleur_chauffage", "pac_ecs": "pac_chaleur_ecs",
    "pac_eau_chaude": "pac_chaleur_ecs",
    "temperature": "meteo", "temperature_exterieure": "meteo", "fioul": "mazout",
    "pv": "solaire", "photovoltaique": "solaire", "production_solaire": "solaire", "panneaux_solaires": "solaire",
    "solaire_photovoltaique": "solaire", "rayonnement_global": "rayonnement", "ensoleillement": "rayonnement",
    "irradiation": "rayonnement", "rayonnement_solaire": "rayonnement"})
ETATS_SYNONYMES = {"actif": "actif", "connecte": "actif", "oui": "actif", "a_connecter": "a_connecter",
                   "en_attente": "a_connecter", "inactif": "inactif", "non": "inactif", "hors_service": "inactif"}


def _profil(v):
    p = PROFILS_SYNONYMES.get(_cle(v))
    if not p:
        raise ErreurSaisie("Profil inconnu : choisir Habité, Partiel, Vide ou Travaux.")
    return p


# ---------------------------------------------------------------- validation


def valider_immeuble(d):
    im = {
        "id": _identifiant(d.get("id"), "Code immeuble"),
        "nom": _texte(d.get("nom"), "Nom de l'immeuble", obligatoire=True, maxi=120),
        "rue": _texte(d.get("rue"), "Rue et numéro", obligatoire=True, maxi=120),
        "npa_localite": _texte(d.get("npa_localite"), "NPA et localité", obligatoire=True, maxi=80),
        "profil": _profil(d.get("profil") or "Habite"),
        "taux_occupation": _nombre(d.get("taux_occupation"), "Taux d'occupation", 0, 100),
        "logements": _nombre(d.get("logements"), "Logements", 0, 5000, entier=True),
        "sre_m2": _nombre(d.get("sre_m2"), "Surface de référence énergétique", 0, 1e6),
        "talon_horsgel_kwh_j": _nombre(d.get("talon_horsgel_kwh_j"), "Talon hors-gel", 0, 1e5),
        "proprietaire": _texte(d.get("proprietaire"), "Propriétaire", maxi=120),
        "remarque": _texte(d.get("remarque"), "Remarque", maxi=500),
    }
    if im["taux_occupation"] is not None and im["taux_occupation"] > 1:
        im["taux_occupation"] = im["taux_occupation"] / 100  # saisi en %
    if im["profil"] == "Partiel" and im["taux_occupation"] is None:
        raise ErreurSaisie("Un immeuble partiellement occupé doit avoir un taux d'occupation.")
    lat, lon = d.get("latitude"), d.get("longitude")
    if str(lat or "").strip() or str(lon or "").strip():
        try:
            im["latitude"], im["longitude"] = geo.valider_coordonnees(lat, lon)
        except geo.ErreurGeo as e:
            raise ErreurSaisie(str(e)) from None
    else:
        im["latitude"] = im["longitude"] = None
    return im


def valider_point(d, immeubles_connus):
    fluide = FLUIDES_SYNONYMES.get(_cle(d.get("fluide")))
    if not fluide:
        raise ErreurSaisie("Fluide inconnu : " + ", ".join(lib for lib, _, _ in db.FLUIDES.values()) + ".")
    lib, unite_def, nature_def = db.FLUIDES[fluide]
    immeuble_id = _texte(d.get("immeuble_id"), "Immeuble", obligatoire=fluide not in db.FLUIDES_METEO, maxi=40)
    if immeuble_id and immeuble_id not in immeubles_connus:
        raise ErreurSaisie(f"Immeuble inconnu : {immeuble_id}. Créez d'abord l'immeuble.")
    unite = _texte(d.get("unite"), "Unité", maxi=10) or unite_def
    unite = {"m³": "m3", "kwh": "kWh", "°c": "degC", "kw": "kW", "w/m2": "W/m2", "w/m²": "W/m2", "litre": "l",
             "litres": "l"}.get(unite.lower(), unite)
    if unite not in UNITES:
        raise ErreurSaisie("Unité inconnue : kWh, m3, degC, kW, l, W/m2, kg ou m3/h.")
    nature = _cle(d.get("nature")) or nature_def
    if nature not in db.NATURES:
        raise ErreurSaisie("Nature inconnue : index (compteur cumulé), intervalle (consommation du pas), instantane "
                           "ou livraison (bon de livraison).")
    pas = _nombre(d.get("pas_min"), "Pas de temps", 1, db.PAS_MENSUEL, entier=True) or PAS_DEFAUT
    if pas not in PAS:
        raise ErreurSaisie("Pas de temps : 1, 5, 10, 15, 30, 60, 1440 (journalier) ou 43200 (mensuel) minutes.")
    for cle in ("service_debut", "service_fin"):
        if str(d.get(cle) or "").strip() and not MOIS_RE.match(str(d[cle]).strip()):
            raise ErreurSaisie("Bornes de service du compteur : mois au format AAAA-MM.")
    etat = ETATS_SYNONYMES.get(_cle(d.get("etat")) or "a_connecter")
    if not etat:
        raise ErreurSaisie("État : actif, à connecter ou inactif.")
    return {
        "id": _identifiant(d.get("id"), "Code compteur"),
        "immeuble_id": immeuble_id, "fluide": fluide,
        "libelle": _texte(d.get("libelle"), "Libellé", maxi=120) or lib,
        "unite": unite, "nature": nature, "pas_min": pas,
        "source": _texte(d.get("source"), "Connexion", maxi=120) or "Import CSV manuel",
        "identifiant": _texte(d.get("identifiant"), "Identifiant du compteur", maxi=120),
        "fournisseur": _texte(d.get("fournisseur"), "Fournisseur", maxi=120),
        "etat": etat,
        **valider_solaire(d, fluide),
        **{c: _texte(d[c], c, maxi=120) for c in POINT_SERVICE if c in d},
    }


def valider_solaire(d, fluide):
    """Caractéristiques d'une installation solaire : puissance crête (obligatoire), production prévue, année de mise
    en service et décote annuelle des modules. Vides pour les autres fluides."""
    if fluide != "solaire":
        return {c: None for c in db.SOLAIRE_CHAMPS}
    out = {"puissance_crete_kwc": _nombre(d.get("puissance_crete_kwc"), "Puissance crête (kWc)", 0.1, 100000),
           "production_prevue_kwh_an": _nombre(d.get("production_prevue_kwh_an"), "Production prévue (kWh/an)", 0, 1e8),
           "mise_en_service": _nombre(d.get("mise_en_service"), "Année de mise en service", 1980, 2100, entier=True),
           "degradation_pct_an": _nombre(d.get("degradation_pct_an"), "Décote annuelle (%/an)", 0, 5)}
    if out["puissance_crete_kwc"] is None:
        raise ErreurSaisie("« Puissance crête (kWc) » est obligatoire pour une installation solaire.")
    return out


def avertissements_point(p):
    out = []
    pmax = PAS_MAX.get(p["fluide"])
    if p["pas_min"] >= db.PAS_MENSUEL:
        out.append(f"{p['id']} : relevé mensuel. Consommations et qualité des données suivies ; gaz et PAC comparés "
                   "au même mois des années précédentes ; les règles horaires et journalières (fuite de nuit, "
                   "signature de chauffage, rendement de la PAC, solaire) ne s'appliquent pas à ce pas de temps.")
    elif pmax and p["pas_min"] > pmax:
        out.append(f"{p['id']} : pas de {p['pas_min']} min trop grossier pour détecter toutes les dérives "
                   f"({p['fluide']} : {pmax} min au maximum). " + PERTE_PAS_GROSSIER.get(p["fluide"], ""))
    if p["fluide"] == "gaz" and p.get("unite") == "m3" and p["pas_min"] < db.PAS_MENSUEL:
        out.append(f"{p['id']} : gaz en m³ converti en kWh avec le pouvoir calorifique du référentiel "
                   "(gaz_pcs_kwh_par_m3, valeur d'exemple à remplacer par celle du distributeur).")
    if p["fluide"] == "solaire" and not p.get("production_prevue_kwh_an"):
        out.append(f"{p['id']} : production prévue (kWh/an) non renseignée : pas de référence nominale pour une "
                   "installation sans historique, ni de projection sur 12 mois.")
    if p["fluide"] == "solaire" and not p.get("mise_en_service"):
        out.append(f"{p['id']} : année de mise en service non renseignée : l'âge des modules est inconnu. La décote "
                   "est déduite entre l'historique et aujourd'hui, mais pas dans la référence nominale (installation "
                   "sans historique), qui est alors trop indulgente.")
    if p["fluide"] in ("mazout", "eau_chaude") and p["pas_min"] < db.PAS_MENSUEL:
        out.append(f"{p['id']} : fluide surveillé pour la qualité des données uniquement (pas encore de détecteur de dérive).")
    return out


def valider_prestataire(d, immeubles_connus):
    metier = _texte(d.get("metier"), "Métier", obligatoire=True, maxi=60)
    connu = {_cle(m): m for m in moteur.METIERS}
    metier = connu.get(_cle(metier), metier)
    email = _texte(d.get("email"), "E-mail", obligatoire=True, maxi=160)
    if not EMAIL_RE.match(email):
        raise ErreurSaisie(f"Adresse e-mail invalide : {email}")
    perimetre = _texte(d.get("perimetre"), "Immeubles couverts", maxi=500) or "*"
    if perimetre.strip().lower() in ("*", "tous", "tout le parc"):
        perimetre = "*"
    else:
        ids = [x.strip() for x in re.split(r"[,;\s]+", perimetre) if x.strip()]
        inconnus = [x for x in ids if x not in immeubles_connus]
        if inconnus:
            raise ErreurSaisie("Immeubles inconnus dans le périmètre : " + ", ".join(inconnus))
        perimetre = ",".join(ids)
    return {"nom": _texte(d.get("nom"), "Nom de l'entreprise", obligatoire=True, maxi=120), "metier": metier,
            "contact": _texte(d.get("contact"), "Personne de contact", maxi=120), "email": email,
            "telephone": _texte(d.get("telephone"), "Téléphone", maxi=40), "perimetre": perimetre,
            "actif": 0 if str(d.get("actif", 1)).lower() in ("0", "false", "non") else 1}


# ---------------------------------------------------------------- lecture


def immeubles_connus(cx):
    return {r[0] for r in cx.execute("SELECT id FROM immeuble")}


def completude_point(p, fin):
    """Part des relevés attendus reçus : sur 30 jours, ou sur 12 mois (depuis le premier relevé) pour un compteur
    mensuel. None sans données, ou pour des bons de livraison (irréguliers par nature)."""
    if not fin or p.get("nature") == "livraison":
        return None
    if p["pas_min"] >= db.PAS_MENSUEL:
        if not p.get("premiere"):
            return 0.0
        return round(min(1.0, (p.get("mesures_12m") or 0) / db.mois_attendus(p["premiere"], fin)), 3)
    return round(min(1.0, (p.get("mesures_30j") or 0) / (30 * 24 * 60 / p["pas_min"])), 3)


def arbre(cx):
    """Parc → adresses → immeubles → compteurs, avec l'état des données et des alertes ouvertes."""
    etats, fin = db.etat_points(cx)
    alertes = {}
    for a in db.lignes(cx, "SELECT id, immeuble_id, point_id, gravite FROM alerte WHERE statut = 'ouverte'"):
        alertes.setdefault(a["point_id"], []).append(a["gravite"])
    adresses = db.lignes(cx, "SELECT * FROM adresse ORDER BY rue")
    for ad in adresses:
        ad["immeubles"] = db.lignes(cx, "SELECT * FROM immeuble WHERE adresse_id = ? ORDER BY nom", (ad["id"],))
        for im in ad["immeubles"]:
            im["points"] = db.lignes(cx, "SELECT * FROM point_mesure WHERE immeuble_id = ? ORDER BY fluide, id", (im["id"],))
            for p in im["points"]:
                p.update(etats.get(p["id"], {"derniere": None, "premiere": None, "mesures_30j": 0, "mesures_12m": 0}))
                p["completude"] = completude_point(p, fin)
                p["alertes"] = alertes.get(p["id"], [])
                p["avertissements"] = avertissements_point(p)
    meteo = db.lignes(cx, f"SELECT * FROM point_mesure WHERE fluide IN {db.SQL_METEO} "
                          "ORDER BY fluide, etat != 'actif', id")
    for p in meteo:
        p.update(etats.get(p["id"], {"derniere": None, "mesures_30j": 0}))
    return {"adresses": adresses, "meteo": meteo, "fin_donnees": fin}


# ---------------------------------------------------------------- écriture


def enregistrer_immeuble(cx, d):
    im = valider_immeuble(d)
    aid = db.id_adresse(im["rue"], im["npa_localite"])
    cx.execute("INSERT OR IGNORE INTO adresse (id, rue, npa_localite) VALUES (?,?,?)", (aid, im["rue"], im["npa_localite"]))
    if im.get("latitude") is not None:  # coordonnées saisies à la main : prioritaires, jamais écrasées
        cx.execute("UPDATE adresse SET lat = ?, lon = ?, geo_source = 'manuel', geo_label = NULL WHERE id = ?",
                   (im["latitude"], im["longitude"], aid))
    cx.execute("""INSERT INTO immeuble (id, adresse_id, nom, profil, taux_occupation, logements, sre_m2,
                  talon_horsgel_kwh_j, proprietaire, remarque) VALUES (?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET adresse_id=excluded.adresse_id, nom=excluded.nom,
                  profil=excluded.profil, taux_occupation=excluded.taux_occupation, logements=excluded.logements,
                  sre_m2=excluded.sre_m2, talon_horsgel_kwh_j=excluded.talon_horsgel_kwh_j,
                  proprietaire=excluded.proprietaire, remarque=excluded.remarque""",
               (im["id"], aid, im["nom"], im["profil"], im["taux_occupation"], im["logements"], im["sre_m2"],
                im["talon_horsgel_kwh_j"], im["proprietaire"], im["remarque"]))
    _nettoyer_adresses(cx)
    cx.commit()
    return im


def _nettoyer_adresses(cx):
    cx.execute("DELETE FROM adresse WHERE id NOT IN (SELECT adresse_id FROM immeuble)")


def supprimer_immeuble(cx, iid):
    """Supprime l'immeuble, ses compteurs et leurs mesures. Les bons de travaux restent dans l'historique."""
    pts = [r[0] for r in cx.execute("SELECT id FROM point_mesure WHERE immeuble_id = ?", (iid,))]
    cx.executemany("DELETE FROM mesure WHERE point_id = ?", [(p,) for p in pts])
    cx.execute("DELETE FROM point_mesure WHERE immeuble_id = ?", (iid,))
    cx.execute("DELETE FROM batiment WHERE immeuble_id = ?", (iid,))
    cx.execute("DELETE FROM installation WHERE immeuble_id = ?", (iid,))
    cx.execute("DELETE FROM alerte WHERE immeuble_id = ?", (iid,))
    cx.execute("DELETE FROM declaration WHERE immeuble_id = ?", (iid,))
    n = cx.execute("DELETE FROM immeuble WHERE id = ?", (iid,)).rowcount
    _nettoyer_adresses(cx)
    cx.commit()
    if not n:
        raise ErreurSaisie("Immeuble introuvable.")


def enregistrer_point(cx, d):
    p = valider_point(d, immeubles_connus(cx))
    # rôle et bornes de service : une saisie qui ne les mentionne pas (formulaire) conserve ceux de la base
    existant = db.lignes(cx, f"SELECT {', '.join(POINT_SERVICE)} FROM point_mesure WHERE id = ?", (p["id"],))
    p = {**{c: (existant[0][c] if existant else None) for c in POINT_SERVICE}, **p}
    champs = ("id", "immeuble_id", "fluide", "libelle", "unite", "nature", "pas_min", "source", "identifiant",
              "fournisseur", "etat", *db.SOLAIRE_CHAMPS, *POINT_SERVICE)
    cx.execute(f"INSERT INTO point_mesure ({', '.join(champs)}) VALUES ({', '.join('?' * len(champs))}) "
               f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in champs[1:])}",
               tuple(p[k] for k in champs))
    cx.commit()
    avert = avertissements_point(p)
    doublons = [r[0] for r in cx.execute("SELECT id FROM point_mesure WHERE immeuble_id = ? AND fluide = ? AND id != ? "
                                         "AND etat = 'actif'", (p["immeuble_id"], p["fluide"], p["id"]))]
    if doublons and p["etat"] == "actif":
        avert.append(f"{p['id']} : l'immeuble a déjà un compteur actif pour ce fluide ({', '.join(doublons)}). "
                     "La détection de dérive n'en analyse qu'un (le dernier par code) ; passez l'autre en « Inactif » "
                     "ou déclarez un sous-compteur dans un autre immeuble.")
    return p, avert


def supprimer_point(cx, pid):
    cx.execute("DELETE FROM mesure WHERE point_id = ?", (pid,))
    n = cx.execute("DELETE FROM point_mesure WHERE id = ?", (pid,)).rowcount
    cx.commit()
    if not n:
        raise ErreurSaisie("Compteur introuvable.")


def enregistrer_prestataire(cx, d, pid=None):
    p = valider_prestataire(d, immeubles_connus(cx))
    champs = ("nom", "metier", "contact", "email", "telephone", "perimetre", "actif")
    if pid:
        n = cx.execute(f"UPDATE prestataire SET {', '.join(c + ' = ?' for c in champs)} WHERE id = ?",
                       tuple(p[c] for c in champs) + (pid,)).rowcount
        if not n:
            raise ErreurSaisie("Prestataire introuvable.")
    else:
        pid = cx.execute(f"INSERT INTO prestataire ({', '.join(champs)}) VALUES ({', '.join('?' * len(champs))})",
                         tuple(p[c] for c in champs)).lastrowid
    cx.commit()
    return {**p, "id": pid}


def reprendre_prestataires(cx, chemin_source):
    """Reprend les prestataires d'une autre base Vigie (lue seule). Un prestataire déjà présent (même nom et même
    métier) n'est pas dupliqué. Les immeubles couverts qui n'existent pas dans ce parc sont retirés du périmètre ; un
    prestataire qui n'en couvre plus aucun (« orphelin ») est réparti sur les quartiers du parc, à tour de rôle entre
    les orphelins du même métier. Retourne le bilan, avec le nouveau périmètre de chaque prestataire réparti."""
    import sqlite3
    source = sqlite3.connect(f"file:{chemin_source}?mode=ro", uri=True)
    try:
        champs = ("nom", "metier", "contact", "email", "telephone", "perimetre", "actif")
        anciens = [dict(zip(champs, r)) for r in source.execute(f"SELECT {', '.join(champs)} FROM prestataire ORDER BY id")]
    finally:
        source.close()
    connus = immeubles_connus(cx)
    quartiers = {}
    for iid, quartier in cx.execute("SELECT id, quartier FROM immeuble WHERE quartier IS NOT NULL ORDER BY id"):
        quartiers.setdefault(quartier, []).append(iid)
    deja = {(_cle(r[0]), _cle(r[1])) for r in cx.execute("SELECT nom, metier FROM prestataire")}
    nouveaux = [p for p in anciens if (_cle(p["nom"]), _cle(p["metier"])) not in deja]
    bilan = {"repris": len(nouveaux), "deja_presents": len(anciens) - len(nouveaux), "repartis": []}
    orphelins = {}
    for p in nouveaux:
        if (p["perimetre"] or "*") != "*":
            restants = [x.strip() for x in p["perimetre"].split(",") if x.strip() in connus]
            p["perimetre"] = ",".join(restants)
            if not restants:
                orphelins.setdefault(_cle(p["metier"]), []).append(p)
    for groupe in orphelins.values():  # quartiers attribués à tour de rôle entre les orphelins du métier
        attribues = {id(p): [] for p in groupe}
        for i, quartier in enumerate(sorted(quartiers)):
            attribues[id(groupe[i % len(groupe)])].append(quartier)
        for p in groupe:
            p["perimetre"] = ",".join(iid for q in attribues[id(p)] for iid in quartiers[q])
            bilan["repartis"].append({"nom": p["nom"], "metier": p["metier"], "quartiers": attribues[id(p)],
                                      "immeubles": len([x for x in p["perimetre"].split(",") if x])})
    for p in nouveaux:
        cx.execute("INSERT INTO prestataire (nom, metier, contact, email, telephone, perimetre, actif) VALUES (?,?,?,?,?,?,?)",
                   (p["nom"], p["metier"], p["contact"], p["email"], p["telephone"], p["perimetre"] or "", p["actif"]))
    cx.commit()
    return bilan


def supprimer_prestataire(cx, pid):
    """Un prestataire déjà lié à un bon est désactivé plutôt que supprimé (historique conservé)."""
    if cx.execute("SELECT 1 FROM bon WHERE prestataire_id = ? LIMIT 1", (pid,)).fetchone():
        cx.execute("UPDATE prestataire SET actif = 0 WHERE id = ?", (pid,))
        cx.commit()
        return "desactive"
    cx.execute("DELETE FROM prestataire WHERE id = ?", (pid,))
    cx.commit()
    return "supprime"


# ---------------------------------------------------------------- règles et coûts


def liste_regles(cx, ref_defauts):
    reglages = db.lire_regles(cx)
    effectives = moteur.regles_effectives({"regles": reglages})
    defauts = moteur.regles_effectives({})
    compteurs = cx.execute("SELECT fluide, pas_min, count(*) FROM point_mesure WHERE etat = 'actif' "
                           "GROUP BY fluide, pas_min").fetchall()
    out = []
    for cause, r in effectives.items():
        d = defauts[cause]
        out.append({"id": cause, "fluide_point": r["fluide_point"], "pas_releve": list(r["pas_releve"]),
                    **regles.applicabilite(cause, compteurs), **{k: r[k] for k in (
            "libelle", "titre", "fluide", "active", "profils", "seuil", "unite_seuil", "seuil_min", "seuil_max",
            "aide_seuil", "persistance", "unite_persistance", "gravite", "delai", "metier", "consigne", "sinistre",
            "payeur")}, "modifiee": bool(reglages.get(cause)), "defaut": {
            k: d[k] for k in ("active", "profils", "seuil", "persistance", "gravite", "delai", "metier", "consigne")}})
    P = {**ref_defauts["parametres"], **(db.lire_parametre(cx, "parametres") or {})}
    qualite = {"silence_max_heures": P["silence_max_heures"], "completude_min": P["completude_min"],
               "metier": moteur.METIER_DONNEES}
    return {"regles": out, "qualite": qualite, "profils": moteur.PROFILS, "gravites": moteur.GRAVITES,
            "metiers": moteur.METIERS,
            "couverture": regles.couverture(compteurs, out, {k: v[0] for k, v in db.FLUIDES.items()}),
            "matrice": regles.matrice([r["id"] for r in out if r["active"]], compteurs)}


def enregistrer_regle(cx, cause, d):
    if cause not in moteur.REGLES:
        raise ErreurSaisie("Règle inconnue.")
    base = moteur.regles_effectives({})[cause]
    profils = d.get("profils")
    if profils is not None:
        if not isinstance(profils, list) or any(p not in moteur.PROFILS for p in profils):
            raise ErreurSaisie("Profils : Habite, Partiel, Vide ou Travaux.")
        if not profils:  # sans type d'immeuble, la règle ne s'appliquerait nulle part sans le dire
            raise ErreurSaisie("Cochez au moins un type d'immeuble, ou décochez « Règle active ».")
    gravite = d.get("gravite")
    if gravite is not None and gravite not in moteur.GRAVITES:
        raise ErreurSaisie("Gravité : Critique, Élevée ou Modérée.")
    seuil = _nombre(d.get("seuil"), "Seuil", base["seuil_min"], base["seuil_max"])
    persistance = _nombre(d.get("persistance"), "Persistance", 1, 60, entier=True)
    cx.execute("INSERT OR REPLACE INTO regle VALUES (?,?,?,?,?,?,?,?,?)", (
        cause, None if d.get("active") is None else int(bool(d["active"])),
        None if profils is None else ",".join(profils), seuil, persistance, gravite,
        _texte(d.get("delai"), "Délai", maxi=40), _texte(d.get("metier"), "Métier", maxi=60),
        _texte(d.get("consigne"), "Consigne", maxi=1000)))
    cx.commit()


def reinitialiser_regle(cx, cause):
    cx.execute("DELETE FROM regle WHERE id = ?", (cause,))
    cx.commit()


VECTEURS = {"electricite": ("Électricité", "kWh"), "chaleur": ("Chaleur", "kWh"), "cad": ("Chauffage à distance", "kWh"),
            "gaz": ("Gaz", "kWh"), "solaire": ("Production solaire perdue", "kWh"), "eau": ("Eau", "m3")}


def lire_couts(cx, ref_defauts):
    tarifs = {**ref_defauts["tarifs"], **(db.lire_parametre(cx, "tarifs") or {})}
    co2 = {**ref_defauts["facteurs_co2_kg_par_kwh"], **(db.lire_parametre(cx, "facteurs_co2_kg_par_kwh") or {})}
    P = {**ref_defauts["parametres"], **(db.lire_parametre(cx, "parametres") or {})}
    return {"tarifs": [{"vecteur": v, "libelle": lib, "unite": u, "chf_par_unite": tarifs[v]["chf_par_unite"],
                        "statut": tarifs[v].get("_statut", "EXEMPLE"), "co2_kg_par_kwh": co2.get(v)}
                       for v, (lib, u) in VECTEURS.items()],
            "enjeu_min_chf_mois": round(moteur.seuil_enjeu_mois(P), 2),
            "silence_max_heures": P["silence_max_heures"], "completude_min": P["completude_min"]}


def enregistrer_couts(cx, d, ref_defauts):
    tarifs = {**ref_defauts["tarifs"], **(db.lire_parametre(cx, "tarifs") or {})}
    co2 = {**ref_defauts["facteurs_co2_kg_par_kwh"], **(db.lire_parametre(cx, "facteurs_co2_kg_par_kwh") or {})}
    for t in d.get("tarifs", []):
        v = t.get("vecteur")
        if v not in VECTEURS:
            raise ErreurSaisie("Vecteur inconnu.")
        prix = _nombre(t.get("chf_par_unite"), f"Tarif {VECTEURS[v][0]}", 0, 100)
        if prix is None:
            raise ErreurSaisie(f"Le tarif {VECTEURS[v][0]} est obligatoire.")
        statut = "CONTRAT" if t.get("statut") == "CONTRAT" else "EXEMPLE"
        tarifs[v] = {"chf_par_unite": prix, "unite": VECTEURS[v][1], "_statut": statut}
        if v != "eau" and t.get("co2_kg_par_kwh") not in (None, ""):
            co2[v] = _nombre(t.get("co2_kg_par_kwh"), f"Facteur CO₂ {VECTEURS[v][0]}", 0, 2)
    P = dict(db.lire_parametre(cx, "parametres") or ref_defauts["parametres"])
    if d.get("enjeu_min_chf_mois") not in (None, ""):  # l'enjeu se règle désormais en CHF par mois (30 jours)
        P.pop("enjeu_min_chf_an", None)
    P.pop("jours_saison_chauffe", None)  # plus d'annualisation du chauffage : paramètre retiré
    for cle, lib, mini, maxi, entier in (
            ("enjeu_min_chf_mois", "Enjeu minimal", 0, 1e5, False),
            ("silence_max_heures", "Silence maximal", 1, 720, True),
            ("completude_min", "Complétude minimale", 0.1, 1, False)):
        if d.get(cle) not in (None, ""):
            P[cle] = _nombre(d[cle], lib, mini, maxi, entier)
    db.ecrire_parametre(cx, "tarifs", tarifs)
    db.ecrire_parametre(cx, "facteurs_co2_kg_par_kwh", co2)
    db.ecrire_parametre(cx, "parametres", P)


# ---------------------------------------------------------------- import / export Excel

COLONNES = {
    "Immeubles": [("immeuble_id", "id"), ("nom", "nom"), ("rue", "rue"), ("npa_localite", "npa_localite"),
                  ("profil", "profil"), ("taux_occupation", "taux_occupation"), ("logements", "logements"),
                  ("sre_m2", "sre_m2"), ("talon_horsgel_kwh_j", "talon_horsgel_kwh_j"),
                  ("proprietaire", "proprietaire"), ("remarque", "remarque"), ("latitude", "latitude"),
                  ("longitude", "longitude")],
    "Compteurs": [("point_id", "id"), ("immeuble_id", "immeuble_id"), ("fluide", "fluide"), ("libelle", "libelle"),
                  ("unite", "unite"), ("nature", "nature"), ("pas_min", "pas_min"), ("connexion", "source"),
                  ("identifiant", "identifiant"), ("fournisseur", "fournisseur"), ("etat", "etat"),
                  ("puissance_crete_kwc", "puissance_crete_kwc"), ("production_prevue_kwh_an", "production_prevue_kwh_an"),
                  ("mise_en_service", "mise_en_service"), ("degradation_pct_an", "degradation_pct_an")],
    "Prestataires": [("nom", "nom"), ("metier", "metier"), ("contact", "contact"), ("email", "email"),
                     ("telephone", "telephone"), ("immeubles", "perimetre")],
}
# En-têtes tolérés (après normalisation : minuscules, sans accents), par feuille
SYNONYMES = {
    "Immeubles": {"immeuble_id": "id", "code": "id", "code_immeuble": "id", "id_immeuble": "id",
                  "nom_immeuble": "nom", "immeuble": "nom", "adresse": "rue", "rue_et_numero": "rue",
                  "localite": "localite", "commune": "localite", "occupation": "profil", "taux": "taux_occupation",
                  "nb_logements": "logements", "nombre_de_logements": "logements", "sre": "sre_m2",
                  "talon_hors_gel": "talon_horsgel_kwh_j", "talon_horsgel": "talon_horsgel_kwh_j",
                  "lat": "latitude", "lon": "longitude", "lng": "longitude"},
    "Compteurs": {"point_id": "id", "compteur": "id", "compteur_id": "id", "code_compteur": "id",
                  "immeuble": "immeuble_id", "code_immeuble": "immeuble_id", "pas": "pas_min",
                  "pas_de_temps": "pas_min", "connexion": "source", "protocole": "source",
                  "numero_de_serie": "identifiant", "n_serie": "identifiant", "no_serie": "identifiant",
                  "numero_serie": "identifiant", "deveui": "identifiant", "kwc": "puissance_crete_kwc",
                  "puissance_crete": "puissance_crete_kwc", "production_prevue": "production_prevue_kwh_an",
                  "production_prevue_kwh": "production_prevue_kwh_an", "annee_mise_en_service": "mise_en_service",
                  "degradation": "degradation_pct_an", "decote": "degradation_pct_an",
                  "decote_annuelle": "degradation_pct_an"},
    "Prestataires": {"entreprise": "nom", "raison_sociale": "nom", "corps_de_metier": "metier", "mail": "email",
                     "e_mail": "email", "courriel": "email", "tel": "telephone", "immeubles": "perimetre",
                     "immeubles_couverts": "perimetre"},
}


def _feuille(feuilles, nom):
    """Lignes d'une feuille sous forme de (n° de ligne, dict), en-têtes tolérants (accents, casse, synonymes)."""
    cible = next((n for n in feuilles if _cle(n) == _cle(nom)), None)
    if cible is None or not feuilles[cible]:
        return []
    lignes = feuilles[cible]
    entetes = [SYNONYMES[nom].get(_cle(h), _cle(h)) for h in lignes[0]]
    out = []
    for n, ligne in enumerate(lignes[1:], start=2):
        if not any(v not in (None, "") for v in ligne):
            continue
        d = {entetes[i]: v for i, v in enumerate(ligne) if i < len(entetes) and entetes[i]}
        if nom == "Immeubles" and not d.get("npa_localite") and (d.get("npa") or d.get("localite")):
            d["npa_localite"] = f"{d.get('npa') or ''} {d.get('localite') or ''}".strip()
        out.append((n, d))
    return out


def _fusion(ancien, d):
    """Ligne Excel complétée par l'existant : une colonne absente ou une cellule vide ne modifie rien."""
    base = dict(ancien or {})
    base.update({k: v for k, v in d.items() if v is not None and str(v).strip() != ""})
    return base


def _compare(ancien, nouveau):
    if not ancien:
        return "nouveaux"
    return "inchanges" if all((ancien.get(k) or None) == (v or None) for k, v in nouveau.items()) else "modifies"


def importer_parc_excel(cx, contenu, appliquer=False):
    """Analyse (et applique si `appliquer`) un classeur Excel du parc. Rien n'est supprimé."""
    feuilles = excel.lire_xlsx(contenu)
    if not any(_cle(n) in ("immeubles", "compteurs", "prestataires") for n in feuilles):
        raise ErreurSaisie("Le classeur doit contenir au moins une feuille « Immeubles », « Compteurs » ou "
                           "« Prestataires ». Téléchargez le modèle pour voir la structure attendue.")
    rapport = {"feuilles": list(feuilles), "erreurs": [], "avertissements": [], "applique": False}
    for k in ("immeubles", "compteurs", "prestataires"):
        rapport[k] = {"nouveaux": 0, "modifies": 0, "inchanges": 0}
    existants = {r["id"]: r for r in db.lignes(cx, "SELECT i.*, a.rue, a.npa_localite, CASE WHEN a.geo_source = 'manuel' THEN a.lat END AS latitude, "
                         "CASE WHEN a.geo_source = 'manuel' THEN a.lon END AS longitude FROM immeuble i "
                                                   "JOIN adresse a ON a.id = i.adresse_id")}
    connus = set(existants)
    immeubles, points, prestataires = [], [], []
    for n, d in _feuille(feuilles, "Immeubles"):
        try:
            im = valider_immeuble(_fusion(existants.get(str(d.get("id") or "").strip()), d))
        except ErreurSaisie as e:
            rapport["erreurs"].append({"feuille": "Immeubles", "ligne": n, "message": str(e)})
            continue
        rapport["immeubles"][_compare(existants.get(im["id"]), im)] += 1
        immeubles.append(im)
        connus.add(im["id"])
    anciens_pts = {r["id"]: r for r in db.lignes(cx, "SELECT * FROM point_mesure")}
    for n, d in _feuille(feuilles, "Compteurs"):
        ancien = anciens_pts.get(str(d.get("id") or "").strip())
        try:
            p = valider_point(_fusion(ancien, d), connus)
        except ErreurSaisie as e:
            rapport["erreurs"].append({"feuille": "Compteurs", "ligne": n, "message": str(e)})
            continue
        rapport["compteurs"][_compare(ancien, p)] += 1
        rapport["avertissements"] += avertissements_point(p)
        points.append(p)
    anciens_pr = {(_cle(r["nom"]), _cle(r["metier"])): r for r in db.lignes(cx, "SELECT * FROM prestataire")}
    for n, d in _feuille(feuilles, "Prestataires"):
        ancien = anciens_pr.get((_cle(d.get("nom")), _cle(d.get("metier"))))
        try:
            p = valider_prestataire(_fusion(ancien, d), connus)
        except ErreurSaisie as e:
            rapport["erreurs"].append({"feuille": "Prestataires", "ligne": n, "message": str(e)})
            continue
        rapport["prestataires"][_compare(ancien, p)] += 1
        prestataires.append((ancien["id"] if ancien else None, p))
    if appliquer:
        for im in immeubles:
            enregistrer_immeuble(cx, im)
        for p in points:
            enregistrer_point(cx, p)
        for pid, p in prestataires:
            enregistrer_prestataire(cx, p, pid)
        rapport["applique"] = True
    return rapport


def exporter_parc_excel(cx):
    """Classeur Excel du parc actuel (sert aussi de modèle à compléter)."""
    feuilles = {}
    ims = db.lignes(cx, "SELECT i.*, a.rue, a.npa_localite, CASE WHEN a.geo_source = 'manuel' THEN a.lat END AS latitude, "
                         "CASE WHEN a.geo_source = 'manuel' THEN a.lon END AS longitude FROM immeuble i JOIN adresse a ON a.id = i.adresse_id "
                        "ORDER BY a.rue, i.nom")
    feuilles["Immeubles"] = [[c for c, _ in COLONNES["Immeubles"]]] + [
        [im[k] for _, k in COLONNES["Immeubles"]] for im in ims]
    pts = db.lignes(cx, "SELECT * FROM point_mesure WHERE immeuble_id IS NOT NULL ORDER BY immeuble_id, fluide, id")
    feuilles["Compteurs"] = [[c for c, _ in COLONNES["Compteurs"]]] + [
        [p[k] for _, k in COLONNES["Compteurs"]] for p in pts]
    prs = db.lignes(cx, "SELECT * FROM prestataire WHERE actif = 1 ORDER BY metier, nom")
    feuilles["Prestataires"] = [[c for c, _ in COLONNES["Prestataires"]]] + [
        [p[k] for _, k in COLONNES["Prestataires"]] for p in prs]
    if not ims:  # modèle vide : une ligne d'exemple pour montrer le format
        feuilles["Immeubles"].append(["IMM01", "Résidence exemple", "Rue de l'Exemple 1", "1200 Genève", "Habité",
                                      None, 12, None, None, None, None])
        feuilles["Compteurs"].append(["IMM01_EAU", "IMM01", "Eau froide", "Eau froide générale", "m3", "index", 60,
                                      "LoRaWAN", "N° de série", "Services industriels", "à connecter",
                                      None, None, None, None])
        feuilles["Compteurs"].append(["IMM01_PV", "IMM01", "Solaire", "Production solaire (onduleur)", "kWh",
                                      "intervalle", 60, "Modbus TCP", "N° de série de l'onduleur", None, "à connecter",
                                      30, 31500, 2020, 0.5])
        feuilles["Prestataires"].append(["Entreprise sanitaire exemple", "Sanitaire", "Nom du contact",
                                         "contact@entreprise.example", "+41 22 000 00 00", "*"])
    feuilles["Aide"] = [["Colonne", "Valeurs possibles"],
                        ["profil", "Habité, Partiel, Vide, Travaux"],
                        ["taux_occupation", "Pour un immeuble partiel : 40 ou 0,4 pour 40 %"],
                        ["latitude / longitude", "Facultatif : position GPS (ex. 46.2038 / 6.1495) si l'adresse n'est pas trouvée automatiquement"],
                        ["talon_horsgel_kwh_j", "Chaleur maximale attendue en hors-gel, kWh par jour (immeuble vide)"],
                        ["fluide", ", ".join(lib for k, (lib, _, _) in db.FLUIDES.items() if k not in db.FLUIDES_METEO)],
                        ["unite", "kWh, m3, kW, degC, l, W/m2"],
                        ["puissance_crete_kwc", "Solaire : puissance crête de l'installation en kWc (obligatoire)"],
                        ["production_prevue_kwh_an", "Solaire : production brute prévue par l'installateur, kWh par an"],
                        ["mise_en_service", "Solaire : année de mise en service (âge des modules)"],
                        ["degradation_pct_an", "Solaire : décote annuelle prévue des modules, % par an (0,5 si vide)"],
                        ["nature", "index (compteur cumulé), intervalle (consommation du pas), instantane"],
                        ["pas_min", "60 (horaire, recommandé pour tous les compteurs) ou 1440 (journalier : fuite de "
                                    "nuit, électricité de nuit et PAC non surveillées) — minutes"],
                        ["connexion", "; ".join(SOURCES)],
                        ["etat", "actif, à connecter, inactif"],
                        ["metier", ", ".join(moteur.METIERS)],
                        ["immeubles (prestataires)", "* pour tout le parc, sinon les codes séparés par des virgules"],
                        ["Règle d'import", "Les lignes sont ajoutées ou mises à jour par code ; rien n'est supprimé."]]
    return excel.ecrire_xlsx(feuilles)


# ---------------------------------------------------------------- fiche technique de l'immeuble

CHAUFFAGES = ["PAC air/eau", "PAC sol/eau", "PAC eau/eau", "Mixte PAC + chaudière d'appoint", "Chaudière gaz",
              "Chaudière mazout", "Chauffage à distance (CAD)", "Bois / pellets", "Électrique direct"]
PRODUCTIONS_ECS = ["Par la PAC", "Par la chaudière", "Boilers électriques", "Solaire thermique + appoint", "CAD"]
TECHNIQUE_CHAMPS = [  # (clé, libellé, type, bornes ou choix)
    ("annee_construction", "Année de construction", "entier", (1500, 2100)),
    ("annee_renovation", "Dernière rénovation", "entier", (1500, 2100)),
    ("egid", "N° EGID (registre fédéral des bâtiments)", "texte", 20),
    ("etages", "Nombre d'étages", "entier", (0, 100)),
    ("chauffage", "Production de chaleur", "choix", CHAUFFAGES),
    ("ecs", "Production d'eau chaude", "choix", PRODUCTIONS_ECS),
    ("puissance_kw", "Puissance de chauffage (kW)", "nombre", (0, 100000)),
    ("installation", "Installation (marque, modèle)", "texte", 120),
    ("annee_installation", "Année d'installation", "entier", (1950, 2100)),
    ("frigorigene", "Fluide frigorigène (PAC)", "texte", 30),
    ("emplacement", "Emplacement chaufferie / local technique", "texte", 120),
    ("notes", "Notes techniques", "texte", 1000),
]
CONTACTS = [("gestionnaire", "Gestionnaire", 120), ("gestionnaire_email", "E-mail du gestionnaire", 160),
            ("gestionnaire_tel", "Téléphone du gestionnaire", 40), ("concierge", "Concierge", 120),
            ("concierge_email", "E-mail du concierge", 160), ("concierge_tel", "Téléphone du concierge", 40)]
# Métier du partenaire technique qui intervient sur chaque fluide
# CAD : le chauffagiste règle la sous-station côté immeuble ; un défaut côté réseau est signalé au fournisseur (SIG)
METIER_PAR_FLUIDE = {"electricite": "Électricien", "chaleur": "Chauffagiste", "cad": "Chauffagiste", "gaz": "Chauffagiste",
                     "mazout": "Chauffagiste", "pac_electricite": "Frigoriste", "pac_chaleur": "Frigoriste",
                     "pac_chaleur_chauffage": "Frigoriste", "pac_chaleur_ecs": "Frigoriste", "eau": "Sanitaire",
                     "eau_chaude": "Sanitaire", "solaire": "Solaire", "electricite_injection": "Électricien",
                     "electricite_sous_compteur": "Électricien", "granules": "Chauffagiste",
                     "cad_debit": "Chauffagiste", "cad_temperature_aller": "Chauffagiste",
                     "cad_temperature_retour": "Chauffagiste"}


def valider_fiche(d):
    out = {}
    for cle, lib, maxi in CONTACTS:
        if cle in d:
            v = _texte(d.get(cle), lib, maxi=maxi)
            if v and cle.endswith("_email") and not EMAIL_RE.match(v):
                raise ErreurSaisie(f"Adresse e-mail invalide : {v}")
            out[cle] = v
    if "technique" in d:
        t, tech = d.get("technique") or {}, {}
        if not isinstance(t, dict):
            raise ErreurSaisie("Données techniques illisibles.")
        for cle, lib, genre, borne in TECHNIQUE_CHAMPS:
            v = t.get(cle)
            if v is None or str(v).strip() == "":
                continue
            if genre in ("entier", "nombre"):
                tech[cle] = _nombre(v, lib, borne[0], borne[1], entier=genre == "entier")
            elif genre == "choix":
                if v not in borne:
                    raise ErreurSaisie(f"« {lib} » : choisir dans la liste.")
                tech[cle] = v
            else:
                tech[cle] = _texte(v, lib, maxi=borne)
        out["technique"] = tech
    return out


def enregistrer_fiche(cx, immeuble_id, d):
    """Contacts et données techniques (seuls les champs fournis sont modifiés)."""
    if immeuble_id not in immeubles_connus(cx):
        raise ErreurSaisie("Immeuble introuvable.")
    f = valider_fiche(d)
    if "technique" in f:
        f["technique"] = json.dumps(f["technique"], ensure_ascii=False)
    if f:
        cx.execute(f"UPDATE immeuble SET {', '.join(k + ' = ?' for k in f)} WHERE id = ?", (*f.values(), immeuble_id))
        cx.commit()


def partenaires_par_fluide(cx, immeuble_id):
    """Pour chaque fluide suivi de l'immeuble : le partenaire technique qui intervient (et la télérelève)."""
    from .bons import choisir_prestataire
    fluides = [r[0] for r in cx.execute("SELECT DISTINCT fluide FROM point_mesure WHERE immeuble_id = ? "
                                        "AND etat != 'inactif' ORDER BY fluide", (immeuble_id,))]
    vus, out = set(), []
    for f in fluides + ["donnees"]:
        metier = moteur.METIER_DONNEES if f == "donnees" else METIER_PAR_FLUIDE.get(f)
        if not metier:
            continue
        libelle = "Données des compteurs" if f == "donnees" else db.FLUIDES.get(f, (f,))[0]
        libelle = "Pompe à chaleur" if f.startswith("pac") else libelle
        if (metier, libelle) in vus:
            continue
        vus.add((metier, libelle))
        p = choisir_prestataire(cx, metier, immeuble_id)
        out.append({"fluide": f, "libelle": libelle, "metier": metier,
                    "prestataire": {k: p[k] for k in ("id", "nom", "contact", "email", "telephone", "perimetre")}
                    if p else None})
    return out


def fiche(cx, immeuble_id):
    r = db.lignes(cx, "SELECT i.*, a.rue, a.npa_localite, a.lat, a.lon, a.geo_source FROM immeuble i "
                      "JOIN adresse a ON a.id = i.adresse_id WHERE i.id = ?", (immeuble_id,))
    if not r:
        raise ErreurSaisie("Immeuble introuvable.")
    im = r[0]
    im["technique"] = json.loads(im["technique"]) if im.get("technique") else {}
    return {"immeuble": im, "partenaires": partenaires_par_fluide(cx, immeuble_id),
            "batiments": db.lignes(cx, "SELECT * FROM batiment WHERE immeuble_id = ? ORDER BY id", (immeuble_id,)),
            "installations": db.lignes(cx, "SELECT * FROM installation WHERE immeuble_id = ? ORDER BY id", (immeuble_id,)),
            "listes": {"technique": [{"cle": c, "libelle": l, "type": g, "choix": b if g == "choix" else None}
                                     for c, l, g, b in TECHNIQUE_CHAMPS]}}
