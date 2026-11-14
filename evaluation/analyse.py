"""Métriques de la campagne à partir des résultats bruts (JSONL) : evaluation/sorties/<etiquette>/resume.json + CSV.

  python -m evaluation.analyse [--etiquette=horaire]
"""
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

from .campagne import AGE_DELAI, AMPLITUDES, CAUSE, DETECTEURS, SORTIES, UNITE_AMPLITUDE


def lire(dossier, exp):
    chemin = os.path.join(dossier, f"brut_{exp}.jsonl")
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - m), 3), round(min(1.0, c + m), 3))


def quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    q = lambda p: xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]  # noqa: E731
    return {"n": len(xs), "min": xs[0], "q1": q(0.25), "mediane": q(0.5), "q3": q(0.75), "max": xs[-1],
            "moyenne": sum(xs) / len(xs)}


def seuil_effectif(points, niveau):
    """Plus petite amplitude où P(détection) atteint `niveau` (interpolation linéaire entre deux amplitudes)."""
    pts = sorted(points)
    for i, (a, p) in enumerate(pts):
        if p >= niveau:
            if i == 0:
                return a
            a0, p0 = pts[i - 1]
            return a0 + (a - a0) * (niveau - p0) / (p - p0) if p != p0 else a
    return None


def erreur_chiffrage(r, alerte, cause):
    """Écart relatif au réel du chiffrage d'une alerte (estimé / réel − 1).

    Moteur actuel, chauffage et PAC (« mesure ») : excès mesuré depuis le début de la dérive ÷ excès réel cumulé depuis
    son début réel. Moteur actuel, eau et électricité (« annuel ») et moteur V0.2.0 : excès par jour de l'alerte
    (montant annuel ÷ 365, ou ÷ 210 jours de saison de chauffe en V0.2.0) ÷ excès réel moyen par jour."""
    if not alerte:
        return None
    eau = cause.startswith("eau")
    if alerte.get("chiffrage") == "mesure":
        return alerte["kwh_mesure"] / r["verite_cumul"] - 1 if r.get("verite_cumul") else None
    if not r.get("verite_j"):
        return None
    v = alerte["m3_an"] if eau else alerte["kwh_an"]
    if v is None:
        return None
    jours = 365 if alerte.get("chiffrage") == "annuel" or cause in ("eau_nuit", "eau_vide", "elec_nuit") else 210
    return v / jours / r["verite_j"] - 1


def balayage(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["det"], r["meteo"])].append(r)
    for (det, met), rs in groupes.items():
        cause = CAUSE[det]
        par_a = defaultdict(list)
        for r in rs:
            par_a[r["amplitude"]].append(r)
        courbe, erreurs_tout = [], []
        for a in AMPLITUDES[det]:
            g = par_a.get(a, [])
            k = sum(r["coupes"][0]["detectee"] for r in g)
            autres = Counter(i for r in g for i in r["coupes"][0]["autres"])
            errs, conf, verites = [], [], []
            for r in g:
                al = r["coupes"][0]["alerte"]
                if al:
                    conf.append(al["confiance"])
                    e = erreur_chiffrage(r, al, cause)
                    if e is not None:
                        errs.append(e)
                        verites.append(r.get("verite_j"))
            erreurs_tout += errs
            courbe.append({"amplitude": a, "n": len(g), "detectees": k, "p": k / len(g) if g else None,
                           "ic95": wilson(k, len(g)), "autres_alertes": dict(autres),
                           "confiance_moy": sum(conf) / len(conf) if conf else None,
                           "erreur_chiffrage": quantiles(errs),
                           "verite_j_moy": sum(verites) / len(verites) if verites and None not in verites else None})
        pts = [(c["amplitude"], c["p"]) for c in courbe if c["p"] is not None]
        sains = next((c for c in courbe if c["amplitude"] == AMPLITUDES[det][0]), None)
        out[f"{det}|{met}"] = {"det": det, "meteo": met, "unite": UNITE_AMPLITUDE[det], "courbe": courbe,
                               "seuil50": seuil_effectif(pts, 0.5), "seuil90": seuil_effectif(pts, 0.9),
                               "erreur_chiffrage": quantiles(erreurs_tout),
                               "fausses_sur_sains": sains["detectees"] if sains else None}
    return out


