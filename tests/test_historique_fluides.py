"""Historique du même mois étendu (chauffage à distance, électricité, eau, solaire), ses garde-fous, et le
calendrier des jours ouvrés dans la signature de chauffage."""
import unittest

import numpy as np
import pandas as pd
from commun import base_exemple, base_vide
from test_historique import DJ, FIN, MOIS, serie

from vigie import calendrier, historique, moteur, parc, regles, service

VIDE = pd.Series(dtype=float)


class TestGardeFous(unittest.TestCase):
    """Une année anormale ou un changement d'installation ne doivent pas passer pour une dérive."""

    def test_reference_prudente_avec_deux_annees(self):
        self.assertEqual(historique.reference_prudente([10, 30, 20]), 20)          # médiane
        self.assertEqual(historique.reference_prudente([10, 30]), 30)              # excès : la plus haute des deux
        self.assertEqual(historique.reference_prudente([10, 30], sens=-1), 10)     # manque : la plus basse

    def test_une_seule_annee_de_reference_ne_suffit_pas(self):
        s, dj = serie()["2024-01":], DJ["2024-01":]                                # 2 ans : un seul « même mois »
        self.assertIsNone(historique.attendu_mois(s, dj, pd.Period("2025-12", "M")))
        self.assertIsNone(historique.det_historique(s * 2, dj, FIN))

    def test_annee_de_fermeture_dans_la_reference_sans_fausse_alerte(self):
        s = serie({f"2021-{m:02d}": 0.4 for m in range(1, 6)})                     # site fermé de janvier à mai 2021
        for fin in ("2022-06-01", "2023-06-01", "2024-06-01"):                     # les années suivantes sont normales
            vu = s[s.index < pd.Period(fin[:7], "M")]
            self.assertIsNone(historique.det_historique(vu, DJ, pd.Timestamp(fin)), fin)
            self.assertIsNone(historique.det_historique(vu, VIDE, pd.Timestamp(fin), seuil_pct=30), fin)

    def test_changement_d_installation_la_reference_ne_remonte_pas_avant(self):
        s = serie({str(m): 2.0 for m in MOIS if m >= pd.Period("2023-01", "M")})   # PAC posée en janvier 2023 : × 2
        sans = historique.det_historique(s[:"2023-12"], DJ, pd.Timestamp("2024-01-01"))
        self.assertTrue(sans["mesure"].startswith("+10"), sans["mesure"])          # environ +100 % sans la date du changement
        depuis = pd.Period("2023-02", "M")
        for fin in ("2024-01-01", "2025-01-01", "2026-01-01"):                     # avec : jamais une dérive
            vu = s[s.index < pd.Period(fin[:7], "M")]
            self.assertIsNone(historique.det_historique(vu, DJ, pd.Timestamp(fin), depuis=depuis), fin)

    def test_changements_lus_dans_la_table_des_installations(self):
        cx = base_vide("historique-installations")
        cx.execute("PRAGMA foreign_keys = OFF")  # seules les dates des installations comptent ici
        cx.executemany("INSERT INTO installation (id, immeuble_id, type, libelle, mise_en_service, retrait) VALUES (?,?,?,?,?,?)",
                       [("I1", "A", "chaudiere_mazout", "Chaudière", "1996-01", "2022-07"),
                        ("I2", "A", "pac_sol_eau", "PAC", "2022-09", None), ("I3", "B", "chaudiere_gaz", "Chaudière", "2005-01", None)])
        self.assertEqual(historique.changements(cx), {"A": pd.Period("2022-10", "M"), "B": pd.Period("2005-02", "M")})
        self.assertEqual(historique.changements(None), {})


