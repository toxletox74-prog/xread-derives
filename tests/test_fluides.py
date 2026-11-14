"""CAD et gaz (signature, immeuble vide, conversion m³ -> kWh), projection séparée de la dérive constatée."""
import copy
import unittest

from commun import base_exemple

from evaluation import simulateur as S
from vigie import bons, db, moteur, service


def analyser(sc, defauts=None, graine=1):
    res, _ = S.executer(sc, graine, "fictive", (0,), defauts or service.defauts())
    return {a["cause"]: a for a in res[0]["alertes"]}


def sc(type_, derive, amplitude, **extra):
    return {"type": type_, "derive": derive, "amplitude": amplitude, "age_j": 14, **extra}


class TestCadGaz(unittest.TestCase):
    def test_cad_signature_chiffree_au_tarif_du_cad(self):
        a = analyser(sc("chaufferie", "signature", 0.20, chauffage="cad"))["cad_signature"]
        tarif = service.defauts()["tarifs"]["cad"]["chf_par_unite"]
        self.assertAlmostEqual(a["chf_mesure"], a["kwh_mesure"] * tarif, delta=1)
        self.assertEqual(moteur.regles_effectives({})["cad_signature"]["metier"], "Chauffagiste")

    def test_gaz_en_m3_converti_par_le_pcs(self):
        a = analyser(sc("chaufferie", "signature", 0.20, chauffage="gaz"))["gaz_signature"]
        self.assertGreater(a["kwh_mesure"], 0)

    def test_gaz_en_m3_sans_pcs_aucune_alerte_energie(self):
        d = copy.deepcopy(service.defauts())
        d["parametres"].pop("gaz_pcs_kwh_par_m3")
        self.assertNotIn("gaz_signature", analyser(sc("chaufferie", "signature", 0.20, chauffage="gaz"), d))

    def test_cad_et_gaz_sains_sans_alerte(self):
        for ch in ("cad", "gaz"):
            self.assertEqual(analyser(sc("chaufferie", None, 0, chauffage=ch)), {}, ch)
            self.assertEqual(analyser(sc("vide", None, 0, chauffage=ch)), {}, ch)

    def test_cad_immeuble_vide_chauffe(self):
        self.assertIn("cad_vide", analyser(sc("vide", "chaleur_vide", 1.0, chauffage="cad")))


class TestProjection(unittest.TestCase):
    def test_projection_etiquetee_et_hors_du_score(self):
        normal = analyser(sc("chaufferie", "signature", 0.20))["chaleur_signature"]
        d = copy.deepcopy(service.defauts())
        d["parametres"]["dj16_annuel_normal"] *= 2  # autre hypothèse de climat
        autre = analyser(sc("chaufferie", "signature", 0.20), d)["chaleur_signature"]
        self.assertIn("hypothèse : climat normal", normal["projection"])
        self.assertGreater(autre["chf_proj"], normal["chf_proj"])
        for cle in ("score", "gravite", "chf_mesure", "chf_mois", "persistance"):  # la mesure seule décide
            self.assertEqual(autre[cle], normal[cle], cle)

    def test_sans_climat_normal_pas_de_projection_mais_meme_alerte(self):
        d = copy.deepcopy(service.defauts())
        d["parametres"].pop("dj16_annuel_normal")
        a = analyser(sc("pac", "pac", 0.25, comptage="totale"), d)["pac_cop"]
        self.assertIsNone(a["chf_proj"])
        self.assertIn("non calculée", a["projection"])
        self.assertGreater(a["chf_mesure"], 0)

    def test_bon_ne_transmet_que_la_derive_constatee(self):
        cx = base_exemple("bon-constate")
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        a = next(x for x in alertes if x["id"] == "OB-chaleur_signature")
        _, corps = bons.composer(a, None, "B-TEST", {})
        self.assertIn("Dérive constatée", corps)
        self.assertNotIn("Projection", corps)
        self.assertNotIn("CHF", corps)

    def test_exemple_douze_mois_reference_meme_saison(self):
        cx = base_exemple("reference-saison")
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        a = next(x for x in alertes if x["id"] == "OB-chaleur_signature")
        self.assertEqual(a["reference"], "saison")


if __name__ == "__main__":
    unittest.main()
