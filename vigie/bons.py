"""Suivi des alertes et bons de travaux.

Cycle : analyse -> alertes synchronisées (ouverte / résolue) -> bon de travaux adressé au prestataire du bon
métier pour l'immeuble -> envoi par e-mail (SMTP) ou fichier .eml à ouvrir dans Outlook -> suivi jusqu'à la
clôture. Les chiffres d'un bon viennent tous de l'alerte calculée par le moteur ; aucun n'est saisi ou inventé.
"""
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import db

RETOURS = ("pertinente", "deja_connue", "fausse_alerte")
STATUTS_BON = ("brouillon", "envoye", "en_cours", "retour", "termine", "annule")
BON_OUVERT = ("brouillon", "envoye", "en_cours", "retour")
RESULTATS_RETOUR = {"resolu": "Problème résolu", "non_resolu": "Problème non résolu", "a_suivre": "À suivre (2e passage)",
                    "rien_trouve": "Rien constaté sur place"}
SUIVIS = {"en_attente": "En attente", "bon_envoye": "Bon envoyé", "retour_incident": "Retour d'incident",
          "a_verifier": "Intervention faite, dérive encore mesurée", "cloturee": "Clôturée"}
ORDRE_GRAVITE = {"Critique": 3, "Élevée": 2, "Modérée": 1, "Données": 0}
AUTOMATISATION_DEFAUT = {"mode": "brouillon", "gravite_min": "Élevée", "inclure_donnees": True}
MESSAGERIE_DEFAUT = {"expediteur_nom": "", "expediteur_email": "", "copie_a": "", "signature": "",
                     "smtp_hote": "", "smtp_port": 587, "smtp_utilisateur": "", "smtp_securite": "starttls"}
ENV_MOT_DE_PASSE = "VIGIE_SMTP_MOT_DE_PASSE"
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[A-Za-z]{2,}$")


class ErreurBon(ValueError):
    pass


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- historique


def evenement(cx, immeuble_id, type_, texte, alerte_id=None, bon_id=None, le=None):
    """Historique horodaté de l'immeuble (alertes, bons, retours) ; jamais modifié ni effacé par l'interface."""
    cx.execute("INSERT INTO evenement (le, immeuble_id, alerte_id, bon_id, type, texte) VALUES (?,?,?,?,?,?)",
               (le or maintenant(), immeuble_id, alerte_id, bon_id, type_, texte))


def historique(cx, immeuble_id, limite=300):
    return db.lignes(cx, "SELECT e.*, b.numero FROM evenement e LEFT JOIN bon b ON b.id = e.bon_id "
                         "WHERE e.immeuble_id = ? ORDER BY e.le DESC, e.id DESC LIMIT ?", (immeuble_id, limite))


# ---------------------------------------------------------------- alertes


def synchroniser_alertes(cx, alertes):
    """Enregistre le résultat d'une analyse. Retourne les identifiants des alertes nouvelles ou rouvertes.

    Une alerte est identifiée par immeuble + cause (+ point pour les données) : la même dérive détectée
    à chaque analyse reste UNE alerte. Une alerte qui n'est plus détectée passe à « résolue ».
    """
    t = maintenant()
    existantes = {r["id"]: r for r in db.lignes(cx, "SELECT id, statut, immeuble_id, donnees FROM alerte")}
    nouvelles, vues = [], set()
    for a in alertes:
        vues.add(a["id"])
        donnees = json.dumps(a, ensure_ascii=False, default=str)
        ex = existantes.get(a["id"])
        if ex is None:
            cx.execute("INSERT INTO alerte (id, immeuble_id, point_id, cause, gravite, statut, ouverte_le, "
                       "derniere_detection, donnees) VALUES (?,?,?,?,?, 'ouverte', ?, ?, ?)",
                       (a["id"], a["immeuble_id"], a.get("point_id"), a["cause"], a["gravite"], t, t, donnees))
            evenement(cx, a["immeuble_id"], "alerte_ouverte", f"Alerte {a['gravite'].lower()} : {a['titre']}", a["id"], le=t)
            nouvelles.append(a["id"])
        elif ex["statut"] == "resolue":
            cx.execute("UPDATE alerte SET statut = 'ouverte', ouverte_le = ?, derniere_detection = ?, cloturee_le = NULL,"
                       " retour = NULL, retour_le = NULL, gravite = ?, donnees = ? WHERE id = ?",
                       (t, t, a["gravite"], donnees, a["id"]))
            evenement(cx, a["immeuble_id"], "alerte_rouverte", f"Dérive de nouveau mesurée : {a['titre']}", a["id"], le=t)
            nouvelles.append(a["id"])
        else:
            cx.execute("UPDATE alerte SET derniere_detection = ?, gravite = ?, donnees = ? WHERE id = ?",
                       (t, a["gravite"], donnees, a["id"]))
    for aid, ex in existantes.items():
        if aid not in vues and ex["statut"] == "ouverte":
            cx.execute("UPDATE alerte SET statut = 'resolue', cloturee_le = ? WHERE id = ?", (t, aid))
            titre = json.loads(ex["donnees"]).get("titre", aid)
            evenement(cx, ex["immeuble_id"], "alerte_resolue", f"Dérive disparue des mesures : {titre}", aid, le=t)
    cx.commit()
    return nouvelles


