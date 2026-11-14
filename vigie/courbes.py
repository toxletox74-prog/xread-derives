"""Import des courbes fines d'un lot patrimoine : relevés au jour, à l'heure ou au quart d'heure.

Formats (CSV, séparateur ; ou , — point décimal, UTF-8), une ligne par compteur et par pas :
  journalier        date;id_compteur;id_site;fluide;valeur;unite            date = jour civil (heure de Genève)
  heure ou 15 min   horodatage;id_compteur;id_site;energie_kwh[;debit_m3_h;t_aller_c;t_retour_c]
                    horodatage = DÉBUT de l'intervalle, heure légale suisse avec son décalage (+01:00 / +02:00)
Un classeur .xlsx du même lot n'est lu que pour sa feuille « Calendrier » (type de jour, vacances, température et
rayonnement du jour), rangée dans la table des références.

Chaque compteur doit déjà exister (classeur patrimoine importé avant). Sa courbe devient un SECOND compteur, relié au
premier : S13-GZ (relevé mensuel du distributeur) et S13-GZ-JOUR (courbe journalière). Deux pas de temps ne sont jamais
mélangés dans une même série, et rien n'est compté deux fois. Les valeurs sont stockées telles quelles, horodatées en
UTC à la FIN de l'intervalle (convention de Vigie) : le jour civil 2025-01-01 → 2025-01-01T23:00:00Z.

Contrôles tracés dans `anomalie_import` (rien n'est corrigé ni comblé, règles 1 et 4) : compteur inconnu, ligne
illisible, valeur vide, valeur négative (« suspecte »), doublon, pas manquant dans la grille, site ou unité en désaccord
avec le compteur, bilan thermique du chauffage à distance (énergie ≈ 1,163 × débit × écart de température), et écart
entre la courbe et le relevé mensuel du même compteur (elle doit retomber sur le total du mois).
"""
import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db, excel, parc, patrimoine

FUSEAU = ZoneInfo("Europe/Zurich")
FMT = "%Y-%m-%dT%H:%M:%SZ"
SUFFIXES = {1440: ("JOUR", "courbe journalière"), 60: ("HEURE", "courbe horaire"),
            15: ("15MIN", "courbe au quart d'heure")}
# Colonnes supplémentaires du chauffage à distance -> (fluide Vigie, suffixe du code, libellé)
GRANDEURS_CAD = (("debit_m3_h", "cad_debit", "DEBIT", "débit"),
                 ("t_aller_c", "cad_temperature_aller", "TALLER", "température aller"),
                 ("t_retour_c", "cad_temperature_retour", "TRETOUR", "température retour"))
BILAN_CAD_KWH = 1.163           # kWh par (m³/h × °C) sur une heure
BILAN_CAD_TOLERANCE = 0.10      # écart toléré entre l'énergie comptée et le bilan thermique
ECART_MENSUEL = 0.01            # la courbe doit retomber sur le relevé mensuel (lot : 0,5 %)
ECART_MENSUEL_FLUIDE = {"electricite_injection": 0.03}  # injection solaire : 2,5 % de mai à juillet selon le lot
EXEMPLES_MAX = 6                # périodes citées dans le détail d'une anomalie


class PlanCourbes:
    def __init__(self, fichier):
        self.fichier = fichier
        self.points, self.mesures, self.series, self.anomalies, self.references = [], [], [], [], []

    def anomalie(self, type_, objet, periode, detail, traitement):
        self.anomalies.append({"type": type_, "feuille": self.fichier, "ligne": None, "objet": objet,
                               "periode": periode, "detail": detail, "traitement": traitement})


def _nombre(v):
    t = "" if v is None else str(v).strip()
    return None if t == "" else float(t.replace(",", "."))


def _debut(d, journalier):
    """Début de l'intervalle (date-heure avec fuseau). Lève ValueError si la cellule est illisible."""
    if journalier:
        j = datetime.strptime(str(d.get("date") or "").strip(), "%Y-%m-%d")
        return j.replace(tzinfo=FUSEAU)
    t = datetime.fromisoformat(str(d.get("horodatage") or "").strip())
    return t if t.tzinfo else t.replace(tzinfo=FUSEAU)


