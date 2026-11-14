"""Chiffrage sans annualisation du chauffage et de la PAC, priorisation par rythme mensuel, pas horaire et journalier."""
import unittest
from datetime import timedelta

from commun import base_exemple

from evaluation import simulateur as S
from vigie import db, moteur, service


def analyser_simulation(sc, graine=1):
    res, _ = S.executer(sc, graine, "fictive", (0,), service.defauts())
    return {a["cause"]: a for a in res[0]["alertes"]}


def scenario(type_, derive, amplitude, **extra):
    return {"type": type_, "derive": derive, "amplitude": amplitude, "age_j": 14, **extra}


class TestChiffrage(unittest.TestCase):
    def test_chauffage_chiffre_ce_qui_est_mesure_sans_annee_extrapolee(self):
        a = analyser_simulation(scenario("chaufferie", "signature", 0.20))["chaleur_signature"]
        self.assertEqual(a["chiffrage"], "mesure")
        self.assertIsNone(a["chf_an"])
        self.assertIsNone(a["kwh_an"])
        self.assertGreater(a["kwh_mesure"], 0)
        self.assertIn("depuis le", a["periode"])
        # excès réel cumulé de la simulation (avec − sans dérive, mêmes tirages) depuis le début réel de la dérive
        h, fin = S.verite_horaire(scenario("chaufferie", "signature", 0.20), 1, "fictive", "SIM_CHAL")
        vrai = h[h.index > fin - timedelta(days=14)].sum()
        self.assertLess(abs(a["kwh_mesure"] / vrai - 1), 0.10)

    def test_pac_chiffree_par_l_exces_mesure(self):
        a = analyser_simulation(scenario("pac", "pac", 0.25, comptage="totale"))["pac_cop"]
        self.assertEqual((a["chiffrage"], a["chf_an"]), ("mesure", None))
        self.assertGreater(a["chf_mesure"], 0)
        self.assertGreater(a["chf_mois"], 0)

    def test_eau_reste_chiffree_par_an_et_par_mois(self):
        a = analyser_simulation(scenario("chaufferie", "fuite", 60))["eau_nuit"]
        self.assertEqual(a["chiffrage"], "annuel")
        self.assertAlmostEqual(a["m3_an"], 60 * 24 * 365 / 1000, delta=0.5)
        self.assertAlmostEqual(a["m3_mois"], 60 * 24 * 30 / 1000, delta=0.1)
        # dérive constatée : débit de fuite constaté la nuit × heures mesurées depuis le début (≈ 14 jours × 24 h)
        self.assertAlmostEqual(a["m3_mesure"], 60 * a["heures_mesurees"] / 1000, delta=0.2)
        self.assertEqual(a["chf_proj"], a["chf_an"])  # projection d'une dérive constante = 12 mois

    def test_score_par_rythme_mensuel_comparable_entre_fluides(self):
        cx = base_exemple("score")
        for a in moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]:
            if a["gravite"] == "Données":
                continue
            attendu = a["chf_mois"] * a["confiance"] * moteur.URGENCE[a["gravite"]] * (1.5 if a["sinistre"] else 1)
            self.assertAlmostEqual(a["score"], attendu, delta=0.1)

    def test_ancien_enjeu_annuel_converti_au_prorata(self):
        self.assertAlmostEqual(moteur.seuil_enjeu_mois({"enjeu_min_chf_an": 365}), 30.0)
        self.assertEqual(moteur.seuil_enjeu_mois({"enjeu_min_chf_mois": 5, "enjeu_min_chf_an": 365}), 5.0)


class TestPasEtReference(unittest.TestCase):
    def test_pas_journalier_garde_les_regles_journalieres_seulement(self):
        vide = analyser_simulation(scenario("vide", "eau_vide", 200, pas=1440))
        self.assertIn("eau_vide", vide)
        fuite = analyser_simulation(scenario("chaufferie", "fuite", 60, pas=1440))
        self.assertNotIn("eau_nuit", fuite)  # fuite de nuit invisible au pas journalier
        self.assertEqual([c for c, a in fuite.items() if a["gravite"] == "Données"], [])  # pas de faux « muet »

    def test_signature_au_pas_journalier(self):
        a = analyser_simulation(scenario("chaufferie", "signature", 0.20, pas=1440))
        self.assertIn("chaleur_signature", a)

    def test_reference_meme_saison_avec_un_an_sinon_repli(self):
        un_an = analyser_simulation(scenario("chaufferie", "signature", 0.20))["chaleur_signature"]
        court = analyser_simulation(scenario("chaufferie", "signature", 0.20, jours=240))["chaleur_signature"]
        self.assertEqual((un_an["reference"], court["reference"]), ("saison", "antérieure"))
        self.assertIn(court["mesure"], ("+19 %", "+20 %", "+21 %"))  # dérive réelle de +20 %, lue sans biais
        # 120 jours (été puis entrée en saison de chauffe) : aucun jour de référence aussi froid, donc aucune
        # conclusion, plutôt qu'une alerte tirée de jours comparés à des jours plus doux
        self.assertNotIn("chaleur_signature", analyser_simulation(scenario("chaufferie", "signature", 0.20, jours=120)))


if __name__ == "__main__":
    unittest.main()
