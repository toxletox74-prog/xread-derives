"""Serveur MCP (Model Context Protocol) de Vigie : le moteur de dérives interrogé par un assistant IA.

  python -m vigie mcp           sur vigie.db
  python -m vigie mcp --demo    sur la base d'exemple (données fictives)

Transport « stdio » : un message JSON-RPC 2.0 par ligne sur l'entrée standard, les réponses sur la sortie standard
(bibliothèque standard uniquement). Le serveur n'ouvre aucun port et n'appelle aucun service.
Transport HTTP : POST /mcp du serveur web, avec la clé API d'un espace de service tiers (espaces.py) ; les outils
lisent alors la base de cet espace et elle seule (repondre_http).

LECTURE SEULE : aucun outil ne modifie la base, n'envoie de bon ni ne change un réglage. « analyser_a_blanc » calcule
la détection sans rien enregistrer (les alertes en base ne bougent que par l'interface ou `python -m vigie analyser`).

Règle 5 : tous les chiffres renvoyés sortent du moteur ; l'assistant les cite, il ne les recalcule pas.
Règle 9 : ce que les outils renvoient est lu par l'assistant qui les appelle. Avec un modèle hébergé, les alertes et
leurs chiffres quittent donc le poste : à réserver à la base d'exemple, ou à un parc dont le détenteur des données l'a
accepté. Les courbes de consommation ne sont pas exposées.
"""
import contextlib
import json
import sys
import traceback
from types import SimpleNamespace

from . import bons, db, moteur, parc, serveur, service

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # versions du protocole acceptées, la plus récente d'abord
CONSIGNES = (
    "Xread Dérives (Vigie) détecte les dérives de consommation d'un parc immobilier (électricité, gaz, chaleur, "
    "chauffage à distance, PAC, eau, solaire). Outils en lecture seule. Tous les chiffres (kWh, m³, CHF, CO₂) sont "
    "calculés par le moteur : citez-les tels quels, sans les recalculer, les arrondir autrement ni les extrapoler. "
    "Une valeur absente (null) est une donnée manquante : ne la comblez pas, dites qu'elle manque. Les montants "
    "« _mois » sont un rythme par 30 jours, « _mesure » l'excès déjà mesuré, « _proj » une projection sous hypothèse.")
STATUTS_ALERTE = ("ouverte", "sourdine", "resolue", "toutes")
RESUME_ALERTE = ("id", "rang", "gravite", "immeuble_id", "immeuble", "adresse", "fluide", "cause", "titre", "constat",
                 "debut", "persistance", "confiance", "chf_mois", "kwh_mois", "m3_mois", "co2_t_mois", "metier", "delai",
                 "statut", "suivi")
RESUME_POINT = ("id", "libelle", "fluide", "unite", "pas_min", "etat", "derniere", "completude", "alertes")
REQ = SimpleNamespace(headers={}, query={})  # requête vide : les lectures de l'API sont appelées sans passer par HTTP


def _resume(a):
    return {k: a.get(k) for k in RESUME_ALERTE}


def etat(app):
    e = app.etat(REQ)
    e.pop("acces")  # propre à l'interface web
    return e


def lister_alertes(app, statut="ouverte", immeuble_id=None, gravite=None):
    if statut not in STATUTS_ALERTE:
        raise parc.ErreurSaisie("Statut : " + ", ".join(STATUTS_ALERTE) + ".")
    alertes = bons.liste_alertes(app.cx, None if statut == "toutes" else statut)
    return {"alertes": [_resume(a) for a in alertes if immeuble_id in (None, a["immeuble_id"])
                        and gravite in (None, a["gravite"])]}


def lire_alerte(app, id):  # noqa: A002 — nom du paramètre de l'outil
    a = next((a for a in bons.liste_alertes(app.cx, None) if a["id"] == id), None)
    if a is None:
        raise parc.ErreurSaisie("Alerte introuvable.")
    return a


def lire_parc(app):
    arbre = parc.arbre(app.cx)
    return {"fin_donnees": arbre["fin_donnees"], "adresses": [
        {"rue": ad["rue"], "npa_localite": ad["npa_localite"], "immeubles": [
            {**{k: im.get(k) for k in ("id", "nom", "profil", "logements", "sre_m2")},
             "compteurs": [{k: p.get(k) for k in RESUME_POINT} for p in im["points"]]}
            for im in ad["immeubles"]]} for ad in arbre["adresses"]]}