def liste_alertes(cx, statut="ouverte"):
    sql = "SELECT * FROM alerte" + (" WHERE statut = ?" if statut else "")
    out = []
    for r in db.lignes(cx, sql, (statut,) if statut else ()):
        a = json.loads(r.pop("donnees"))
        a.update(statut=r["statut"], ouverte_le=r["ouverte_le"], derniere_detection=r["derniere_detection"],
                 cloturee_le=r["cloturee_le"], retour=r["retour"])
        bon = db.lignes(cx, "SELECT id, numero, statut, destinataire_type, destinataire_nom, destinataire, cree_le, "
                            "envoye_le, retour_resultat, retour_texte, retour_le, cloture_le FROM bon "
                            "WHERE alerte_id = ? ORDER BY id DESC LIMIT 1", (a["id"],))
        a["bon"] = bon[0] if bon else None
        a["suivi"] = suivi(a["statut"], a["bon"])
        out.append(a)
    out.sort(key=lambda a: (a["statut"] != "ouverte", a["gravite"] == "Données", -(a.get("score") or 0)))
    return out


def suivi(statut_alerte, bon):
    """Statut de suivi d'une alerte : en attente, bon envoyé, retour d'incident, à vérifier, clôturée."""
    s = bon["statut"] if bon else None
    if statut_alerte == "resolue" and s in (None, "termine", "annule", "brouillon"):
        return "cloturee"
    if s in (None, "brouillon", "annule"):
        return "en_attente"
    if s in ("envoye", "en_cours"):
        return "bon_envoye"
    if s == "retour":
        return "retour_incident"
    return "a_verifier" if statut_alerte == "ouverte" else "cloturee"  # bon terminé


def enregistrer_retour(cx, alerte_id, retour):
    if retour not in RETOURS:
        raise ErreurBon("Retour : pertinente, déjà connue ou fausse alerte.")
    r = db.lignes(cx, "SELECT immeuble_id, donnees FROM alerte WHERE id = ?", (alerte_id,))
    if not r:
        raise ErreurBon("Alerte introuvable.")
    cx.execute("UPDATE alerte SET retour = ?, retour_le = ? WHERE id = ?", (retour, maintenant(), alerte_id))
    libelles = {"pertinente": "pertinente", "deja_connue": "déjà connue", "fausse_alerte": "fausse alerte"}
    evenement(cx, r[0]["immeuble_id"], "avis", f"Avis du gestionnaire : {libelles[retour]} — "
              f"{json.loads(r[0]['donnees']).get('titre', '')}", alerte_id)
    cx.commit()


def pertinence(cx):
    """Part des alertes jugées pertinentes parmi celles qui ont reçu un retour du gestionnaire."""
    n, p = cx.execute("SELECT count(*), sum(retour = 'pertinente') FROM alerte WHERE retour IS NOT NULL").fetchone()
    return {"retours": n, "pertinentes": p or 0, "taux": (p or 0) / n if n else None}


# ---------------------------------------------------------------- prestataires


