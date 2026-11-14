"""Une méthode par fluide ET par pas de relevé : électricité, PAC et solaire relevés au jour, PAC au mois à chaleur
produite égale. Les méthodes à l'heure et au mois ont leurs propres fichiers de tests."""
import unittest

import numpy as np
import pandas as pd
from test_historique import DJ, FIN, MOIS, serie

from vigie import complements, historique, moteur, regles, service, solaire

P = service.defauts()["parametres"]
R = moteur.regles_effectives({})
VIDE = pd.Series(dtype=float)


class TestElectriciteAuJour(unittest.TestCase):
    FIN = pd.Timestamp("2025-05-01")
    JOURS = pd.date_range("2025-01-01", "2025-04-30", freq="D")

    def bureaux(self):
        """Semaine à 100 kWh par jour, week-end à 40 kWh."""
        return pd.Series(np.where(self.JOURS.dayofweek < 5, 100.0, 40.0), index=self.JOURS)

    def test_semaine_et_week_end_normaux_sans_alerte(self):
        self.assertIsNone(complements.det_elec_jour(self.bureaux(), self.FIN, P))

    def test_hausse_de_trente_pour_cent_jugee_entre_jours_de_meme_type(self):
        s = self.bureaux()
        s[self.JOURS >= "2025-04-21"] *= 1.30                          # les 10 derniers jours, week-end compris
        r = complements.det_elec_jour(s, self.FIN, P)
        self.assertEqual((r["persistance"], r["unite"], r["debut"], r["mesure"]), (10, "jours", "2025-04-21", "+30 %"))
        self.assertAlmostEqual(r["kwh_mesure"], 0.30 * (8 * 100 + 2 * 40))  # excès mesuré : 8 jours ouvrés, 2 de week-end
        self.assertAlmostEqual(r["kwh_j"], 0.30 * (8 * 100 + 2 * 40) / 10)
        self.assertIn("88 kWh/jour un jour de même type", r["attendu"])

    def test_seuil_et_persistance(self):
        s = self.bureaux()
        s[self.JOURS >= "2025-04-21"] *= 1.15
        self.assertIsNone(complements.det_elec_jour(s, self.FIN, P))                       # +15 % sous le seuil de 20 %
        self.assertEqual(complements.det_elec_jour(s, self.FIN, P, seuil_pct=10.0)["mesure"], "+15 %")
        court = self.bureaux()
        court[self.JOURS >= "2025-04-27"] *= 1.50                                          # 4 jours : persistance 5
        self.assertIsNone(complements.det_elec_jour(court, self.FIN, P))

    def test_jour_ferie_du_calendrier_compare_aux_jours_non_ouvres(self):
        s = self.bureaux()
        ferie = pd.Timestamp("2025-04-21")                                                 # lundi de Pâques : 40 kWh
        s[ferie] = 40.0
        s[self.JOURS > ferie] *= 1.30
        sans = complements.det_elec_jour(s, self.FIN, P)                                   # sans calendrier : un lundi
        self.assertEqual((sans["debut"], sans["persistance"]), ("2025-04-22", 9))          # « en baisse », hors de la série
        r = complements.det_elec_jour(s, self.FIN, P, calendrier_lot={ferie: (False, False)})
        self.assertEqual((r["debut"], r["persistance"]), ("2025-04-22", 9))                # férié normal pour un férié

    def test_reference_trop_courte_pas_de_conclusion(self):
        self.assertIsNone(complements.det_elec_jour(self.bureaux()["2025-03-25":] * 2, self.FIN, P))


def meteo_d_hiver(fin, debut="2024-11-01"):
    """Température horaire d'un hiver, avec des jours doux et froids (vague de 9,3 jours)."""
    heures = pd.date_range(f"{debut} 01:00", fin, freq="h")
    jour = heures.dayofyear.to_numpy()
    return pd.Series(9.0 - 7.0 * np.cos(2 * np.pi * (jour - 15) / 365) + 4.0 * np.sin(2 * np.pi * jour / 9.3), index=heures)


