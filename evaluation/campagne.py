"""Campagne d'évaluation des détecteurs Vigie, par fluide et par détecteur.

  python -m evaluation.campagne [--etiquette=horaire] [--moteur=actuel|reference] [--rapide] [--seulement=balayage,delai]

Expériences (résultats bruts JSONL dans evaluation/sorties/<etiquette>/) :
  balayage    probabilité de détection selon l'ampleur de la dérive + justesse du chiffrage + confiance
  delai       délai de détection (fin d'analyse avancée jour par jour) et maintien de l'alerte ; immeubles sains
              analysés chaque jour (fausses alertes par immeuble-jour)
  generateur  fausses alertes et dérives manquées sur l'exemple officiel (generer_demo), standard et grand,
              météo fictive et réelle, ≥ 20 graines
  sain        immeubles sains simulés (≥ 20 graines), météo fictive et réelle
  robustesse  lacunes, bruit, chasses d'eau, occupation qui change, historique court, vague de froid
  qualite     compteur muet, complétude, index qui recule, valeurs négatives (et blocage des alertes énergie)
  pas         même dérive relevée au pas horaire et au pas journalier : ce qu'on perd avec un pas plus grossier
  chiffrage   justesse des montants selon le mois de détection (voir evaluation/chiffrage.py)

Données simulées : 12 mois d'historique, relevés HORAIRES (aucune donnée n'arrive plus finement que l'heure).
Toutes les bases sont des bases SQLite TEMPORAIRES (en mémoire) ; service.SORTIE pointe sur un dossier temporaire.
"""
import json
import os
import sys
import tempfile
import time
from multiprocessing import Pool

ICI = os.path.dirname(os.path.abspath(__file__))
SORTIES = os.path.join(ICI, "sorties")

# ---------------------------------------------------------------- définition des expériences

DETECTEURS = {  # cause -> (type d'immeuble, dérive simulée, comptage PAC, point visé)
    "eau_nuit": ("chaufferie", "fuite", None, "SIM_EAU"),
    "eau_vide": ("vide", "eau_vide", None, "SIM_EAU"),
    "chaleur_signature": ("chaufferie", "signature", None, "SIM_CHAL"),
    "chaleur_vide": ("vide", "chaleur_vide", None, "SIM_CHAL"),
    "elec_nuit": ("chaufferie", "elec_nuit", None, "SIM_ELEC"),
    "pac_totale": ("pac", "pac", "totale", "SIM_PAC_ELEC"),
    "pac_chauffage": ("pac", "pac", "chauffage", "SIM_PAC_ELEC"),
    "pac_ecs": ("pac", "pac", "ecs", "SIM_PAC_ELEC"),
    "pac_aucune": ("pac", "pac", "aucune", "SIM_PAC_ELEC"),
    "cad_signature": ("chaufferie", "signature", None, "SIM_CAD"),
    "cad_vide": ("vide", "chaleur_vide", None, "SIM_CAD"),
    "gaz_signature": ("chaufferie", "signature", None, "SIM_GAZ"),
    "gaz_vide": ("vide", "chaleur_vide", None, "SIM_GAZ"),
}
CHAUFFAGE = {"SIM_CAD": "cad", "SIM_GAZ": "gaz"}  # production de chaleur simulée (sinon chaufferie, compteur de chaleur)
CAUSE = {k: ("pac_cop" if k.startswith("pac") else k) for k in DETECTEURS}
SENSIBLES_METEO = {"chaleur_signature", "chaleur_vide", "pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune",
                   "cad_signature", "cad_vide", "gaz_signature", "gaz_vide"}
UNITE_AMPLITUDE = {"eau_nuit": "l/h", "eau_vide": "l/jour", "chaleur_signature": "% de chaleur en plus",
                   "chaleur_vide": "facteur de marche (hors-gel = 0,12)", "elec_nuit": "% de puissance de nuit en plus",
                   "pac_totale": "% de rendement en moins", "pac_chauffage": "% de rendement en moins",
                   "pac_ecs": "% de rendement en moins", "pac_aucune": "% de rendement en moins",
                   "cad_signature": "% de chaleur livrée en plus", "cad_vide": "facteur de marche (hors-gel = 0,12)",
                   "gaz_signature": "% de gaz en plus", "gaz_vide": "facteur de marche (hors-gel = 0,12)"}