class TestAutresFluides(unittest.TestCase):
    def test_eau_chiffree_en_volume_sans_climat_avec_un_exces_minimal(self):
        fuite = pd.Series(500.0, index=MOIS)
        fuite["2025-10":] *= 1.30
        r = historique.det_historique(fuite, VIDE, FIN, unite="m3", grandeur="m3", exces_min_j=0.48)
        self.assertEqual((r["mesure"], r["persistance"], r["climat"]), ("+30 %", 3, ""))
        self.assertAlmostEqual(r["m3_mesure"], 450.0)
        self.assertAlmostEqual(r["m3_j"], 150 / 31)
        self.assertIn("m³ en décembre 2025", r["detail"])
        self.assertNotIn("climat", r["detail"])
        self.assertNotIn("kwh_mesure", r)
        petit = pd.Series(10.0, index=MOIS)
        petit["2025-10":] *= 1.50                                                  # +5 m³ par mois : sous 480 l/jour
        self.assertIsNone(historique.det_historique(petit, VIDE, FIN, grandeur="m3", exces_min_j=0.48))

    def test_reglages_par_defaut_des_sept_regles(self):
        r = {c: (x["fluide_point"], x["seuil"], x["persistance"], x["unite_persistance"]) for c, x in historique.REGLES.items()}
        self.assertEqual(r, {"gaz_historique": ("gaz", 20.0, 2, "mois"), "pac_historique": ("pac_electricite", 20.0, 2, "mois"),
                             "cad_historique": ("cad", 20.0, 2, "mois"), "chaleur_historique": ("chaleur", 20.0, 2, "mois"),
                             "elec_historique": ("electricite", 20.0, 3, "mois"),
                             "eau_historique": ("eau", 20.0, 2, "mois"), "solaire_historique": ("solaire", 15.0, 2, "mois")})
        self.assertEqual(set(historique.TEXTES), set(historique.REGLES))
        self.assertEqual(set(historique.FLUIDES.values()), set(historique.REGLES))
        self.assertTrue(historique.TEXTES["eau_historique"]["sinistre"])
        self.assertTrue(historique.doublon("solaire_historique", {"solaire_panne"}))
        self.assertTrue(historique.doublon("eau_historique", {"eau_talon"}))
        self.assertFalse(historique.doublon("solaire_historique", {"solaire_onduleur"}))

    def test_candidat_choisit_le_bon_reglage_par_fluide(self):
        ctx = {"dj": DJ, "rayonnement": VIDE, "changements": {}}
        regle = {"seuil": 20.0, "persistance": 2}
        eau = pd.Series(500.0, index=MOIS)
        eau["2025-11":] *= 1.30
        im = {"id": "A", "points": [{"id": "E", "fluide": "eau", "unite": "m3"}, {"id": "C", "fluide": "cad", "unite": "kWh"}]}
        mensuelles = {"E": eau, "C": serie({"2025-11": 1.30, "2025-12": 1.30})}
        pid, r = historique.candidat(im, "eau", mensuelles, set(), ctx, FIN, {}, regle)
        self.assertEqual((pid, r["mesure"], round(r["m3_mesure"])), ("E", "+30 %", 300))
        pid, r = historique.candidat(im, "cad", mensuelles, set(), ctx, FIN, {}, regle)
        self.assertEqual((pid, r["mesure"], r["climat"]), ("C", "+30 %", ", à climat égal"))
        self.assertEqual(historique.candidat(im, "cad", mensuelles, {"C"}, ctx, FIN, {}, regle), (None, None))  # en défaut
        avec = {**ctx, "changements": {"A": pd.Period("2025-06", "M")}}          # installation changée en mai 2025
        self.assertIsNone(historique.candidat(im, "cad", mensuelles, set(), avec, FIN, {}, regle)[1])


RAY_TYPE = np.array([36, 50, 117, 159, 178, 211, 200, 179, 117, 68, 46, 20], dtype=float)
ENSOLEILLEMENT = {2021: 1.00, 2022: 1.08, 2023: 0.95, 2024: 1.02, 2025: 0.85}   # 2025 : année peu ensoleillée
RAY = pd.Series([RAY_TYPE[m.month - 1] * ENSOLEILLEMENT[m.year] for m in MOIS], index=MOIS)