def _fin(debut, pas):
    """Fin de l'intervalle en UTC. Jour civil : minuit local du lendemain (23 h ou 25 h aux changements d'heure)."""
    if pas == 1440:
        lendemain = datetime.combine(debut.date() + timedelta(days=1), time(0), FUSEAU)
        return lendemain.astimezone(timezone.utc)
    return debut.astimezone(timezone.utc) + timedelta(minutes=pas)


def _pas(debuts, journalier):
    if journalier:
        return 1440
    tri = sorted({d.astimezone(timezone.utc) for d in debuts})
    ecarts = Counter(round((b - a).total_seconds() / 60) for a, b in zip(tri, tri[1:]))
    return ecarts.most_common(1)[0][0] if ecarts else None


def _periodes(valeurs):
    v = sorted(valeurs)
    return ", ".join(v[:EXEMPLES_MAX]) + ("…" if len(v) > EXEMPLES_MAX else "")


def lire_csv(texte):
    """Colonnes normalisées et [(n° de ligne, {colonne normalisée: valeur})] d'un CSV (séparateur ; ou ,)."""
    tete = texte[:2000].splitlines()[0] if texte else ""
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=";" if tete.count(";") >= tete.count(",") else ",")
    colonnes = [parc._cle(c) for c in (lecteur.fieldnames or [])]
    return colonnes, [(n, {parc._cle(k): v for k, v in ligne.items() if k}) for n, ligne in enumerate(lecteur, start=2)]


def _point(base, pas, suffixe=None, fluide=None, libelle=None, annee=None, fichier=""):
    """Compteur de la courbe, dérivé du compteur mensuel `base` (même site, même fluide sauf grandeur du CAD)."""
    code, nom = SUFFIXES[pas]
    _lib, unite, nature = db.FLUIDES[fluide] if fluide else (None, base["unite"], "intervalle")
    return {"id": f"{base['id']}-{suffixe or code}", "immeuble_id": base["immeuble_id"], "fluide": fluide or base["fluide"],
            "libelle": (f"{base['libelle'] or base['id']} — {libelle or nom}" + (f" {annee}" if annee else ""))[:120],
            "unite": unite, "nature": nature, "pas_min": pas, "source": f"Courbe de charge ({fichier})"[:120],
            "identifiant": base["id"], "fournisseur": base.get("fournisseur"), "etat": "actif",
            "niveau": "courbe de charge", "parent_id": base["id"], "releve": nom,
            **({} if fluide else {c: base.get(c) for c in db.SOLAIRE_CHAMPS})}


def _serie(plan, cx, base, cid, lignes, journalier, colonnes):
    """Contrôle la série d'un compteur et l'ajoute au plan."""
    if base is None:
        plan.anomalie("compteur inconnu", cid, None, f"{len(lignes)} lignes pour un compteur absent du parc.",
                      "lignes rejetées")
        return
    lus, illisibles = [], 0
    for n, d in lignes:
        try:
            lus.append((n, d, _debut(d, journalier), _nombre(d.get("valeur" if journalier else "energie_kwh"))))
        except ValueError:
            illisibles += 1
    if illisibles:
        plan.anomalie("valeur illisible", cid, None, f"{illisibles} lignes à l'horodatage ou à la valeur illisible.",
                      "lignes rejetées")
    pas = _pas([x[2] for x in lus], journalier)
    if pas not in SUFFIXES or not lus:
        plan.anomalie("pas de temps inconnu", cid, None, f"Pas de {pas} minutes : attendu 15, 60 ou le jour.",
                      "série rejetée")
        return
    point = _point(base, pas, annee=lus[0][2].year, fichier=plan.fichier)
    valeurs, vides, negatifs, doublons, conflits, sites = {}, [], [], [], [], 0
    for _n, d, debut, valeur in lus:
        ts = _fin(debut, pas).strftime(FMT)
        local = debut.strftime("%Y-%m-%d" if journalier else "%Y-%m-%d %H:%M")
        if d.get("id_site") and str(d["id_site"]).strip() != base["immeuble_id"]:
            sites += 1
        if valeur is None:
            vides.append(local)
            continue
        if ts in valeurs:
            (doublons if valeurs[ts][0] == valeur else conflits).append(local)
        if valeur < 0:
            negatifs.append(local)
        valeurs[ts] = (valeur, "suspecte" if valeur < 0 else "valide", debut)
    _tracer(plan, point["id"], vides, negatifs, doublons, conflits, sites, base)
    _unite(plan, point["id"], lus, base, journalier)
    _grille(plan, point["id"], [x[2] for x in lus], pas)
    plan.points.append(point)
    plan.mesures += [(ts, point["id"], v, q) for ts, (v, q, _d) in valeurs.items()]
    extras = _grandeurs_cad(plan, base, lus, pas, colonnes) if base["fluide"] == "cad" else 0
    ecarts = _ecarts_mensuels(plan, cx, base, point["id"], valeurs, pas)
    debuts = sorted(x[2] for x in lus)
    plan.series.append({"id": point["id"], "compteur": cid, "immeuble_id": base["immeuble_id"], "pas_min": pas,
                        "lignes": len(lignes), "valeurs": len(valeurs), "grandeurs_associees": extras,
                        "periode": [debuts[0].strftime("%Y-%m-%d"), debuts[-1].strftime("%Y-%m-%d")],
                        "total": round(sum(v for v, q, _d in valeurs.values() if q == "valide"), 3),
                        "unite": base["unite"], "mois_en_ecart": ecarts})


