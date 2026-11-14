"""Enchaînements partagés par la ligne de commande et l'interface web.

analyser : référentiel en base -> moteur -> sorties (json/csv/html) -> suivi des alertes -> bons automatiques.
"""
import json
import os

from . import bons, db, meteo, moteur, rapport
from . import generer_demo
from .generer_demo import generer

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(RACINE, "config", "referentiel.json")
SORTIE = os.path.join(RACINE, "sorties")

# Prestataires FICTIFS des données d'exemple (domaine réservé .example : aucun courriel ne peut partir)
PRESTATAIRES_EXEMPLE = [
    {"nom": "Sanitaire Exemple SA", "metier": "Sanitaire", "contact": "Service dépannage",
     "email": "depannage@sanitaire-exemple.example", "telephone": "+41 22 000 00 01"},
    {"nom": "Chauffage Exemple Sàrl", "metier": "Chauffagiste", "contact": "Bureau technique",
     "email": "technique@chauffage-exemple.example", "telephone": "+41 22 000 00 02"},
    {"nom": "Froid Exemple SA", "metier": "Frigoriste", "contact": "Service PAC",
     "email": "pac@froid-exemple.example", "telephone": "+41 22 000 00 03"},
    {"nom": "Conciergerie des Tilleuls", "metier": "Concierge", "contact": "Concierge",
     "email": "concierge.tilleuls@regie-exemple.example", "telephone": "+41 79 000 00 04", "perimetre": "T8"},
    {"nom": "Conciergerie des Ormeaux", "metier": "Concierge", "contact": "Concierge",
     "email": "concierge.ormeaux@regie-exemple.example", "telephone": "+41 79 000 00 05", "perimetre": "OA,OB"},
    {"nom": "Conciergerie générale", "metier": "Concierge", "contact": "Équipe conciergerie",
     "email": "conciergerie@regie-exemple.example", "telephone": "+41 22 000 00 06"},
    {"nom": "Télérelève Exemple SA", "metier": "Télérelève", "contact": "Support",
     "email": "support@telereleve-exemple.example", "telephone": "+41 22 000 00 07"},
    {"nom": "Électricité Exemple SA", "metier": "Électricien", "contact": "Dépannage",
     "email": "depannage@electricite-exemple.example", "telephone": "+41 22 000 00 08"},
    {"nom": "Solaire Exemple SA", "metier": "Solaire", "contact": "Service photovoltaïque",
     "email": "photovoltaique@solaire-exemple.example", "telephone": "+41 22 000 00 09"},
]


# Partenaires techniques FICTIFS du grand exemple : un par fluide (métier) et par secteur du canton
SECTEURS = {"rive_droite": ("Rive droite", ("1201", "1202", "1203", "1218", "1219")),
            "rive_gauche": ("Rive gauche", ("1204", "1205", "1206", "1207", "1227")),
            "communes": ("Communes", ("1212", "1213", "1224", "1225"))}
PARTENAIRES_FLUIDE = [  # (métier, fluide, nom par secteur)
    ("Électricien", "électricité", {"rive_droite": "Électro Rive Droite Sàrl", "rive_gauche": "Électricité Rive Gauche SA",
                                    "communes": "Courant Communes Sàrl"}),
    ("Frigoriste", "PAC", {"rive_droite": "Thermo-PAC Rive Droite SA", "rive_gauche": "Froid et PAC Rive Gauche Sàrl",
                           "communes": "PAC Service Communes SA"}),
    ("Sanitaire", "eau", {"rive_droite": "Sanitaire Rive Droite SA", "rive_gauche": "Hydro Rive Gauche Sàrl",
                          "communes": "Aqua Communes SA"}),
    ("Chauffagiste", "chaleur", {"rive_droite": "Chauffage Rive Droite SA", "rive_gauche": "Calor Rive Gauche Sàrl",
                                 "communes": "Chaleur Communes SA"}),
    ("Solaire", "photovoltaïque", {"rive_droite": "Soleil Rive Droite Sàrl", "rive_gauche": "Photovolta Rive Gauche SA",
                                   "communes": "Solaire Communes Sàrl"}),
]
GESTIONNAIRES = {"rive_droite": ("C. Exemple — gestion rive droite", "gestion.rivedroite@regie-exemple.example",
                                 "+41 22 000 01 01"),
                 "rive_gauche": ("D. Exemple — gestion rive gauche", "gestion.rivegauche@regie-exemple.example",
                                 "+41 22 000 01 02"),
                 "communes": ("E. Exemple — gestion communes", "gestion.communes@regie-exemple.example",
                              "+41 22 000 01 03")}


