"""Solaire : production comparée à ensoleillement égal, décote annuelle, panne / dégradation / arrêt, saisie, météo."""
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from commun import base_exemple, base_vide

from vigie import bons, db, meteo, moteur, parc, service, solaire

REGLES = {c: moteur.regles_effectives({})[c] for c in solaire.CAUSES}


def serie(valeurs, fin="2026-11-10"):
    return pd.Series(valeurs, index=pd.date_range(end=fin, periods=len(valeurs), freq="D"))


class TestQualification(unittest.TestCase):
    """Rendement relatif par jour ensoleillé (mesuré / attendu) -> cause."""

    def setUp(self):
        self.rnd = np.random.default_rng(1)

    def bruit(self, n):
        return self.rnd.normal(0, 0.02, n)

    def test_chute_brutale_d_une_chaine_est_une_panne(self):
        q = serie(np.r_[1 + self.bruit(30), 0.75 + self.bruit(6)])
        self.assertEqual(solaire.qualifier(q, REGLES), ("solaire_panne", 6))

    def test_baisse_progressive_est_une_degradation(self):
        q = serie(np.r_[1 + self.bruit(20), np.linspace(1.0, 0.78, 35) + self.bruit(35)])
        cause, n = solaire.qualifier(q, REGLES)
        self.assertEqual(cause, "solaire_degradation")
        self.assertGreaterEqual(n, 7)

    def test_production_nulle_au_soleil_est_un_arret(self):
        q = serie(np.r_[1 + self.bruit(30), [0.0, 0.0, 0.01]])
        self.assertEqual(solaire.qualifier(q, REGLES), ("solaire_arret", 3))

    def test_installation_saine_ou_pic_isole_sans_alerte(self):
        self.assertIsNone(solaire.qualifier(serie(1 + self.bruit(60)), REGLES))
        self.assertIsNone(solaire.qualifier(serie(np.r_[1 + self.bruit(40), [0.7, 0.72]]), REGLES))  # persistance 3

    def test_regle_desactivee(self):
        q = serie(np.r_[1 + self.bruit(30), 0.75 + self.bruit(6)])
        self.assertIsNone(solaire.qualifier(q, {"solaire_arret": REGLES["solaire_arret"]}))

    def test_baisse_brutale_sous_le_seuil_de_panne_jamais_laissee_sans_alerte(self):
        q = serie(np.r_[1 + self.bruit(30), 0.88 + self.bruit(8) / 4])  # −12 % d'un coup : sous le seuil de panne (15 %)
        self.assertEqual(solaire.qualifier(q, REGLES), ("solaire_degradation", 8))
        self.assertTrue(solaire.rupture(q, q.index[-8], 0.0))  # le constat dira « apparue d'un coup »

    def test_seuil_de_panne_abaisse_par_le_gestionnaire(self):
        regles = {**REGLES, "solaire_panne": {**REGLES["solaire_panne"], "seuil": 5.0}}
        q = serie(np.r_[1 + self.bruit(30) / 4, 0.93 + self.bruit(6) / 4])  # −7 % d'un coup
        self.assertEqual(solaire.qualifier(q, regles)[0], "solaire_panne")