AMPLITUDES = {
    "eau_nuit": [0, 5, 10, 15, 18, 20, 22, 25, 30, 40, 60, 100],
    "eau_vide": [0, 20, 30, 40, 50, 60, 70, 80, 100, 150, 200, 400],
    "chaleur_signature": [0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.17, 0.20, 0.30],
    "chaleur_vide": [0.12, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.70, 1.0],
    "elec_nuit": [0, 0.05, 0.10, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30, 0.40, 0.60],
    **{k: [0, 0.05, 0.10, 0.13, 0.15, 0.17, 0.20, 0.25, 0.30, 0.40]
       for k in ("pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune")},
}
AGE_BALAYAGE = {"eau_nuit": 7, "eau_vide": 7, "chaleur_vide": 7, "elec_nuit": 14, "chaleur_signature": 14,
                **{k: 14 for k in ("pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune")}}
NOMINALE = {"eau_nuit": 60, "eau_vide": 200, "chaleur_signature": 0.20, "chaleur_vide": 1.0, "elec_nuit": 0.40,
            **{k: 0.25 for k in ("pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune")}}
ROBUSTE = {"eau_nuit": 30, "eau_vide": 100, "chaleur_signature": 0.15, "chaleur_vide": 0.5, "elec_nuit": 0.30,
           **{k: 0.25 for k in ("pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune")}}
for _fl in ("cad", "gaz"):  # CAD et gaz : mêmes ampleurs que la chaleur (mêmes règles)
    for _d in (AMPLITUDES, AGE_BALAYAGE, NOMINALE, ROBUSTE):
        _d[f"{_fl}_signature"], _d[f"{_fl}_vide"] = _d["chaleur_signature"], _d["chaleur_vide"]
AGE_DELAI = 60  # jours entre le début de la dérive et la fin de la série ; la fin d'analyse recule jour par jour
VARIANTES = {
    "référence": {},
    "lacunes 2 %": {"defauts": [{"type": "lacunes", "point": "*", "taux": 0.02}, {"type": "lacunes", "point": "METEO", "taux": 0.02}]},
    "lacunes 5 %": {"defauts": [{"type": "lacunes", "point": "*", "taux": 0.05}, {"type": "lacunes", "point": "METEO", "taux": 0.05}]},
    "lacunes 10 %": {"defauts": [{"type": "lacunes", "point": "*", "taux": 0.10}, {"type": "lacunes", "point": "METEO", "taux": 0.10}]},
    "passerelle coupée 20 h-4 h (4 nuits)": {"defauts": [{"type": "bloc", "point": "*", "h1": 20, "h2": 4, "nuits": 4}]},
    "météo lacunaire 10 %": {"defauts": [{"type": "lacunes", "point": "METEO", "taux": 0.10}]},
    "bruit × 2": {"bruit": 2.0},
    "bruit × 3": {"bruit": 3.0},
    "chasses d'eau de nuit × 3": {"chasses": 3.0},
    "occupation 50 % → 90 % (J-10)": {"profil": "Partiel", "occ": 0.5, "occ_apres": 0.9, "occ_age_j": 10},
    "occupation 100 % → 60 % (J-10)": {"occ": 1.0, "occ_apres": 0.6, "occ_age_j": 10},
    "historique 45 j": {"jours": 45},
    "historique 60 j": {"jours": 60},
    "historique 90 j": {"jours": 90},
    "historique 180 j": {"jours": 180},
    "vague de froid −8 °C (10 j)": {"froid": (8.0, 10)},
}


# Immeubles sains simulés (un par type d'immeuble et de comptage)
SAINS = ("eau_nuit", "chaleur_vide", "pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune", "cad_signature", "cad_vide",
         "gaz_signature", "gaz_vide")


def scenario(det, amplitude, age_j, extra=None):
    typ, derive, comptage, _ = DETECTEURS[det]
    sc = {"type": typ, "derive": derive if amplitude is not None else None, "amplitude": amplitude or 0.0,
          "age_j": age_j}
    if comptage:
        sc["comptage"] = comptage
    if DETECTEURS[det][3] in CHAUFFAGE:
        sc["chauffage"] = CHAUFFAGE[DETECTEURS[det][3]]
    if det.endswith("_vide") and det != "eau_vide" and amplitude is not None and amplitude <= 0.12:
        sc["derive"] = None  # 0,12 = hors-gel normal : immeuble sain
    if amplitude == 0:
        sc["derive"] = None
    sc.update(extra or {})
    return sc


