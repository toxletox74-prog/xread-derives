"""Accès à l'interface : lecture libre, écriture réservée.

Sur le poste (accès direct à 127.0.0.1, sans mot de passe défini) rien ne change : tout est permis.
Dès qu'un mot de passe est défini (variable d'environnement VIGIE_MOT_DE_PASSE), ou que la requête arrive par un
serveur frontal (nginx : en-têtes X-Forwarded-*), l'interface est en LECTURE SEULE sans identification : toute
modification, et la lecture des réglages de messagerie et du connecteur, exigent une session ouverte avec le mot de
passe. Sans mot de passe défini, un accès par serveur frontal reste en lecture seule (aucune connexion possible).

Le mot de passe n'est jamais écrit sur disque ; les sessions vivent en mémoire (perdues au redémarrage).
"""
import hmac
import re
import secrets
import time
from http.cookies import SimpleCookie

ENV = "VIGIE_MOT_DE_PASSE"
COOKIE = "vigie_session"
DUREE_S = 12 * 3600
DELAI_ECHEC_S = 1.0  # ralentit les essais de mots de passe
MESSAGE = "Lecture seule : connectez-vous pour modifier."
EN_TETES_FRONTAL = ("X-Forwarded-For", "X-Real-IP", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded")
SESSION = "/api/session"
# Lectures réservées : réglages de messagerie (serveur, utilisateur SMTP) et connecteur API (adresse du fournisseur)
LECTURES_RESERVEES = re.compile(r"/api/(reglages|connecteur)")


def reserve(methode, chemin):
    """La requête exige-t-elle une session ? Toute écriture (sauf l'ouverture de session) et les lectures réservées."""
    if methode == "GET":
        return bool(LECTURES_RESERVEES.fullmatch(chemin))
    return not (methode == "POST" and chemin == SESSION)


class Acces:
    def __init__(self, mot_de_passe=None):
        self.mot_de_passe = (mot_de_passe or "").strip() or None
        self.sessions = {}  # jeton -> échéance (horloge monotone)

    def _session(self, entetes):
        jeton = SimpleCookie(entetes.get("Cookie") or "").get(COOKIE)
        return bool(jeton) and self.sessions.get(jeton.value, 0) > time.monotonic()

    def autorise(self, entetes):
        if self.mot_de_passe:
            return self._session(entetes)
        return not any(entetes.get(e) for e in EN_TETES_FRONTAL)  # poste local : accès direct seulement

    def etat(self, entetes):
        """Pour l'interface : peut-on modifier, peut-on se connecter, une session est-elle ouverte ?"""
        return {"ecriture": self.autorise(entetes), "connexion": bool(self.mot_de_passe),
                "session": bool(self.mot_de_passe) and self._session(entetes)}

    def ouvrir(self, mot_de_passe, entetes):
        """En-tête Set-Cookie d'une nouvelle session, ou None si le mot de passe est faux (après un délai)."""
        if not self.mot_de_passe or not hmac.compare_digest(str(mot_de_passe or "").encode(), self.mot_de_passe.encode()):
            time.sleep(DELAI_ECHEC_S)
            return None
        maintenant = time.monotonic()
        self.sessions = {j: e for j, e in self.sessions.items() if e > maintenant}  # sessions échues oubliées
        jeton = secrets.token_urlsafe(32)
        self.sessions[jeton] = maintenant + DUREE_S
        https = "; Secure" if entetes.get("X-Forwarded-Proto") == "https" else ""
        return f"{COOKIE}={jeton}; Path=/; Max-Age={DUREE_S}; HttpOnly; SameSite=Strict{https}"

    def fermer(self, entetes):
        jeton = SimpleCookie(entetes.get("Cookie") or "").get(COOKIE)
        if jeton:
            self.sessions.pop(jeton.value, None)
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