def choisir_prestataire(cx, metier, immeuble_id):
    """Prestataire actif du métier demandé ; celui dédié à l'immeuble passe avant celui de tout le parc."""
    from .parc import _cle  # normalisation sans accents ni casse (« Electricien » = « Électricien »)

    candidats = []
    for p in db.lignes(cx, "SELECT * FROM prestataire WHERE actif = 1 ORDER BY id"):
        if _cle(p["metier"]) != _cle(metier):
            continue
        perimetre = [x.strip() for x in (p["perimetre"] or "*").split(",")]
        if immeuble_id in perimetre:
            candidats.append((0, p))
        elif "*" in perimetre:
            candidats.append((1, p))
    candidats.sort(key=lambda c: c[0])
    return candidats[0][1] if candidats else None


# ---------------------------------------------------------------- destinataires du bon


def destinataires(cx, alerte):
    """Les deux destinataires possibles d'un bon : le concierge de l'immeuble et le partenaire technique du métier.

    Concierge : celui de la fiche de l'immeuble s'il a un e-mail, sinon le prestataire « Concierge » de l'immeuble.
    Partenaire technique : prestataire du métier prévu par la règle (aucun si la règle désigne déjà le concierge).
    """
    im = db.lignes(cx, "SELECT concierge, concierge_email, concierge_tel FROM immeuble WHERE id = ?",
                   (alerte["immeuble_id"],))
    concierge = None
    if im and im[0]["concierge_email"]:
        concierge = {"type": "concierge", "nom": im[0]["concierge"] or "Concierge", "contact": im[0]["concierge"],
                     "email": im[0]["concierge_email"], "telephone": im[0]["concierge_tel"], "prestataire_id": None}
    else:
        p = choisir_prestataire(cx, "Concierge", alerte["immeuble_id"])
        if p:
            concierge = {"type": "concierge", "nom": p["nom"], "contact": p["contact"], "email": p["email"],
                         "telephone": p["telephone"], "prestataire_id": p["id"]}
    partenaire = None
    if (alerte.get("metier") or "").lower() != "concierge":
        p = choisir_prestataire(cx, alerte.get("metier"), alerte["immeuble_id"])
        if p:
            partenaire = {"type": "partenaire", "nom": p["nom"], "contact": p["contact"], "email": p["email"],
                          "telephone": p["telephone"], "prestataire_id": p["id"], "metier": p["metier"]}
    return {"concierge": concierge, "partenaire": partenaire}


# ---------------------------------------------------------------- bons de travaux


def _date_fr(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "")).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def derive_constatee(alerte):
    """Quantité constatée (kWh ou m³) depuis le début de la dérive, sans CHF (internes) ; None si non chiffrée."""
    m3, kwh = alerte.get("m3_mesure") or 0, alerte.get("kwh_mesure") or 0
    if m3 >= 0.05:
        return f"{m3:,.1f} m³".replace(",", " ").replace(".", ",")
    if kwh >= 1:
        return f"{kwh:,.0f} kWh".replace(",", " ")
    return None


def composer(alerte, prestataire, numero, messagerie):
    """Objet et corps du courriel. Tous les chiffres viennent de l'alerte calculée par le moteur."""
    salutation = f"Bonjour {prestataire['contact']}," if prestataire and prestataire.get("contact") else "Madame, Monsieur,"
    lignes = [
        salutation, "",
        "Nous vous confions l'intervention décrite ci-dessous.", "",
        f"Bon de travaux n° {numero}",
        f"Immeuble : {alerte['immeuble']} — {alerte['adresse']}",
        f"Installation : {alerte['fluide']}",
        f"Problème constaté : {alerte['titre']}",
        f"Constat : {alerte['constat']}",
    ]
    if alerte.get("mesure") and alerte.get("attendu"):
        lignes.append(f"Valeur mesurée : {alerte['mesure']} — valeur attendue : {alerte['attendu']}")
    if alerte.get("debut"):
        lignes.append(f"Depuis le : {_date_fr(alerte['debut'])}"
                      + (f" ({alerte['persistance']})" if alerte.get("persistance") else ""))
    constatee = derive_constatee(alerte)
    if constatee:  # seule la dérive CONSTATÉE (mesurée) est transmise ; ni projection ni montant en CHF
        lignes.append(f"Dérive constatée : {constatee} depuis le {_date_fr(alerte['debut'])}")
    lignes += ["", f"Intervention demandée : {alerte['consigne']}", f"Délai souhaité : {alerte['delai']}"]
    if alerte.get("sinistre"):
        lignes.append("Attention : risque de dégât des eaux, merci d'intervenir en priorité.")
    lignes += ["", f"Merci de confirmer la prise en charge par retour de courriel et de rappeler le n° {numero} "
                   "sur votre rapport d'intervention et votre facture.", "", "Meilleures salutations,"]
    signature = (messagerie.get("signature") or messagerie.get("expediteur_nom") or "").strip()
    if signature:
        lignes.append(signature)
    objet = f"Bon de travaux {numero} — {alerte['titre']} — {alerte['immeuble']}"
    return objet, "\n".join(lignes)