class TestPacAuJour(unittest.TestCase):
    FIN = pd.Timestamp("2025-03-01")

    def setUp(self):
        self.text_h = meteo_d_hiver(self.FIN)
        self.jours = pd.date_range("2024-11-01", "2025-02-28", freq="D")
        dj = (16 - self.text_h.resample("D").mean()).clip(lower=0).reindex(self.jours)
        self.pac = pd.Series(20 + 6 * dj.to_numpy(), index=self.jours)       # électricité de la PAC, kWh par jour
        self.elec = pd.Series(np.where(self.jours.dayofweek < 5, 100.0, 40.0), index=self.jours)

    def candidats(self, journ, horaires=()):
        ids = {"pac_electricite": "P", "electricite": "E"}
        return {c: r for c, _pid, r in complements.regles_au_jour(
            ids, journ, dict.fromkeys(horaires), self.text_h, self.FIN, P, R, lambda c: True, lambda c: None, lambda f: f in ids)}

    def test_pac_saine_sans_alerte_et_derive_a_meteo_egale(self):
        self.assertEqual(self.candidats({"P": self.pac, "E": self.elec}), {"pac_signature": None, "elec_jour": None})
        derive = self.pac.copy()
        derive[self.jours >= "2025-02-10"] *= 1.30
        r = self.candidats({"P": derive, "E": self.elec})["pac_signature"]
        self.assertGreaterEqual(r["persistance"], 7)
        self.assertIn(r["mesure"], ("+29 %", "+30 %", "+31 %"))
        self.assertGreater(r["kwh_mesure"], 0)

    def test_compteurs_releves_a_l_heure_laisses_aux_regles_horaires(self):
        self.assertEqual(self.candidats({"P": self.pac, "E": self.elec}, horaires=("P", "E")), {})

    def test_place_dans_la_matrice_des_releves(self):
        self.assertEqual((regles.PAS_REGLES["elec_jour"], regles.PAS_REGLES["pac_signature"]), ((1440, 1440), (1440, 1440)))
        self.assertEqual(regles.applicabilite("elec_jour", [("electricite", 1440, 3), ("electricite", 60, 2)])["compteurs"], 3)
        self.assertEqual(regles.PAS_REGLES["solaire_panne"], (0, 1440))          # solaire : jusqu'au relevé journalier
        self.assertEqual(regles.PAS_REGLES["solaire_onduleur"], (0, 60))         # coupures : relevé à l'heure ou plus fin
        self.assertTrue(historique.doublon("elec_historique", {"elec_jour"}))
        self.assertTrue(historique.doublon("pac_historique", {"pac_signature"}))


def soleil(fin, jours=200):
    """Rayonnement horaire (W/m²) : jours plus ou moins ensoleillés, de 6 h à 18 h."""
    heures = pd.date_range(end=fin, periods=jours * 24, freq="h")
    ciel = 0.55 + 0.40 * np.sin(2 * np.pi * heures.dayofyear.to_numpy() / 6.7) ** 2
    return pd.Series(800 * ciel * np.clip(np.sin(np.pi * (heures.hour.to_numpy() - 6) / 12), 0, None), index=heures)


class TestSolaireAuJour(unittest.TestCase):
    FIN = pd.Timestamp("2026-07-01")
    POINT = {"id": "PV", "puissance_crete_kwc": 100.0, "production_prevue_kwh_an": 100000.0, "mise_en_service": 2024,
             "degradation_pct_an": 0.5}
    REGLES = {c: R[c] for c in solaire.CAUSES}

    def setUp(self):
        self.ray = soleil(self.FIN)
        jours = self.ray.resample("D").sum() / 1000.0                       # kWh/m² par jour
        self.production = (85.0 * jours)[:-1]                               # relevé journalier, jour en cours exclu

    def detecter(self, production):
        return solaire.det_solaire(production, self.ray, None, self.FIN, P, self.POINT, self.REGLES, None, None, True)

    def test_installation_saine_sans_alerte(self):
        self.assertIsNone(self.detecter(self.production))

    def test_chute_de_trente_pour_cent_a_ensoleillement_egal(self):
        perte = self.production.copy()
        perte.iloc[-12:] *= 0.70
        cause, r = self.detecter(perte)
        self.assertEqual(cause, "solaire_panne")
        self.assertGreaterEqual(r["persistance"], 3)
        self.assertIn("−30 %", r["mesure"])
        self.assertEqual(r["repartition"], {})                              # pas de détail dans la journée au pas journalier
        self.assertGreater(r["kwh_mesure"], 0)

    def test_arret_complet(self):
        arret = self.production.copy()
        arret.iloc[-4:] = 0.0
        self.assertEqual(self.detecter(arret)[0], "solaire_arret")