class TestDecote(unittest.TestCase):
    def test_journee_comparable_d_il_y_a_un_an_decotee(self):
        """Même ensoleillement il y a un an : l'attendu d'aujourd'hui = rendement d'alors × (1 − décote)."""
        jours = pd.date_range("2025-10-01", "2026-11-10", freq="D")
        j = pd.DataFrame({"g": 3.0, "n": 24, "ensoleille": True}, index=jours)
        j["p"] = 100.0  # rendement constant : 100 kWh pour 3 kWh/m² sur l'historique
        inst = solaire.installation({"puissance_crete_kwc": 80, "degradation_pct_an": 5})
        limite = pd.Timestamp("2026-10-11")
        j = solaire.attendu_jours(j[(j.index < "2025-12-01") | (j.index >= "2026-11-01")].copy(), limite, inst, None)
        an_plus_tard = j.loc["2026-11-05"]
        self.assertEqual(an_plus_tard["mode"], "historique")
        self.assertAlmostEqual(an_plus_tard["att"], 100 * 0.95, delta=0.3)  # 5 %/an, un an d'écart

    def test_reference_nominale_par_la_production_prevue(self):
        inst = solaire.installation({"puissance_crete_kwc": 30, "production_prevue_kwh_an": 31500,
                                     "mise_en_service": 2016, "degradation_pct_an": 0.5})
        f = solaire.facteur_nominal(inst, {"rayonnement_annuel_normal_kwh_m2": 1385.9})
        age = solaire.age_ans(inst, pd.Timestamp("2026-07-02"))
        self.assertAlmostEqual(age, 10.0, delta=0.01)
        self.assertAlmostEqual(f(pd.Timestamp("2026-07-02")), 31500 * 0.995 ** age / 1385.9, places=6)
        self.assertIsNone(solaire.facteur_nominal(solaire.installation({"puissance_crete_kwc": 30}), {}))


class TestExemple(unittest.TestCase):
    """Petit exemple : T8 perd une chaîne de modules (−25 %), OA est sain."""

    @classmethod
    def setUpClass(cls):
        cls.cx = base_exemple("solaire")
        cls.alertes = {a["id"]: a for a in moteur.analyser(cls.cx, db.referentiel(cls.cx, service.defauts()))[0]}

    def test_panne_detectee_chiffree_au_tarif_solaire_et_adressee_a_l_installateur(self):
        a = self.alertes["T8-solaire_panne"]
        self.assertEqual((a["fluide"], a["gravite"], a["metier"], a["reference"]),
                         ("Solaire", "Élevée", "Solaire", "journées comparables"))
        self.assertIn("La baisse est apparue d'un coup", a["constat"])
        self.assertIn("chaîne (string)", a["constat"])
        self.assertIn("0,5 %/an", a["constat"])
        self.assertAlmostEqual(a["chf_mois"], a["kwh_mois"] * 0.20, delta=1)  # tarif solaire d'EXEMPLE
        self.assertIn("production prévue", a["projection"])
        self.assertGreater(a["kwh_mesure"], 0)
        self.assertFalse(any(i.startswith("OA-solaire") for i in self.alertes))
        bons.synchroniser_alertes(self.cx, list(self.alertes.values()))
        self.assertEqual(bons.choisir_prestataire(self.cx, "Solaire", "T8")["nom"], "Solaire Exemple SA")

    def test_production_au_dela_de_la_puissance_crete_est_un_defaut_de_donnees(self):
        cx = base_exemple("solaire-crete")
        fin = cx.execute("SELECT max(ts) FROM mesure WHERE point_id = 'OA_PV'").fetchone()[0]
        cx.execute("UPDATE mesure SET valeur = 100 WHERE point_id = 'OA_PV' AND ts = ?", (fin,))  # 45 kWc
        cx.commit()
        ids = {a["id"]: a for a in moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]}
        self.assertEqual(ids["OA-donnees-OA_PV"]["cause"], "donnees_crete")
        self.assertIn("puissance crête (45 kWc)", ids["OA-donnees-OA_PV"]["constat"])


class TestSansHistorique(unittest.TestCase):
    def test_installation_neuve_jugee_sur_la_production_prevue(self):
        cx = base_vide("solaire-neuf")
        db.charger_referentiel(cx, service.defauts())
        fin = datetime(2026, 7, 21)
        lignes = []
        for h in range(31 * 24):  # 31 jours : complétude suffisante, aucun historique avant la fenêtre
            t = fin - timedelta(hours=h)
            g = max(0.0, 800 * np.sin((t.hour - 4) / 16 * np.pi)) if 4 <= t.hour <= 20 else 0.0
            ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            lignes += [(ts, "RAYON_FICTIF", g), (ts, "OA_PV", 0.6 * 32.4 * g / 1000)]  # 60 % de l'attendu nominal
        cx.executemany("INSERT INTO mesure VALUES (?,?,?, 'valide', 'test')", lignes)
        cx.commit()
        ids = {a["id"]: a for a in moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]}
        a = ids["OA-solaire_panne"]
        self.assertEqual(a["reference"], "production prévue")
        self.assertIn("la production prévue de l'installation", a["constat"])