def production(pertes=None, rendement=90.0, decote=0.005):
    """Production mensuelle = rendement × rayonnement, décote annuelle comprise ; `pertes` = {mois: facteur}."""
    s = pd.Series([rendement * RAY[m] * (1 - decote) ** (m.year - 2021 + (m.month - 1) / 12) for m in MOIS], index=MOIS)
    for mois, facteur in (pertes or {}).items():
        s[pd.Period(mois, "M")] *= facteur
    return s


class TestSolaireHistorique(unittest.TestCase):
    FIN = pd.Timestamp("2025-09-01")

    def test_annee_peu_ensoleillee_et_decote_prevue_sans_alerte(self):
        self.assertIsNone(historique.det_solaire_historique(production()[:"2025-08"], RAY, self.FIN))
        vieillie = production(decote=0.02)[:"2025-08"]                              # modules qui perdent 2 % par an
        self.assertIsNone(historique.det_solaire_historique(vieillie, RAY, self.FIN, decote=0.02))

    def test_perte_de_vingt_cinq_pour_cent_a_ensoleillement_egal(self):
        s = production({"2025-07": 0.75, "2025-08": 0.75})[:"2025-08"]
        r = historique.det_solaire_historique(s, RAY, self.FIN)
        self.assertEqual((r["mesure"], r["persistance"], r["debut"]), ("−25 %", 2, "2025-07-01"))
        self.assertIn("rayonnement du mois : 152 kWh/m²", r["detail"])            # août 2025 : 179 × 0,85
        attendu = sum(production()[pd.Period(m, "M")] for m in ("2025-07", "2025-08"))
        self.assertAlmostEqual(r["kwh_mesure"], 0.25 * attendu, delta=0.01 * attendu)
        self.assertGreater(r["kwh_proj"], r["kwh_mesure"])
        un_mois = production({"2025-08": 0.75})[:"2025-08"]
        self.assertIsNone(historique.det_solaire_historique(un_mois, RAY, self.FIN))                 # persistance
        sous_le_seuil = production({"2025-07": 0.9, "2025-08": 0.9})[:"2025-08"]
        self.assertIsNone(historique.det_solaire_historique(sous_le_seuil, RAY, self.FIN))           # −10 % < 15 %

    def test_mois_trop_peu_ensoleilles_non_juges(self):
        s = production({"2024-12": 0.3, "2025-01": 0.3})[:"2025-01"]               # neige sur les modules, par exemple
        self.assertIsNone(historique.det_solaire_historique(s, RAY, pd.Timestamp("2025-02-01")))
        self.assertIsNone(historique.attendu_solaire(production(), RAY, pd.Period("2025-12", "M")))
        self.assertIsNotNone(historique.attendu_solaire(production(), RAY, pd.Period("2025-06", "M")))

    def test_rayonnement_mensuel_du_lot_sinon_de_la_station(self):
        heures = pd.date_range("2025-06-01 01:00", "2025-07-01 00:00", freq="h")
        r = historique.rayonnement(None, pd.Series(250.0, index=heures))           # 250 W/m² en continu
        self.assertEqual({str(k): round(v) for k, v in r.items()}, {"2025-06": 180})  # 0,25 kW × 24 h × 30 jours
        cx = base_vide("historique-rayonnement")
        cx.execute("INSERT INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                   (historique.SERIE_RAYONNEMENT, "2025-06", 211.0, "kWh/m²", "test"))
        self.assertEqual(historique.contexte(cx)["rayonnement"].to_dict(), {pd.Period("2025-06", "M"): 211.0})


class TestCalendrier(unittest.TestCase):
    def test_type_de_jour_du_calendrier_sinon_du_jour_de_la_semaine(self):
        jours = pd.to_datetime(["2025-03-14", "2025-03-15", "2025-04-22", "2025-08-01", "2026-05-04"])
        cal = {pd.Timestamp("2025-03-14"): (True, False), pd.Timestamp("2025-03-15"): (False, False),
               pd.Timestamp("2025-04-22"): (True, True), pd.Timestamp("2025-08-01"): (False, True)}   # 1er août : férié
        self.assertEqual(list(calendrier.classes(jours, cal)), ["O", "N", "V", "N", "O"])   # 04.05.2026 : un lundi
        self.assertEqual(list(calendrier.classes(jours)), ["O", "N", "O", "O", "O"])        # sans calendrier
        cx = base_vide("calendrier")
        cx.executemany("INSERT INTO reference (serie, periode, valeur, unite, source) VALUES (?,?,?,?,?)",
                       [("jour_ouvre", "2025-04-22", 1.0, "", "t"), ("jour_vacances_scolaires", "2025-04-22", 1.0, "", "t"),
                        ("jour_ouvre", "2025-04-26", 0.0, "", "t")])
        self.assertEqual(calendrier.lire(cx), {pd.Timestamp("2025-04-22"): (True, True),
                                               pd.Timestamp("2025-04-26"): (False, False)})
        self.assertEqual(calendrier.lire(None), {})

    def test_immeuble_sensible_seulement_si_l_ecart_se_voit_dans_sa_reference(self):
        types = np.array(["O"] * 20 + ["N"] * 12)
        self.assertTrue(calendrier.sensible([1.15] * 20 + [0.78] * 12, types))     # bureaux : week-ends bien plus bas
        self.assertFalse(calendrier.sensible([1.02] * 20 + [0.99] * 12, types))    # logements : pas d'effet
        self.assertFalse(calendrier.sensible([1.15] * 20 + [0.78] * 5, types[:25]))  # trop peu de jours non ouvrés
        ref = np.array(["O", "V", "N", "O"])
        self.assertEqual([m.tolist() for m in calendrier.comparables(ref, "V")],
                         [[False, True, False, False], [True, True, False, True]])
        self.assertEqual([m.tolist() for m in calendrier.comparables(ref, "N")], [[False, False, True, False]])

    def test_signature_de_chauffage_jugee_entre_jours_de_meme_type(self):
        fin = pd.Timestamp("2025-03-01")
        heures = pd.date_range("2024-11-01 01:00", fin, freq="h")
        jour = heures.dayofyear.to_numpy()
        # hiver doux ou froid selon les jours (vague de 9,3 jours, sans lien avec la semaine) : des jours comparables existent
        text_h = pd.Series(9.0 - 7.0 * np.cos(2 * np.pi * (jour - 15) / 365) + 4.0 * np.sin(2 * np.pi * jour / 9.3), index=heures)
        jours = pd.date_range("2024-11-01", "2025-02-28", freq="D")
        dj = (16 - text_h.resample("D").mean()).clip(lower=0).reindex(jours)
        occupation = np.where(jours.dayofweek < 5, 1.15, 0.75)                     # bureaux : week-ends 35 % plus bas
        sain = pd.Series((100 + 40 * dj.to_numpy()) * occupation, index=jours)
        P = service.defauts()["parametres"]
        self.assertIsNone(moteur.det_chaleur_signature(sain, text_h, fin, P, journalier=True))
        derive = sain.copy()
        derive[jours >= "2025-02-10"] *= 1.30                                      # +30 % les 19 derniers jours
        r = moteur.det_chaleur_signature(derive, text_h, fin, P, journalier=True)
        self.assertIsNotNone(r)
        self.assertGreaterEqual(r["persistance"], 7)
        sans, calendrier.sensible = calendrier.sensible, lambda *a: False          # comme avant : tous jours confondus
        try:
            self.assertIsNone(moteur.det_chaleur_signature(derive, text_h, fin, P, journalier=True))  # dérive manquée
        finally:
            calendrier.sensible = sans
        garde, moteur.JUGE_RECENT_MAX_J = moteur.JUGE_RECENT_MAX_J, -1             # dernier jour jugeable trop ancien
        try:
            self.assertIsNone(moteur.det_chaleur_signature(derive, text_h, fin, P, journalier=True))  # pas de conclusion
        finally:
            moteur.JUGE_RECENT_MAX_J = garde


class TestCouvertureDesRegles(unittest.TestCase):
    """Alerte quand une règle ne correspond pas à la granularité des compteurs de son fluide."""

    COMPTEURS = [("eau", 1440, 9), ("eau", 43200, 46), ("gaz", 1440, 6), ("gaz", 43200, 20), ("electricite", 43200, 48),
                 ("mazout", 43200, 7), ("meteo", 60, 1), ("cad_debit", 60, 4)]

    def regles(self, *inactives):
        return [{"id": c, "active": c not in inactives, "libelle": r["libelle"], "fluide_point": r["fluide_point"]}
                for c, r in regles.REGLES.items()]

    def test_releve_exige_et_compteurs_concernes_par_regle(self):
        a = regles.applicabilite("eau_nuit", self.COMPTEURS)
        self.assertEqual(a, {"releve": "à l'heure ou plus fin", "compteurs": 0, "compteurs_fluide": 55, "trop_grossiers": 55})
        horaire = regles.applicabilite("eau_talon", [("eau", 60, 4)])   # eau à l'heure : la fuite de nuit s'en charge
        self.assertEqual((horaire["compteurs"], horaire["trop_grossiers"]), (0, 0))
        self.assertEqual(regles.applicabilite("eau_talon", self.COMPTEURS)["compteurs"], 9)       # au jour seulement
        self.assertEqual(regles.applicabilite("eau_historique", self.COMPTEURS)["compteurs"], 55)  # au mois ou plus fin
        self.assertEqual(set(regles.PAS_REGLES), set(regles.REGLES))                               # aucune règle oubliée

    def test_regle_sans_effet_partielle_et_compteurs_sans_regle(self):
        c = regles.couverture(self.COMPTEURS, self.regles(), {"mazout": "Mazout"})
        par_regle = {a["regle"]: a for a in c["alertes"]}
        self.assertEqual(par_regle["eau_nuit"]["niveau"], "sans_effet")
        self.assertIn("aucun de vos 55 compteur(s) de ce fluide (9 au jour, 46 au mois)", par_regle["eau_nuit"]["texte"])
        self.assertIn("exige un relevé à l'heure ou plus fin", par_regle["eau_nuit"]["texte"])
        self.assertEqual(par_regle["elec_nuit"]["niveau"], "sans_effet")
        self.assertEqual(par_regle["gaz_signature"]["niveau"], "partielle")
        self.assertIn("tourne sur 6 compteur(s) sur 26 : les autres (20 au mois)", par_regle["gaz_signature"]["texte"])
        self.assertNotIn("gaz_historique", par_regle)                    # couvre tous les compteurs de gaz : rien à signaler
        self.assertEqual(c["alertes"][0]["niveau"], "sans_effet")         # les plus graves en premier
        self.assertEqual(c["sans_regle"], [{"fluide": "Mazout", "pas": "au mois", "compteurs": 7}])  # ni météo ni débit
        self.assertEqual((c["sans_effet"], c["compteurs_sans_regle"]), (3, 7))   # eau la nuit, électricité nuit et jour

    def test_regle_desactivee_ses_compteurs_ne_sont_plus_couverts(self):
        c = regles.couverture([("electricite", 43200, 48)], self.regles("elec_historique"), {})
        self.assertEqual([a["regle"] for a in c["alertes"]], ["elec_nuit", "elec_jour"])  # heure et jour : trop fins
        self.assertEqual(c["compteurs_sans_regle"], 48)                   # plus aucune règle active sur ces compteurs

    def test_liste_des_regles_du_serveur_porte_la_couverture(self):
        cx = base_exemple("couverture")                                  # exemple : compteurs relevés à l'heure
        r = parc.liste_regles(cx, service.defauts())
        nuit = next(x for x in r["regles"] if x["id"] == "eau_nuit")
        self.assertGreater(nuit["compteurs"], 0)
        self.assertEqual((nuit["releve"], nuit["pas_releve"], nuit["fluide_point"]), ("à l'heure ou plus fin", [0, 60], "eau"))
        self.assertEqual(r["couverture"]["sans_effet"], 0)                # aucune règle horaire sans compteur horaire


if __name__ == "__main__":
    unittest.main()