def _tracer(plan, pid, vides, negatifs, doublons, conflits, sites, base):
    for liste, type_, quoi, traitement in (
            (vides, "relevé manquant", "valeurs vides", "aucune mesure créée, jamais comblée"),
            (negatifs, "valeur négative", "valeurs négatives", "importées, marquées « suspectes », exclues des calculs"),
            (doublons, "doublon", "relevés en double, identiques", "une seule mesure conservée"),
            (conflits, "doublon contradictoire", "relevés en double, différents", "la dernière valeur l'emporte, à vérifier")):
        if liste:
            plan.anomalie(type_, pid, f"{min(liste)} à {max(liste)}", f"{len(liste)} {quoi} : {_periodes(liste)}.", traitement)
    if sites:
        plan.anomalie("désaccord avec le compteur", pid, None,
                      f"{sites} lignes portent un autre site que celui du compteur ({base['immeuble_id']}).",
                      "importées avec le site du compteur, à vérifier")


def _unite(plan, pid, lus, base, journalier):
    if not journalier:
        return
    unites = Counter(patrimoine.UNITES.get(parc._cle(d.get("unite")), str(d.get("unite"))) for _n, d, _t, _v in lus)
    autres = {u: n for u, n in unites.items() if u != base["unite"]}
    if autres:
        plan.anomalie("désaccord avec le compteur", pid, None,
                      f"Unité {', '.join(f'{u} ({n} lignes)' for u, n in autres.items())} alors que le compteur est en "
                      f"{base['unite']}.", "importées dans l'unité du compteur, à vérifier")


def _grille(plan, pid, debuts, pas):
    """Pas manquants entre le premier et le dernier relevé (aucune ligne du tout)."""
    if pas == 1440:
        presents = {d.date() for d in debuts}
        jour, fin, absents = min(presents), max(presents), []
        while jour <= fin:
            if jour not in presents:
                absents.append(jour.isoformat())
            jour += timedelta(days=1)
    else:
        presents = {d.astimezone(timezone.utc) for d in debuts}
        t, fin, absents = min(presents), max(presents), []
        while t <= fin:
            if t not in presents:
                absents.append(t.astimezone(FUSEAU).strftime("%Y-%m-%d %H:%M"))
            t += timedelta(minutes=pas)
    if absents:
        plan.anomalie("pas sans relevé", pid, f"{absents[0]} à {absents[-1]}",
                      f"{len(absents)} pas de temps sans aucune ligne : {_periodes(absents)}.", "laissés vides, jamais comblés")


def _grandeurs_cad(plan, base, lus, pas, colonnes):
    """Débit et températures de la sous-station (colonnes facultatives) et contrôle du bilan thermique."""
    presentes = [g for g in GRANDEURS_CAD if g[0] in colonnes]
    for colonne, fluide, suffixe, libelle in presentes:
        p = _point(base, pas, suffixe=suffixe, fluide=fluide, libelle=libelle, fichier=plan.fichier)
        plan.points.append(p)
        for _n, d, debut, _v in lus:
            try:
                v = _nombre(d.get(colonne))
            except ValueError:
                v = None
            if v is not None:
                plan.mesures.append((_fin(debut, pas).strftime(FMT), p["id"], v, "valide"))
    if len(presentes) == len(GRANDEURS_CAD) and pas == 60:
        _bilan_cad(plan, base, lus, pas)
    return len(presentes)


