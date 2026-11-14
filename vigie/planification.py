"""Analyse automatique : toutes les N heures, et après un relevé API automatique qui a rapporté de nouvelles mesures.

Désactivée par défaut (réglage « analyse_auto » de l'automatisation, Réglages › Automatisation). L'état de la dernière
analyse automatique (date, résultat ou erreur) est gardé en base pour être affiché dans les Réglages.
"""
import traceback
from datetime import datetime, timedelta, timezone

from . import bons, db, parc, service

PARAM = "analyse_auto"  # état de la dernière analyse automatique (table parametre)
FMT = "%Y-%m-%dT%H:%M:%SZ"
INTERVALLE_MIN_H, INTERVALLE_MAX_H = 1, 168


def valider(a, actuel):
    """Réglages d'analyse automatique reçus par PUT /api/reglages ; un champ absent garde sa valeur actuelle."""
    intervalle = parc._nombre(a.get("analyse_intervalle_h", actuel["analyse_intervalle_h"]),
                              "Fréquence de l'analyse automatique (heures)", INTERVALLE_MIN_H, INTERVALLE_MAX_H, entier=True)
    return {"analyse_auto": bool(a.get("analyse_auto", actuel["analyse_auto"])),
            "analyse_intervalle_h": intervalle or actuel["analyse_intervalle_h"]}


def declencheur(auto, etat, releve=False, maintenant=None):
    """Pourquoi une analyse automatique est due maintenant (« relevé API », « intervalle »), ou None."""
    if not auto["analyse_auto"]:
        return None
    if releve:
        return "relevé API"
    if not etat:
        return "intervalle"
    derniere = datetime.strptime(etat["le"], FMT).replace(tzinfo=timezone.utc)
    ecoule = (maintenant or datetime.now(timezone.utc)) - derniere
    return "intervalle" if ecoule >= timedelta(hours=auto["analyse_intervalle_h"]) else None


def _resume(r):
    """(statut, message) d'une analyse terminée : « attention » si rien à analyser ou si un envoi a échoué."""
    if r["donnees_au"] is None:
        return "attention", "Aucune mesure à analyser."
    b = r["bons"] or {"crees": [], "envoyes": [], "erreurs": []}
    message = f"{len(r['alertes'])} alerte(s), {len(r['nouvelles'])} nouvelle(s)"
    if b["crees"]:
        message += f", {len(b['crees'])} bon(s) préparé(s), {len(b['envoyes'])} envoyé(s)"
    if b["erreurs"]:
        return "attention", message + " ; envois impossibles : " + " · ".join(b["erreurs"])
    return "ok", message + "."


def verifier(app, releve=False, maintenant=None, envoi=None):
    """Lance l'analyse si elle est due et enregistre son état ; retourne cet état, ou None si rien n'était dû."""
    # Sous le verrou de l'application et sur sa connexion, exactement comme le bouton « Lancer l'analyse » : l'analyse
    # écrit en base (alertes, bons), le verrou la sérialise avec l'interface sans seconde connexion en écriture.
    with app.verrou:
        raison = declencheur(bons.lire_automatisation(app.cx), db.lire_parametre(app.cx, PARAM), releve, maintenant)
        if not raison:
            return None
        etat = {"le": (maintenant or datetime.now(timezone.utc)).strftime(FMT), "declencheur": raison}
        try:
            r = service.analyser(app.cx, app.mot_de_passe, envoi=envoi)
            etat["statut"], etat["message"] = _resume(r)
            etat["donnees_au"] = r["donnees_au"]
        except Exception as e:  # noqa: BLE001 — l'erreur doit se voir dans les Réglages, pas seulement en console
            traceback.print_exc()
            app.cx.rollback()
            etat["statut"], etat["message"] = "erreur", f"Analyse interrompue ({type(e).__name__}) : {e}"[:300]
        db.ecrire_parametre(app.cx, PARAM, etat)
        return etat


def analyse_automatique(app, arret, releve=None, verification_s=60, premier_delai_s=30):
    """Fil de fond : vérifie chaque minute si une analyse est due (intervalle écoulé ou nouveau relevé API).

    `releve` (threading.Event) est levé par le fil du relevé API quand de nouvelles valeurs sont arrivées.
    """
    if arret.wait(premier_delai_s):
        return
    while True:
        try:
            nouveau = releve is not None and releve.is_set()
            if nouveau:
                releve.clear()
            etat = verifier(app, nouveau)
            if etat:
                print(f"Analyse automatique ({etat['declencheur']}) : {etat['message']}")
        except Exception:  # noqa: BLE001 — le fil de fond ne doit jamais arrêter Vigie
            traceback.print_exc()
        if arret.wait(verification_s):
            return
