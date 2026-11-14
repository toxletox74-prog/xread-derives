"""Import d'un classeur « patrimoine » : sites, bâtiments, installations, compteurs et relevés MENSUELS.

Format du lot communal (CC BY 4.0), feuilles :
  Batiments      id_batiment, id_site, nom_site, quartier, typologie, nom_batiment, annee_construction,
                 annee_renovation, sre_m2, niveaux, label, logements, ouverture, x_km, y_km, remarque
  Installations  id_installation, id_site, type, libelle, vecteur, puissance_kw, mise_en_service, retrait, remarque
  Compteurs      id_compteur, id_site, libelle, fluide, unite, niveau, mesure, parent, fournisseur_donnee, releve,
                 debut, fin
  Mesures        mois (AAAA-MM), id_compteur, id_site, fluide, mesure, valeur, unite, energie_kwh, qualite
  Ref_Climat, Ref_Climat_Normale, Ref_Conversion, Ref_CO2   références mensuelles (facultatives)

Correspondance avec Vigie : un SITE devient un immeuble (même code : S01), ses BÂTIMENTS gardent leur identifiant
(S01-B1) dans la table `batiment`, les compteurs gardent leur code (S01-EL). Chaque relevé mensuel est stocké tel quel,
dans l'unité du compteur, horodaté à la FIN du mois (convention fin d'intervalle : janvier 2021 → 2021-02-01T00:00:00Z).

Contrôles (chaque écart est gardé dans `anomalie_import` et dans sorties/anomalies_import.csv ; rien n'est corrigé
ni comblé en silence, règles 1 et 4) :
  - compteur inconnu, mois illisible, valeur non numérique → ligne rejetée ;
  - relevé « manquant » ou valeur vide → aucune mesure créée (jamais comblée) ;
  - valeur négative → marquée « suspecte », exclue des calculs ;
  - relevé « estimé » par le distributeur → marqué « estimee », affiché mais exclu des décisions ;
  - doublon (compteur, mois) : identique → une seule mesure ; différent → la dernière l'emporte ; livraisons d'un
    même mois → additionnées ;
  - site, fluide ou unité en désaccord avec la feuille Compteurs ; mois hors des bornes de service du compteur ;
    énergie (kWh) en désaccord avec valeur × facteur de conversion ; mois sans aucun relevé dans une série mensuelle.
`preparer()` ne modifie rien (aperçu) ; `appliquer()` écrit. Rien n'est supprimé : ajout ou mise à jour par code.
"""
import csv
import os
import re
import uuid
from collections import Counter, defaultdict

from . import db, excel, geo, meteo, parc

FEUILLES_REQUISES = ("Batiments", "Compteurs", "Mesures")
MOIS_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
SOURCE_PLAN = geo.SOURCE_PLAN  # site placé depuis le plan du jeu (x_km, y_km) : GPS calculé, jamais géocodé

# Type d'installation du classeur -> production de chaleur de la fiche technique (parc.CHAUFFAGES)
CHAUFFAGE_PAR_TYPE = {"chaudiere_gaz": "Chaudière gaz", "chaudiere_mazout": "Chaudière mazout",
                      "sous_station_cad": "Chauffage à distance (CAD)", "pac_sol_eau": "PAC sol/eau",
                      "pac_air_eau": "PAC air/eau", "chaudiere_granules": "Bois / pellets",
                      "electrique_direct": "Électrique direct"}
UNITES = {"kwh": "kWh", "m3": "m3", "litre": "l", "litres": "l", "l": "l", "kg": "kg"}
QUALITES = {"mesure": "valide", "estime": "estimee", "manquant": None}
CONVERSION_PAR_FLUIDE = {"gaz": "gaz", "mazout": "mazout", "granules": "granules_de_bois"}  # fluide Vigie -> Ref_Conversion
TOLERANCE_KWH = 1.0  # l'énergie du classeur est arrondie au kWh


class ErreurPatrimoine(ValueError):
    pass


# ---------------------------------------------------------------- lecture


def _vide(v):
    return v is None or str(v).strip() == ""


def _texte(v):
    return None if _vide(v) else str(v).strip()


def _nombre(v):
    if _vide(v):
        return None
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", ".").replace("'", "").replace(" ", ""))