def _bilan_cad(plan, base, lus, pas):
    ecarts = []
    for _n, d, debut, energie in lus:
        try:
            q, ta, tr = (_nombre(d.get(c)) for c in ("debit_m3_h", "t_aller_c", "t_retour_c"))
        except ValueError:
            continue
        if None in (energie, q, ta, tr):
            continue
        bilan = BILAN_CAD_KWH * q * (ta - tr)
        if abs(energie - bilan) > max(2.0, BILAN_CAD_TOLERANCE * abs(bilan)):
            ecarts.append(debut.strftime("%Y-%m-%d %H:%M"))
    if ecarts:
        plan.anomalie("bilan thermique incohérent", f"{base['id']}-{SUFFIXES[pas][0]}", f"{min(ecarts)} à {max(ecarts)}",
                      f"{len(ecarts)} heures où l'énergie comptée s'écarte de plus de 10 % de 1,163 × débit × "
                      f"(aller − retour) : {_periodes(ecarts)}.", "valeurs importées telles quelles, à vérifier")


def _ecarts_mensuels(plan, cx, base, pid, valeurs, pas):
    """La courbe retombe-t-elle sur le relevé mensuel du même compteur ? Mois complets seulement."""
    par_mois, nombre = defaultdict(float), Counter()
    for v, q, debut in valeurs.values():
        mois = debut.astimezone(FUSEAU).strftime("%Y-%m")
        nombre[mois] += 1
        if q == "valide":
            par_mois[mois] += v
    tolerance = ECART_MENSUEL_FLUIDE.get(base["fluide"], ECART_MENSUEL)
    en_ecart = 0
    for mois in sorted(par_mois):
        a, m = int(mois[:4]), int(mois[5:7])
        jours = (datetime(a + (m == 12), m % 12 + 1, 1) - datetime(a, m, 1)).days
        attendus = jours * 1440 // pas
        if abs(nombre[mois] - attendus) > (4 if pas < 1440 else 0):  # mois incomplet (hors heure du changement d'heure)
            continue
        r = cx.execute("SELECT valeur FROM mesure WHERE point_id = ? AND ts = ? AND qualite = 'valide'",
                       (base["id"], patrimoine.ts_fin_mois(mois))).fetchone()
        if not r or not r[0]:
            continue
        ecart = par_mois[mois] / r[0] - 1
        if abs(ecart) > tolerance:
            en_ecart += 1
            pourcent = f"{ecart * 100:+.1f} %".replace("-", "−").replace(".", ",")
            plan.anomalie("écart avec le relevé mensuel", pid, mois,
                          f"Courbe : {par_mois[mois]:.0f} {base['unite']} ; relevé mensuel {base['id']} : {r[0]:.0f} "
                          f"({pourcent}).", "les deux séries sont conservées, à examiner")
    return en_ecart


def lire_classeur(contenu, fichier):
    """Colonnes et lignes des feuilles de courbes d'un classeur .xlsx (mêmes colonnes que le CSV, valeurs en texte
    ou en nombre). Les feuilles de même en-tête que la première feuille de courbes sont lues à la suite."""
    feuilles = excel.lire_xlsx(contenu)
    colonnes, lignes = None, []
    for nom, contenu_feuille in feuilles.items():
        entetes = [parc._cle(c) for c in (contenu_feuille[0] if contenu_feuille else [])]
        if "id_compteur" in entetes and (colonnes is None or entetes == colonnes):
            colonnes = entetes
            lignes.extend(patrimoine.lignes_feuille(feuilles, nom))
    if colonnes is None:
        raise patrimoine.ErreurPatrimoine(
            f"{fichier} : aucune feuille de courbes (colonne id_compteur) ni feuille « Calendrier » dans ce classeur.")
    return colonnes, lignes


def preparer(cx, texte, fichier):
    """Lit et contrôle un fichier de courbes .csv sans rien écrire."""
    return preparer_lignes(cx, *lire_csv(texte), fichier)


