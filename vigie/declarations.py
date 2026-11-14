"""Déclarations du gestionnaire sur un immeuble : sourdine justifiée, travaux ou vacance datés, changement.

Première source de fausses alertes : ce que le gestionnaire sait déjà (travaux, logements vides, compteur remplacé,
consigne ou courbe de chauffe modifiée). Chaque déclaration est datée, motivée (motif obligatoire) et tracée dans
l'historique de l'immeuble. Le moteur ne compare les dates qu'à la date analysée (fin des relevés, ou date rejouée) :
une déclaration ne vaut qu'à partir de sa date de début, y compris dans un rejeu.

- `sourdine`   une règle (cause) d'un immeuble, jusqu'à une date de fin obligatoire : la dérive reste calculée et sa
               référence gelée, mais l'alerte porte « en sourdine jusqu'au … : motif », sort des alertes à traiter et
               ne prépare aucun bon. À l'échéance, elle redevient une alerte ordinaire (jamais de silence invisible).
- `travaux`, `vacance`  du début à la fin : l'immeuble est jugé comme le profil « Travaux » (règles d'énergie suspendues,
               fuites et défauts de données maintenus). Les jours de la période sont retirés des séries d'énergie : ils
               ne servent ni de jours jugés ni de référence ensuite (règle 4 : rien n'est comblé).
- `changement` à une date, pour un compteur ou pour tout l'immeuble (compteur remplacé, consigne ou courbe de chauffe
               modifiée) : les séries concernées ne sont vues qu'APRÈS cette date. La référence ne remonte donc jamais
               avant le changement, comme la garde « dernier changement d'installation » de historique.py ; tant que
               la référence postérieure est insuffisante, les règles ne concluent pas (règles 4 et 7). Un recul d'index
               le jour d'un changement déclaré sur le compteur n'est plus un défaut de données.
"""
import json
import sqlite3
from datetime import date

import pandas as pd

from . import db

TYPES = {"sourdine": "Sourdine d'une règle", "travaux": "Travaux", "vacance": "Vacance",
         "changement": "Changement (compteur, consigne, courbe de chauffe)"}
PERIODES = ("travaux", "vacance")
PROFIL_SUSPENDU = "Travaux"        # profil appliqué pendant une période déclarée (voir R[c]["profils"])
FLUIDES_EAU = ("eau", "eau_chaude")  # jamais retirés : les fuites restent surveillées pendant et après la période
NUIT_REF_J = 50                    # électricité de nuit : la référence J-50 à J-20 doit être postérieure au changement
UN_JOUR = pd.Timedelta(days=1)
ETATS = {"a_venir": "À venir", "en_cours": "En cours", "echue": "Échue", "en_vigueur": "En vigueur"}


class ErreurDeclaration(ValueError):
    pass


# ---------------------------------------------------------------- moteur


class Declarations:
    """Déclarations en vigueur à la date analysée `jour` (celles dont le début est postérieur sont ignorées)."""

    def __init__(self, lignes, jour):
        self.jour = jour
        self.lignes = [d for d in lignes if pd.Timestamp(d["debut"]) <= jour]
        en_cours = [d for d in self.lignes if d["fin"] and jour <= pd.Timestamp(d["fin"])]
        self.suspendus = {d["immeuble_id"] for d in en_cours if d["type"] in PERIODES}
        self.sourdines = {(d["immeuble_id"], d["cause"]): d for d in en_cours if d["type"] == "sourdine"}

    def profil(self, im):
        """Profil sous lequel l'immeuble est jugé : « Travaux » pendant une période de travaux ou de vacance."""
        return PROFIL_SUSPENDU if im["id"] in self.suspendus else im["profil"]

    def sourdine(self, alerte):
        """Marque l'alerte d'une règle en sourdine (elle reste calculée : sa référence reste gelée)."""
        d = self.sourdines.get((alerte["immeuble_id"], alerte["cause"]))
        if d:
            alerte["sourdine"] = {"jusquau": d["fin"], "motif": d["motif"], "declaration_id": d["id"]}
        return alerte


def _lire(cx):
    try:
        return db.lignes(cx, "SELECT * FROM declaration ORDER BY id")
    except sqlite3.OperationalError:  # base ouverte sans le schéma courant
        return []


def _reculs_hors_changement(raw, pid, fin, jours):
    """Reculs d'index du compteur, sauf ceux dont l'intervalle contient un jour de changement déclaré."""
    g = raw[(raw["point_id"] == pid) & (raw["ts"] <= fin)].sort_values("ts")
    recul = g["valeur"].where(g["qualite"] == "valide").diff() < 0
    avant = g["ts"].shift()
    for j in jours:
        recul &= ~((avant < j + UN_JOUR) & (g["ts"] > j))
    return int(recul.sum())