def delai(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["det"], r["meteo"])].append(r)
    for (det, met), rs in groupes.items():
        delais, pertes, profils = [], [], defaultdict(list)
        for r in rs:
            ages = sorted(((AGE_DELAI - c["coupe_h"] / 24, c["detectee"]) for c in r["coupes"]))
            for age, d in ages:
                profils[age].append(d)
            premier = next((age for age, d in ages if d), None)
            delais.append(premier)
            if premier is not None:
                perdu = next((age for age, d in ages if age > premier and not d), None)
                pertes.append(perdu)
        out[f"{det}|{met}"] = {
            "det": det, "meteo": met, "n": len(rs), "delai_j": quantiles([d for d in delais if d is not None]),
            "jamais": sum(d is None for d in delais),
            "perte_j": quantiles([p for p in pertes if p is not None]), "n_perte": sum(p is not None for p in pertes),
            "profil": [{"age_j": a, "p": sum(v) / len(v)} for a, v in sorted(profils.items())]}
    return out


def type_sain(det):
    """Type d'immeuble sain : chaufferie, vide, pac_<comptage>, éventuellement suffixé du chauffage (cad, gaz)."""
    from .campagne import CHAUFFAGE
    typ, _, comptage, point = DETECTEURS[det]
    return typ + (f"_{comptage}" if comptage else "") + (f"_{CHAUFFAGE[point]}" if point in CHAUFFAGE else "")


def delai_sain(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(type_sain(r["det"]), r["meteo"])].append(r)
    for (typ, met), rs in groupes.items():
        jours = sum(len(r["coupes"]) for r in rs)
        fa = Counter(a["cause"] for r in rs for c in r["coupes"] for a in c["toutes"])
        jours_avec = sum(1 for r in rs for c in r["coupes"] if c["toutes"])
        out[f"{typ}|{met}"] = {"type": typ, "meteo": met, "immeubles_jours": jours, "jours_avec_alerte": jours_avec,
                               "taux": jours_avec / jours if jours else None, "ic95": wilson(jours_avec, jours),
                               "par_cause": dict(fa)}
    return out


def generateur(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        groupes[(r["taille"], r["meteo"])].append(r)
    for (taille, met), rs in groupes.items():
        ok = [r for r in rs if r["ok"]]
        fa = Counter(i for r in ok for i in r["fausses"])
        fn = Counter(i for r in ok for i in r["manquees"])
        immeubles = 5 if taille == "standard" else 21
        sains = immeubles - (4 if taille == "standard" else 7)  # immeubles sans dérive injectée
        out[f"{taille}|{met}"] = {
            "taille": taille, "meteo": met, "graines": len(ok), "erreurs": len(rs) - len(ok),
            "meteo_effective": Counter(r["meteo_effective"] for r in ok),
            "fausses_total": sum(fa.values()), "manquees_total": sum(fn.values()), "fausses": dict(fa),
            "manquees": dict(fn), "attendues_par_graine": ok[0]["n_attendues"] if ok else None,
            "precision": (sum(r["n_attendues"] - len(r["manquees"]) for r in ok) /
                          max(1, sum(r["n_alertes"] for r in ok))) if ok else None,
            "rappel": (sum(r["n_attendues"] - len(r["manquees"]) for r in ok) /
                       max(1, sum(r["n_attendues"] for r in ok))) if ok else None,
            "immeubles_sains": sains, "runs_sans_fausse": sum(not r["fausses"] for r in ok)}
    return out


def sain(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["det"], r["meteo"])].append(r)
    for (det, met), rs in groupes.items():
        k = sum(bool(r["coupes"][0]["toutes"]) for r in rs)
        out[f"{det}|{met}"] = {"type": DETECTEURS[det][0], "comptage": DETECTEURS[det][2], "meteo": met, "n": len(rs),
                               "avec_alerte": k, "ic95": wilson(k, len(rs)),
                               "par_cause": dict(Counter(a["cause"] for r in rs for a in r["coupes"][0]["toutes"]))}
    return out


def robustesse(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["variante"], r["det"], r["amplitude"] == 0)].append(r)
    for (var, det, est_sain), rs in groupes.items():
        cause = CAUSE[det]
        if est_sain:
            k = sum(bool(r["coupes"][0]["toutes"]) for r in rs)
            causes = Counter(a["cause"] for r in rs for a in r["coupes"][0]["toutes"])
            out[f"{var}|{det}|sain"] = {"variante": var, "det": det, "sain": True, "n": len(rs), "avec_alerte": k,
                                        "par_cause": dict(causes)}
        else:
            k = sum(r["coupes"][0]["detectee"] for r in rs)
            errs = [e for r in rs if (e := erreur_chiffrage(r, r["coupes"][0]["alerte"], cause)) is not None]
            autres = Counter(a["cause"] for r in rs for a in r["coupes"][0]["toutes"] if a["cause"] != cause)
            out[f"{var}|{det}|derive"] = {"variante": var, "det": det, "sain": False, "n": len(rs), "detectees": k,
                                          "erreur_chiffrage": quantiles(errs), "autres": dict(autres)}
    return out