def preparer_lignes(cx, colonnes, lignes, fichier):
    """Contrôle les lignes d'un fichier de courbes (CSV ou classeur) sans rien écrire."""
    journalier = "date" in colonnes
    if "id_compteur" not in colonnes or not (journalier and "valeur" in colonnes
                                             or "horodatage" in colonnes and "energie_kwh" in colonnes):
        raise patrimoine.ErreurPatrimoine(
            f"{fichier} : colonnes attendues date;id_compteur;valeur (jour) ou horodatage;id_compteur;energie_kwh.")
    plan = PlanCourbes(fichier)
    bases = {r["id"]: r for r in db.lignes(cx, "SELECT * FROM point_mesure")}
    par_compteur = defaultdict(list)
    for n, d in lignes:
        par_compteur[str(d.get("id_compteur") or "").strip()].append((n, d))
    for cid, serie in par_compteur.items():
        _serie(plan, cx, bases.get(cid), cid, serie, journalier, colonnes)
    return plan


def preparer_calendrier(contenu, fichier):
    """Feuille « Calendrier » d'un classeur du lot -> références du jour (type de jour, vacances, météo du jour)."""
    feuilles = excel.lire_xlsx(contenu, seulement=lambda nom: parc._cle(nom).startswith("calendrier"))
    plan = PlanCourbes(fichier)
    for nom in feuilles:
        for _n, r in patrimoine.lignes_feuille(feuilles, nom):
            jour = patrimoine._texte(r.get("date"))
            if not jour:
                continue
            type_jour = parc._cle(r.get("type"))
            for serie, valeur, unite in (
                    ("jour_ouvre", float(type_jour == "ouvre"), "1 = jour ouvré"),
                    ("jour_ferie", float(type_jour == "ferie"), "1 = jour férié"),
                    ("jour_vacances_scolaires", float(parc._cle(r.get("vacances_scolaires")) == "oui"), "1 = vacances"),
                    ("jour_temperature_moyenne_c", patrimoine._sur(r.get("temperature_moyenne_c")), "°C"),
                    ("jour_rayonnement_global_w_m2", patrimoine._sur(r.get("rayonnement_global_w_m2")), "W/m²")):
                if valeur is not None:
                    plan.references.append((serie, jour, valeur, unite, f"{fichier} · {nom}"))
    if not plan.references:
        raise patrimoine.ErreurPatrimoine(f"{fichier} : aucune feuille « Calendrier » lisible dans ce classeur.")
    return plan


def rapport(plan, applique=False, lot=None):
    return {"fichier": plan.fichier, "applique": applique, "lot": lot, "series": plan.series,
            "compteurs": len(plan.points), "mesures": len(plan.mesures), "references": len(plan.references),
            "anomalies_par_type": dict(Counter(a["type"] for a in plan.anomalies).most_common()),
            "anomalies": plan.anomalies}


def appliquer(cx, plan, dossier_sortie=None):
    """Écrit les compteurs de courbe, leurs mesures, les références et la trace des anomalies."""
    lot = "courbes-" + uuid.uuid4().hex[:8]
    for p in plan.points:
        parc.enregistrer_point(cx, p)
        # la même série rechargée depuis un autre fichier : son ancienne trace d'anomalies est remplacée
        cx.execute("DELETE FROM anomalie_import WHERE lot LIKE 'courbes-%' AND objet = ?", (p["id"],))
    cx.executemany("INSERT OR REPLACE INTO mesure VALUES (?,?,?,?,?)", [(*m, lot) for m in plan.mesures])
    cx.executemany("INSERT OR REPLACE INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                   plan.references)
    patrimoine.enregistrer_anomalies(cx, lot, plan.fichier, plan.anomalies)
    cx.commit()
    r = rapport(plan, True, lot)
    if dossier_sortie:
        r["fichier_anomalies"] = patrimoine.exporter_anomalies(cx, dossier_sortie)
    return r


def importer(cx, contenu, fichier, appliquer_=False, dossier_sortie=None):
    """Aperçu ou import d'un fichier de courbes (.csv ou classeur .xlsx de mêmes colonnes), ou du calendrier d'un
    classeur du lot (.xlsx avec une feuille « Calendrier » : seule cette feuille est lue)."""
    if contenu[:2] == b"PK":
        calendrier = excel.lire_xlsx(contenu, seulement=lambda nom: parc._cle(nom).startswith("calendrier"))
        plan = (preparer_calendrier(contenu, fichier) if calendrier
                else preparer_lignes(cx, *lire_classeur(contenu, fichier), fichier))
    else:
        plan = preparer(cx, contenu.decode("utf-8-sig", errors="replace"), fichier)
    return appliquer(cx, plan, dossier_sortie) if appliquer_ else rapport(plan)