class TestPacAuMoisAChaleurEgale(unittest.TestCase):
    """PAC avec compteur de chaleur relevé au mois : l'électricité est jugée à chaleur produite égale (rendement)."""

    def test_hiver_plus_froid_meme_rendement_sans_alerte_meme_sans_degres_jours(self):
        electricite = serie()                                               # 2025 : 25 % plus froide, donc plus de kWh
        chaleur = electricite * 4.0                                         # rendement constant de 4
        self.assertIsNotNone(historique.det_historique(electricite, VIDE, FIN))            # comparaison brute : alerte
        self.assertIsNone(historique.det_historique(electricite, VIDE, FIN, chaleur=chaleur))

    def test_rendement_en_baisse_detecte_et_explique(self):
        chaleur = serie() * 4.0
        electricite = serie({"2025-10": 1.30, "2025-11": 1.30, "2025-12": 1.30})   # même chaleur, 30 % d'électricité en plus
        r = historique.det_historique(electricite, DJ, FIN, chaleur=chaleur)
        self.assertEqual((r["mesure"], r["persistance"], r["climat"]), ("+30 %", 3, ", à chaleur produite égale"))
        self.assertIn("rendement du mois : 3,1 au lieu de 4,0", r["detail"])
        self.assertGreater(r["kwh_proj"], r["kwh_mesure"])

    def test_mois_sans_chaleur_comptee_non_juge(self):
        chaleur = (serie() * 4.0).drop(pd.Period("2025-12", "M"))
        electricite = serie({"2025-11": 1.30, "2025-12": 1.30})
        self.assertIsNone(historique.det_historique(electricite, DJ, FIN, chaleur=chaleur))  # décembre : pas de chaleur

    def test_candidat_prend_la_chaleur_de_l_immeuble_quand_elle_existe(self):
        ctx = {"dj": DJ, "rayonnement": VIDE, "changements": {}}
        regle = {"seuil": 20.0, "persistance": 2}
        electricite = serie({"2025-11": 1.30, "2025-12": 1.30})
        im = {"id": "A", "points": [{"id": "E", "fluide": "pac_electricite", "unite": "kWh"},
                                    {"id": "C", "fluide": "pac_chaleur", "unite": "kWh"}]}
        pid, r = historique.candidat(im, "pac_electricite", {"E": electricite, "C": serie() * 4.0}, set(), ctx, FIN, {}, regle)
        self.assertEqual((pid, r["climat"]), ("E", ", à chaleur produite égale"))
        sans = historique.candidat(im, "pac_electricite", {"E": electricite}, set(), ctx, FIN, {}, regle)[1]
        self.assertEqual(sans["climat"], ", à climat égal")                 # sans compteur de chaleur : le climat
        self.assertEqual(len(MOIS), 60)