def preparer(cx, ref, fin, brut, qualite, series, journ, mensuelles):
    """Applique les périodes et les changements déclarés aux séries de l'analyse (modifiées en place) et retourne
    les déclarations en vigueur. `series` : horaires ; `journ` : journalières ; `mensuelles` : par mois civil."""
    decl = Declarations(_lire(cx), fin.normalize())
    for im in ref["immeubles"]:
        siennes = [d for d in decl.lignes if d["immeuble_id"] == im["id"]]
        for d in siennes:
            debut = pd.Timestamp(d["debut"])
            if d["type"] in PERIODES:
                dernier = pd.Timestamp(d["fin"])
                for p in im["points"]:
                    if p["fluide"] in FLUIDES_EAU:
                        continue
                    pid = p["id"]
                    if pid in series:  # jour d'une heure = celui de son horodatage, comme dans le moteur
                        j = series[pid].index.normalize()
                        series[pid] = series[pid].mask((j >= debut) & (j <= dernier))
                    if pid in journ:
                        journ[pid] = journ[pid][(journ[pid].index < debut) | (journ[pid].index > dernier)]
                    if pid in mensuelles:  # un mois entamé par la période n'est ni jugé ni référence
                        m = mensuelles[pid].index
                        mensuelles[pid] = mensuelles[pid][(m.end_time < debut) | (m.start_time >= dernier + UN_JOUR)]
            elif d["type"] == "changement":
                for p in im["points"]:
                    pid = p["id"]
                    if d["point_id"] not in (None, pid):
                        continue
                    if pid in series:
                        series[pid] = series[pid][series[pid].index.normalize() > debut]  # jour du changement écarté
                        if p["fluide"] == "electricite" and (decl.jour - debut).days < NUIT_REF_J:
                            series.pop(pid)  # nuits de référence encore antérieures au changement : pas de jugement
                    if pid in journ:
                        journ[pid] = journ[pid][journ[pid].index > debut]
                    if pid in mensuelles:  # premier mois complet après le changement, comme historique.changements
                        mensuelles[pid] = mensuelles[pid][mensuelles[pid].index > pd.Period(debut, "M")]
                    for serie in (series, journ, mensuelles):
                        if pid in serie and serie[pid].empty:
                            serie.pop(pid)  # plus rien après le changement : aucune règle ne tourne sur ce compteur
        for p in im["points"]:  # compteur remplacé : l'index repart d'une autre valeur, ce n'est pas un défaut
            jours = [pd.Timestamp(d["debut"]) for d in siennes if d["type"] == "changement" and d["point_id"] == p["id"]]
            if jours and (qualite.get(p["id"]) or {}).get("index_recule"):
                qualite[p["id"]]["index_recule"] = _reculs_hors_changement(brut[1], p["id"], fin, jours)
    return decl


# ---------------------------------------------------------------- saisie (API et interface)


def _jour_reference(cx):
    """« Aujourd'hui » des déclarations : la date des relevés de la dernière analyse (celle du moteur), sinon ce jour."""
    derniere = db.lire_parametre(cx, "derniere_analyse") or {}
    return pd.Timestamp(str(derniere["donnees_au"])[:10]) if derniere.get("donnees_au") else pd.Timestamp(date.today())


def _date(v, champ, obligatoire=True):
    t = str(v or "").strip()
    if not t:
        if obligatoire:
            raise ErreurDeclaration(f"« {champ} » est obligatoire.")
        return None
    try:
        return date.fromisoformat(t).isoformat()
    except ValueError:
        raise ErreurDeclaration(f"« {champ} » : date attendue au format AAAA-MM-JJ.") from None


def _texte(v, champ, maxi, obligatoire=False):
    t = str(v or "").strip()
    if obligatoire and not t:
        raise ErreurDeclaration(f"« {champ} » est obligatoire.")
    if len(t) > maxi:
        raise ErreurDeclaration(f"« {champ} » : {maxi} caractères au maximum.")
    return t or None


def _fr(iso):
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def libelle(d):
    from .regles import REGLES
    if d["type"] == "sourdine":
        regle = REGLES.get(d["cause"], {}).get("libelle", d["cause"])
        return f"Sourdine de la règle « {regle} » jusqu'au {_fr(d['fin'])} (depuis le {_fr(d['debut'])})"
    if d["type"] in PERIODES:
        return f"{TYPES[d['type']]} du {_fr(d['debut'])} au {_fr(d['fin'])}"
    return f"Changement le {_fr(d['debut'])}" + (f" sur le compteur {d['point_id']}" if d["point_id"] else
                                                 " (tous les compteurs de l'immeuble)")


