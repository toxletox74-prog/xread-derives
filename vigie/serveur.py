"""Serveur local de l'interface de gestion (bibliothèque standard uniquement).

Écoute uniquement sur 127.0.0.1 : aucune donnée ne quitte le poste (règle 9). Protections :
  - en-tête Host vérifié (empêche le « DNS rebinding » depuis un site web malveillant) ;
  - toute requête qui modifie quelque chose doit porter l'en-tête X-Vigie (bloque les formulaires d'autres sites) ;
  - lecture seule sans identification dès qu'un mot de passe est défini ou qu'un serveur frontal relaie (acces.py) ;
  - taille des envois limitée ; erreurs détaillées dans la console, message simple dans l'interface.
"""
import contextlib
import io
import json
import mimetypes
import os
import re
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import acces, bons, connecteur, courbes, db, declarations, excel, geo, meteo, moteur, parc, patrimoine
from . import planification, secret, service

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
FICHIER_WEB_RE = re.compile(r"^/([a-z_]+\.(?:js|css|html))$")  # fichiers plats de vigie/web, sans sous-dossier
TAILLE_MAX = 50 * 1024 * 1024
ERREURS_METIER = (parc.ErreurSaisie, bons.ErreurBon, excel.ErreurExcel, meteo.ErreurMeteo, geo.ErreurGeo,
                  connecteur.ErreurConnecteur, secret.ErreurSecret, patrimoine.ErreurPatrimoine,
                  declarations.ErreurDeclaration)
ANOMALIES_MAX = 300  # anomalies d'import renvoyées à l'écran (toutes sont dans la base et le fichier CSV)
# Appels réseau au fournisseur : connexion SQLite propre, sans le verrou commun (l'interface reste utilisable, et le
# fournisseur de démonstration, servi par ce même serveur, peut répondre pendant l'appel).
# Ouverture de session : hors verrou aussi (le délai après un mot de passe faux ne doit pas figer l'interface).
SANS_VERROU = {"tester_connecteur", "synchroniser_connecteur", "demo_fournisseur", "ouvrir_session"}
ORDRE_ETAT = {"Critique": 0, "Élevée": 1, "Modérée": 2, "Données": 3, "Attente": 4, "OK": 5}
TUILES = "https://wmts.geo.admin.ch"  # fonds de carte swisstopo (seule ressource externe autorisée)


class Fichier:
    def __init__(self, contenu, nom, type_mime):
        self.contenu, self.nom, self.type_mime = contenu, nom, type_mime


class Reponse:
    """Réponse JSON avec un code HTTP choisi (fournisseur de démonstration : 401, 404…)."""

    def __init__(self, code, donnees, entetes=None):
        self.code, self.donnees, self.entetes = code, donnees, entetes


