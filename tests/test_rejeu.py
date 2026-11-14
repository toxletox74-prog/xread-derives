"""Rejeu de la détection sur une période passée, et règles complémentaires (eau au jour, retour du CAD, injection)."""
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from commun import base_exemple, base_vide

from vigie import bons, complements, db, meteo, moteur, rejeu, service

P = {"fenetre_analyse_jours": 30}
FIN = pd.Timestamp("2025-09-01")


def jours(n, valeurs):
    """Série journalière (m³ par jour) des n derniers jours avant FIN."""
    return pd.Series(valeurs, index=pd.date_range(end=FIN - pd.Timedelta(days=1), periods=n, freq="D"))


def heures(n_jours, fonction):
    """Série horaire (fin d'intervalle, UTC naïf) des n derniers jours avant FIN : fonction(horodatage) -> valeur."""
    index = pd.date_range(end=FIN, periods=n_jours * 24, freq="h")
    return pd.Series([fonction(t) for t in index], index=index)


class TestEauAuJour(unittest.TestCase):
    """Semaine type : 3 m³ les jours ouvrés, 0,5 m³ le week-end (niveau de base 500 l/jour)."""

    def semaine(self, n):
        index = pd.date_range(end=FIN - pd.Timedelta(days=1), periods=n, freq="D")
        return np.array([0.5 if t.dayofweek >= 5 else 3.0 for t in index])

    def test_fuite_continue_releve_le_niveau_de_base(self):
        v = self.semaine(120)
        v[-12:] += 3.0  # fuite de 3 000 l/jour depuis 12 jours
        r = complements.det_eau_talon(jours(120, v), FIN, P)
        # le minimum de 7 jours est relevé dès que la fenêtre ne contient plus de week-end normal (dernier : 16-17 août) ;
        # le début retenu est le plus tôt possible : le lundi 18, deux jours avant la fuite réelle
        self.assertEqual((r["persistance"], r["debut"], r["attendu"]), (8, "2025-08-18", "500 l/jour"))
        self.assertAlmostEqual(r["m3_j"], 2.875, places=2)
        self.assertAlmostEqual(r["m3_mesure"], 2.875 * 14, places=1)  # excès × jours mesurés depuis le début

    def test_pic_d_usage_ou_semaine_normale_sans_alerte(self):
        v = self.semaine(120)
        self.assertIsNone(complements.det_eau_talon(jours(120, v), FIN, P))
        v[-5] += 600.0  # remplissage d'un bassin : un pic ne relève pas le minimum de la semaine
        self.assertIsNone(complements.det_eau_talon(jours(120, v), FIN, P))
        self.assertIsNone(complements.det_eau_talon(jours(20, self.semaine(20)), FIN, P))  # référence trop courte


class TestRetourCad(unittest.TestCase):
    def series(self, hausse):
        text = heures(120, lambda t: 8.0 + 4 * np.sin(t.dayofyear / 9))
        aller = heures(120, lambda t: 80.0)
        retour = heures(120, lambda t: 50.0 - 0.2 * (8.0 + 4 * np.sin(t.dayofyear / 9)))
        retour.iloc[-10 * 24:] += hausse
        return aller, retour, text

    def test_retour_trop_chaud_a_temperature_exterieure_egale(self):
        r = complements.det_cad_retour(*self.series(8.0), FIN, P)
        self.assertEqual((r["persistance"], r["debut"]), (10, "2025-08-22"))
        self.assertIn("°C à température extérieure égale", r["attendu"])
        self.assertIn("L'écart entre l'aller et le retour", r["detail"])

    def test_retour_normal_ou_hausse_sous_le_seuil_sans_alerte(self):
        self.assertIsNone(complements.det_cad_retour(*self.series(0.0), FIN, P))
        self.assertIsNone(complements.det_cad_retour(*self.series(3.0), FIN, P))  # seuil : 5 °C


