"""Règle « historique du même mois » (gaz, PAC) : comparaison aux mêmes mois des années précédentes, à climat égal."""
import unittest

import numpy as np
import pandas as pd
from commun import base_exemple, base_vide

from vigie import db, historique, moteur, parc, service

FIN = pd.Timestamp("2026-01-01")
MOIS = pd.period_range("2021-01", "2025-12", freq="M")
# Degrés-jours d'une année type, plus ou moins froide selon l'année (2025 : 25 % plus froide que les précédentes)
DJ_TYPE = np.array([500, 430, 350, 200, 80, 10, 0, 0, 60, 180, 380, 480], dtype=float)
RIGUEUR = {2021: 1.00, 2022: 1.06, 2023: 0.94, 2024: 1.00, 2025: 1.25}
DJ = pd.Series([DJ_TYPE[m.month - 1] * RIGUEUR[m.year] for m in MOIS], index=MOIS)


def serie(derive=None, base=300.0, pente=8.0):
    """Consommation mensuelle = base + pente × degrés-jours ; `derive` = {mois: facteur} appliqué en plus."""
    s = base + pente * DJ
    for mois, facteur in (derive or {}).items():
        s[pd.Period(mois, "M")] *= facteur
    return s


class TestAttenduDuMois(unittest.TestCase):
    def test_meme_mois_des_trois_annees_precedentes_corrige_du_climat(self):
        a = historique.attendu_mois(serie(), DJ, pd.Period("2025-12", "M"))
        self.assertEqual((a["annees"], a["corrige"]), ([2022, 2023, 2024], True))
        self.assertAlmostEqual(a["reference"], 300 + 8 * 480, places=3)           # médiane des mois de décembre
        self.assertAlmostEqual(a["attendu"], 300 + 8 * 480 * 1.25, delta=1.0)     # ramené au climat de décembre 2025

    def test_sans_degres_jours_la_comparaison_reste_brute(self):
        a = historique.attendu_mois(serie(), pd.Series(dtype=float), pd.Period("2025-12", "M"))
        self.assertEqual((a["corrige"], round(a["attendu"])), (False, 300 + 8 * 480))

    def test_aucun_meme_mois_connu_pas_d_attendu(self):
        self.assertIsNone(historique.attendu_mois(serie()["2025-03":], DJ["2025-03":], pd.Period("2025-12", "M")))


class TestDeriveHistorique(unittest.TestCase):
    def test_hiver_plus_froid_sans_derive_aucune_alerte(self):
        self.assertIsNone(historique.det_historique(serie(), DJ, FIN))
        # la même série comparée sans le climat : fausse alerte, c'est ce que la correction évite
        brut = historique.det_historique(serie(), pd.Series(dtype=float), FIN)
        self.assertIn("sans correction du climat", brut["detail"])

    def test_derive_de_trente_pour_cent_tenue_deux_mois(self):
        r = historique.det_historique(serie({"2025-11": 1.30, "2025-12": 1.30}), DJ, FIN, kwh_par_unite=11.1, unite="m3")
        self.assertEqual((r["persistance"], r["unite"], r["debut"], r["mesure"]), (2, "mois", "2025-11-01", "+30 %"))
        self.assertEqual((r["climat"], r["persistance_jours"], r["heures_mesurees"]), (", à climat égal", 61, 61 * 24))
        self.assertIn("m³ en décembre 2025 au lieu de", r["detail"])
        self.assertIn("référence : décembre 2022 à 2024, corrigée du climat du mois", r["detail"])
        attendu = [300 + 8 * dj for dj in (380 * 1.25, 480 * 1.25)]
        self.assertAlmostEqual(r["kwh_mesure"], 0.30 * sum(attendu) * 11.1, delta=0.01 * sum(attendu) * 11.1)
        self.assertAlmostEqual(r["kwh_j"], 0.30 * attendu[1] * 11.1 / 31, delta=0.01 * attendu[1] * 11.1 / 31)
        self.assertGreater(r["kwh_proj"], r["kwh_mesure"])                      # projection : une année de référence

    def test_un_seul_mois_ou_un_ecart_sous_le_seuil_aucune_alerte(self):
        self.assertIsNone(historique.det_historique(serie({"2025-12": 1.50}), DJ, FIN))                    # persistance
        self.assertIsNone(historique.det_historique(serie({"2025-11": 1.15, "2025-12": 1.15}), DJ, FIN))   # seuil 20 %
        r = historique.det_historique(serie({"2025-11": 1.15, "2025-12": 1.15}), DJ, FIN, seuil_pct=10.0)
        self.assertEqual(r["mesure"], "+15 %")                                                             # seuil réglable

    def test_mois_manquant_interrompt_la_serie_et_releve_trop_ancien_non_juge(self):
        s = serie({m: 1.40 for m in ("2025-09", "2025-10", "2025-11", "2025-12")})
        self.assertEqual(historique.det_historique(s, DJ, FIN)["persistance"], 4)
        self.assertEqual(historique.det_historique(s.drop(pd.Period("2025-10", "M")), DJ, FIN)["persistance"], 2)
        self.assertIsNone(historique.det_historique(s, DJ, pd.Timestamp("2026-06-01")))  # dernier relevé : 5 mois

    def test_reference_gelee_une_derive_de_plus_d_un_an_reste_en_alerte(self):
        s = serie({str(m): 1.35 for m in MOIS if m >= pd.Period("2024-06", "M")})
        libre = historique.det_historique(s, DJ, FIN)
        gelee = historique.det_historique(s, DJ, FIN, ref_avant=pd.Timestamp("2024-06-01"))
        self.assertEqual(gelee["mesure"], "+35 %")              # comparée aux années d'avant la dérive
        self.assertIn("décembre 2021 à 2023", gelee["detail"])
        self.assertLess(float(libre["mesure"].rstrip(" %")), 35)  # sans gel, décembre 2024 (déjà en dérive) entre dans la référence