def _numero(cx):
    prefixe = f"BT-{datetime.now(timezone.utc).year}-"
    dernier = cx.execute("SELECT max(numero) FROM bon WHERE numero LIKE ?", (prefixe + "%",)).fetchone()[0]
    n = int(dernier.rsplit("-", 1)[1]) + 1 if dernier else 1
    return f"{prefixe}{n:04d}"


def _journal(cx, bon_id, texte):
    """Journal du bon + historique de l'immeuble (même horodatage)."""
    journal, immeuble_id, alerte_id, numero = cx.execute(
        "SELECT journal, immeuble_id, alerte_id, numero FROM bon WHERE id = ?", (bon_id,)).fetchone()
    t = maintenant()
    j = json.loads(journal)
    j.append({"le": t, "texte": texte})
    cx.execute("UPDATE bon SET journal = ? WHERE id = ?", (json.dumps(j, ensure_ascii=False), bon_id))
    evenement(cx, immeuble_id, "bon", f"Bon {numero} : {texte}", alerte_id, bon_id, le=t)


def bon_ouvert(cx, alerte_id):
    r = db.lignes(cx, f"SELECT * FROM bon WHERE alerte_id = ? AND statut IN ({','.join('?' * len(BON_OUVERT))})"
                      " ORDER BY id DESC LIMIT 1", (alerte_id, *BON_OUVERT))
    return r[0] if r else None


def creer_bon(cx, alerte_id, prestataire_id=None, mode="manuel", destinataire_type=None):
    """Crée le bon de travaux d'une alerte (ou renvoie le bon déjà en cours : un seul bon ouvert par alerte).

    destinataire_type : "concierge" ou "partenaire" ; par défaut, celui que désigne la règle (métier).
    """
    existant = bon_ouvert(cx, alerte_id)
    if existant:
        return lire_bon(cx, existant["id"]), False
    r = db.lignes(cx, "SELECT donnees FROM alerte WHERE id = ?", (alerte_id,))
    if not r:
        raise ErreurBon("Alerte introuvable.")
    alerte = json.loads(r[0]["donnees"])
    if prestataire_id:
        pr = db.lignes(cx, "SELECT * FROM prestataire WHERE id = ?", (prestataire_id,))
        if not pr:
            raise ErreurBon("Prestataire introuvable.")
        prestataire = {**pr[0], "type": "concierge" if pr[0]["metier"].lower() == "concierge" else "partenaire",
                       "prestataire_id": pr[0]["id"]}
    else:
        possibles = destinataires(cx, alerte)
        defaut = "concierge" if (alerte.get("metier") or "").lower() == "concierge" else "partenaire"
        choix = destinataire_type or defaut
        if choix not in ("concierge", "partenaire"):
            raise ErreurBon("Destinataire : concierge ou partenaire technique.")
        prestataire = possibles[choix] or possibles["partenaire" if choix == "concierge" else "concierge"]
        repli = prestataire is not None and prestataire["type"] != choix
    numero = _numero(cx)
    objet, corps = composer(alerte, prestataire, numero, lire_messagerie(cx))
    bid = cx.execute("INSERT INTO bon (numero, alerte_id, immeuble_id, prestataire_id, statut, cree_le, destinataire, "
                     "objet, corps, mode, destinataire_type, destinataire_nom) VALUES (?,?,?,?, 'brouillon', ?,?,?,?,?,?,?)",
                     (numero, alerte_id, alerte["immeuble_id"], prestataire["prestataire_id"] if prestataire else None,
                      maintenant(), prestataire["email"] if prestataire else None, objet, corps, mode,
                      prestataire["type"] if prestataire else None, prestataire["nom"] if prestataire else None)).lastrowid
    _journal(cx, bid, ("Bon créé automatiquement après l'analyse" if mode == "auto" else "Bon créé par le gestionnaire")
             + (f", destinataire : {'concierge' if prestataire['type'] == 'concierge' else 'partenaire technique'} "
                f"{prestataire['nom']}." if prestataire else "."))
    if not prestataire_id and prestataire and repli:
        _journal(cx, bid, f"Aucun partenaire « {alerte.get('metier')} » pour cet immeuble : bon adressé au concierge, "
                          "à réorienter si besoin.")
    if not prestataire:
        _journal(cx, bid, f"Aucun prestataire « {alerte.get('metier')} » pour cet immeuble : à choisir avant l'envoi.")
    cx.commit()
    return lire_bon(cx, bid), True