def lire_immeuble(app, id):  # noqa: A002
    f = app.lire_fiche(REQ, id)
    for cle in ("listes", "suivis", "resultats_retour"):  # listes de choix des formulaires de l'interface
        f.pop(cle)
    return f


def lister_regles(app):
    r = parc.liste_regles(app.cx, service.defauts())
    for regle in r["regles"]:
        regle.pop("defaut")
    return {k: r[k] for k in ("regles", "qualite", "couverture")}


def analyser_a_blanc(app):
    alertes, fin = moteur.analyser(app.cx, db.referentiel(app.cx, service.defauts()))
    en_base = {a["id"] for a in bons.liste_alertes(app.cx, None) if a["statut"] == "ouverte"}
    calculees = {a["id"] for a in alertes}
    return {"donnees_au": None if fin is None else str(fin), "enregistre": False,
            "alertes": [_resume(a) for a in alertes],
            "absentes_de_la_base": sorted(calculees - en_base),  # seraient ouvertes par une analyse enregistrée
            "plus_detectees": sorted(en_base - calculees)}       # seraient résolues par une analyse enregistrée


def lister_bons(app):
    return {"bons": bons.liste_bons(app.cx)}


def lire_rejeu(app):
    return app.lire_rejeu(REQ)


_TEXTE = {"type": "string"}
OUTILS = [  # (fonction, description, propriétés du schéma d'entrée, paramètres obligatoires)
    (etat, "État général : fin des données, date de la dernière analyse, nombre de compteurs et d'alertes, rythme "
           "mensuel cumulé des dérives ouvertes (CHF, kWh, m³, CO₂), état de la météo, couverture des règles.", {}, []),
    (lister_alertes, "Alertes de dérive enregistrées, de la plus prioritaire à la moins prioritaire (résumé : "
                     "immeuble, fluide, gravité, constat, début, rythme mensuel chiffré, suivi).",
     {"statut": {"type": "string", "enum": list(STATUTS_ALERTE), "description": "Par défaut : ouverte."},
      "immeuble_id": {**_TEXTE, "description": "Limiter à un immeuble (identifiant, ex. R41)."},
      "gravite": {"type": "string", "enum": [*moteur.GRAVITES, "Données"]}}, []),
    (lire_alerte, "Détail complet d'une alerte : mesure et attendu, persistance, confiance, chiffrage (mesuré, par "
                  "mois, projeté), consigne, payeur, bon de travaux lié.",
     {"id": {**_TEXTE, "description": "Identifiant de l'alerte (ex. R41-chaleur_vide)."}}, ["id"]),
    (lire_parc, "Parc : adresses, immeubles et compteurs (fluide, pas de relevé, état, dernier relevé, complétude).",
     {}, []),
    (lire_immeuble, "Fiche d'un immeuble : contacts, données techniques, partenaires par fluide, alertes, historique "
                    "des événements, déclarations (sourdines, travaux, vacance, changements).",
     {"id": {**_TEXTE, "description": "Identifiant de l'immeuble."}}, ["id"]),
    (lister_regles, "Règles de détection et leurs réglages (seuil, persistance, gravité, profils, métier, consigne), "
                    "seuils de qualité des données, couverture des compteurs par les règles.", {}, []),
    (analyser_a_blanc, "Calcule la détection sur les relevés actuels SANS RIEN ENREGISTRER (ni alerte, ni bon, ni "
                       "courriel) et la compare aux alertes ouvertes en base. Peut prendre plusieurs dizaines de "
                       "secondes sur un grand parc.", {}, []),
    (lister_bons, "Bons de travaux (destinataire, statut, journal, retour d'intervention, résumé de l'alerte).", {}, []),
    (lire_rejeu, "Dernier rejeu de la détection sur une période passée : épisodes de dérive, date de détection, durée.",
     {}, []),
]
FONCTIONS = {f.__name__: (f, set(proprietes), set(requis)) for f, _, proprietes, requis in OUTILS}