def _entier(v):
    n = _nombre(v)
    return None if n is None else int(n)


def _sur(v):
    """Nombre, ou None si la cellule est vide ou illisible (références facultatives)."""
    try:
        return _nombre(v)
    except ValueError:
        return None


def _mois(v):
    """'AAAA-MM' ou None si vide ; lève ValueError si illisible."""
    t = _texte(v)
    if t is None:
        return None
    if not MOIS_RE.match(t):
        raise ValueError(t)
    return t


def lignes_feuille(feuilles, nom):
    """[(n° de ligne Excel, {colonne normalisée: valeur})] d'une feuille, [] si elle est absente ou vide."""
    cible = next((n for n in feuilles if parc._cle(n) == parc._cle(nom)), None)
    lignes = feuilles.get(cible) or []
    if not lignes:
        return []
    entetes = [parc._cle(c) for c in lignes[0]]
    out = []
    for n, ligne in enumerate(lignes[1:], start=2):
        if not any(not _vide(c) for c in ligne):
            continue
        out.append((n, {entetes[i]: c for i, c in enumerate(ligne) if i < len(entetes) and entetes[i]}))
    return out


def ts_fin_mois(mois):
    """Fin du mois (fin d'intervalle, UTC) : 'AAAA-MM' -> 1er du mois suivant à 00:00:00Z."""
    a, m = int(mois[:4]), int(mois[5:7])
    return f"{a + (m == 12):04d}-{m % 12 + 1:02d}-01T00:00:00Z"


def mois_entre(debut, fin):
    """Mois 'AAAA-MM' de `debut` à `fin` inclus."""
    a, m = int(debut[:4]), int(debut[5:7])
    out = []
    while f"{a:04d}-{m:02d}" <= fin:
        out.append(f"{a:04d}-{m:02d}")
        a, m = a + (m == 12), m % 12 + 1
    return out


def commune(feuilles):
    """Nom du jeu (première cellule de « Lisez-moi », avant le premier « · »), sinon « Commune »."""
    lm = next((v for n, v in feuilles.items() if parc._cle(n) in ("lisez_moi", "lisezmoi")), None)
    titre = _texte(lm[0][0]) if lm and lm[0] else None
    return (titre.split("·")[0].strip() or "Commune") if titre else "Commune"


def fluide_vigie(c):
    """Compteur du classeur -> (fluide Vigie, unité, nature). Lève ErreurPatrimoine si le fluide est inconnu."""
    f, mesure, niveau = parc._cle(c.get("fluide")), parc._cle(c.get("mesure")), parc._cle(c.get("niveau"))
    code = str(c.get("id_compteur") or "")
    if f == "electricite_solaire":
        cle = "solaire"
    elif f == "electricite" and mesure == "injection":
        cle = "electricite_injection"
    elif f == "electricite" and niveau == "sous_compteur":
        cle = "pac_electricite" if code.upper().endswith("-PAC") else "electricite_sous_compteur"
    elif f == "electricite":
        cle = "electricite"
    elif f == "chaleur_a_distance":
        cle = "cad"
    elif f == "chaleur":
        cle = "pac_chaleur" if niveau == "mesure_de_chaleur" else "chaleur"
    elif f.startswith("bois"):
        cle = "granules"
    elif f in ("gaz", "mazout", "eau"):
        cle = f
    else:
        raise ErreurPatrimoine(f"Fluide inconnu : {c.get('fluide')}")
    unite = UNITES.get(parc._cle(c.get("unite")))
    if unite is None:
        raise ErreurPatrimoine(f"Unité inconnue : {c.get('unite')}")
    livraison = mesure == "livraison" or "livraison" in parc._cle(c.get("releve"))
    return cle, unite, "livraison" if livraison else "intervalle"


# ---------------------------------------------------------------- préparation (aucune écriture)


