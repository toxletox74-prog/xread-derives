"""Espaces des services tiers : une base isolée par service, ouverte par une clé API.

  python -m vigie espace creer <id> [--nom="Service X"]   crée l'espace s'il n'existe pas et affiche une NOUVELLE clé
  python -m vigie espace lister                           espaces, clés actives et révoquées (jamais les clés)
  python -m vigie espace revoquer <id>                    révoque toutes les clés de l'espace (sa base est gardée)

Chaque espace a son dossier espaces/<id>/ : sa base vigie.db (parc, relevés, alertes, bons) et ses sorties/. Une
requête qui porte « Authorization: Bearer <clé> » travaille sur la base de l'espace de la clé, jamais sur une autre :
le service y importe ses relevés, lance l'analyse et lit ses dérives, par l'API JSON ou par le serveur MCP (/mcp).

La clé n'est affichée qu'une fois ; le registre (espaces/registre.db) n'en garde que l'empreinte SHA-256.
Routes interdites aux espaces : celles qui font sortir quelque chose du serveur (courriels, connecteur fournisseur)
ou qui ne concernent que l'interface de gestion (session, base d'exemple).

Clé MCP de la base principale : générée depuis l'interface par une personne connectée (bouton « Claude (MCP) »),
elle n'ouvre que /mcp (outils en lecture seule) sur la base principale, jamais l'API. Une seule active à la fois.
"""
import hashlib
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

PREFIXE = "vgk_"
PRINCIPAL = "_principal"  # espace réservé (hors ID_RE : impossible à créer en ligne de commande) = base principale
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
INTERDITES = re.compile(r"/api/(session|reglages|exemple|mcp(/cle)?|connecteur(/.*)?|bons/\d+/envoyer)"
                        r"|/demo-fournisseur/.*")
ENTETE_CONSULTATION = "X-Vigie-Espace"  # interface : espace consulté en lecture seule, sans clé
MESSAGE_LECTURE = "Espace consulté en lecture seule depuis l'interface : modifications impossibles."
MESSAGE_CLE = "Clé API absente, invalide ou révoquée."
MESSAGE_INTERDITE = "Route réservée à l'interface de gestion : indisponible avec une clé API."
SCHEMA = """CREATE TABLE IF NOT EXISTS cle (
    empreinte TEXT PRIMARY KEY, espace TEXT NOT NULL, nom TEXT, creee TEXT NOT NULL, revoquee TEXT)"""


class ErreurEspace(ValueError):
    pass


def jeton(entetes):
    """Clé de l'en-tête « Authorization: Bearer … », ou None si la requête n'en porte pas."""
    valeur = (entetes.get("Authorization") or "").strip()
    if not valeur.lower().startswith("bearer "):
        return None
    return valeur[7:].strip()


def interdite(chemin):
    return bool(INTERDITES.fullmatch(chemin))


def consultables():
    """Espaces que l'interface peut afficher en lecture seule, sans clé : ceux que l'exploitant nomme dans
    VIGIE_ESPACES_CONSULTABLES (« id1,id2 »), par exemple un jeu de test. Aucun par défaut : l'espace d'un service
    tiers reste réservé à sa clé (règle 9)."""
    ids = (e.strip() for e in os.environ.get("VIGIE_ESPACES_CONSULTABLES", "").split(","))
    return [e for e in ids if ID_RE.fullmatch(e)]