def lire_bon(cx, bid):
    r = db.lignes(cx, "SELECT b.*, p.nom AS prestataire, p.metier AS prestataire_metier, p.telephone AS prestataire_tel, "
                      "i.nom AS immeuble, a.statut AS alerte_statut, a.donnees AS alerte_donnees "
                      "FROM bon b LEFT JOIN prestataire p ON p.id = b.prestataire_id "
                      "LEFT JOIN immeuble i ON i.id = b.immeuble_id LEFT JOIN alerte a ON a.id = b.alerte_id "
                      "WHERE b.id = ?", (bid,))
    if not r:
        raise ErreurBon("Bon introuvable.")
    b = r[0]
    b["journal"] = json.loads(b["journal"])
    a = json.loads(b.pop("alerte_donnees") or "{}")
    b["alerte"] = {k: a.get(k) for k in ("titre", "gravite", "fluide", "chiffrage", "periode", "projection", "chf_mois",
                                         "chf_an", "kwh_an", "m3_an", "chf_mesure", "kwh_mesure", "m3_mesure", "chf_proj",
                                         "kwh_proj", "m3_proj", "jours_rythme", "debut", "payeur", "metier", "delai",
                                         "sinistre", "adresse", "immeuble")}
    if not b["immeuble"]:
        b["immeuble"] = a.get("immeuble")
    return b


def liste_bons(cx):
    return [lire_bon(cx, r[0]) for r in cx.execute("SELECT id FROM bon ORDER BY id DESC")]


LIBELLES_STATUT = {"brouillon": "Remis en brouillon", "envoye": "Marqué comme envoyé", "en_cours": "Intervention en cours",
                   "retour": "Retour d'incident reçu", "termine": "Intervention terminée", "annule": "Bon annulé"}


def changer_destinataire(cx, bid, destinataire_type):
    """Bon en brouillon : bascule entre le concierge et le partenaire technique (message recomposé)."""
    b = lire_bon(cx, bid)
    if b["statut"] != "brouillon":
        raise ErreurBon("Seul un bon en brouillon peut changer de destinataire.")
    alerte = json.loads(cx.execute("SELECT donnees FROM alerte WHERE id = ?", (b["alerte_id"],)).fetchone()[0])
    d = destinataires(cx, alerte).get(destinataire_type) if destinataire_type in ("concierge", "partenaire") else None
    if not d:
        raise ErreurBon("Aucun " + ("concierge" if destinataire_type == "concierge" else "partenaire technique")
                        + " pour cet immeuble : complétez la fiche de l'immeuble ou la liste des prestataires.")
    objet, corps = composer(alerte, d, b["numero"], lire_messagerie(cx))
    cx.execute("UPDATE bon SET destinataire_type = ?, destinataire_nom = ?, destinataire = ?, prestataire_id = ?, "
               "objet = ?, corps = ? WHERE id = ?", (d["type"], d["nom"], d["email"], d["prestataire_id"], objet, corps, bid))
    _journal(cx, bid, f"Destinataire : {'concierge' if d['type'] == 'concierge' else 'partenaire technique'} {d['nom']}.")
    cx.commit()
    return lire_bon(cx, bid)