class Plan:
    """Résultat de la lecture : ce qui sera écrit, et toutes les anomalies relevées."""

    def __init__(self, nom_commune):
        self.commune = nom_commune
        self.sites, self.batiments, self.installations, self.points = {}, [], [], {}
        self.mesures, self.references, self.anomalies, self.erreurs = {}, [], [], []
        self.stats = Counter()
        self.premier_mois = self.dernier_mois = None

    def anomalie(self, type_, feuille, ligne, objet, periode, detail, traitement):
        self.anomalies.append({"type": type_, "feuille": feuille, "ligne": ligne, "objet": objet, "periode": periode,
                               "detail": detail, "traitement": traitement})

    def erreur(self, feuille, ligne, message):
        self.erreurs.append({"feuille": feuille, "ligne": ligne, "message": message})


def _batiment(b):
    return {"id": parc._identifiant(b.get("id_batiment"), "id_batiment"),
            "immeuble_id": parc._identifiant(b.get("id_site"), "id_site"),
            "nom": _texte(b.get("nom_batiment")) or _texte(b.get("nom_site")) or str(b.get("id_batiment")),
            "annee_construction": _entier(b.get("annee_construction")),
            "annee_renovation": _entier(b.get("annee_renovation")), "sre_m2": _nombre(b.get("sre_m2")),
            "niveaux": _entier(b.get("niveaux")), "label": _texte(b.get("label")),
            "logements": _entier(b.get("logements")), "ouverture": _mois(b.get("ouverture")),
            "remarque": _texte(b.get("remarque"))}


def _sites(plan, feuilles):
    par_site = defaultdict(list)
    for n, b in lignes_feuille(feuilles, "Batiments"):
        try:
            bat = _batiment(b)
        except (ValueError, parc.ErreurSaisie) as e:
            plan.erreur("Batiments", n, f"{b.get('id_batiment') or '?'} : valeur illisible ({e}).")
            continue
        par_site[bat["immeuble_id"]].append((n, b, bat))
    for sid, lignes in par_site.items():
        n, b, _bat = lignes[0]
        bats = [x[2] for x in lignes]
        quartier = _texte(b.get("quartier")) or ""
        lieu = "Tous quartiers" if parc._cle(quartier) == "tous" else f"Quartier {quartier}" if quartier else ""
        try:
            im = parc.valider_immeuble({
                "id": sid, "nom": _texte(b.get("nom_site")) or sid, "rue": _texte(b.get("nom_site")) or sid,
                "npa_localite": " · ".join(x for x in (lieu, plan.commune) if x), "profil": "Habite",
                "logements": sum(x["logements"] or 0 for x in bats) or None,
                "sre_m2": sum(x["sre_m2"] or 0 for x in bats),
                "remarque": " ".join(x["remarque"] for x in bats if x["remarque"]) or None})
            x_km, y_km = _nombre(b.get("x_km")), _nombre(b.get("y_km"))
        except (ValueError, parc.ErreurSaisie) as e:
            plan.erreur("Batiments", n, f"{sid} : {e}")
            continue
        plan.sites[sid] = {**im, "typologie": _texte(b.get("typologie")), "quartier": quartier or None,
                           "x_km": x_km, "y_km": y_km, "batiments": bats, "installations": []}
        plan.batiments += bats


def _installations(plan, feuilles):
    for n, i in lignes_feuille(feuilles, "Installations"):
        sid, iid = _texte(i.get("id_site")), _texte(i.get("id_installation"))
        if sid not in plan.sites or not iid:
            plan.erreur("Installations", n, f"{iid or '?'} : site inconnu ({sid}).")
            continue
        try:
            inst = {"id": parc._identifiant(iid, "id_installation"), "immeuble_id": sid,
                    "type": _texte(i.get("type")) or "autre", "libelle": _texte(i.get("libelle")) or iid,
                    "vecteur": _texte(i.get("vecteur")), "puissance_kw": _nombre(i.get("puissance_kw")),
                    "mise_en_service": _mois(i.get("mise_en_service")), "retrait": _mois(i.get("retrait")),
                    "remarque": _texte(i.get("remarque"))}
        except (ValueError, parc.ErreurSaisie) as e:
            plan.erreur("Installations", n, f"{iid} : valeur illisible ({e}).")
            continue
        plan.installations.append(inst)
        plan.sites[sid]["installations"].append(inst)