def _empreinte(cle):
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def _maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Espaces:
    def __init__(self, dossier):
        self.dossier = dossier
        self.verrou = threading.Lock()
        self.apps = {}  # id d'espace -> Application (une connexion SQLite par espace, ouverte à la première requête)

    def _registre(self):
        os.makedirs(self.dossier, exist_ok=True)
        cx = sqlite3.connect(os.path.join(self.dossier, "registre.db"))
        cx.execute(SCHEMA)
        return cx

    def base(self, espace):
        return os.path.join(self.dossier, espace, "vigie.db")

    def creer(self, espace, nom=None):
        """Nouvelle clé pour l'espace (créé au besoin). La clé en clair n'est rendue qu'ici."""
        if not ID_RE.fullmatch(espace or ""):
            raise ErreurEspace("Identifiant d'espace : minuscules, chiffres et tirets, 40 caractères au plus.")
        from . import db
        os.makedirs(os.path.dirname(self.base(espace)), exist_ok=True)
        db.connecter(self.base(espace)).close()  # base vide au schéma courant
        return self._nouvelle_cle(espace, nom)

    def _nouvelle_cle(self, espace, nom, remplacer=False):
        cle = PREFIXE + secrets.token_urlsafe(32)
        cx = self._registre()
        try:
            if remplacer:
                cx.execute("UPDATE cle SET revoquee = ? WHERE espace = ? AND revoquee IS NULL", (_maintenant(), espace))
            cx.execute("INSERT INTO cle (empreinte, espace, nom, creee) VALUES (?, ?, ?, ?)",
                       (_empreinte(cle), espace, nom, _maintenant()))
            cx.commit()
        finally:
            cx.close()
        return cle

    def cle_principale(self):
        """Nouvelle clé MCP de la base principale ; la précédente cesse aussitôt de fonctionner."""
        return self._nouvelle_cle(PRINCIPAL, "Claude (MCP), base principale", remplacer=True)

    def etat_principal(self):
        """Date de création de la clé MCP active de la base principale, ou None."""
        if not os.path.exists(os.path.join(self.dossier, "registre.db")):
            return None
        cx = self._registre()
        try:
            ligne = cx.execute("SELECT max(creee) FROM cle WHERE espace = ? AND revoquee IS NULL", (PRINCIPAL,)).fetchone()
        finally:
            cx.close()
        return ligne[0]

    def lister(self):
        cx = self._registre()
        try:
            lignes = cx.execute("SELECT espace, nom, creee, revoquee FROM cle ORDER BY espace, creee").fetchall()
        finally:
            cx.close()
        return [{"espace": e, "nom": n, "creee": c, "revoquee": r} for e, n, c, r in lignes]

    def consultables(self):
        """Espaces consultables qui existent, avec leur nom (celui de leur dernière clé)."""
        noms = {}
        if os.path.exists(os.path.join(self.dossier, "registre.db")):
            noms = {c["espace"]: c["nom"] for c in self.lister()}  # trié par date de création : la dernière l'emporte
        return [{"id": e, "nom": noms.get(e) or e} for e in consultables() if os.path.exists(self.base(e))]

    def revoquer(self, espace):
        """Révoque toutes les clés actives de l'espace ; rend leur nombre. La base de l'espace n'est pas touchée."""
        cx = self._registre()
        try:
            n = cx.execute("UPDATE cle SET revoquee = ? WHERE espace = ? AND revoquee IS NULL",
                           (_maintenant(), espace)).rowcount
            cx.commit()
        finally:
            cx.close()
        return n

    def espace_de(self, cle):
        """Espace d'une clé active, ou None."""
        if not cle or not cle.startswith(PREFIXE) or not os.path.exists(os.path.join(self.dossier, "registre.db")):
            return None
        cx = self._registre()
        try:
            ligne = cx.execute("SELECT espace FROM cle WHERE empreinte = ? AND revoquee IS NULL",
                               (_empreinte(cle),)).fetchone()
        finally:
            cx.close()
        return ligne[0] if ligne else None

    def application(self, espace):
        """Application du serveur sur la base de l'espace (mêmes routes, même moteur, sorties à part)."""
        from . import serveur
        with self.verrou:
            if espace not in self.apps:
                self.apps[espace] = serveur.Application(self.base(espace),
                                                        sortie=os.path.join(self.dossier, espace, "sorties"))
            return self.apps[espace]
