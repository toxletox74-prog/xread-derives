"""Validation de livraison (CLAUDE.md §10) : 4 évaluations officielles + tests unitaires, consignées en JSON.

  python -m evaluation.validation   ->  evaluation/sorties/validation.json

Les évaluations « --meteo-reelle » téléchargent la série MétéoSuisse du jour (comportement de `python -m vigie evaluer`).
"""
import json
import os
import re
import subprocess
import sys
import time

from .campagne import SORTIES

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALUATIONS = [[], ["--meteo-reelle"], ["--grand"], ["--grand", "--meteo-reelle"]]


def _executer(args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    debut = time.time()
    p = subprocess.run([sys.executable, *args], cwd=RACINE, capture_output=True, text=True, encoding="utf-8", env=env)
    return p.returncode, p.stdout + p.stderr, round(time.time() - debut)


def main():
    res = {"evaluations": [], "tests": None}
    for opts in EVALUATIONS:
        code, sortie, duree = _executer(["-m", "vigie", "evaluer", *opts])
        prec = re.search(r"Précision.*?:\s*(\d+)\s*%", sortie)
        rapp = re.search(r"Rappel.*?:\s*(\d+)\s*%", sortie)
        ligne = next((x for x in sortie.splitlines() if x.startswith("Exemple")), "")
        res["evaluations"].append({"commande": " ".join(["python -m vigie evaluer", *opts]).strip(), "code": code,
                                   "precision": int(prec.group(1)) if prec else None,
                                   "rappel": int(rapp.group(1)) if rapp else None, "resume": ligne,
                                   "fausses": [x.strip() for x in sortie.splitlines() if "fausse alerte" in x],
                                   "manquees": [x.strip() for x in sortie.splitlines() if "dérive manquée" in x],
                                   "duree_s": duree})
        print(res["evaluations"][-1]["commande"], "->", res["evaluations"][-1]["precision"], res["evaluations"][-1]["rappel"])
    code, sortie, duree = _executer(["-m", "unittest", "discover", "-s", "tests"])
    n = re.search(r"Ran (\d+) tests", sortie)
    res["tests"] = {"code": code, "tests": int(n.group(1)) if n else None, "ok": code == 0 and "\nOK" in sortie,
                    "duree_s": duree, "fin": sortie.strip().splitlines()[-1] if sortie.strip() else ""}
    print("tests :", res["tests"])
    with open(os.path.join(SORTIES, "validation.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