def taches(rapide=False, seulement=None):
    g = (lambda n: max(2, n // 4)) if rapide else (lambda n: n)
    t = []
    meteos = lambda det: ("fictive", "reelle") if det in SENSIBLES_METEO else ("fictive",)  # noqa: E731
    for det, amps in AMPLITUDES.items():
        for met in meteos(det):
            for a in amps:
                for s in range(g(12)):
                    t.append({"exp": "balayage", "det": det, "amplitude": a, "meteo": met, "graine": 1000 + s,
                              "sc": scenario(det, a, AGE_BALAYAGE[det]), "coupes": [0]})
    for det in DETECTEURS:
        for met in meteos(det):
            for s in range(g(10)):
                t.append({"exp": "delai", "det": det, "amplitude": NOMINALE[det], "meteo": met, "graine": 2000 + s,
                          "sc": scenario(det, NOMINALE[det], AGE_DELAI), "coupes": [24 * k for k in range(AGE_DELAI + 1)]})
    for typ_det in SAINS:
        for met in ("fictive", "reelle"):
            for s in range(g(6)):
                t.append({"exp": "delai_sain", "det": typ_det, "amplitude": 0, "meteo": met, "graine": 2500 + s,
                          "sc": scenario(typ_det, 0, AGE_DELAI), "coupes": [24 * k for k in range(AGE_DELAI + 1)]})
    for taille in ("standard", "grand"):
        for met in ("fictive", "reelle"):
            for s in range(g(20)):
                t.append({"exp": "generateur", "taille": taille, "meteo": met, "graine": 3000 + s})
    for det in SAINS:
        for met in ("fictive", "reelle"):
            for s in range(g(30)):
                t.append({"exp": "sain", "det": det, "amplitude": 0, "meteo": met, "graine": 4000 + s,
                          "sc": scenario(det, 0, 14), "coupes": [0]})
    for nom, extra in VARIANTES.items():
        for det in DETECTEURS:
            for s in range(g(10)):
                t.append({"exp": "robustesse", "variante": nom, "det": det, "amplitude": ROBUSTE[det], "meteo": "fictive",
                          "graine": 5000 + s, "sc": scenario(det, ROBUSTE[det], AGE_BALAYAGE[det], extra), "coupes": [0]})
        for det in SAINS:
            for s in range(g(10)):
                t.append({"exp": "robustesse", "variante": nom, "det": det, "amplitude": 0, "meteo": "fictive",
                          "graine": 5000 + s, "sc": scenario(det, 0, 14, extra), "coupes": [0]})
    qual = [("silence", "SIM_EAU", "eau_nuit", [0, 12, 20, 23, 25, 30, 48, 72]),
            ("completude", "SIM_ELEC", "elec_nuit", [0, 0.05, 0.08, 0.09, 0.11, 0.15, 0.30]),
            ("recul", "SIM_EAU", "eau_nuit", [0, 1, 2, 5]),
            ("negatifs", "SIM_ELEC", "elec_nuit", [0, 1, 2, 10])]
    for typ, point, det, niveaux in qual:
        for n in niveaux:
            d = {"silence": {"type": "silence", "heures": n}, "completude": {"type": "lacunes", "taux": n, "jours": 30},
                 "recul": {"type": "recul", "n": n}, "negatifs": {"type": "negatifs", "n": n}}[typ]
            for s in range(g(10)):
                t.append({"exp": "qualite", "defaut": typ, "niveau": n, "det": det, "point": point, "meteo": "fictive",
                          "graine": 6000 + s, "amplitude": NOMINALE[det],
                          "sc": scenario(det, NOMINALE[det], 10, {"defauts": [{**d, "point": point}] if n else []}),
                          "coupes": [0]})
    for det in DETECTEURS:  # pas de relevé : horaire (référence) et journalier
        for met in meteos(det):
            for pas in (60, 1440):
                for a in (0, ROBUSTE[det], NOMINALE[det]):
                    for s in range(g(10)):
                        t.append({"exp": "pas", "det": det, "amplitude": a, "meteo": met, "graine": 8000 + s,
                                  "pas": pas, "sc": scenario(det, a, AGE_BALAYAGE[det], {"pas": pas}), "coupes": [0]})
    from . import chiffrage, simulateur
    t += chiffrage.taches(scenario, DETECTEURS, NOMINALE, simulateur.FIN_FICTIVE, 2 if rapide else None)
    if seulement:
        t = [x for x in t if x["exp"] in seulement or (x["exp"] == "delai_sain" and "delai" in seulement)]
    return t


# ---------------------------------------------------------------- exécution (processus de travail)

_ETAT = {}


# Paramètres du référentiel V0.2.0 retirés depuis (plus d'annualisation, enjeu en CHF/mois) : fournis à la copie figée
PARAMETRES_V0_2_0 = {"enjeu_min_chf_an": 100, "jours_saison_chauffe": 210}


def _init(moteur_nom):
    sys.path.insert(0, os.path.dirname(ICI))
    import pandas as pd

    from vigie import moteur, service

    from . import meteo_gve, simulateur
    defauts = service.defauts()
    if moteur_nom == "reference":
        from .reference import moteur_v0_2_0 as ref
        simulateur.MOTEUR = ref
        _ETAT["moteur"] = ref
        defauts["parametres"] = {**PARAMETRES_V0_2_0, **defauts["parametres"]}
    else:
        _ETAT["moteur"] = moteur
    dossier = tempfile.mkdtemp(prefix="vigie-campagne-")
    service.SORTIE = dossier  # jamais le dossier sorties/ du projet
    longue = meteo_gve.serie_longue(3)  # 3 ans de température horaire GVE : 12 mois d'historique à toute fin d'analyse
    _ETAT.update(reelle=pd.Series(longue).sort_index(), reelle_dict=meteo_gve.serie_reelle(jours=400),
                 defauts=defauts, dossier=dossier)


def _verite(t):
    """Vérité de l'excès (simulation sans dérive, mêmes tirages, relevé horaire) : excès moyen par jour civil complet
    entre le début de la dérive et la fin d'analyse, et excès cumulé heure par heure depuis le début réel."""
    from datetime import timedelta

    import pandas as pd

    from . import chiffrage
    from . import simulateur as S
    cible = DETECTEURS[t["det"]][3]
    met = _ETAT["reelle"] if t["meteo"] == "reelle" else "fictive"
    h, fin = S.verite_horaire(t["sc"], t["graine"], met, cible)
    if t["exp"] == "chiffrage":
        return chiffrage.verites(h, fin)
    debut_derive = fin - timedelta(days=t["sc"]["age_j"])
    diff = h.resample("D").sum()
    debut = pd.Timestamp(debut_derive).normalize() + timedelta(days=1)
    jours = diff[(diff.index >= debut) & (diff.index < pd.Timestamp(fin).normalize())]
    return {"verite_j": float(jours.mean()) if len(jours) else None,
            "verite_cumul": float(h[h.index > debut_derive].sum())}


def _scenario(t):
    from . import simulateur as S
    met = _ETAT["reelle"] if t["meteo"] == "reelle" else "fictive"
    res, brut = S.executer(t["sc"], t["graine"], met, t["coupes"], _ETAT["defauts"],
                           suivi=t["exp"] in ("delai", "delai_sain"))
    cause = CAUSE[t["det"]]
    cible = f"SIM-{cause}"
    out = {k: v for k, v in t.items() if k not in ("sc", "coupes")}
    out["age_j"] = t["sc"].get("age_j")
    coupes = []
    for r in res:
        ids = [a["id"] for a in r["alertes"]]
        trouvee = next((a for a in r["alertes"] if a["id"] == cible), None)
        coupes.append({"coupe_h": r["coupe_h"], "fin": r["fin"], "detectee": trouvee is not None,
                       "autres": [i for i in ids if i != cible], "alerte": trouvee, "toutes": r["alertes"]})
    out["coupes"] = coupes
    if t["exp"] in ("balayage", "robustesse", "pas", "chiffrage") and coupes[0]["detectee"] and t["sc"].get("derive"):
        out.update(_verite(t))
    return out


def _generateur(t):
    from vigie import db, service
    from vigie.__main__ import ATTENDUES
    meteo = service.meteo
    reelle = _ETAT["reelle_dict"]
    origine = meteo.temperatures_reelles
    meteo.temperatures_reelles = lambda **kw: dict(reelle)  # série MétéoSuisse figée de la campagne
    try:
        cx = db.connecter(":memory:")
        info = service.charger_exemple(cx, graine=t["graine"], meteo_reelle=t["meteo"] == "reelle", taille=t["taille"])
        alertes, fin = _ETAT["moteur"].analyser(cx, db.referentiel(cx, _ETAT["defauts"]))
        cx.close()
    finally:
        meteo.temperatures_reelles = origine
    attendues = set(ATTENDUES) | (set(service.exemple_grand()["derives_attendues"]) if t["taille"] == "grand" else set())
    ids = {a["id"] for a in alertes}
    return {**t, "fin": str(fin), "meteo_effective": info["meteo"], "fausses": sorted(ids - attendues),
            "manquees": sorted(attendues - ids), "n_alertes": len(ids), "n_attendues": len(attendues),
            "alertes": [{k: a.get(k) for k in ("id", "cause", "chiffrage", "kwh_an", "m3_an", "chf_an", "chf_mois",
                                               "chf_mesure", "confiance", "persistance")} for a in alertes]}


def travailler(t):
    try:
        r = _generateur(t) if t["exp"] == "generateur" else _scenario(t)
        r["ok"] = True
    except Exception as e:  # une erreur est consignée, jamais masquée
        import traceback
        r = {**{k: v for k, v in t.items() if k not in ("sc", "coupes")}, "ok": False, "erreur": repr(e),
             "trace": traceback.format_exc()}
    return r


def _json(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def main(argv):
    etiquette = next((a.split("=", 1)[1] for a in argv if a.startswith("--etiquette=")), "horaire")
    moteur_nom = next((a.split("=", 1)[1] for a in argv if a.startswith("--moteur=")), "actuel")
    seulement = next((a.split("=", 1)[1].split(",") for a in argv if a.startswith("--seulement=")), None)
    rapide = "--rapide" in argv
    dossier = os.path.join(SORTIES, etiquette)
    os.makedirs(dossier, exist_ok=True)
    from . import meteo_gve
    meteo_gve.serie_longue(3)  # téléchargement unique (ou cache) avant de lancer les processus
    tout = taches(rapide, seulement)
    print(f"Campagne « {etiquette} » · moteur {moteur_nom} · {len(tout)} scénarios")
    debut = time.time()
    fichiers = {}
    try:
        with Pool(max(1, (os.cpu_count() or 2) - 1), initializer=_init, initargs=(moteur_nom,)) as pool:
            for i, r in enumerate(pool.imap_unordered(travailler, sorted(tout, key=lambda x: x["exp"] != "generateur"),
                                                      chunksize=1), 1):
                exp = r["exp"]
                if exp not in fichiers:
                    fichiers[exp] = open(os.path.join(dossier, f"brut_{exp}.jsonl"), "w", encoding="utf-8")
                fichiers[exp].write(json.dumps(r, ensure_ascii=False, default=_json) + "\n")
                if not r["ok"]:
                    print("  ERREUR", r["exp"], r.get("det"), r["erreur"])
                if i % 200 == 0:
                    print(f"  {i}/{len(tout)} · {time.time() - debut:.0f} s")
    finally:
        for f in fichiers.values():
            f.close()
    nom_bilan = "campagne.json" if not seulement else f"campagne_{'_'.join(seulement)}.json"
    with open(os.path.join(dossier, nom_bilan), "w", encoding="utf-8") as f:
        json.dump({"etiquette": etiquette, "moteur": moteur_nom, "rapide": rapide, "seulement": seulement,
                   "scenarios": len(tout),
                   "duree_s": round(time.time() - debut), "meteo_reelle": meteo_gve.maintenant().isoformat()},
                  f, ensure_ascii=False, indent=1)
    print(f"Terminé en {time.time() - debut:.0f} s -> {dossier}")


if __name__ == "__main__":
    main(sys.argv)