def secteur(npa_localite):
    npa = str(npa_localite)[:4]
    return next((k for k, (_, npas) in SECTEURS.items() if npa in npas), "communes")


def partenaires_exemple(immeubles):
    """Partenaires par fluide et par secteur, couvrant les immeubles G* du grand exemple."""
    import re
    par_secteur = {}
    for im in immeubles:
        if im["id"].startswith("G"):
            par_secteur.setdefault(secteur(im["npa"]), []).append(im["id"])
    out = []
    for metier, fluide, noms in PARTENAIRES_FLUIDE:
        for sec, ids in sorted(par_secteur.items()):
            nom = noms[sec]
            slug = re.sub(r"[^a-z0-9]+", "-", nom.lower().replace("é", "e").replace("à", "a")).strip("-")
            out.append({"nom": nom, "metier": metier, "contact": f"Service {fluide}",
                        "email": f"interventions@{slug}.example",
                        "telephone": f"+41 22 000 {len(out) + 10:02d} 00", "perimetre": ",".join(ids)})
    return out


TECHNIQUE_ORIGINE = {
    "T8": {"chauffage": "Mixte PAC + chaudière d'appoint", "ecs": "Par la PAC", "annee_construction": 1978,
           "annee_renovation": 2016, "frigorigene": "R410A", "installation": "PAC air/eau (modèle exemple) + chaudière gaz"},
    "R41": {"chauffage": "Chaudière gaz", "ecs": "Par la chaudière", "annee_construction": 1932, "annee_renovation": 1995},
    "OA": {"chauffage": "Chaudière gaz", "ecs": "Par la chaudière", "annee_construction": 1965},
    "OB": {"chauffage": "Chaudière gaz", "ecs": "Par la chaudière", "annee_construction": 1965},
    "VG": {"chauffage": "Chaudière gaz", "ecs": "Par la chaudière", "annee_construction": 1988, "annee_renovation": 2012},
}
CONCIERGES_ORIGINE = {
    "T8": ("Conciergerie des Tilleuls", "concierge.tilleuls@regie-exemple.example", "+41 79 000 00 04"),
    "OA": ("Conciergerie des Ormeaux", "concierge.ormeaux@regie-exemple.example", "+41 79 000 00 05"),
    "OB": ("Conciergerie des Ormeaux", "concierge.ormeaux@regie-exemple.example", "+41 79 000 00 05"),
    "R41": ("Conciergerie générale", "conciergerie@regie-exemple.example", "+41 22 000 00 06"),
    "VG": ("Conciergerie générale", "conciergerie@regie-exemple.example", "+41 22 000 00 06"),
}


def technique_exemple(im, n, logements):
    """Données techniques fictives cohérentes avec les compteurs de l'immeuble (CAD, gaz ou PAC)."""
    fluides = {p.get("fluide") for p in im.get("points", [])}
    kw = round(logements * 1.8)
    commun = {"annee_construction": 1950 + n % 60, "annee_installation": 2012 + n % 12}
    if "cad" in fluides:
        return {**commun, "chauffage": "Chauffage à distance (CAD)", "ecs": "CAD",
                "installation": f"Sous-station CAD {kw} kW (modèle exemple)"}
    if "gaz" in fluides:
        return {**commun, "chauffage": "Chaudière gaz", "ecs": "Par la chaudière",
                "installation": f"Chaudière gaz à condensation {kw} kW (modèle exemple)"}
    return {**commun, "chauffage": "PAC air/eau" if n % 3 else "PAC sol/eau", "ecs": "Par la PAC",
            "frigorigene": "R32" if n % 2 else "R410A", "installation": f"PAC {kw} kW (modèle exemple)"}