def enregistrer_retour_incident(cx, bid, resultat, texte, le=None):
    """Retour du concierge ou du partenaire après intervention (compte rendu horodaté)."""
    b = lire_bon(cx, bid)
    if b["statut"] not in ("envoye", "en_cours", "retour"):
        raise ErreurBon("Un retour d'incident s'enregistre sur un bon envoyé.")
    if resultat not in RESULTATS_RETOUR:
        raise ErreurBon("Résultat : résolu, non résolu, à suivre ou rien constaté.")
    texte = str(texte or "").strip()
    if not texte or len(texte) > 2000:
        raise ErreurBon("Décrivez le retour d'intervention (2000 caractères au maximum).")
    quand = le or maintenant()
    try:
        datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
    except ValueError:
        raise ErreurBon("Date du retour illisible.") from None
    cx.execute("UPDATE bon SET statut = 'retour', retour_resultat = ?, retour_texte = ?, retour_le = ? WHERE id = ?",
               (resultat, texte, quand, bid))
    _journal(cx, bid, f"Retour d'incident ({RESULTATS_RETOUR[resultat].lower()}) : {texte}")
    cx.commit()
    return lire_bon(cx, bid)


def modifier_bon(cx, bid, d):
    b = lire_bon(cx, bid)
    if any(k in d for k in ("objet", "corps", "destinataire", "prestataire_id")):
        if b["statut"] != "brouillon":
            raise ErreurBon("Seul un bon en brouillon peut être modifié.")
        if d.get("prestataire_id"):
            pr = db.lignes(cx, "SELECT * FROM prestataire WHERE id = ?", (d["prestataire_id"],))
            if not pr:
                raise ErreurBon("Prestataire introuvable.")
            cx.execute("UPDATE bon SET prestataire_id = ?, destinataire = ? WHERE id = ?",
                       (pr[0]["id"], pr[0]["email"], bid))
            _journal(cx, bid, f"Prestataire choisi : {pr[0]['nom']}.")
        for champ, maxi in (("objet", 300), ("corps", 10000), ("destinataire", 160)):
            if d.get(champ) is not None:
                v = str(d[champ]).strip()
                if not v or len(v) > maxi:
                    raise ErreurBon(f"« {champ} » est vide ou trop long.")
                if champ == "destinataire" and not EMAIL_RE.match(v):
                    raise ErreurBon(f"Adresse e-mail invalide : {v}")
                if champ == "objet" and ("\n" in v or "\r" in v):
                    raise ErreurBon("L'objet doit tenir sur une ligne.")
                cx.execute(f"UPDATE bon SET {champ} = ? WHERE id = ?", (v, bid))
    if "statut" in d:
        statut = d["statut"]
        if statut not in STATUTS_BON:
            raise ErreurBon("Statut inconnu.")
        cx.execute("UPDATE bon SET statut = ?, cloture_le = ? WHERE id = ?",
                   (statut, maintenant() if statut in ("termine", "annule") else None, bid))
        if statut == "envoye" and not b["envoye_le"]:
            cx.execute("UPDATE bon SET envoye_le = ? WHERE id = ?", (maintenant(), bid))
        _journal(cx, bid, LIBELLES_STATUT[statut] + (f" — {d['commentaire']}" if d.get("commentaire") else ""))
    cx.commit()
    return lire_bon(cx, bid)


# ---------------------------------------------------------------- e-mail


def lire_messagerie(cx):
    return {**MESSAGERIE_DEFAUT, **(db.lire_parametre(cx, "messagerie") or {})}


def lire_automatisation(cx):
    return {**AUTOMATISATION_DEFAUT, **(db.lire_parametre(cx, "automatisation") or {})}


def message(bon, messagerie):
    m = EmailMessage()
    m["Subject"] = bon["objet"]
    m["To"] = bon["destinataire"]
    if messagerie.get("expediteur_email"):
        m["From"] = formataddr((messagerie.get("expediteur_nom") or "", messagerie["expediteur_email"]))
    if messagerie.get("copie_a"):
        m["Cc"] = messagerie["copie_a"]
    m["Message-ID"] = make_msgid(domain="vigie.local")
    m.set_content(bon["corps"])
    return m


def fichier_eml(bon, messagerie):
    """Courriel prêt à envoyer : un double-clic l'ouvre dans Outlook en mode brouillon (en-tête X-Unsent)."""
    if not bon["destinataire"]:
        raise ErreurBon("Choisissez d'abord un prestataire (aucune adresse e-mail).")
    try:
        m = message(bon, messagerie)
        m["X-Unsent"] = "1"
        return m.as_bytes()
    except ValueError as e:
        raise ErreurBon(f"Courriel impossible à composer : {e}") from e