def technique(site):
    """Fiche technique de l'immeuble d'après ses bâtiments et son installation de chauffage en service."""
    bats, t = site["batiments"], {}
    annees = [b["annee_construction"] for b in bats if b["annee_construction"]]
    renos = [b["annee_renovation"] for b in bats if b["annee_renovation"]]
    niveaux = [b["niveaux"] for b in bats if b["niveaux"] is not None]
    if annees:
        t["annee_construction"] = min(annees)
    if renos:
        t["annee_renovation"] = max(renos)
    if niveaux:
        t["etages"] = max(niveaux)
    chauffages = [i for i in site["installations"] if i["type"] in CHAUFFAGE_PAR_TYPE and not i["retrait"]]
    if chauffages:
        c = max(chauffages, key=lambda i: i["mise_en_service"] or "")
        t["chauffage"] = CHAUFFAGE_PAR_TYPE[c["type"]]
        t["installation"] = c["libelle"][:120]
        if c["puissance_kw"]:
            t["puissance_kw"] = c["puissance_kw"]
        if c["mise_en_service"] and int(c["mise_en_service"][:4]) >= 1950:
            t["annee_installation"] = int(c["mise_en_service"][:4])
    labels = sorted({b["label"] for b in bats if b["label"]})
    if labels:
        t["notes"] = ("Label : " + ", ".join(labels))[:1000]
    return t


def _source(c):
    releve = _texte(c.get("releve")) or "mensuel"
    mode = releve.capitalize() if "livraison" in parc._cle(releve) else "Relevé " + releve
    return " — ".join(x for x in (mode, _texte(c.get("fournisseur_donnee"))) if x)


def _solaire(site):
    """Puissance crête (kWc) et année de mise en service de l'installation photovoltaïque du site."""
    pv = [i for i in site["installations"] if i["type"] == "pv" and i["puissance_kw"]]
    if not pv:
        return {}
    en_service = [i for i in pv if not i["retrait"]] or pv
    out = {"puissance_crete_kwc": sum(i["puissance_kw"] for i in en_service)}
    mises = [i["mise_en_service"] for i in en_service if i["mise_en_service"]]
    if mises and int(min(mises)[:4]) >= 1980:
        out["mise_en_service"] = int(min(mises)[:4])
    return out


def _compteurs(plan, feuilles):
    for n, c in lignes_feuille(feuilles, "Compteurs"):
        cid, sid = _texte(c.get("id_compteur")), _texte(c.get("id_site"))
        if sid not in plan.sites:
            plan.erreur("Compteurs", n, f"{cid or '?'} : site inconnu ({sid}).")
            continue
        try:
            fluide, unite, nature = fluide_vigie(c)
            debut, fin = _mois(c.get("debut")), _mois(c.get("fin"))
            hors_service = bool(fin and plan.dernier_mois and fin < plan.dernier_mois)
            d = {"id": cid, "immeuble_id": sid, "fluide": fluide, "libelle": _texte(c.get("libelle")),
                 "unite": unite, "nature": nature, "pas_min": db.PAS_MENSUEL, "source": _source(c),
                 "fournisseur": _texte(c.get("fournisseur_donnee")), "etat": "inactif" if hors_service else "actif",
                 "niveau": _texte(c.get("niveau")), "parent_id": _texte(c.get("parent")),
                 "service_debut": debut, "service_fin": fin, "releve": _texte(c.get("releve")),
                 **(_solaire(plan.sites[sid]) if fluide == "solaire" else {})}
            p = parc.valider_point(d, set(plan.sites))
        except (ValueError, ErreurPatrimoine, parc.ErreurSaisie) as e:
            plan.erreur("Compteurs", n, f"{cid or '?'} : {e}")
            continue
        plan.points[p["id"]] = {**p, "_feuille": c}


def _conversions(feuilles):
    """{vecteur normalisé: {mois ou 'toujours': facteur}} depuis Ref_Conversion."""
    out = defaultdict(dict)
    for _n, r in lignes_feuille(feuilles, "Ref_Conversion"):
        facteur = _sur(r.get("facteur"))
        if facteur is not None:
            out[parc._cle(r.get("vecteur"))][_texte(r.get("mois")) or "toujours"] = facteur
    return out