def fiche_exemple(im):
    """Contacts et données techniques fictifs d'un immeuble de l'exemple (déterministes)."""
    n = sum(ord(c) for c in im["id"])
    concierge = CONCIERGES_ORIGINE.get(im["id"]) or (
        f"Concierge {im['nom']}", f"concierge.{im['id'].lower()}@regie-exemple.example",
        f"+41 79 000 {n % 90 + 10:02d} {n % 7 + 10:02d}")
    logements = im.get("logements") or 20
    tech = dict(TECHNIQUE_ORIGINE.get(im["id"]) or technique_exemple(im, n, logements))
    tech.setdefault("puissance_kw", round(logements * 1.8))
    tech.setdefault("etages", 3 + n % 6)
    tech.setdefault("emplacement", "Sous-sol, local technique")
    g = GESTIONNAIRES[secteur(im["npa"])]
    return {"gestionnaire": g[0], "gestionnaire_email": g[1], "gestionnaire_tel": g[2], "concierge": concierge[0],
            "concierge_email": concierge[1], "concierge_tel": concierge[2], "technique": tech}


def completer_exemple(cx, immeubles):
    """Fiches (contacts, technique) et partenaires par fluide de l'exemple ; ne remplace jamais une fiche remplie."""
    from . import parc
    for im in immeubles:
        r = cx.execute("SELECT gestionnaire, technique FROM immeuble WHERE id = ?", (im["id"],)).fetchone()
        if r and not r[0] and not r[1]:
            parc.enregistrer_fiche(cx, im["id"], fiche_exemple(im))
    deja = {(p["nom"], p["metier"]) for p in db.lignes(cx, "SELECT nom, metier FROM prestataire")}
    for p in partenaires_exemple(immeubles):
        if (p["nom"], p["metier"]) not in deja:
            cx.execute("INSERT INTO prestataire (nom, metier, contact, email, telephone, perimetre) VALUES (?,?,?,?,?,?)",
                       (p["nom"], p["metier"], p["contact"], p["email"], p["telephone"], p["perimetre"]))
    cx.commit()


def defauts():
    with open(REF, encoding="utf-8") as f:
        return json.load(f)


def analyser(cx, mot_de_passe=None, automatiser=True, envoi=None):
    ref = db.referentiel(cx, defauts())
    alertes, fin = moteur.analyser(cx, ref)
    if fin is None:
        return {"alertes": [], "donnees_au": None, "nouvelles": [], "bons": None}
    os.makedirs(SORTIE, exist_ok=True)
    rapport.ecrire([a for a in alertes if not a.get("sourdine")], fin, SORTIE)  # sourdines : hors des alertes à traiter
    nouvelles = bons.synchroniser_alertes(cx, alertes)
    auto = bons.automatiser(cx, nouvelles, mot_de_passe, envoi) if automatiser else None
    db.ecrire_parametre(cx, "derniere_analyse", {"le": bons.maintenant(), "donnees_au": str(fin), "alertes": len(alertes)})
    return {"alertes": alertes, "donnees_au": str(fin), "nouvelles": nouvelles, "bons": auto}


def parc_vide(cx):
    return cx.execute("SELECT count(*) FROM immeuble").fetchone()[0] == 0


GRAND = os.path.join(RACINE, "config", "exemple_grand.json")


def exemple_grand():
    with open(GRAND, encoding="utf-8") as f:
        return json.load(f)