def liste_outils():
    return [{"name": f.__name__, "description": description,
             "inputSchema": {"type": "object", "properties": proprietes, "required": requis,
                             "additionalProperties": False},
             "annotations": {"readOnlyHint": True}} for f, description, proprietes, requis in OUTILS]


def appeler(app, nom, arguments):
    """Résultat d'un outil au format MCP. Une erreur de saisie est rendue à l'assistant, qui peut se corriger."""
    fonction, connus, requis = FONCTIONS[nom]
    try:
        if set(arguments) - connus:
            raise parc.ErreurSaisie("Paramètre inconnu : " + ", ".join(sorted(set(arguments) - connus)) + ".")
        if requis - set(arguments):
            raise parc.ErreurSaisie("Paramètre obligatoire : " + ", ".join(sorted(requis - set(arguments))) + ".")
        resultat, erreur = fonction(app, **arguments), False
    except serveur.ERREURS_METIER as e:
        resultat, erreur = {"erreur": str(e)}, True
    except Exception:  # noqa: BLE001 — journalisé sur la sortie d'erreur, message générique à l'assistant
        traceback.print_exc(file=sys.stderr)
        resultat, erreur = {"erreur": "Erreur interne de Vigie."}, True
    return {"content": [{"type": "text", "text": json.dumps(resultat, ensure_ascii=False, default=str)}],
            "isError": erreur}


def traiter(app, message):
    """Réponse JSON-RPC à un message du client, ou None s'il n'en attend pas (notification, réponse)."""
    if not isinstance(message, dict) or "method" not in message or "id" not in message:
        return None
    methode, params = message["method"], message.get("params") or {}
    reponse = {"jsonrpc": "2.0", "id": message["id"]}
    if methode == "initialize":
        demandee = params.get("protocolVersion")
        reponse["result"] = {"protocolVersion": demandee if demandee in VERSIONS else VERSIONS[0],
                             "capabilities": {"tools": {}}, "instructions": CONSIGNES,
                             "serverInfo": {"name": "xread-derives", "title": "Xread Dérives (Vigie)",
                                            "version": "0.3.0"}}
    elif methode == "ping":
        reponse["result"] = {}
    elif methode == "tools/list":
        reponse["result"] = {"tools": liste_outils()}
    elif methode == "tools/call" and params.get("name") in FONCTIONS and isinstance(params.get("arguments") or {}, dict):
        reponse["result"] = appeler(app, params["name"], params.get("arguments") or {})
    elif methode == "tools/call":
        reponse["error"] = {"code": -32602, "message": "Outil inconnu ou arguments illisibles."}
    else:
        reponse["error"] = {"code": -32601, "message": f"Méthode inconnue : {methode}"}
    return reponse


def repondre_http(app, corps):
    """Transport HTTP (« Streamable HTTP » sans flux SSE) : un message JSON-RPC, ou un lot, par requête POST.

    Rend (code HTTP, réponse) ; réponse None (202) quand le client n'en attend pas (notification, réponse)."""
    try:
        message = json.loads(corps or b"null")
    except ValueError:
        return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON illisible."}}
    if isinstance(message, list):  # lot de messages (protocole 2025-03-26)
        reponse = [r for r in (traiter(app, m) for m in message) if r is not None] or None
    else:
        reponse = traiter(app, message)
    return (202, None) if reponse is None else (200, reponse)


def servir(chemin_base, entree=None, sortie=None):
    """Boucle stdio jusqu'à la fermeture de l'entrée. La sortie standard est réservée au protocole."""
    entree, sortie = entree or sys.stdin.buffer, sortie or sys.stdout.buffer
    with contextlib.redirect_stdout(sys.stderr):  # un print() égaré ne doit jamais corrompre le flux JSON-RPC
        app = serveur.Application(chemin_base)
        try:
            for ligne in entree:
                if not ligne.strip():
                    continue
                try:
                    reponse = traiter(app, json.loads(ligne))
                except ValueError:
                    reponse = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON illisible."}}
                if reponse is not None:
                    sortie.write(json.dumps(reponse, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
                    sortie.flush()
        finally:
            app.cx.close()
