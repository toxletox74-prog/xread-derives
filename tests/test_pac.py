"""Détecteur PAC selon le comptage disponible : chaleur totale, chauffage seul, eau chaude seule, électricité seule."""
import os
import unittest

from commun import DOSSIER, base_vide

from vigie import db, generer_demo, moteur, service

FLUIDE = {"chauffage": "pac_chaleur_chauffage", "ecs": "pac_chaleur_ecs"}


def analyser_comptage(mesure, sans=()):
    """Base d'exemple (météo fictive) où la PAC de T8 n'a que le comptage `mesure`."""
    nom = f"pac-{mesure}-{'-'.join(sans) or 'derive'}"
    csv = os.path.join(DOSSIER, nom + ".csv")
    generer_demo.generer(csv, 42, sans=sans, pac_mesure=mesure)
    cx = base_vide(nom)
    db.charger_referentiel(cx, service.defauts())
    if mesure != "totale":
        cx.execute("DELETE FROM point_mesure WHERE id = 'T8_PAC_CHAL'")
        if mesure in FLUIDE:
            cx.execute("INSERT INTO point_mesure (id, immeuble_id, fluide, libelle, unite, nature, pas_min, source, etat) "
                       "VALUES (?, 'T8', ?, 'PAC chaleur partielle', 'kWh', 'intervalle', 60, 'test', 'actif')",
                       (generer_demo.COMPTAGES_PAC[mesure], FLUIDE[mesure]))
        cx.commit()
    _, rejets, _ = db.importer_csv(cx, csv)
    assert not rejets, rejets[:3]
    alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
    return {a["id"]: a for a in alertes}


class TestPacSelonComptage(unittest.TestCase):
    def test_chaleur_totale_donne_le_rendement(self):
        a = analyser_comptage("totale")["T8-pac_cop"]
        self.assertEqual(a["titre"], "PAC : rendement en baisse")
        self.assertIn("rendement de", a["constat"])

    def test_chauffage_seul_detecte_la_derive(self):
        a = analyser_comptage("chauffage")["T8-pac_cop"]
        self.assertEqual(a["titre"], "PAC : consommation électrique en hausse")
        self.assertIn("chaleur mesurée égales", a["constat"])

    def test_eau_chaude_seule_detecte_la_derive(self):
        self.assertIn("T8-pac_cop", analyser_comptage("ecs"))

    def test_electricite_seule_detecte_la_derive_sans_fausse_alerte_si_saine(self):
        a = analyser_comptage("aucune")["T8-pac_cop"]
        self.assertIn("à météo égale", a["constat"])
        self.assertGreater(a["chf_mesure"], 0)  # PAC : excès mesuré depuis le début de la dérive, pas de CHF/an
        self.assertIsNone(a["chf_an"])
        self.assertNotIn("T8-pac_cop", analyser_comptage("aucune", sans=("pac",)))

    def test_pac_saine_avec_chauffage_seul_sans_alerte(self):
        self.assertNotIn("T8-pac_cop", analyser_comptage("chauffage", sans=("pac",)))


if __name__ == "__main__":
    unittest.main()