def _etat(d, jour):
    if pd.Timestamp(d["debut"]) > jour:
        return "a_venir"
    if d["type"] == "changement":
        return "en_vigueur"
    return "en_cours" if jour <= pd.Timestamp(d["fin"]) else "echue"


def liste(cx, immeuble_id):
    jour = _jour_reference(cx)
    out = db.lignes(cx, "SELECT * FROM declaration WHERE immeuble_id = ? ORDER BY debut DESC, id DESC", (immeuble_id,))
    for d in out:
        d["libelle"], d["etat"] = libelle(d), _etat(d, jour)
    return out


def valider(cx, immeuble_id, d):
    from .regles import REGLES
    if not cx.execute("SELECT 1 FROM immeuble WHERE id = ?", (immeuble_id,)).fetchone():
        raise ErreurDeclaration("Immeuble introuvable.")
    type_ = d.get("type")
    if type_ not in TYPES:
        raise ErreurDeclaration("Type de déclaration : sourdine, travaux, vacance ou changement.")
    out = {"immeuble_id": immeuble_id, "type": type_, "cause": None, "point_id": None, "fin": None,
           "motif": _texte(d.get("motif"), "Motif", 500, obligatoire=True), "auteur": _texte(d.get("auteur"), "Auteur", 120)}
    if type_ == "sourdine":
        if d.get("cause") not in REGLES:
            raise ErreurDeclaration("Sourdine : choisissez la règle concernée.")
        out["cause"] = d["cause"]
        # sans date de début : dès maintenant, c'est-à-dire à la date des derniers relevés analysés
        out["debut"] = _date(d.get("debut"), "Début", obligatoire=False) or str(_jour_reference(cx).date())
    else:
        out["debut"] = _date(d.get("debut"), "Date du changement" if type_ == "changement" else "Début")
    if type_ == "changement":
        if d.get("point_id"):
            if not cx.execute("SELECT 1 FROM point_mesure WHERE id = ? AND immeuble_id = ?",
                              (d["point_id"], immeuble_id)).fetchone():
                raise ErreurDeclaration("Ce compteur n'appartient pas à l'immeuble.")
            out["point_id"] = d["point_id"]
    else:
        out["fin"] = _date(d.get("fin"), "Fin")  # obligatoire : ni sourdine ni période sans échéance
        if out["fin"] < out["debut"]:
            raise ErreurDeclaration("La fin précède le début.")
    return out


def _actualiser_alertes(cx, immeuble_id):
    """Sourdine déclarée ou supprimée : les alertes ouvertes de l'immeuble le montrent sans attendre l'analyse."""
    decl = Declarations(_lire(cx), _jour_reference(cx))
    for aid, donnees in cx.execute("SELECT id, donnees FROM alerte WHERE immeuble_id = ? AND statut = 'ouverte'",
                                   (immeuble_id,)).fetchall():
        alerte = json.loads(donnees)
        avant = alerte.pop("sourdine", None)
        if decl.sourdine(alerte).get("sourdine") != avant:
            cx.execute("UPDATE alerte SET donnees = ? WHERE id = ?", (json.dumps(alerte, ensure_ascii=False), aid))


def creer(cx, immeuble_id, d):
    """Enregistre une déclaration (tracée dans l'historique de l'immeuble) et la retourne."""
    from . import bons
    v = valider(cx, immeuble_id, d)
    v["cree_le"] = bons.maintenant()
    v["id"] = cx.execute(f"INSERT INTO declaration ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})",
                         tuple(v.values())).lastrowid
    bons.evenement(cx, immeuble_id, "declaration", f"Déclaration : {libelle(v)} — motif : {v['motif']}"
                   + (f" ({v['auteur']})" if v["auteur"] else ""), le=v["cree_le"])
    _actualiser_alertes(cx, immeuble_id)
    cx.commit()
    return v


def supprimer(cx, did):
    """Supprime une déclaration (tracé dans l'historique) ; retourne l'immeuble concerné."""
    from . import bons
    r = db.lignes(cx, "SELECT * FROM declaration WHERE id = ?", (did,))
    if not r:
        raise ErreurDeclaration("Déclaration introuvable.")
    cx.execute("DELETE FROM declaration WHERE id = ?", (did,))
    bons.evenement(cx, r[0]["immeuble_id"], "declaration", f"Déclaration supprimée : {libelle(r[0])}")
    _actualiser_alertes(cx, r[0]["immeuble_id"])
    cx.commit()
    return r[0]["immeuble_id"]