class TestElectriciteDeNuitAMeteoEgale(unittest.TestCase):
    """Un bâtiment chauffé à l'électricité consomme plus la nuit quand il fait froid : ce n'est pas une dérive."""
    FIN = pd.Timestamp("2025-01-10")

    def setUp(self):
        self.text_h = meteo_d_hiver(self.FIN, debut="2024-09-01")
        froid = (16 - self.text_h).clip(lower=0)
        self.chauffe = 5.0 + 0.8 * froid                       # kWh par heure : socle + chauffage électrique
        self.sans_chauffage = pd.Series(5.0, index=self.text_h.index)

    def nuit(self, serie, avec_meteo=True):
        return moteur.det_elec_nuit(serie, self.FIN, P, 1.20, 3, None, self.text_h if avec_meteo else None)

    def test_vague_de_froid_sans_derive_aucune_alerte(self):
        self.text_h[self.text_h.index >= "2025-01-04"] -= 6.0              # six jours de grand froid, aucune dérive
        chauffe = 5.0 + 0.8 * (16 - self.text_h).clip(lower=0)
        self.assertIsNotNone(self.nuit(chauffe, avec_meteo=False))         # ancienne comparaison : fausse alerte
        self.assertIsNone(self.nuit(chauffe))                              # à température égale : rien
        self.assertIsNone(self.nuit(self.chauffe))                         # hiver ordinaire : rien non plus

    def test_derive_reelle_detectee_a_temperature_egale(self):
        derive = self.chauffe.copy()
        derive[derive.index >= "2024-12-28"] *= 1.40
        r = self.nuit(derive)
        self.assertGreaterEqual(r["persistance"], 3)
        self.assertIn("à température extérieure égale", r["attendu"])
        self.assertGreater(r["kwh_mesure"], 0)

    def test_batiment_insensible_au_froid_regle_habituelle(self):
        self.assertIsNone(self.nuit(self.sans_chauffage))
        derive = self.sans_chauffage.copy()
        derive[derive.index >= "2025-01-03"] *= 1.40
        r = self.nuit(derive)
        self.assertEqual((r["persistance"], r["attendu"]), (7, "5,0 kW"))  # nuits de référence, sans la météo
        nuits = derive[(derive.index.hour > 1) & (derive.index.hour <= 5)]
        sensible, resultat = complements.elec_nuit_meteo(nuits.groupby(nuits.index.date).mean(), derive, self.text_h,
                                                         self.FIN, P, 1.20, 3, None)
        self.assertEqual((sensible, resultat), (False, None))


class TestMatriceFluidePas(unittest.TestCase):
    """La matrice est la source unique de l'interface et du document des méthodes."""

    def test_chaque_fluide_a_une_methode_a_chaque_pas(self):
        m = regles.matrice()
        self.assertEqual([ligne["fluide"] for ligne in m], [nom for nom, _fluides in regles.FLUIDES_MATRICE])
        for ligne in m:
            self.assertEqual([c["libelle"] for c in ligne["cases"]], ["Quart d'heure", "Heure", "Jour", "Mois"])
            for case in ligne["cases"]:
                self.assertTrue(case["regles"], (ligne["fluide"], case["libelle"]))     # aucune case sans méthode
        self.assertEqual(set(regles.METHODES), set(regles.REGLES))                      # chaque règle a son nom court

    def test_la_methode_change_avec_le_pas_du_releve(self):
        eau = {c["libelle"]: [r["id"] for r in c["regles"]] for c in regles.matrice()[0]["cases"]}
        self.assertIn("eau_nuit", eau["Heure"])
        self.assertNotIn("eau_nuit", eau["Jour"])            # la nuit ne se voit pas au jour
        self.assertIn("eau_talon", eau["Jour"])
        self.assertNotIn("eau_talon", eau["Heure"])          # à l'heure, la fuite de nuit s'en charge
        self.assertEqual(eau["Mois"], ["eau_historique"])    # au mois : le même mois des années précédentes
        solaire_ = {c["libelle"]: [r["id"] for r in c["regles"]] for c in regles.matrice()[-1]["cases"]}
        self.assertEqual(solaire_["Heure"][0], "solaire_onduleur")                      # la méthode la plus fine d'abord
        self.assertNotIn("solaire_onduleur", solaire_["Jour"])
        self.assertIn("solaire_panne", solaire_["Jour"])

    def test_regles_actives_et_compteurs_du_parc(self):
        compteurs = [("eau", 1440, 9), ("eau", 43200, 46), ("cad", 60, 4), ("cad_temperature_retour", 60, 4)]
        m = regles.matrice(set(regles.REGLES) - {"eau_historique"}, compteurs)
        self.assertEqual([c["compteurs"] for c in m[0]["cases"]], [0, 0, 9, 46])
        self.assertEqual(m[0]["cases"][3]["regles"], [])                                # règle du mois désactivée
        cad = next(ligne for ligne in m if ligne["fluide"] == "Chauffage à distance")
        self.assertEqual(cad["cases"][1]["compteurs"], 4)    # la température de retour n'est pas un second compteur
        self.assertIn("cad_retour", [r["id"] for r in cad["cases"][1]["regles"]])


if __name__ == "__main__":
    unittest.main()