class TestSeriesMensuelles(unittest.TestCase):
    def test_releve_mensuel_et_courbe_plus_fine_ramenes_au_mois_civil(self):
        pts = pd.DataFrame({"fluide": ["gaz", "pac_electricite", "mazout"], "nature": "intervalle",
                            "pas_min": [db.PAS_MENSUEL, 1440.0, db.PAS_MENSUEL]}, index=["G", "P", "E"])
        mensuel = pd.DataFrame({"ts": pd.to_datetime(["2025-02-01", "2025-03-01", "2025-04-01"]), "point_id": "G",
                                "valeur": [100.0, 90.0, 80.0], "qualite": ["valide", "estimee", "valide"]})
        jours = pd.date_range("2025-01-01 23:00", "2025-03-10 23:00", freq="D")   # janvier et février complets, mars non
        courbe = pd.DataFrame({"ts": jours, "point_id": "P", "valeur": 10.0, "qualite": "valide"})
        eau = pd.DataFrame({"ts": pd.to_datetime(["2025-02-01"]), "point_id": "E", "valeur": [5.0], "qualite": "valide"})
        m = historique.series_mensuelles(pts, pd.concat([mensuel, courbe, eau], ignore_index=True))
        self.assertEqual(sorted(m), ["G", "P"])                                   # pas le mazout (livraisons)
        self.assertEqual({str(k): v for k, v in m["G"].items()}, {"2025-01": 100.0, "2025-03": 80.0})   # estimé exclu
        self.assertEqual({str(k): v for k, v in m["P"].items()}, {"2025-01": 310.0, "2025-02": 280.0})  # mois complets
        vu = historique.series_mensuelles(pts, mensuel, jusqua=pd.Timestamp("2025-02-15"))
        self.assertEqual([str(k) for k in vu["G"].index], ["2025-01"])            # rejeu : rien du futur

    def test_degres_jours_du_lot_sinon_temperature_horaire(self):
        cx = base_vide("historique-dj")
        heures = pd.date_range("2025-01-01 01:00", "2025-03-01 00:00", freq="h")
        dj = historique.degres_jours(cx, pd.Series(6.0, index=heures))
        self.assertEqual({str(k): round(v) for k, v in dj.items()}, {"2025-01": 310, "2025-02": 280})  # (16 − 6) × jours
        cx.execute("INSERT INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                   (historique.SERIE_DJ, "2025-01", 512.0, "°C·jour", "test"))
        self.assertEqual(historique.degres_jours(cx, None).to_dict(), {pd.Period("2025-01", "M"): 512.0})
        self.assertTrue(historique.degres_jours(None, None).empty)


class TestDansLeMoteur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cx = base_vide("historique-moteur")
        for code, fluide, unite in (("A", "gaz", "m3"), ("B", "pac_electricite", "kWh")):
            parc.enregistrer_immeuble(cls.cx, {"id": code, "nom": f"Immeuble {code}", "rue": f"Rue du Test {code}",
                                               "npa_localite": "1200 Genève", "profil": "Habite", "sre_m2": 1000})
            parc.enregistrer_point(cls.cx, {"id": f"{code}-M", "immeuble_id": code, "fluide": fluide, "unite": unite,
                                            "nature": "intervalle", "pas_min": db.PAS_MENSUEL, "libelle": "Relevé mensuel",
                                            "etat": "actif"})
        derive = {"A": {"2025-11": 1.30, "2025-12": 1.30}, "B": {}}   # A : gaz en dérive ; B : PAC saine
        for code, facteurs in derive.items():
            cls.cx.executemany("INSERT INTO mesure VALUES (?,?,?,?,?)", [
                ((m + 1).start_time.strftime("%Y-%m-%dT%H:%M:%SZ"), f"{code}-M", float(v), "valide", "test")
                for m, v in serie(facteurs).items()])
        cls.cx.executemany("INSERT INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                           [(historique.SERIE_DJ, str(m), float(v), "°C·jour", "test") for m, v in DJ.items()])
        db.ecrire_parametre(cls.cx, "parametres", {**service.defauts()["parametres"], "gaz_pcs_kwh_par_m3": 11.1})
        cls.cx.commit()
        cls.ref = db.referentiel(cls.cx, service.defauts())

    def test_alerte_gaz_chiffree_et_pac_saine_sans_alerte(self):
        alertes = {a["id"]: a for a in moteur.analyser(self.cx, self.ref)[0]}
        self.assertEqual(sorted(alertes), ["A-gaz_historique"])
        a = alertes["A-gaz_historique"]
        self.assertEqual((a["cause"], a["gravite"], a["metier"], a["persistance"], a["mesure"], a["point_id"]),
                         ("gaz_historique", "Élevée", "Chauffagiste", "2 mois", "+30 %", "A-M"))
        self.assertIn("mêmes mois des années précédentes, à climat égal", a["constat"])
        self.assertGreater(a["kwh_mesure"], 0)
        self.assertEqual(a["chf_mesure"], round(a["kwh_mesure"] * self.ref["tarifs"]["gaz"]["chf_par_unite"]))
        self.assertIn("depuis le 01.11.2025", a["periode"])
        self.assertIn("année de référence du compteur", a["projection"])

    def test_seuil_et_profils_reglables_et_gaz_sans_pouvoir_calorifique_non_juge(self):
        regles = {"gaz_historique": {"seuil": 40.0}}
        self.assertEqual(moteur.analyser(self.cx, {**self.ref, "regles": regles})[0], [])
        regles = {"gaz_historique": {"profils": ["Vide"]}}
        self.assertEqual(moteur.analyser(self.cx, {**self.ref, "regles": regles})[0], [])
        sans_pcs = {**self.ref, "parametres": {k: v for k, v in self.ref["parametres"].items() if k != "gaz_pcs_kwh_par_m3"}}
        self.assertEqual(moteur.analyser(self.cx, sans_pcs)[0], [])

    def test_le_rejeu_ne_declare_la_derive_qu_au_deuxieme_mois_recu(self):
        ids = lambda date: {a["id"] for a in moteur.analyser(self.cx, self.ref, jusqua=pd.Timestamp(date), gelees={})[0]}  # noqa: E731
        self.assertEqual(ids("2025-12-15"), set())                    # un seul mois au-dessus : pas encore
        self.assertEqual(ids("2026-01-01"), {"A-gaz_historique"})     # relevé de décembre reçu : deux mois

    def test_une_regle_plus_fine_deja_en_alerte_remplace_la_regle_historique(self):
        self.assertTrue(historique.doublon("gaz_historique", {"gaz_signature", "gaz_historique"}))
        self.assertTrue(historique.doublon("pac_historique", {"pac_cop"}))
        self.assertFalse(historique.doublon("gaz_historique", {"gaz_historique", "pac_cop"}))
        self.assertFalse(historique.doublon("gaz_signature", {"gaz_historique"}))


class TestExempleEtReglages(unittest.TestCase):
    def test_exemple_de_douze_mois_la_regle_reste_muette(self):
        cx = base_exemple("historique-exemple")
        causes = {a["cause"] for a in moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]}
        self.assertFalse(causes & set(historique.FLUIDES.values()))   # aucun « même mois » d'une année précédente

    def test_regle_enregistree_sans_type_d_immeuble_refusee(self):
        cx = base_exemple("historique-reglages")
        with self.assertRaisesRegex(parc.ErreurSaisie, "au moins un type d'immeuble"):
            parc.enregistrer_regle(cx, "gaz_historique", {"profils": [], "seuil": 25, "persistance": 2})
        parc.enregistrer_regle(cx, "gaz_historique", {"profils": ["Habite"], "seuil": 25, "persistance": 3})
        r = moteur.regles_effectives(db.referentiel(cx, service.defauts()))["gaz_historique"]
        self.assertEqual((r["profils"], r["seuil"], r["persistance"], r["unite_persistance"]), (["Habite"], 25.0, 3, "mois"))


if __name__ == "__main__":
    unittest.main()
