"""Solaire : défaut de l'onduleur = production à zéro entre deux relevés producteurs, du lever au coucher du soleil."""
import unittest

import numpy as np
import pandas as pd
import commun  # noqa: F401  (chemin du projet)

from vigie import moteur, solaire

FIN = pd.Timestamp("2025-06-11")
POINT = {"puissance_crete_kwc": 100}
REGLE = moteur.regles_effectives({})["solaire_onduleur"]


def rayonnement(jours=10):
    """Rayonnement horaire de la station (W/m², fin d'intervalle UTC) : jour de 4 h à 19 h UTC, nuit à zéro."""
    index = pd.date_range(end=FIN, periods=jours * 24, freq="h")
    return pd.Series([max(0.0, 800 * np.sin((t.hour - 4) / 15 * np.pi)) if 4 < t.hour <= 19 else 0.0 for t in index],
                     index=index)


def production(jours=10, pas="15min"):
    """Production au quart d'heure (kWh), proportionnelle au rayonnement de l'heure, nulle la nuit."""
    ray = rayonnement(jours)
    index = pd.date_range(end=FIN, periods=jours * 24 * (4 if pas == "15min" else 1), freq=pas)
    return pd.Series(ray.reindex(index.ceil("h")).to_numpy() / 800 * (20.0 if pas == "15min" else 80.0), index=index)


class TestCoupures(unittest.TestCase):
    def test_zero_entre_deux_releves_producteurs_de_jour(self):
        s = production()
        s[pd.Timestamp("2025-06-09 10:15"):pd.Timestamp("2025-06-09 10:45")] = 0.0   # 3 quarts d'heure à zéro
        c = solaire.coupures(s, rayonnement())
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["de"], c[0]["a"], c[0]["pas"]),
                         (pd.Timestamp("2025-06-09 10:15"), pd.Timestamp("2025-06-09 10:45"), 3))
        self.assertGreater(c[0]["kwh"], 0)   # estimation : moyenne des deux relevés qui encadrent × 3

    def test_nuit_aube_et_arret_complet_ne_sont_pas_des_coupures(self):
        ray = rayonnement()
        self.assertEqual(solaire.coupures(production(), ray), [])            # zéro la nuit : normal
        s = production()
        s[pd.Timestamp("2025-06-09 00:15"):pd.Timestamp("2025-06-09 23:45")] = 0.0   # journée entière à l'arrêt
        self.assertEqual(solaire.coupures(s, ray), [])                       # aucun relevé producteur ce jour : règle « arrêt »
        s = production()
        s[pd.Timestamp("2025-06-09 04:15"):pd.Timestamp("2025-06-09 06:00")] = 0.0   # démarrage tardif le matin
        self.assertEqual(solaire.coupures(s, ray), [])                       # pas de relevé producteur AVANT : pas « entre deux »


class TestDetecteur(unittest.TestCase):
    def test_defaut_declare_des_la_premiere_coupure(self):
        s = production()
        s[pd.Timestamp("2025-06-09 10:15"):pd.Timestamp("2025-06-09 10:45")] = 0.0
        r = solaire.det_onduleur(s, rayonnement(), FIN, POINT, REGLE["seuil"], REGLE["persistance"])
        self.assertEqual((r["persistance"], r["debut"]), (1, "2025-06-09"))
        self.assertIn("1 coupure", r["mesure"])
        self.assertIn("45 minutes", r["mesure"])
        self.assertIn("09.06.2025 de 12:00 à 12:45", r["detail"])            # heure de Genève (UTC + 2 en été)
        self.assertGreater(r["kwh_mesure"], 0)

    def test_sans_coupure_ou_coupure_trop_ancienne_pas_d_alerte(self):
        self.assertIsNone(solaire.det_onduleur(production(), rayonnement(), FIN, POINT, 1, 1))
        s = production(20)
        s[pd.Timestamp("2025-05-25 10:15"):pd.Timestamp("2025-05-25 10:45")] = 0.0   # il y a plus de 7 jours
        self.assertIsNone(solaire.det_onduleur(s, rayonnement(20), FIN, POINT, 1, 1))

    def test_reglages_duree_minimale_et_nombre_de_jours(self):
        s = production()
        s[pd.Timestamp("2025-06-09 10:15")] = 0.0                                    # un seul quart d'heure
        self.assertIsNotNone(solaire.det_onduleur(s, rayonnement(), FIN, POINT, 1, 1))
        self.assertIsNone(solaire.det_onduleur(s, rayonnement(), FIN, POINT, 2, 1))  # au moins 2 relevés à zéro
        self.assertIsNone(solaire.det_onduleur(s, rayonnement(), FIN, POINT, 1, 2))  # au moins 2 jours avec coupure

    def test_releves_horaires(self):
        s = production(pas="h")
        s[pd.Timestamp("2025-06-10 11:00")] = 0.0
        r = solaire.det_onduleur(s, rayonnement(), FIN, POINT, 1, 1)
        self.assertIn("60 minutes", r["mesure"])


if __name__ == "__main__":
    unittest.main()
