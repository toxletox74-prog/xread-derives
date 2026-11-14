"""Fenêtres de nuit à l'heure de Zurich : la nuit de 1 h à 5 h, la nuit large 22 h – 6 h et l'abaissement nocturne du
chauffage se lisent à l'heure locale, alors que les mesures restent stockées en UTC (fin d'intervalle)."""
import unittest

import numpy as np
import pandas as pd
import commun  # noqa: F401  (chemin du projet)

from vigie import calendrier, moteur

P = {"heures_nuit": [1, 5], "fenetre_analyse_jours": 30}


def heures_utc(debut, fin):
    """Index horaire UTC naïf (fin d'intervalle), comme les séries du moteur."""
    return pd.date_range(debut, fin, freq="h")


def eau(index, profil):
    """Débit horaire (m³/h) : `profil(heure locale)` en l/h, à chaque heure de l'index UTC."""
    return pd.Series([profil(h) / 1000 for h in calendrier.locale(index).hour], index=index)


def habitee(h):
    """Immeuble sain : rien de 1 h à 5 h (heure de Zurich), puis les occupants se lèvent."""
    return 0.0 if 1 < h <= 5 else 300.0


class TestHeureLocale(unittest.TestCase):
    def test_ete_et_hiver(self):
        index = pd.DatetimeIndex(["2026-01-15 03:00", "2026-07-15 03:00"])  # 3 h UTC
        self.assertEqual(list(calendrier.locale(index).hour), [4, 5])       # 4 h l'hiver, 5 h l'été à Zurich

    def test_changements_d_heure(self):
        mars = calendrier.locale(heures_utc("2026-03-28 23:00", "2026-03-29 04:00"))
        self.assertEqual(list(mars.hour), [0, 1, 3, 4, 5, 6])               # 2 h n'existe pas : nuit de 23 h
        octobre = calendrier.locale(heures_utc("2026-10-24 22:00", "2026-10-25 04:00"))
        self.assertEqual(list(octobre.hour), [0, 1, 2, 2, 3, 4, 5])         # 2 h revient deux fois : nuit de 25 h

    def test_abaissement_nocturne_de_22_h_a_5_h_locales(self):
        ete = pd.DatetimeIndex(["2026-07-15 19:00", "2026-07-15 20:00", "2026-07-16 02:00", "2026-07-16 03:00"])
        self.assertEqual(list(moteur.heures_nuit_chauffe(ete)), [False, True, True, False])   # 21 h, 22 h, 4 h, 5 h
        hiver = pd.DatetimeIndex(["2026-01-15 20:00", "2026-01-15 21:00", "2026-01-16 03:00", "2026-01-16 04:00"])
        self.assertEqual(list(moteur.heures_nuit_chauffe(hiver)), [False, True, True, False])