def smtp_configure(messagerie):
    return bool(messagerie.get("smtp_hote") and messagerie.get("expediteur_email"))


def envoyer_bon(cx, bid, mot_de_passe=None, envoi=None):
    """Envoie le bon par SMTP. `envoi` permet de remplacer l'envoi réel (tests)."""
    bon = lire_bon(cx, bid)
    if bon["statut"] not in ("brouillon", "envoye"):
        raise ErreurBon("Ce bon n'est plus à envoyer.")
    if not bon["destinataire"]:
        raise ErreurBon("Choisissez d'abord un prestataire (aucune adresse e-mail).")
    messagerie = lire_messagerie(cx)
    if not smtp_configure(messagerie):
        raise ErreurBon("La messagerie n'est pas configurée (Réglages › Messagerie). "
                        "Vous pouvez télécharger le courriel et l'envoyer depuis Outlook.")
    try:
        m = message(bon, messagerie)
    except ValueError as e:
        raise ErreurBon(f"Courriel impossible à composer : {e}") from e
    (envoi or _envoi_smtp)(m, messagerie, mot_de_passe or os.environ.get(ENV_MOT_DE_PASSE))
    cx.execute("UPDATE bon SET statut = 'envoye', envoye_le = ? WHERE id = ?", (maintenant(), bid))
    _journal(cx, bid, f"Envoyé par e-mail à {bon['destinataire']}.")
    cx.commit()
    return lire_bon(cx, bid)


def _envoi_smtp(m, messagerie, mot_de_passe):
    hote, port = messagerie["smtp_hote"], int(messagerie.get("smtp_port") or 587)
    contexte = ssl.create_default_context()
    try:
        if messagerie.get("smtp_securite") == "ssl":
            serveur = smtplib.SMTP_SSL(hote, port, context=contexte, timeout=20)
        else:
            serveur = smtplib.SMTP(hote, port, timeout=20)
            if messagerie.get("smtp_securite", "starttls") == "starttls":
                serveur.starttls(context=contexte)
        with serveur:
            if messagerie.get("smtp_utilisateur"):
                sans_chiffrement = messagerie.get("smtp_securite") == "aucune"
                if sans_chiffrement and hote not in ("localhost", "127.0.0.1"):
                    raise ErreurBon("Mot de passe refusé sur une connexion non chiffrée : choisissez STARTTLS ou SSL.")
                if not mot_de_passe:
                    raise ErreurBon("Mot de passe de messagerie manquant (Réglages › Messagerie).")
                serveur.login(messagerie["smtp_utilisateur"], mot_de_passe)
            serveur.send_message(m)
    except (smtplib.SMTPException, OSError) as e:
        raise ErreurBon(f"Échec de l'envoi : {e}") from e


# ---------------------------------------------------------------- automatisation


def automatiser(cx, nouvelles, mot_de_passe=None, envoi=None):
    """Après une analyse : crée (et envoie si demandé) les bons des nouvelles alertes selon les réglages."""
    auto = lire_automatisation(cx)
    resultat = {"crees": [], "envoyes": [], "a_completer": [], "erreurs": []}
    if auto["mode"] == "manuel" or not nouvelles:
        return resultat
    seuil = ORDRE_GRAVITE.get(auto["gravite_min"], 2)
    for aid in nouvelles:
        r = db.lignes(cx, "SELECT gravite FROM alerte WHERE id = ?", (aid,))
        if not r:
            continue
        g = r[0]["gravite"]
        if g == "Données" and not auto["inclure_donnees"]:
            continue
        if g != "Données" and ORDRE_GRAVITE.get(g, 0) < seuil:
            continue
        bon, cree = creer_bon(cx, aid, mode="auto")
        if not cree:
            continue
        resultat["crees"].append(bon["numero"])
        if not bon["destinataire"]:
            resultat["a_completer"].append(bon["numero"])
            continue
        if auto["mode"] == "envoi" and smtp_configure(lire_messagerie(cx)):
            try:
                envoyer_bon(cx, bon["id"], mot_de_passe, envoi)
                resultat["envoyes"].append(bon["numero"])
            except ErreurBon as e:
                _journal(cx, bon["id"], f"Envoi automatique impossible : {e}")
                cx.commit()
                resultat["erreurs"].append(f"{bon['numero']} : {e}")
    return resultat