def _mesures(plan, feuilles):
    """Contrôle chaque ligne de Mesures. Retourne {(compteur, mois): (ligne, valeur ou None)} des lignes vues."""
    conversions = _conversions(feuilles)
    vus = {}
    for n, m in lignes_feuille(feuilles, "Mesures"):
        plan.stats["lues"] += 1
        cid = _texte(m.get("id_compteur"))
        p = plan.points.get(cid)
        if p is None:
            plan.stats["rejetees"] += 1
            plan.anomalie("compteur inconnu", "Mesures", n, cid, _texte(m.get("mois")),
                          "Compteur absent de la feuille Compteurs.", "ligne rejetée")
            continue
        try:
            mois = _mois(m.get("mois"))
            if mois is None:
                raise ValueError("mois vide")
            valeur = _nombre(m.get("valeur"))
        except ValueError:
            plan.stats["rejetees"] += 1
            plan.anomalie("valeur illisible", "Mesures", n, cid, _texte(m.get("mois")),
                          f"Mois ou valeur illisible : {m.get('mois')!r}, {m.get('valeur')!r}.", "ligne rejetée")
            continue
        _accord(plan, n, m, p, cid, mois)
        qualite = QUALITES.get(parc._cle(m.get("qualite")), "valide")
        if valeur is None or qualite is None:
            plan.stats["manquantes"] += 1
            plan.anomalie("relevé manquant", "Mesures", n, cid, mois,
                          f"Pas de relevé ce mois (qualité « {_texte(m.get('qualite')) or 'vide'} »).",
                          "aucune mesure créée, jamais comblée")
            vus.setdefault((cid, mois), (n, None))
            continue
        if qualite == "estimee":
            plan.anomalie("relevé estimé", "Mesures", n, cid, mois, f"Valeur estimée par le distributeur : {valeur:g}.",
                          "importée, marquée « estimée », exclue des décisions")
        if valeur < 0:
            qualite = "suspecte"
            plan.anomalie("valeur négative", "Mesures", n, cid, mois, f"Valeur négative : {valeur:g} {p['unite']}.",
                          "importée, marquée « suspecte », exclue des calculs")
        _energie(plan, n, m, p, cid, mois, valeur, conversions)
        deja = vus.get((cid, mois))
        if deja and deja[1] is not None:
            valeur = _doublon(plan, n, p, cid, mois, valeur, deja)
        vus[(cid, mois)] = (n, valeur)
        plan.mesures[(cid, mois)] = (ts_fin_mois(mois), cid, valeur, qualite)
    return vus


def _doublon(plan, n, p, cid, mois, valeur, deja):
    """Deuxième ligne pour le même (compteur, mois) : trace, et valeur à conserver."""
    n0, v0 = deja
    plan.stats["doublons"] += 1
    if p["nature"] == "livraison":
        plan.anomalie("livraisons du même mois", "Mesures", n, cid, mois, f"Deuxième livraison du mois (ligne {n0}).",
                      "livraisons additionnées")
        return valeur + v0
    if valeur == v0:
        plan.anomalie("doublon", "Mesures", n, cid, mois, f"Même relevé qu'à la ligne {n0} ({valeur:g}).",
                      "une seule mesure conservée")
    else:
        plan.anomalie("doublon contradictoire", "Mesures", n, cid, mois,
                      f"Deux valeurs pour le même mois : {v0:g} (ligne {n0}) puis {valeur:g}.",
                      "la dernière valeur l'emporte, à vérifier")
    return valeur


def _accord(plan, n, m, p, cid, mois):
    """La ligne de mesure s'accorde-t-elle avec la feuille Compteurs (site, fluide, unité, bornes de service) ?"""
    c = p["_feuille"]
    for cle, lib in (("id_site", "Site"), ("fluide", "Fluide"), ("unite", "Unité"), ("mesure", "Rôle")):
        if not _vide(m.get(cle)) and parc._cle(m.get(cle)) != parc._cle(c.get(cle)):
            plan.anomalie("désaccord avec le compteur", "Mesures", n, cid, mois,
                          f"{lib} « {m.get(cle)} » alors que le compteur indique « {c.get(cle)} ».",
                          "importée avec les caractéristiques du compteur, à vérifier")
    if (p["service_debut"] and mois < p["service_debut"]) or (p["service_fin"] and mois > p["service_fin"]):
        plan.anomalie("hors période de service", "Mesures", n, cid, mois,
                      f"Relevé hors des bornes du compteur ({p['service_debut'] or '…'} à {p['service_fin'] or '…'}).",
                      "importée, à vérifier")