class TestFuiteDeNuit(unittest.TestCase):
    def test_lever_d_ete_a_6_h_locales_n_est_plus_la_nuit(self):
        # Juillet : 300 l/h dès 6 h locales (heure qui finit à 4 h UTC, puis 5 h UTC). L'ancienne fenêtre 1 h – 5 h UTC
        # couvrait 3 h – 7 h locales ; le minimum de nuit reste nul parce que la fenêtre s'arrête à 5 h locales.
        index = heures_utc("2026-06-20 01:00", "2026-07-20 06:00")
        s = eau(index, habitee)
        self.assertGreater(s[index.hour == 4].min(), 0.2)   # les occupants consomment bien à 4 h UTC
        self.assertIsNone(moteur.det_eau_nuit(s, P))
        # même immeuble dont les occupants se lèveraient une heure plus tôt : toujours hors de la fenêtre de nuit
        self.assertIsNone(moteur.det_eau_nuit(eau(index, lambda h: 0.0 if 1 < h <= 4 else 300.0), P))

    def test_matin_d_ete_pris_pour_la_nuit_avec_une_fenetre_utc(self):
        # Cas que la fenêtre UTC ratait (31 nuits de « fuite » à 300 l/h avec l'ancien moteur) : des occupants actifs dès
        # 2 h locales remplissent toute la fenêtre 1 h – 5 h UTC (3 h – 7 h locales). À l'heure de Zurich, l'heure qui
        # finit à 2 h reste à zéro : pas de fuite.
        index = heures_utc("2026-06-20 01:00", "2026-07-20 06:00")
        s = eau(index, lambda h: 0.0 if h <= 2 else 300.0)
        self.assertGreater(s[(index.hour > 1) & (index.hour <= 5)].min(), 0.2)
        self.assertIsNone(moteur.det_eau_nuit(s, P))

    def fuite(self, debut, fin, depuis):
        index = heures_utc(debut, fin)
        s = eau(index, habitee)
        s[index >= pd.Timestamp(depuis)] += 0.095   # fuite continue de 95 l/h
        return moteur.det_eau_nuit(s, P)

    def test_fuite_detectee_de_la_meme_facon_en_janvier_et_en_juillet(self):
        janvier = self.fuite("2025-12-10 01:00", "2026-01-20 06:00", "2026-01-15 12:00")
        juillet = self.fuite("2026-06-10 01:00", "2026-07-20 05:00", "2026-07-15 12:00")   # 7 h locales aussi
        for r, debut in ((janvier, "2026-01-16"), (juillet, "2026-07-16")):
            self.assertEqual((r["persistance"], r["debut"], r["mesure"], r["attendu"]), (5, debut, "95 l/h", "0 l/h"))
        self.assertAlmostEqual(janvier["m3_j"], juillet["m3_j"])
        # chiffrage depuis minuit LOCAL de la première nuit, jusqu'à 7 h locales le dernier jour : même durée
        self.assertEqual((janvier["heures_mesurees"], juillet["heures_mesurees"]), (104, 104))

    def test_nuit_de_23_h_en_mars_jugee_sur_trois_heures(self):
        # 29 mars 2026 : 2 h n'existe pas, la nuit compte 3 relevés (3 h, 4 h, 5 h) = le minimum exigé (3 sur 4)
        r = self.fuite("2026-02-20 01:00", "2026-03-30 06:00", "2026-03-27 12:00")
        self.assertEqual((r["persistance"], r["debut"], r["mesure"]), (3, "2026-03-28", "95 l/h"))
        # un relevé perdu cette nuit-là : 2 heures sur 4, la nuit n'est pas jugée (elle est sautée, pas comptée)
        index = heures_utc("2026-02-20 01:00", "2026-03-30 06:00")
        s = eau(index, habitee)
        s[index >= pd.Timestamp("2026-03-27 12:00")] += 0.095
        s[pd.Timestamp("2026-03-29 02:00")] = np.nan   # 4 h locales
        self.assertIsNone(moteur.det_eau_nuit(s, P))                 # 2 nuits jugées seulement : pas encore d'alerte
        r = moteur.det_eau_nuit(s, P, persistance=2)
        self.assertEqual((r["persistance"], r["debut"]), (2, "2026-03-28"))   # nuits du 28 et du 30, sans rupture

    def test_nuit_de_25_h_en_octobre_jugee_sur_cinq_heures(self):
        # 25 octobre 2026 : 2 h revient deux fois, la nuit compte 5 relevés ; une seule nuit, sans doublon ni trou
        r = self.fuite("2026-09-20 01:00", "2026-10-27 06:00", "2026-10-23 12:00")
        self.assertEqual((r["persistance"], r["debut"], r["mesure"]), (4, "2026-10-24", "95 l/h"))
        index = heures_utc("2026-09-20 01:00", "2026-10-27 06:00")
        self.assertIsNone(moteur.det_eau_nuit(eau(index, habitee), P))   # immeuble sain : rien aux changements d'heure


class TestElectriciteDeNuit(unittest.TestCase):
    @staticmethod
    def elec(debut, fin, depuis=None):
        """3 kW de base, 9 kW de plus de 6 h à 23 h (heure de Zurich) ; dérive : +1,5 kW de 22 h à 6 h locales."""
        index = heures_utc(debut, fin)
        h = calendrier.locale(index).hour
        s = pd.Series(np.where((h > 6) & (h <= 23), 12.0, 3.0), index=index)
        if depuis:
            s[(index >= pd.Timestamp(depuis)) & ((h > 22) | (h <= 6))] += 1.5
        return s

    def test_matin_d_ete_pas_pris_pour_une_hausse_de_nuit(self):
        # L'heure d'été arrive le 29 mars : avec une fenêtre UTC, la nuit « 1 h – 5 h » glissait sur 3 h – 7 h locales
        # et attrapait le lever de 7 h (12 kW) : +75 % d'un coup sur des nuits pourtant identiques.
        fin = pd.Timestamp("2026-04-08 06:00")
        s = self.elec("2026-01-01 01:00", fin)
        self.assertGreater(s[s.index.hour == 5].iloc[-1], 10)   # 5 h UTC = 7 h locales en avril : occupants levés
        self.assertIsNone(moteur.det_elec_nuit(s, fin, P))

    def test_hausse_de_nuit_identique_en_janvier_et_en_juillet(self):
        janvier = moteur.det_elec_nuit(self.elec("2025-10-01 01:00", "2026-01-20 06:00", "2026-01-10 12:00"),
                                       pd.Timestamp("2026-01-20 06:00"), P)
        juillet = moteur.det_elec_nuit(self.elec("2026-04-01 01:00", "2026-07-20 06:00", "2026-07-10 12:00"),
                                       pd.Timestamp("2026-07-20 06:00"), P)
        for r, debut in ((janvier, "2026-01-11"), (juillet, "2026-07-11")):
            self.assertEqual((r["persistance"], r["debut"], r["mesure"], r["attendu"]), (10, debut, "4,5 kW", "3,0 kW"))
            self.assertAlmostEqual(r["delta_kw"], 1.5)

    def test_changements_d_heure_sans_fausse_alerte(self):
        for debut, fin in (("2026-01-01 01:00", "2026-03-31 06:00"), ("2026-08-01 01:00", "2026-10-28 06:00")):
            self.assertIsNone(moteur.det_elec_nuit(self.elec(debut, fin), pd.Timestamp(fin), P))


if __name__ == "__main__":
    unittest.main()