def qualite(lignes):
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["defaut"], r["niveau"])].append(r)
    for (defaut, niveau), rs in sorted(groupes.items()):
        pid = rs[0]["point"]
        cause = CAUSE[rs[0]["det"]]
        k_donnees = sum(any(a["id"] == f"SIM-donnees-{pid}" for a in r["coupes"][0]["toutes"]) for r in rs)
        k_energie = sum(r["coupes"][0]["detectee"] for r in rs)
        bloquee = sum(any(a["id"] == f"SIM-donnees-{pid}" for a in r["coupes"][0]["toutes"])
                      and r["coupes"][0]["detectee"] for r in rs)
        out[f"{defaut}|{niveau}"] = {"defaut": defaut, "niveau": niveau, "point": pid, "cause": cause, "n": len(rs),
                                     "alerte_donnees": k_donnees, "alerte_energie": k_energie,
                                     "energie_malgre_donnees": bloquee,
                                     "causes_donnees": dict(Counter(a["cause"] for r in rs for a in r["coupes"][0]["toutes"]
                                                                    if a["gravite"] == "Données"))}
    return out


def pas(lignes):
    """Même dérive relevée au pas horaire et au pas journalier : détection, fausses alertes, justesse du chiffrage."""
    out = {}
    groupes = defaultdict(list)
    for r in lignes:
        if r["ok"]:
            groupes[(r["det"], r["meteo"], r["pas"], r["amplitude"])].append(r)
    for (det, met, p, a), rs in sorted(groupes.items()):
        cause = CAUSE[det]
        k = sum(r["coupes"][0]["detectee"] for r in rs)
        autres = Counter(i for r in rs for i in r["coupes"][0]["autres"] if "-donnees-" not in i)
        donnees = Counter(i for r in rs for i in r["coupes"][0]["autres"] if "-donnees-" in i)
        errs = [e for r in rs if (e := erreur_chiffrage(r, r["coupes"][0]["alerte"], cause)) is not None]
        out[f"{det}|{met}|{p}|{a}"] = {"det": det, "meteo": met, "pas": p, "amplitude": a, "sain": a == 0,
                                       "n": len(rs), "detectees": k, "ic95": wilson(k, len(rs)),
                                       "autres_alertes": dict(autres), "alertes_donnees": dict(donnees),
                                       "erreur_chiffrage": quantiles(errs)}
    return out


def chiffrage(lignes):
    if not lignes:
        return {}
    from . import chiffrage as C
    return C.resume(lignes, C.verite_annuelle_unitaire())


EXPERIENCES = ("balayage", "delai", "delai_sain", "generateur", "sain", "robustesse", "qualite", "pas", "chiffrage")


def main(argv):
    etiquette = next((a.split("=", 1)[1] for a in argv if a.startswith("--etiquette=")), "horaire")
    dossier = os.path.join(SORTIES, etiquette)
    res = {"balayage": balayage(lire(dossier, "balayage")), "delai": delai(lire(dossier, "delai")),
           "delai_sain": delai_sain(lire(dossier, "delai_sain")), "generateur": generateur(lire(dossier, "generateur")),
           "sain": sain(lire(dossier, "sain")), "robustesse": robustesse(lire(dossier, "robustesse")),
           "qualite": qualite(lire(dossier, "qualite")), "pas": pas(lire(dossier, "pas")),
           "chiffrage": chiffrage(lire(dossier, "chiffrage"))}
    erreurs = sum(1 for exp in EXPERIENCES for r in lire(dossier, exp) if not r["ok"])
    res["erreurs_execution"] = erreurs
    with open(os.path.join(dossier, "resume.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    # tableau de synthèse par détecteur (CSV, séparateur ;)
    with open(os.path.join(dossier, "synthese_detecteurs.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["detecteur", "meteo", "unite", "seuil_50", "seuil_90", "delai_median_j", "perte_alerte_mediane_j",
                    "erreur_chiffrage_mediane", "erreur_q1", "erreur_q3"])
        for k, b in sorted(res["balayage"].items()):
            d = res["delai"].get(k, {})
            e = b["erreur_chiffrage"] or {}
            w.writerow([b["det"], b["meteo"], b["unite"], b["seuil50"], b["seuil90"],
                        (d.get("delai_j") or {}).get("mediane"), (d.get("perte_j") or {}).get("mediane"),
                        e.get("mediane"), e.get("q1"), e.get("q3")])
    print(f"Résumé écrit : {dossier}/resume.json ({erreurs} erreurs d'exécution)")
    return res


if __name__ == "__main__":
    main(sys.argv)