def _energie(plan, n, m, p, cid, mois, valeur, conversions):
    """L'énergie (kWh) du classeur correspond-elle à valeur × facteur de conversion ?"""
    energie = _sur(m.get("energie_kwh"))
    if energie is None:
        return
    if p["unite"] == "kWh":
        attendu = valeur
    else:
        facteurs = conversions.get(CONVERSION_PAR_FLUIDE.get(p["fluide"], ""), {})
        facteur = facteurs.get(mois, facteurs.get("toujours"))
        if facteur is None:
            return
        attendu = valeur * facteur
    if abs(energie - attendu) > max(TOLERANCE_KWH, 0.001 * abs(attendu)):
        plan.anomalie("énergie incohérente", "Mesures", n, cid, mois,
                      f"energie_kwh = {energie:g} alors que valeur × facteur = {attendu:.0f} kWh.",
                      "valeur brute importée, énergie à vérifier")


def _trous(plan, vus):
    """Mois sans AUCUNE ligne dans une série mensuelle en service (hors bons de livraison)."""
    presents = defaultdict(set)
    for (cid, mois) in vus:
        presents[cid].add(mois)
    for cid, p in plan.points.items():
        if p["nature"] == "livraison" or not presents[cid]:
            continue
        bats = plan.sites[p["immeuble_id"]]["batiments"]
        ouvertures = [b["ouverture"] for b in bats if b["ouverture"]]
        ouverture = min(ouvertures) if len(ouvertures) == len(bats) else None  # site entier ouvert en cours de période
        debut = max(x for x in (plan.premier_mois, p["service_debut"], ouverture) if x)
        fin = min(x for x in (plan.dernier_mois, p["service_fin"]) if x)
        absents = [x for x in mois_entre(debut, fin) if x not in presents[cid]]
        if absents:
            plan.stats["mois_absents"] += len(absents)
            plan.anomalie("mois sans relevé", "Mesures", None, cid, f"{absents[0]} à {absents[-1]}",
                          f"{len(absents)} mois sans aucune ligne : {', '.join(absents[:12])}"
                          + ("…" if len(absents) > 12 else "") + ".", "laissés vides, jamais comblés")


def _references(plan, feuilles):
    def ajoute(serie, periode, valeur, unite=None, source=None):
        if valeur is not None and periode:
            plan.references.append((serie, str(periode), float(valeur), unite, source))
    for _n, r in lignes_feuille(feuilles, "Ref_Climat"):
        for cle, unite in (("temperature_moy_c", "°C"), ("degres_jours_20_12", "°C·jour"),
                           ("rayonnement_kwh_m2", "kWh/m²"), ("ensoleillement_h", "h")):
            ajoute(cle, _texte(r.get("mois")), _sur(r.get(cle)), unite, "Ref_Climat")
    for _n, r in lignes_feuille(feuilles, "Ref_Climat_Normale"):
        mois = _sur(r.get("mois_calendaire"))
        for cle, unite in (("temperature_moy_c", "°C"), ("degres_jours_20_12", "°C·jour")):
            ajoute("normale_" + cle, None if mois is None else f"{int(mois):02d}", _sur(r.get(cle)), unite,
                   "Ref_Climat_Normale (1991-2020)")
    for _n, r in lignes_feuille(feuilles, "Ref_Conversion"):
        ajoute("conversion_" + parc._cle(r.get("vecteur")), _texte(r.get("mois")) or "toujours", _sur(r.get("facteur")),
               _texte(r.get("unite")), _texte(r.get("source")))
    for _n, r in lignes_feuille(feuilles, "Ref_CO2"):
        vecteur = parc._cle(r.get("vecteur"))
        ajoute(f"co2_kg_par_unite_{vecteur}", "toujours", _sur(r.get("kg_co2_par_unite")),
               f"kg CO₂ par {_texte(r.get('unite')) or 'unité'}", _texte(r.get("portee")))
        ajoute(f"co2_kg_par_kwh_{vecteur}", "toujours", _sur(r.get("kg_co2_par_kwh")), "kg CO₂ par kWh",
               _texte(r.get("portee")))