def charger_exemple(cx, graine=42, meteo_reelle=False, telecharger_fn=None, taille="standard"):
    """Parc fictif, prestataires fictifs et 12 mois de consommations simulées (horaires) avec dérives injectées.

    taille="standard" : 5 immeubles (4 adresses), référence de validation. taille="grand" : + 16 immeubles chauffés
    par PAC, au chauffage à distance ou au gaz à de vraies adresses genevoises (config/exemple_grand.json), soit
    24 adresses.

    meteo_reelle=True : la température est la vraie série MétéoSuisse de Genève-Cointrin (les consommations
    simulées de chauffage et de PAC en dépendent) ; repli sur la température fictive si MétéoSuisse est injoignable.
    """
    os.makedirs(SORTIE, exist_ok=True)
    csv_demo = os.path.join(SORTIE, "donnees_demo.csv")
    temperatures, avertissement = None, None
    ref = defauts()
    supplementaires = exemple_grand()["immeubles"] if taille == "grand" else None
    if supplementaires:
        ref = {**ref, "immeubles": ref["immeubles"] + supplementaires}
    rayonnement = None
    if meteo_reelle:
        try:
            temperatures, rayonnement = meteo.meteo_reelle(jours=generer_demo.JOURS + 10, telecharger_fn=telecharger_fn)
        except (meteo.ErreurMeteo, ValueError) as e:
            avertissement = f"Météo réelle indisponible ({e}) : température fictive utilisée."
        if rayonnement is not None and len(rayonnement) < 0.9 * generer_demo.JOURS * 24:
            rayonnement = None  # rayonnement réel absent ou lacunaire : production solaire simulée sur rayonnement fictif
    try:
        n = generer(csv_demo, graine=graine, temperatures=temperatures,
                    point_meteo="METEO_GVE" if temperatures else ref["meteo"]["id"], supplementaires=supplementaires,
                    rayonnement=rayonnement if temperatures else None,
                    point_rayonnement="RAYON_GVE" if temperatures and rayonnement else ref["rayonnement"]["id"])
    except ValueError as e:  # série réelle trop lacunaire
        avertissement, temperatures, rayonnement = f"{e} Température fictive utilisée.", None, None
        n = generer(csv_demo, graine=graine, supplementaires=supplementaires)
    db.charger_referentiel(cx, ref, PRESTATAIRES_EXEMPLE)
    pid_ray = None
    if temperatures:
        db.ecrire_parametre(cx, "meteo", {**meteo.CONFIG_DEFAUT, "point_id": None})
        pid = meteo.point_meteo(cx, meteo.STATION_DEFAUT)  # crée METEO_GVE et met la météo fictive hors service
        if rayonnement:  # crée RAYON_GVE et met le rayonnement fictif hors service
            pid_ray = meteo.point_meteo(cx, meteo.STATION_DEFAUT, "rayonnement")
        message = ("Météo RÉELLE MétéoSuisse Genève-Cointrin ; consommations simulées à partir d'elle jusqu'à la "
                   "création de l'exemple. Une mise à jour n'ajoute que les heures nouvelles.")
        statut = "exemple_reel"
    else:
        pid = defauts()["meteo"]["id"]
        message, statut = "Températures fictives de la base d'exemple.", "exemple"
    # Base d'exemple : mise à jour automatique désactivée par défaut. Sur météo réelle, une mise à jour (manuelle ou
    # cochée) n'ajoute que les heures nouvelles : celles qui ont servi à la simulation ne sont jamais réécrites.
    db.ecrire_parametre(cx, "meteo", {**meteo.CONFIG_DEFAUT, "source": "exemple", "auto": False, "point_id": pid,
                                      "point_rayonnement": pid_ray, "statut": statut, "message": message})
    completer_exemple(cx, ref["immeubles"])
    ok, rejets, lot = db.importer_csv(cx, csv_demo)
    if temperatures:
        derniere = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = ?", (pid,)).fetchone()[0]
        db.ecrire_parametre(cx, "meteo", {**meteo.lire_config(cx), "derniere_mesure": derniere,
                                          "derniere_maj": bons.maintenant()})
    return {"mesures": n, "importees": ok, "rejets": len(rejets), "lot": lot,
            "meteo": "réelle" if temperatures else "fictive", "avertissement": avertissement}