class TestInjection(unittest.TestCase):
    def series(self, production_fin):
        # 90 jours : production 100 kWh à midi et injection 60 ; les 10 premiers jours, 5 kWh et aucune injection.
        # Les 5 derniers jours : production donnée, injection nulle.
        debut = FIN - pd.Timedelta(days=90)
        pv = heures(90, lambda t: (5.0 if t < debut + pd.Timedelta(days=10) else 100.0) if t.hour == 12 else 0.0)
        inj = heures(90, lambda t: (0.0 if t < debut + pd.Timedelta(days=10) else 60.0) if t.hour == 12 else 0.0)
        derniers = pv.index >= FIN - pd.Timedelta(days=5)
        pv[derniers & (pv.index.hour == 12)] = production_fin
        inj[derniers] = 0.0
        return pv, inj

    def test_injection_nulle_alors_que_l_installation_produit(self):
        constat = complements.det_injection_nulle(*self.series(100.0), FIN, P)
        self.assertIn("nulle depuis 5 jours", constat)
        self.assertIn("60 % de la production", constat)

    def test_petite_production_sans_injection_reste_normale(self):
        self.assertIsNone(complements.det_injection_nulle(*self.series(6.0), FIN, P))  # comme les jours de référence


class TestRecalage(unittest.TestCase):
    def test_attendu_recale_sur_les_jours_de_meteo_comparable(self):
        index = pd.date_range("2025-01-01", periods=60, freq="D")
        j = pd.DataFrame({"q": 30.0, "att_mesure": 10.0, "att": 10.0, "n": 24, "dj": 0.0, "juge": True}, index=index)
        j.loc[index[-1], "dj"] = 12.0  # jour froid : aucune météo comparable dans la référence
        moteur._recaler_sur_meteo_comparable(j, index[:40])
        self.assertEqual(j["att"].iloc[45], 30.0)                      # été : attendu recalé (× 3) sur les jours comparables
        self.assertEqual((bool(j["juge"].iloc[45]), bool(j["juge"].iloc[-1])), (True, False))