class TestSaisie(unittest.TestCase):
    def test_puissance_crete_obligatoire_et_caracteristiques_enregistrees(self):
        cx = base_exemple("solaire-saisie")
        base = {"id": "OB_PV", "immeuble_id": "OB", "fluide": "Photovoltaïque", "etat": "actif"}
        with self.assertRaisesRegex(parc.ErreurSaisie, "Puissance crête"):
            parc.enregistrer_point(cx, base)
        with self.assertRaisesRegex(parc.ErreurSaisie, "Décote"):
            parc.enregistrer_point(cx, {**base, "puissance_crete_kwc": "25", "degradation_pct_an": "9"})
        p, avert = parc.enregistrer_point(cx, {**base, "puissance_crete_kwc": "25,5", "mise_en_service": "2021"})
        self.assertEqual((p["fluide"], p["unite"], p["puissance_crete_kwc"]), ("solaire", "kWh", 25.5))
        self.assertTrue(any("production prévue" in a for a in avert))
        r = db.lignes(cx, "SELECT puissance_crete_kwc, mise_en_service, production_prevue_kwh_an FROM point_mesure "
                          "WHERE id = 'OB_PV'")[0]
        self.assertEqual(r, {"puissance_crete_kwc": 25.5, "mise_en_service": 2021, "production_prevue_kwh_an": None})
        eau = parc.enregistrer_point(cx, {"id": "OB_EAU", "immeuble_id": "OB", "fluide": "eau", "etat": "actif",
                                          "puissance_crete_kwc": "99"})[0]
        self.assertIsNone(eau["puissance_crete_kwc"])  # caractéristiques solaires ignorées pour un autre fluide
        self.assertEqual(parc.METIER_PAR_FLUIDE["solaire"], "Solaire")
        self.assertIn("Solaire", moteur.METIERS)

    def test_excel_du_parc_avec_les_colonnes_solaires(self):
        from vigie import excel
        cx = base_exemple("solaire-excel")
        feuille = excel.lire_xlsx(parc.exporter_parc_excel(cx))["Compteurs"]
        entetes = feuille[0]
        for c in db.SOLAIRE_CHAMPS:
            self.assertIn(c, entetes)
        t8 = next(ligne for ligne in feuille if ligne[0] == "T8_PV")
        self.assertEqual(float(t8[entetes.index("puissance_crete_kwc")]), 30.0)


class TestRayonnementMeteoSuisse(unittest.TestCase):
    ENTETE = "station_abbr;reference_timestamp;tre200h0;gre000h0\n"

    def test_rayonnement_lu_et_importe_avec_la_temperature(self):
        texte = self.ENTETE + "GVE;12.11.2026 11:00;8.5;412\nGVE;12.11.2026 12:00;9.0;\nGVE;12.11.2026 13:00;9.1;9999\n"
        lu = meteo.lire_csv(texte, "GVE")
        self.assertEqual(lu["rayonnement"], [("2026-11-12T11:00:00Z", 412.0)])  # manquant et implausible écartés
        self.assertEqual(len(lu["meteo"]), 3)
        cx = base_vide("meteo-rayonnement")
        r = meteo.mettre_a_jour(cx, lambda url: "" if "historical" in url else texte,
                                datetime(2026, 11, 12, 14, tzinfo=timezone.utc))
        self.assertEqual(r["heures_rayonnement"], 1)
        ref = db.referentiel(cx, {"parametres": {}, "tarifs": {}, "facteurs_co2_kg_par_kwh": {}})
        self.assertEqual((ref["meteo"]["id"], ref["rayonnement"]["id"]), ("METEO_GVE", "RAYON_GVE"))


if __name__ == "__main__":
    unittest.main()
