"""Outils partagés par les tests : base d'exemple créée une seule fois puis copiée pour chaque test."""
import atexit
import os
import shutil
import sys
import tempfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from vigie import db, service  # noqa: E402

DOSSIER = tempfile.mkdtemp(prefix="vigie-tests-")
atexit.register(shutil.rmtree, DOSSIER, ignore_errors=True)
service.SORTIE = os.path.join(DOSSIER, "sorties")  # les tests n'écrasent jamais les sorties du projet
_MODELE = []
ATTENDUES = {"T8-eau_nuit", "T8-pac_cop", "R41-chaleur_vide", "OA-elec_nuit", "OB-chaleur_signature",
             "T8-solaire_panne", "R41-donnees-R41_ECS"}


def _modele():
    """Base d'exemple (parc fictif + 120 jours de mesures), générée une fois pour toute la série."""
    if not _MODELE:
        chemin = os.path.join(DOSSIER, "modele.db")
        cx = db.connecter(chemin)
        service.charger_exemple(cx)
        cx.close()
        _MODELE.append(chemin)
    return _MODELE[0]


def _chemin_unique(nom):
    """Un fichier par appel : sous Windows, une base encore ouverte ne peut être ni écrasée ni supprimée."""
    _COMPTEUR.append(1)
    return os.path.join(DOSSIER, f"{nom}-{len(_COMPTEUR)}.db")


_COMPTEUR = []


def base_exemple(nom):
    """Copie fraîche de la base d'exemple, propre à un test."""
    chemin = _chemin_unique(nom)
    shutil.copy(_modele(), chemin)
    return db.connecter(chemin)


def base_vide(nom):
    return db.connecter(_chemin_unique(nom))