class TestRejeu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cx = base_exemple("rejeu")
        cls.ref = db.referentiel(cls.cx, service.defauts())
        cls.fin = moteur.analyser(cls.cx, cls.ref)[1]

    def test_le_moteur_ne_voit_pas_le_futur(self):
        avant, vu = moteur.analyser(self.cx, self.ref, jusqua=self.fin - pd.Timedelta(days=20), gelees={})
        self.assertEqual(vu, self.fin - pd.Timedelta(days=20))
        self.assertNotIn("T8-eau_nuit", {a["id"] for a in avant})      # la fuite commence 5 nuits avant la fin

    def test_episodes_du_premier_au_dernier_jour_d_alerte(self):
        r = rejeu.rejouer(self.cx, self.ref, self.fin - pd.Timedelta(days=12), self.fin, pas_jours=3)
        self.assertEqual(r["analyses"], 5)
        e = {x["id"]: x for x in r["episodes"]}
        fuite = e["T8-eau_nuit"]
        self.assertEqual((fuite["cause"], fuite["gravite"], fuite["disparu_le"]), ("eau_nuit", "Critique", None))
        self.assertGreater(fuite["detecte_le"], fuite["debut"])        # détectée après la persistance, jamais avant le début
        self.assertGreater(fuite["m3_mesure"], 0)
        self.assertGreaterEqual(e["OB-chaleur_signature"]["jours_en_alerte"], 1)
        self.assertIsNone(rejeu.enregistrer(self.cx, r, None))
        self.assertEqual(len(db.lire_parametre(self.cx, "rejeu")["episodes"]), len(r["episodes"]))

    def test_reference_gelee_portee_par_l_alerte_et_reprise_a_l_analyse_suivante(self):
        gel = pd.Timestamp(str((self.fin - pd.Timedelta(days=90)).date()))
        alertes, _fin = moteur.analyser(self.cx, self.ref, gelees={"OB-chaleur_signature": gel})
        a = {x["id"]: x for x in alertes}
        self.assertEqual(a["OB-chaleur_signature"]["reference_gelee"], str(gel.date()))
        self.assertGreater(a["OB-chaleur_signature"]["debut"], str(gel.date()))  # début recalculé, plus tardif
        self.assertNotIn("reference_gelee", a["T8-eau_nuit"])           # règle sans référence gelée
        cx = base_vide("rejeu-gel")
        bons.synchroniser_alertes(cx, alertes)                          # comme à la fin d'un rejeu
        gelees = moteur.references_gelees(cx)
        self.assertEqual(gelees["OB-chaleur_signature"], gel)           # le gel du rejeu, pas le début recalculé
        self.assertEqual(gelees["T8-eau_nuit"], pd.Timestamp(str(a["T8-eau_nuit"]["debut"])[:10]))

    def test_compteur_pas_encore_releve_a_la_date_rejouee_n_est_pas_muet(self):
        cx = base_exemple("rejeu-demarrage")
        ref = db.referentiel(cx, service.defauts())
        cx.execute("DELETE FROM mesure WHERE point_id = 'OA_ELEC' AND ts < ?",
                   ((self.fin - pd.Timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
        cx.commit()
        avant = {a["id"] for a in moteur.analyser(cx, ref, jusqua=self.fin - pd.Timedelta(days=20), gelees={})[0]}
        self.assertNotIn("OA-donnees-OA_ELEC", avant)                  # premier relevé 10 jours plus tard
        cx.execute("DELETE FROM mesure WHERE point_id = 'OA_ELEC'")
        cx.commit()
        for date in (None, self.fin - pd.Timedelta(days=20)):           # jamais relevé : toujours signalé
            alertes = {a["id"]: a for a in moteur.analyser(cx, ref, jusqua=date, gelees={})[0]}
            self.assertEqual(alertes["OA-donnees-OA_ELEC"]["constat"], "Aucune donnée reçue.")

    def test_completude_mensuelle_comptee_en_mois_civils(self):
        pts = pd.DataFrame({"nature": "intervalle", "pas_min": [db.PAS_MENSUEL, 60.0], "fluide": ["cad", "electricite"]},
                           index=["C", "H"])
        mois = pd.date_range("2024-08-01", "2025-03-01", freq="MS")     # relevés de juillet 2024 à février 2025
        mensuel = pd.DataFrame({"ts": mois, "point_id": "C", "valeur": 100.0, "qualite": "valide"})

        def completude(date, releves):                                  # une courbe horaire porte la fin des relevés
            horaire = pd.DataFrame({"ts": [pd.Timestamp(date)], "point_id": "H", "valeur": 1.0, "qualite": "valide"})
            brut = (pts, pd.concat([releves, horaire], ignore_index=True))
            return moteur.charger_series(None, pd.Timestamp(date), brut)[2]["C"]["completude"]

        for date in ("2025-01-30", "2025-01-31", "2025-02-01", "2025-02-28"):   # le 31 : pas de relevé « manquant »
            self.assertEqual(completude(date, mensuel), 1.0, date)
        sans_octobre = mensuel[mensuel["ts"] != pd.Timestamp("2024-11-01")]
        self.assertAlmostEqual(completude("2025-01-31", sans_octobre), 5 / 6)   # un relevé réellement manquant reste compté

    def test_serie_recente_jugee_depuis_son_premier_releve(self):
        cx = base_exemple("rejeu-recent")
        cx.execute("DELETE FROM mesure WHERE point_id = 'OA_ELEC' AND ts < ?",
                   ((self.fin - pd.Timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
        cx.commit()
        ids = {a["id"] for a in moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]}
        self.assertNotIn("OA-donnees-OA_ELEC", ids)                    # 10 jours complets : pas « données incomplètes »


class TestMeteoPeriode(unittest.TestCase):
    def test_meteo_d_une_periode_passee(self):
        cx = base_vide("meteo-periode")
        fichier = ("station_abbr;reference_timestamp;tre200h0;gre000h0\n"
                   "GVE;31.12.2024 23:00;1.0;0\nGVE;01.01.2025 12:00;4.5;210\nGVE;02.01.2025 12:00;5.5;190\n")
        demandes = []

        def faux(url):
            demandes.append(url)
            return fichier
        b = meteo.charger_periode(cx, datetime(2025, 1, 1), datetime(2025, 1, 1, 23), faux,
                                  datetime(2026, 11, 13, tzinfo=timezone.utc))
        self.assertEqual((b["meteo"], b["rayonnement"]), (1, 1))        # seule la période demandée est gardée
        self.assertEqual(len(demandes), 1)
        self.assertTrue(demandes[0].endswith("ogd-smn_gve_h_historical_2020-2029.csv"))
        self.assertEqual(cx.execute("SELECT point_id, valeur FROM mesure ORDER BY point_id").fetchall(),
                         [("METEO_GVE", 4.5), ("RAYON_GVE", 210.0)])


if __name__ == "__main__":
    unittest.main()