def preparer(contenu):
    """Lit et contrôle le classeur sans rien écrire. Retourne un Plan."""
    feuilles = excel.lire_xlsx(contenu)
    presentes = {parc._cle(n) for n in feuilles}
    manquantes = [f for f in FEUILLES_REQUISES if parc._cle(f) not in presentes]
    if manquantes:
        raise ErreurPatrimoine("Classeur patrimoine : feuille(s) manquante(s) : " + ", ".join(manquantes)
                               + ". Attendu : Batiments, Compteurs, Mesures (et Installations, Ref_*).")
    plan = Plan(commune(feuilles))
    mois = sorted({t for _n, m in lignes_feuille(feuilles, "Mesures") if (t := _texte(m.get("mois"))) and MOIS_RE.match(t)})
    if mois:
        plan.premier_mois, plan.dernier_mois = mois[0], mois[-1]
    _sites(plan, feuilles)
    _installations(plan, feuilles)
    _compteurs(plan, feuilles)
    vus = _mesures(plan, feuilles)
    if mois:
        _trous(plan, vus)
    _references(plan, feuilles)
    return plan


# ---------------------------------------------------------------- rapport et écriture


def rapport(cx, plan, applique=False, lot=None):
    connus = parc.immeubles_connus(cx)
    points_connus = {r[0] for r in cx.execute("SELECT id FROM point_mesure")}
    qualites = Counter(q for (_ts, _pid, _v, q) in plan.mesures.values())
    return {
        "commune": plan.commune, "applique": applique, "lot": lot,
        "periode": [plan.premier_mois, plan.dernier_mois],
        "sites": {"total": len(plan.sites), "nouveaux": len(set(plan.sites) - connus)},
        "batiments": len(plan.batiments), "installations": len(plan.installations),
        "compteurs": {"total": len(plan.points), "nouveaux": len(set(plan.points) - points_connus),
                      "actifs": sum(p["etat"] == "actif" for p in plan.points.values()),
                      "hors_service": sum(p["etat"] == "inactif" for p in plan.points.values()),
                      "par_fluide": dict(Counter(db.FLUIDES[p["fluide"]][0] for p in plan.points.values()).most_common())},
        "mesures": {"lues": plan.stats["lues"], "a_importer": len(plan.mesures), "rejetees": plan.stats["rejetees"],
                    "manquantes": plan.stats["manquantes"], "doublons": plan.stats["doublons"],
                    "estimees": qualites["estimee"], "suspectes": qualites["suspecte"],
                    "mois_absents": plan.stats["mois_absents"]},
        "references": len(plan.references), "erreurs": plan.erreurs,
        "anomalies_par_type": dict(Counter(a["type"] for a in plan.anomalies).most_common()),
        "anomalies": plan.anomalies,
    }