class Application:
    """État partagé du serveur : une connexion SQLite protégée par un verrou."""

    def __init__(self, chemin_base):
        self.chemin = chemin_base
        self.cx = db.connecter(chemin_base)
        self.verrou = threading.Lock()
        self.mot_de_passe = None  # mot de passe SMTP : en mémoire seulement, jamais écrit sur disque
        self.demo = connecteur.FournisseurDemo()
        self.acces = acces.Acces(os.environ.get(acces.ENV))  # lecture seule sans identification (voir acces.py)
        if geo.placer_plan(self.cx):  # base importée avant l'enregistrement des coordonnées GPS des sites fictifs
            self.cx.commit()
        if os.path.basename(chemin_base) == "vigie_demo.db" and meteo.lire_config(self.cx)["source"] != "exemple":
            # base d'exemple créée avant la V0.2 météo : ses températures fictives ne doivent pas être remplacées
            db.ecrire_parametre(self.cx, "meteo", {**meteo.lire_config(self.cx), "source": "exemple", "auto": False,
                                                   "statut": "exemple",
                                                   "message": "Températures fictives de la base d'exemple."})
        self.routes = [
            ("GET", r"/api/etat", self.etat),
            ("POST", acces.SESSION, self.ouvrir_session),
            ("DELETE", acces.SESSION, self.fermer_session),
            ("GET", r"/api/parc", self.lire_parc),
            ("POST", r"/api/immeubles", self.ecrire_immeuble),
            ("DELETE", r"/api/immeubles/([^/]+)", self.effacer_immeuble),
            ("POST", r"/api/compteurs", self.ecrire_compteur),
            ("DELETE", r"/api/compteurs/([^/]+)", self.effacer_compteur),
            ("GET", r"/api/serie/([^/]+)", self.serie),
            ("GET", r"/api/consommation/([^/]+)", self.consommation),
            ("GET", r"/api/immeubles/([^/]+)/fiche", self.lire_fiche),
            ("PUT", r"/api/immeubles/([^/]+)/fiche", self.ecrire_fiche),
            ("GET", r"/api/immeubles/([^/]+)/declarations", self.lire_declarations),
            ("POST", r"/api/immeubles/([^/]+)/declarations", self.ecrire_declaration),
            ("DELETE", r"/api/declarations/(\d+)", self.effacer_declaration),
            ("PUT", r"/api/bons/(\d+)/destinataire", self.destinataire_bon),
            ("POST", r"/api/bons/(\d+)/retour", self.retour_bon),
            ("GET", r"/api/prestataires", self.lire_prestataires),
            ("POST", r"/api/prestataires", self.ecrire_prestataire),
            ("PUT", r"/api/prestataires/(\d+)", self.ecrire_prestataire),
            ("DELETE", r"/api/prestataires/(\d+)", self.effacer_prestataire),
            ("GET", r"/api/regles", self.lire_regles),
            ("PUT", r"/api/regles/([a-z_]+)", self.ecrire_regle),
            ("DELETE", r"/api/regles/([a-z_]+)", self.effacer_regle),
            ("GET", r"/api/couts", self.lire_couts),
            ("PUT", r"/api/couts", self.ecrire_couts),
            ("GET", r"/api/alertes", self.lire_alertes),
            ("POST", r"/api/alertes/([^/]+)/retour", self.retour_alerte),
            ("POST", r"/api/alertes/([^/]+)/bon", self.bon_alerte),
            ("GET", r"/api/bons", self.lire_bons),
            ("GET", r"/api/bons/(\d+)", self.lire_bon),
            ("PUT", r"/api/bons/(\d+)", self.ecrire_bon),
            ("POST", r"/api/bons/(\d+)/envoyer", self.envoyer_bon),
            ("GET", r"/api/bons/(\d+)/eml", self.eml_bon),
            ("GET", r"/api/reglages", self.lire_reglages),
            ("PUT", r"/api/reglages", self.ecrire_reglages),
            ("GET", r"/api/carte", self.lire_carte),
            ("POST", r"/api/geocoder", self.geocoder),
            ("PUT", r"/api/adresses/([^/]+)/coordonnees", self.ecrire_coordonnees),
            ("GET", r"/api/meteo", self.lire_meteo),
            ("PUT", r"/api/meteo", self.ecrire_meteo),
            ("POST", r"/api/meteo/maj", self.maj_meteo),
            ("POST", r"/api/analyser", self.analyser),
            ("POST", r"/api/exemple", self.exemple),
            ("POST", r"/api/import/parc", self.import_parc),
            ("GET", r"/api/export/parc", self.export_parc),
            ("POST", r"/api/import/mesures", self.import_mesures),
            ("POST", r"/api/import/patrimoine", self.import_patrimoine),
            ("GET", r"/api/import/patrimoine", self.lire_patrimoine),
            ("POST", r"/api/import/courbes", self.import_courbes),
            ("GET", r"/api/rejeu", self.lire_rejeu),
            ("GET", r"/api/connecteur", self.lire_connecteur),
            ("PUT", r"/api/connecteur", self.ecrire_connecteur),
            ("DELETE", r"/api/connecteur/cle", self.effacer_cle_connecteur),
            ("POST", r"/api/connecteur/tester", self.tester_connecteur),
            ("POST", r"/api/connecteur/synchroniser", self.synchroniser_connecteur),
            ("POST", r"/api/connecteur/demo", self.demo_connecteur),
            ("GET", r"/demo-fournisseur/points/([^/]+)/mesures", self.demo_fournisseur),
        ]

    # ------------------------------------------------------------ lecture

    def etat(self, req):
        cx = self.cx
        ouvertes = bons.liste_alertes(cx, "ouverte")
        metier = [a for a in ouvertes if a["gravite"] != "Données"]
        _, fin = db.etat_points(cx)
        nb = lambda sql: cx.execute(sql).fetchone()[0]
        tarifs = db.lire_parametre(cx, "tarifs") or service.defauts()["tarifs"]
        return {
            "base": os.path.basename(self.chemin),
            "parc_vide": service.parc_vide(cx),
            "derniere_analyse": db.lire_parametre(cx, "derniere_analyse"),
            "fin_donnees": fin,
            "compteurs": {"total": nb("SELECT count(*) FROM point_mesure WHERE immeuble_id IS NOT NULL"),
                          "actifs": nb("SELECT count(*) FROM point_mesure WHERE immeuble_id IS NOT NULL AND etat = 'actif'"),
                          "a_connecter": nb("SELECT count(*) FROM point_mesure WHERE etat = 'a_connecter'")},
            "immeubles": nb("SELECT count(*) FROM immeuble"), "adresses": nb("SELECT count(*) FROM adresse"),
            "kpis": {"alertes": len(ouvertes), "critiques": sum(a["gravite"] == "Critique" for a in ouvertes),
                     "donnees": sum(a["gravite"] == "Données" for a in ouvertes),
                     # rythme par 30 jours (tous fluides, comparable) et excès déjà mesuré (chauffage, PAC)
                     **{cle: sum(a.get(cle) or 0 for a in metier)
                        for cle in ("chf_mois", "kwh_mois", "m3_mois", "co2_t_mois", "chf_mesure", "chf_proj", "chf_an")},
                     "bons_ouverts": nb("SELECT count(*) FROM bon WHERE statut IN ('brouillon','envoye','en_cours')"),
                     "bons_brouillon": nb("SELECT count(*) FROM bon WHERE statut = 'brouillon'"),
                     "pertinence": bons.pertinence(cx)},
            "tarifs_exemple": any(t.get("_statut", "EXEMPLE") != "CONTRAT" for t in tarifs.values()),
            "meteo": self.etat_meteo(fin),
            # parc avec le climat du classeur patrimoine : la météo horaire n'est pas attendue d'office
            "climat_mensuel": bool(nb("SELECT count(*) FROM reference WHERE serie = 'temperature_moy_c'")),
            "patrimoine": db.lire_parametre(cx, "patrimoine"),
            # règles qui ne correspondent pas à la granularité des compteurs de leur fluide, compteurs sans règle
            "couverture": parc.liste_regles(cx, service.defauts())["couverture"],
            "smtp_configure": bons.smtp_configure(bons.lire_messagerie(cx)),
            "acces": self.acces.etat(req.headers),
            # envoi automatique des bons demandé, mais mot de passe SMTP perdu (redémarrage) : à montrer (règle 3)
            "smtp_mot_de_passe_manquant": bons.mot_de_passe_manquant(cx, self.mot_de_passe),
        }

    def ouvrir_session(self, req):
        temoin = self.acces.ouvrir(req.json().get("mot_de_passe"), req.headers)
        if not temoin:
            return Reponse(401, {"erreur": "Mot de passe incorrect."})
        return Reponse(200, {"ok": True}, {"Set-Cookie": temoin})

    def fermer_session(self, req):
        return Reponse(200, {"ok": True}, {"Set-Cookie": self.acces.fermer(req.headers)})

    def etat_meteo(self, fin):
        """La température extérieure conditionne 2 règles : son absence ou son silence doit se voir (règle 3)."""
        r = self.cx.execute("SELECT max(m.ts) FROM point_mesure p LEFT JOIN mesure m ON m.point_id = p.id "
                            "WHERE p.fluide = 'meteo' AND p.etat = 'actif'").fetchone()
        derniere = r[0] if r else None
        P = {**service.defauts()["parametres"], **(db.lire_parametre(self.cx, "parametres") or {})}
        muette = bool(fin and derniere) and self.cx.execute(
            "SELECT (julianday(?) - julianday(?)) * 24 > ?", (fin, derniere, P["silence_max_heures"])).fetchone()[0]
        return {"derniere": derniere, "ok": bool(derniere) and not muette}

    def lire_parc(self, req):
        return {**parc.arbre(self.cx), "listes": {
            "profils": moteur.PROFILS, "fluides": [{"id": k, "libelle": v[0], "unite": v[1], "nature": v[2]}
                                                   for k, v in db.FLUIDES.items()],
            "natures": list(db.NATURES), "unites": list(parc.UNITES), "pas": list(parc.PAS),
            "sources": parc.SOURCES, "etats": list(db.ETATS_POINT)}}

    def serie(self, req, pid):
        try:
            jours = min(365, max(7, int((req.query.get("jours") or ["60"])[0])))
        except ValueError:
            jours = 60
        return serie_journaliere(self.cx, pid, jours)

    def consommation(self, req, pid):
        echelle = (req.query.get("echelle") or ["jour"])[0]
        return serie_consommation(self.cx, pid, echelle)

    def lire_fiche(self, req, iid):
        f = parc.fiche(self.cx, iid)
        f["alertes"] = [a for a in bons.liste_alertes(self.cx, None) if a["immeuble_id"] == iid]
        f["historique"] = bons.historique(self.cx, iid)
        f["suivis"] = bons.SUIVIS
        f["resultats_retour"] = bons.RESULTATS_RETOUR
        f["declarations"] = self.lire_declarations(req, iid)
        return f

    def ecrire_fiche(self, req, iid):
        parc.enregistrer_fiche(self.cx, iid, req.json())
        return self.lire_fiche(req, iid)

    def lire_declarations(self, req, iid):
        """Sourdines, périodes de travaux ou de vacance et changements déclarés sur l'immeuble."""
        return {"declarations": declarations.liste(self.cx, iid), "types": declarations.TYPES,
                "etats": declarations.ETATS}

    def ecrire_declaration(self, req, iid):
        declarations.creer(self.cx, iid, req.json())
        return self.lire_declarations(req, iid)

    def effacer_declaration(self, req, did):
        return self.lire_declarations(req, declarations.supprimer(self.cx, int(did)))

    def destinataire_bon(self, req, bid):
        return bons.changer_destinataire(self.cx, int(bid), req.json().get("destinataire_type"))

    def retour_bon(self, req, bid):
        d = req.json()
        return bons.enregistrer_retour_incident(self.cx, int(bid), d.get("resultat"), d.get("texte"), d.get("le") or None)

    def lire_prestataires(self, req):
        regles = moteur.regles_effectives({"regles": db.lire_regles(self.cx)})
        return {"prestataires": db.lignes(self.cx, "SELECT * FROM prestataire ORDER BY actif DESC, metier, nom"),
                "metiers": moteur.METIERS,
                "besoins": sorted({r["metier"] for r in regles.values() if r["active"]} | {moteur.METIER_DONNEES})}

    def lire_regles(self, req):
        return parc.liste_regles(self.cx, service.defauts())

    def lire_couts(self, req):
        return parc.lire_couts(self.cx, service.defauts())

    def lire_alertes(self, req):
        statut = (req.query.get("statut") or ["ouverte"])[0]
        return {"alertes": bons.liste_alertes(self.cx, None if statut == "toutes" else statut)}

    def lire_bons(self, req):
        return {"bons": bons.liste_bons(self.cx)}

    def lire_bon(self, req, bid):
        b = bons.lire_bon(self.cx, int(bid))
        b["prestataires"] = db.lignes(self.cx, "SELECT id, nom, metier, email FROM prestataire WHERE actif = 1 "
                                               "ORDER BY metier, nom")
        donnees = self.cx.execute("SELECT donnees FROM alerte WHERE id = ?", (b["alerte_id"],)).fetchone()
        b["destinataires"] = bons.destinataires(self.cx, json.loads(donnees[0])) if donnees else {}
        b["resultats_retour"] = bons.RESULTATS_RETOUR
        return b

    def lire_reglages(self, req):
        return {"automatisation": bons.lire_automatisation(self.cx), "messagerie": bons.lire_messagerie(self.cx),
                "mot_de_passe_present": bool(self.mot_de_passe or os.environ.get(bons.ENV_MOT_DE_PASSE)),
                "mot_de_passe_manquant": bons.mot_de_passe_manquant(self.cx, self.mot_de_passe),
                "analyse_auto": db.lire_parametre(self.cx, planification.PARAM),
                "gravites": moteur.GRAVITES}

    # ------------------------------------------------------------ écriture

    def ecrire_immeuble(self, req):
        im = parc.enregistrer_immeuble(self.cx, req.json())
        localisation = None
        aid = db.id_adresse(im["rue"], im["npa_localite"])
        lat, source = self.cx.execute("SELECT lat, geo_source FROM adresse WHERE id = ?", (aid,)).fetchone()
        if lat is None and source != patrimoine.SOURCE_PLAN:  # un site d'un jeu fictif n'est jamais géocodé
            try:  # nouvelle adresse : localisation immédiate (adresse seule envoyée au géocodeur fédéral)
                r = geo.geocoder(im["rue"], im["npa_localite"])
                if r:
                    geo.enregistrer(self.cx, aid, r[0], r[1], geo.SOURCE, r[2])
                localisation = "localisée" if r else "introuvable"
            except geo.ErreurGeo:
                localisation = "hors ligne"
        return {"immeuble": im, "localisation": localisation}

    # ------------------------------------------------------------ carte

    def lire_carte(self, req):
        """Adresses avec coordonnées, immeubles, problèmes ouverts et état le plus grave (pour la carte et la liste)."""
        alertes = {}
        for a in bons.liste_alertes(self.cx, "ouverte"):
            alertes.setdefault(a["immeuble_id"], []).append(
                {"id": a["id"], "gravite": a["gravite"], "titre": a["titre"], "fluide": a["fluide"],
                 "chf_mois": a.get("chf_mois") or 0, "sinistre": a["sinistre"]})
        a_connecter = {r[0] for r in self.cx.execute(
            "SELECT DISTINCT immeuble_id FROM point_mesure WHERE etat = 'a_connecter'")}
        out = []
        for ad in db.lignes(self.cx, "SELECT * FROM adresse ORDER BY rue"):
            ad["immeubles"] = []
            for im in db.lignes(self.cx, "SELECT id, nom, profil, logements FROM immeuble WHERE adresse_id = ? "
                                         "ORDER BY nom", (ad["id"],)):
                im["alertes"] = sorted(alertes.get(im["id"], []), key=lambda x: ORDRE_ETAT[x["gravite"]])
                im["etat"] = (im["alertes"][0]["gravite"] if im["alertes"]
                              else "Attente" if im["id"] in a_connecter else "OK")
                ad["immeubles"].append(im)
            ad["etat"] = min((im["etat"] for im in ad["immeubles"]), key=ORDRE_ETAT.get, default="OK")
            ad["chf_mois"] = sum(a["chf_mois"] for im in ad["immeubles"] for a in im["alertes"])
            out.append(ad)
        out.sort(key=lambda a: (ORDRE_ETAT[a["etat"]], -a["chf_mois"], a["rue"]))
        fictives = sum(a["geo_source"] == geo.SOURCE_PLAN and a["lat"] is not None for a in out)
        return {"adresses": out, "tuiles": TUILES, "plan_reporte": fictives,
                "non_localisees": sum(a["lat"] is None for a in out)}

    def geocoder(self, req):
        return geo.geocoder_parc(self.cx, reessayer=True)

    def ecrire_coordonnees(self, req, aid):
        d = req.json()
        lat, lon = geo.valider_coordonnees(d.get("lat"), d.get("lon"))
        geo.enregistrer(self.cx, aid, lat, lon, "manuel")
        return {"ok": True, "lat": lat, "lon": lon}

    def effacer_immeuble(self, req, iid):
        parc.supprimer_immeuble(self.cx, iid)
        return {"ok": True}

    def ecrire_compteur(self, req):
        p, avert = parc.enregistrer_point(self.cx, req.json())
        return {"compteur": p, "avertissements": avert}

    def effacer_compteur(self, req, pid):
        parc.supprimer_point(self.cx, pid)
        return {"ok": True}

    def ecrire_prestataire(self, req, pid=None):
        return {"prestataire": parc.enregistrer_prestataire(self.cx, req.json(), int(pid) if pid else None)}

    def effacer_prestataire(self, req, pid):
        return {"resultat": parc.supprimer_prestataire(self.cx, int(pid))}

    def ecrire_regle(self, req, cause):
        parc.enregistrer_regle(self.cx, cause, req.json())
        return self.lire_regles(req)

    def effacer_regle(self, req, cause):
        parc.reinitialiser_regle(self.cx, cause)
        return self.lire_regles(req)

    def ecrire_couts(self, req):
        parc.enregistrer_couts(self.cx, req.json(), service.defauts())
        return self.lire_couts(req)

    def retour_alerte(self, req, aid):
        bons.enregistrer_retour(self.cx, aid, req.json().get("retour"))
        return {"ok": True}

    def bon_alerte(self, req, aid):
        d = req.json()
        bon, cree = bons.creer_bon(self.cx, aid, d.get("prestataire_id"))
        return {"bon": bon, "cree": cree}

    def ecrire_bon(self, req, bid):
        return bons.modifier_bon(self.cx, int(bid), req.json())

    def envoyer_bon(self, req, bid):
        return bons.envoyer_bon(self.cx, int(bid), self.mot_de_passe)

    def eml_bon(self, req, bid):
        b = bons.lire_bon(self.cx, int(bid))
        contenu = bons.fichier_eml(b, bons.lire_messagerie(self.cx))
        return Fichier(contenu, f"{b['numero']}.eml", "message/rfc822")

    def ecrire_reglages(self, req):
        d = req.json()
        if "automatisation" in d:
            a = d["automatisation"] or {}
            if a.get("mode") not in ("manuel", "brouillon", "envoi"):
                raise parc.ErreurSaisie("Mode d'automatisation inconnu.")
            if a.get("gravite_min") not in moteur.GRAVITES:
                raise parc.ErreurSaisie("Gravité minimale inconnue.")
            db.ecrire_parametre(self.cx, "automatisation", {"mode": a["mode"], "gravite_min": a["gravite_min"],
                                                            "inclure_donnees": bool(a.get("inclure_donnees")),
                                                            **planification.valider(a, bons.lire_automatisation(self.cx))})
        if "messagerie" in d:
            m = d["messagerie"] or {}
            propre = {}
            for cle, lib, maxi in (("expediteur_nom", "Nom de l'expéditeur", 120), ("signature", "Signature", 1000),
                                   ("smtp_hote", "Serveur d'envoi", 200), ("smtp_utilisateur", "Utilisateur", 200)):
                propre[cle] = parc._texte(m.get(cle), lib, maxi=maxi) or ""
            for cle, lib in (("expediteur_email", "E-mail de l'expéditeur"), ("copie_a", "Copie à")):
                v = parc._texte(m.get(cle), lib, maxi=160) or ""
                if v and not parc.EMAIL_RE.match(v):
                    raise parc.ErreurSaisie(f"Adresse e-mail invalide : {v}")
                propre[cle] = v
            propre["smtp_port"] = parc._nombre(m.get("smtp_port"), "Port", 1, 65535, entier=True) or 587
            if m.get("smtp_securite") not in ("starttls", "ssl", "aucune"):
                raise parc.ErreurSaisie("Sécurité de connexion : STARTTLS, SSL ou aucune.")
            propre["smtp_securite"] = m["smtp_securite"]
            db.ecrire_parametre(self.cx, "messagerie", propre)
        if d.get("mot_de_passe"):
            self.mot_de_passe = str(d["mot_de_passe"])
        return self.lire_reglages(req)

    def lire_meteo(self, req):
        return meteo.etat(self.cx)

    def ecrire_meteo(self, req):
        meteo.ecrire_config(self.cx, req.json())
        return meteo.etat(self.cx)

    def maj_meteo(self, req):
        return {**meteo.mettre_a_jour(self.cx), "etat": meteo.etat(self.cx)}

    def analyser(self, req):
        res = service.analyser(self.cx, self.mot_de_passe)
        return {"donnees_au": res["donnees_au"], "alertes": len(res["alertes"]), "nouvelles": res["nouvelles"],
                "bons": res["bons"]}

    def exemple(self, req):
        if not service.parc_vide(self.cx):
            raise parc.ErreurSaisie("L'exemple ne peut être chargé que dans une base vide (votre parc n'est pas modifié).")
        info = service.charger_exemple(self.cx, meteo_reelle=True, taille="grand")
        res = service.analyser(self.cx, self.mot_de_passe)
        return {**info, "alertes": len(res["alertes"])}

    def import_parc(self, req):
        appliquer = (req.query.get("appliquer") or ["0"])[0] == "1"
        return parc.importer_parc_excel(self.cx, req.corps(), appliquer)

    def export_parc(self, req):
        return Fichier(parc.exporter_parc_excel(self.cx), "parc_vigie.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def import_patrimoine(self, req):
        """Classeur patrimoine (sites, bâtiments, compteurs, relevés mensuels) : aperçu, ou import si appliquer=1."""
        appliquer = (req.query.get("appliquer") or ["0"])[0] == "1"
        return self._rapport_import(patrimoine.importer(self.cx, req.corps(), appliquer, service.SORTIE if appliquer else None))

    def import_courbes(self, req):
        """Courbes fines (jour, heure, quart d'heure) en CSV, ou calendrier d'un classeur : aperçu, ou import."""
        appliquer = (req.query.get("appliquer") or ["0"])[0] == "1"
        nom = os.path.basename((req.query.get("nom") or ["courbes.csv"])[0])[:80] or "courbes.csv"
        return self._rapport_import(courbes.importer(self.cx, req.corps(), nom, appliquer,
                                                     service.SORTIE if appliquer else None))

    @staticmethod
    def _rapport_import(r):
        r["anomalies_total"] = len(r["anomalies"])
        r["anomalies"] = r["anomalies"][:ANOMALIES_MAX]
        r.pop("fichier_anomalies", None)  # chemin local : inutile à l'écran
        return r

    def lire_rejeu(self, req):
        """Dernier rejeu de la détection (python -m vigie rejouer) : période, nombre d'analyses, épisodes."""
        return {"rejeu": db.lire_parametre(self.cx, "rejeu")}

    def lire_patrimoine(self, req):
        """Dernier import de classeur patrimoine, et trace des anomalies de tous les imports (conservée en base)."""
        total = self.cx.execute("SELECT count(*) FROM anomalie_import").fetchone()[0]
        par_type = dict(self.cx.execute("SELECT type, count(*) FROM anomalie_import GROUP BY type ORDER BY count(*) DESC"))
        return {"resume": db.lire_parametre(self.cx, "patrimoine"), "anomalies_total": total,
                "anomalies_par_type": par_type, "anomalies": patrimoine.anomalies(self.cx, ANOMALIES_MAX)}

    def import_mesures(self, req):
        corps = req.corps()
        if corps[:2] == b"PK":  # classeur Excel .xlsx (archive zip)
            ok, rejets, lot = db.importer_xlsx(self.cx, corps)
        else:
            ok, rejets, lot = db.importer_mesures(self.cx, io.StringIO(corps.decode("utf-8-sig", errors="replace")))
        return {"importees": ok, "rejets": len(rejets), "lot": lot,
                "detail_rejets": [{"ligne": n, "motif": m} for n, m in rejets[:50]]}

    # ------------------------------------------------------------ connexion API des compteurs

    def lire_connecteur(self, req):
        return {**connecteur.etat(self.cx), "base_exemple": meteo.lire_config(self.cx)["source"] == "exemple"}

    def ecrire_connecteur(self, req):
        return connecteur.enregistrer(self.cx, req.json())

    def effacer_cle_connecteur(self, req):
        return connecteur.supprimer_cle(self.cx)

    def _sans_verrou(self, fonction):
        cx = db.connecter(self.chemin)
        try:
            return fonction(cx)
        finally:
            cx.close()

    def tester_connecteur(self, req):
        return self._sans_verrou(connecteur.tester)

    def synchroniser_connecteur(self, req):
        return self._sans_verrou(connecteur.synchroniser)

    def demo_connecteur(self, req):
        if meteo.lire_config(self.cx)["source"] != "exemple":
            raise connecteur.ErreurConnecteur("Le fournisseur de démonstration ne sert que dans la base d'exemple : "
                                              "il ne doit jamais remplacer les vrais relevés de votre parc.")
        return connecteur.activer_demo(self.cx, req.server.server_address[1])

    def demo_fournisseur(self, req, identifiant):
        if req.headers.get("X-API-Key") != connecteur.DEMO_CLE:
            return Reponse(401, {"erreur": "Clé API invalide."})
        try:
            debut = connecteur._date((req.query.get("debut") or [""])[0])
            fin = connecteur._date((req.query.get("fin") or [""])[0])
        except ValueError:
            return Reponse(400, {"erreur": "Paramètres debut et fin attendus (ex. 2026-11-12T06:00:00Z)."})
        if fin - debut > connecteur.timedelta(days=connecteur.JOURS_MAX):
            return Reponse(400, {"erreur": "Période trop longue."})

        def lire(cx):
            if meteo.lire_config(cx)["source"] != "exemple":
                return Reponse(404, {"erreur": "Fournisseur de démonstration réservé à la base d'exemple."})
            r = self.demo.mesures(cx, identifiant, debut, fin)
            return r if r is not None else Reponse(404, {"erreur": "Compteur inconnu."})
        return self._sans_verrou(lire)


ECHELLES = {"jour": ("D", 90), "mois": ("MS", 60), "annee": ("YS", 10)}


def serie_consommation(cx, pid, echelle):
    """Consommation (ou moyenne d'une température) par jour, mois ou année, heure de Zurich, pour l'affichage."""
    import pandas as pd

    if echelle not in ECHELLES:
        raise parc.ErreurSaisie("Échelle : jour, mois ou année.")
    regle, nombre = ECHELLES[echelle]
    pt = db.lignes(cx, "SELECT * FROM point_mesure WHERE id = ?", (pid,))
    if not pt:
        raise parc.ErreurSaisie("Compteur introuvable.")
    pt = pt[0]
    rows = cx.execute("SELECT ts, valeur, qualite FROM mesure WHERE point_id = ? ORDER BY ts", (pid,)).fetchall()
    if not rows:
        return {"point": pt, "echelle": echelle, "valeurs": [], "total": None, "moyenne": None}
    df = pd.DataFrame(rows, columns=["ts", "valeur", "qualite"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Europe/Zurich")
    df = df.set_index("ts")
    if pt["pas_min"] >= moteur.PAS_JOURNALIER:
        # relevé journalier ou mensuel horodaté à la FIN de l'intervalle : rattaché au jour ou au mois écoulé
        df.index = df.index - pd.Timedelta(minutes=pt["pas_min"] / 2)
    v = df["valeur"].where(df["qualite"] != "suspecte")
    if pt["nature"] == "index":
        d = v.diff()
        v = d.where(d >= 0)
    instantane = pt["nature"] == "instantane"
    groupe = v.resample(regle)
    s = (groupe.mean() if instantane else groupe.sum(min_count=1)).tail(nombre)
    couverture = groupe.count()
    estimees = (df["qualite"] == "estimee").resample(regle).sum()  # valeurs estimées par le distributeur : signalées
    fmt = {"jour": "%Y-%m-%d", "mois": "%Y-%m", "annee": "%Y"}[echelle]
    valeurs = [{"periode": k.strftime(fmt), "valeur": None if pd.isna(x) else round(float(x), 3),
                "mesures": int(couverture.get(k, 0)), "estimee": bool(estimees.get(k, 0))} for k, x in s.items()]
    connues = [x["valeur"] for x in valeurs if x["valeur"] is not None]
    return {"point": pt, "echelle": echelle, "valeurs": valeurs, "instantane": instantane,
            "total": None if instantane or not connues else round(sum(connues), 3),
            "moyenne": round(sum(connues) / len(connues), 3) if connues else None}


def serie_journaliere(cx, pid, jours):
    """Consommation (ou moyenne d'une température) par jour, heure de Zurich, pour l'affichage uniquement."""
    import pandas as pd

    pt = db.lignes(cx, "SELECT * FROM point_mesure WHERE id = ?", (pid,))
    if not pt:
        raise parc.ErreurSaisie("Compteur introuvable.")
    pt = pt[0]
    fin = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = ?", (pid,)).fetchone()[0]
    if not fin:
        return {"point": pt, "jours": []}
    rows = cx.execute("SELECT ts, valeur, qualite FROM mesure WHERE point_id = ? AND julianday(?) - julianday(ts) <= ? "
                      "ORDER BY ts", (pid, fin, jours + 1)).fetchall()
    df = pd.DataFrame(rows, columns=["ts", "valeur", "qualite"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Europe/Zurich")
    df = df.set_index("ts")
    v = df["valeur"].where(df["qualite"] != "suspecte")
    if pt["nature"] == "index":
        d = v.diff()
        v = d.where(d >= 0)
    par_jour = v.resample("D").mean() if pt["nature"] == "instantane" else v.resample("D").sum(min_count=1)
    return {"point": pt, "jours": [{"jour": str(k.date()), "valeur": None if pd.isna(x) else round(float(x), 3)}
                                   for k, x in par_jour.tail(jours).items()]}


class Gestionnaire(BaseHTTPRequestHandler):
    app = None  # Application, injectée par creer_serveur()
    server_version = "Vigie"

    def log_message(self, fmt, *args):  # console sobre : seules les erreurs sont affichées
        pass

    def corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > TAILLE_MAX:
            raise parc.ErreurSaisie("Fichier trop volumineux (50 Mo au maximum).")
        return self.rfile.read(n) if n else b""

    def json(self):
        try:
            d = json.loads(self.corps() or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise parc.ErreurSaisie("Requête illisible.") from None
        if not isinstance(d, dict):
            raise parc.ErreurSaisie("Requête illisible.")
        return d

    def _envoyer(self, code, contenu, type_mime, entetes=None):
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(contenu)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         f"default-src 'self'; img-src 'self' data: {TUILES}; frame-ancestors 'none'")
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(contenu)

    def _json(self, code, donnees, entetes=None):
        self._envoyer(code, json.dumps(donnees, ensure_ascii=False, default=str).encode("utf-8"),
                      "application/json; charset=utf-8", entetes)

    def _hote_autorise(self):
        hote = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return hote in ("127.0.0.1", "localhost")

    def _traiter(self, methode):
        if not self._hote_autorise():
            return self._json(403, {"erreur": "Accès refusé."})
        url = urlparse(self.path)
        self.query = parse_qs(url.query)
        chemin = unquote(url.path)
        if methode == "GET" and (chemin == "/" or FICHIER_WEB_RE.match(chemin)):
            nom = "index.html" if chemin == "/" else FICHIER_WEB_RE.match(chemin).group(1)
            if os.path.isfile(os.path.join(WEB, nom)):
                return self._statique(nom)
        if methode != "GET" and self.headers.get("X-Vigie") != "1":
            return self._json(403, {"erreur": "Requête refusée."})
        if acces.reserve(methode, chemin) and not self.app.acces.autorise(self.headers):
            return self._json(401, {"erreur": acces.MESSAGE})
        for m, motif, fonction in self.app.routes:
            res = re.fullmatch(motif, chemin) if m == methode else None
            if not res:
                continue
            try:
                with contextlib.nullcontext() if fonction.__name__ in SANS_VERROU else self.app.verrou:
                    resultat = fonction(self, *res.groups())
            except ERREURS_METIER as e:
                return self._json(400, {"erreur": str(e)})
            except Exception:  # noqa: BLE001 — journalisé, message générique à l'écran
                traceback.print_exc()
                return self._json(500, {"erreur": "Erreur interne : voir la fenêtre de commande de Vigie."})
            if isinstance(resultat, Reponse):
                return self._json(resultat.code, resultat.donnees, resultat.entetes)
            if isinstance(resultat, Fichier):
                return self._envoyer(200, resultat.contenu, resultat.type_mime,
                                     {"Content-Disposition": f'attachment; filename="{resultat.nom}"'})
            return self._json(200, resultat)
        return self._json(404, {"erreur": "Page introuvable."})

    def _statique(self, nom):
        with open(os.path.join(WEB, nom), "rb") as f:
            contenu = f.read()
        if nom.endswith(".js"):
            type_mime = "text/javascript; charset=utf-8"
        else:
            type_mime = (mimetypes.guess_type(nom)[0] or "application/octet-stream") + "; charset=utf-8"
        self._envoyer(200, contenu, type_mime)

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def do_PUT(self):
        self._traiter("PUT")

    def do_DELETE(self):
        self._traiter("DELETE")


def meteo_automatique(chemin_base, arret, intervalle_s=meteo.INTERVALLE_AUTO_H * 3600, premier_delai_s=5):
    """Fil de fond : met à jour la température MétéoSuisse au démarrage puis toutes les 3 h, tant que Vigie tourne.

    Connexion SQLite propre au fil (pas de verrou de l'interface pendant le téléchargement).
    """
    if arret.wait(premier_delai_s):
        return
    while True:
        cx = db.connecter(chemin_base)
        try:
            cfg = meteo.lire_config(cx)
            if cfg["auto"] and not meteo.exemple_fictif(cfg):
                r = meteo.mettre_a_jour(cx)
                print(f"Météo {cfg['station']} à jour : dernière mesure {r['derniere_mesure']} (UTC).")
        except meteo.ErreurMeteo as e:
            print(f"Météo : mise à jour impossible — {e}")
        except Exception:  # noqa: BLE001 — le fil de fond ne doit jamais arrêter Vigie
            traceback.print_exc()
        try:  # adresses pas encore localisées (nouvelles adresses importées par Excel, par exemple)
            g = geo.geocoder_parc(cx)
            if g["traitees"]:
                print(f"Carte : {len(g['localisees'])} adresse(s) localisée(s), {len(g['introuvables'])} introuvable(s).")
        except geo.ErreurGeo as e:
            print(f"Carte : localisation impossible — {e}")
        except Exception:  # noqa: BLE001 — le fil de fond ne doit jamais arrêter Vigie
            traceback.print_exc()
        finally:
            cx.close()
        if arret.wait(intervalle_s):
            return


def connecteur_automatique(chemin_base, arret, verification_s=300, premier_delai_s=20, releve=None):
    """Fil de fond : relève les compteurs reliés à l'API selon la fréquence choisie (si l'option est cochée).

    `releve` (threading.Event) est levé quand de nouvelles valeurs sont arrivées : l'analyse automatique s'en sert.
    """
    if arret.wait(premier_delai_s):
        return
    while True:
        cx = db.connecter(chemin_base)
        try:
            if connecteur.a_synchroniser(connecteur.lire_config(cx)):
                r = connecteur.synchroniser(cx)
                print(f"Connexion API : {r['message']}")
                if releve is not None and r["importees"]:
                    releve.set()
        except (connecteur.ErreurConnecteur, secret.ErreurSecret) as e:
            db.ecrire_parametre(cx, connecteur.PARAM, {**connecteur.lire_config(cx), "statut": "erreur", "message": str(e),
                                                       "derniere_synchro": connecteur._heure().strftime(connecteur.FMT)})
            print(f"Connexion API : relevé impossible — {e}")
        except Exception:  # noqa: BLE001 — le fil de fond ne doit jamais arrêter Vigie
            traceback.print_exc()
        finally:
            cx.close()
        if arret.wait(verification_s):
            return


class ServeurVigie(ThreadingHTTPServer):
    # Sous Windows, la réutilisation d'adresse laisse deux Vigie écouter le même port sans erreur : interdit ici
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def creer_serveur(chemin_base, port=8765):
    app = Application(chemin_base)
    gestionnaire = type("GestionnaireVigie", (Gestionnaire,), {"app": app})
    return ServeurVigie(("127.0.0.1", port), gestionnaire), app


def lancer(chemin_base, port=8765, ouvrir=True):
    url = f"http://127.0.0.1:{port}/"
    try:
        serveur, app = creer_serveur(chemin_base, port)
    except OSError:
        print(f"Vigie semble déjà ouvert (port {port} occupé) : ouvrez {url} dans votre navigateur.")
        if ouvrir:
            webbrowser.open(url)
        return
    print(f"Vigie — interface de gestion : {url}")
    print(f"Base : {chemin_base}")
    print("Fermez cette fenêtre (ou Ctrl+C) pour arrêter.")
    if ouvrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    arret, releve = threading.Event(), threading.Event()
    threading.Thread(target=meteo_automatique, args=(chemin_base, arret), daemon=True, name="meteo").start()
    threading.Thread(target=connecteur_automatique, args=(chemin_base, arret), kwargs={"releve": releve}, daemon=True,
                     name="connecteur").start()
    threading.Thread(target=planification.analyse_automatique, args=(app, arret, releve), daemon=True,
                     name="analyse").start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de Vigie.")
    finally:
        arret.set()
        serveur.server_close()
