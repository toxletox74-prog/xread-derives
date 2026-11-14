"""Temps de génération, d'import et d'analyse de l'exemple officiel (12 mois de relevés horaires, météo fictive).

  python -m evaluation.temps   ->  evaluation/sorties/temps_exemple.json

Base SQLite temporaire et service.SORTIE sur un dossier temporaire (rien n'est écrit dans le projet hors sorties
d'évaluation).
"""
import json
import os
import shutil
import tempfile
import time

from vigie import db, generer_demo, moteur, service

from .campagne import SORTIES


def mesurer(taille):
    dossier = tempfile.mkdtemp(prefix="vigie-temps-")
    ancien, service.SORTIE = service.SORTIE, dossier
    try:
        sup = service.exemple_grand()["immeubles"] if taille == "grand" else None
        t0 = time.perf_counter()
        n = generer_demo.generer(os.path.join(dossier, "gen.csv"), 42, supplementaires=sup)
        generation = time.perf_counter() - t0
        cx = db.connecter(os.path.join(dossier, "temps.db"))
        t0 = time.perf_counter()
        info = service.charger_exemple(cx, taille=taille)  # génération + import CSV
        import_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        analyse = time.perf_counter() - t0
        cx.close()
    finally:
        service.SORTIE = ancien
        shutil.rmtree(dossier, ignore_errors=True)
    return {"mesures": n, "importees": info["importees"], "generation_s": round(generation, 1),
            "import_s": round(import_s, 1), "analyse_s": round(analyse, 1), "alertes": len(alertes)}


def main():
    res = {f"exemple {t}": mesurer(t) for t in ("standard", "grand")}
    with open(os.path.join(SORTIES, "temps_exemple.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(res)


if __name__ == "__main__":
    main()
