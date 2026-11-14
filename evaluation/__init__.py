"""Campagne d'évaluation des détecteurs de dérives Vigie (scripts reproductibles, bases SQLite temporaires).

  python -m evaluation.campagne            campagne complète (résultats bruts et figures dans evaluation/sorties/)
  python -m evaluation.campagne --rapide   même campagne avec moins de graines (contrôle rapide)
  python -m evaluation.figures             figures à partir des résultats bruts
  python -m evaluation.pdf                 document PDF (docs/Vigie_methodes_et_evaluation_derives.pdf)

Toutes les consommations sont SIMULÉES ; la température réelle est la série MétéoSuisse de Genève-Cointrin,
téléchargée une fois puis figée dans evaluation/sorties/cache_meteo/ (reproductibilité).
"""