def appliquer(cx, plan, dossier_sortie=None):
    """Écrit le plan dans la base (ajout ou mise à jour par code, rien n'est supprimé). Retourne le rapport."""
    lot = "patrimoine-" + uuid.uuid4().hex[:8]
    r = rapport(cx, plan, True, lot)
    for sid, s in plan.sites.items():
        parc.enregistrer_immeuble(cx, s)
        cx.execute("UPDATE immeuble SET typologie = ?, quartier = ? WHERE id = ?", (s["typologie"], s["quartier"], sid))
        if s["x_km"] is not None and s["y_km"] is not None:  # plan du jeu : GPS recalculé, jamais envoyé au géocodeur
            cx.execute("UPDATE adresse SET x_km = ?, y_km = ?, geo_source = ?, lat = NULL, lon = NULL "
                       "WHERE (lat IS NULL OR geo_source = ?) AND id = (SELECT adresse_id FROM immeuble WHERE id = ?)",
                       (s["x_km"], s["y_km"], SOURCE_PLAN, SOURCE_PLAN, sid))
        if not cx.execute("SELECT technique FROM immeuble WHERE id = ?", (sid,)).fetchone()[0]:
            parc.enregistrer_fiche(cx, sid, {"technique": technique(s)})  # une fiche déjà remplie n'est jamais remplacée
    geo.placer_plan(cx)  # coordonnées GPS des sites, calculées depuis le plan du jeu et enregistrées
    champs_b = ("id", "immeuble_id", "nom", "annee_construction", "annee_renovation", "sre_m2", "niveaux", "label",
                "logements", "ouverture", "remarque")
    cx.executemany(f"INSERT OR REPLACE INTO batiment ({', '.join(champs_b)}) VALUES ({', '.join('?' * len(champs_b))})",
                   [tuple(b[c] for c in champs_b) for b in plan.batiments])
    champs_i = ("id", "immeuble_id", "type", "libelle", "vecteur", "puissance_kw", "mise_en_service", "retrait", "remarque")
    cx.executemany(f"INSERT OR REPLACE INTO installation ({', '.join(champs_i)}) VALUES ({', '.join('?' * len(champs_i))})",
                   [tuple(i[c] for c in champs_i) for i in plan.installations])
    for p in plan.points.values():
        parc.enregistrer_point(cx, {k: v for k, v in p.items() if k != "_feuille"})
    cx.executemany("INSERT OR REPLACE INTO mesure VALUES (?,?,?,?,?)",
                   [(ts, pid, v, q, lot) for (ts, pid, v, q) in plan.mesures.values()])
    cx.executemany("INSERT OR REPLACE INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                   plan.references)
    enregistrer_anomalies(cx, lot, None, plan.anomalies)
    cx.commit()
    if db.lire_parametre(cx, "meteo") is None:  # parc mensuel : le climat vient des références du classeur
        db.ecrire_parametre(cx, "meteo", {**meteo.CONFIG_DEFAUT, "auto": False, "message": (
            "Climat mensuel fourni par le classeur patrimoine (table des références). La mise à jour horaire MétéoSuisse "
            "est désactivée ; activez-la pour les règles qui demandent la météo à l'heure.")})
    resume = {k: v for k, v in r.items() if k not in ("anomalies", "erreurs")}
    db.ecrire_parametre(cx, "patrimoine", {**resume, "erreurs": len(plan.erreurs), "anomalies": len(plan.anomalies)})
    if dossier_sortie:
        r["fichier_anomalies"] = exporter_anomalies(cx, dossier_sortie)
    return r


def enregistrer_anomalies(cx, lot, fichier, anomalies):
    """Trace en base des anomalies d'un import. Un nouvel import du même classeur (ou du même fichier de courbes)
    remplace sa trace précédente : la table reflète toujours le dernier import de chaque source."""
    if lot.startswith("courbes-"):
        cx.execute("DELETE FROM anomalie_import WHERE lot LIKE 'courbes-%' AND feuille = ?", (fichier,))
    else:
        cx.execute("DELETE FROM anomalie_import WHERE lot LIKE 'patrimoine-%'")
    cx.executemany("INSERT INTO anomalie_import (lot, type, feuille, ligne, objet, periode, detail, traitement) "
                   "VALUES (?,?,?,?,?,?,?,?)",
                   [(lot, a["type"], a["feuille"], a["ligne"], a["objet"], a["periode"], a["detail"], a["traitement"])
                    for a in anomalies])


COLONNES_ANOMALIES = ("lot", "type", "feuille", "ligne", "objet", "periode", "detail", "traitement")


def anomalies(cx, limite=None):
    sql = f"SELECT {', '.join(COLONNES_ANOMALIES)} FROM anomalie_import ORDER BY id"
    return db.lignes(cx, sql + (" LIMIT ?" if limite else ""), (limite,) if limite else ())


def exporter_anomalies(cx, dossier):
    """Trace de toutes les anomalies d'import (CSV, séparateur ;, lisible dans Excel)."""
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, "anomalies_import.csv")
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLONNES_ANOMALIES)
        w.writerows([["" if a[c] is None else a[c] for c in COLONNES_ANOMALIES] for a in anomalies(cx)])
    return chemin


def importer(cx, contenu, appliquer_=False, dossier_sortie=None):
    """Aperçu (appliquer_=False : aucune écriture) ou import du classeur. Retourne le rapport."""
    plan = preparer(contenu)
    return appliquer(cx, plan, dossier_sortie) if appliquer_ else rapport(cx, plan)
