"""Déclarations : sourdine justifiée, travaux ou vacance datés, changement (compteur, consigne, courbe de chauffe)."""
import http.client
import json
import threading
import unittest

import numpy as np
import pandas as pd
from commun import ATTENDUES, base_exemple

from vigie import bons, db, declarations, moteur, serveur, service

P = service.defauts()["parametres"]
FIN = pd.Timestamp("2025-03-01")


def heures(n_jours, fonction):
    """Série horaire (fin d'intervalle, UTC naïf) des n derniers jours avant FIN : fonction(horodatage) -> valeur."""
    index = pd.date_range(end=FIN, periods=n_jours * 24, freq="h")
    return pd.Series([fonction(t) for t in index], index=index)


class Exemple(unittest.TestCase):
    """Base d'exemple : relevés jusqu'au 11.11.2026, sept alertes attendues sans déclaration."""

    def setUp(self):
        self.cx = base_exemple("declarations")
        self.ref = db.referentiel(self.cx, service.defauts())
        self.jour = moteur.analyser(self.cx, self.ref)[1].normalize()

    def j(self, n):
        return str((self.jour + pd.Timedelta(days=n)).date())

    def declarer(self, immeuble, **d):
        return declarations.creer(self.cx, immeuble, {"motif": "Motif du test", **d})

    def alertes(self, jusqua=None):
        return {a["id"]: a for a in moteur.analyser(self.cx, self.ref, jusqua=jusqua)[0]}


class TestSourdine(Exemple):
    def test_alerte_en_sourdine_visible_sans_bon_puis_reprise_a_l_echeance(self):
        service.analyser(self.cx)  # l'alerte existe, son bon a été préparé automatiquement (gravité élevée)
        d = self.declarer("OB", type="sourdine", cause="chaleur_signature", fin=self.j(10), motif="Essai de consigne")
        self.assertEqual(d["debut"], self.j(0))  # sans date de début : dès la date des derniers relevés analysés
        a = self.alertes()["OB-chaleur_signature"]  # la dérive reste calculée, marquée, sa référence reste gelée
        self.assertEqual(a["sourdine"], {"jusquau": self.j(10), "motif": "Essai de consigne", "declaration_id": d["id"]})
        self.assertEqual(set(self.alertes()), ATTENDUES)  # les autres alertes ne sont pas touchées
        # visible tout de suite, hors des alertes à traiter
        self.assertNotIn("OB-chaleur_signature", {x["id"] for x in bons.liste_alertes(self.cx, "ouverte")})
        muettes = bons.liste_alertes(self.cx, "sourdine")
        self.assertEqual([(x["id"], x["suivi"], x["sourdine"]["motif"]) for x in muettes],
                         [("OB-chaleur_signature", "sourdine", "Essai de consigne")])
        self.assertEqual(service.analyser(self.cx)["nouvelles"], [])
        # échéance dépassée (la date analysée est celle des relevés) : l'alerte reprend seule
        self.cx.execute("UPDATE declaration SET debut = ?, fin = ? WHERE id = ?", (self.j(-9), self.j(-1), d["id"]))
        self.assertNotIn("sourdine", self.alertes()["OB-chaleur_signature"])
        self.assertEqual(service.analyser(self.cx)["nouvelles"], ["OB-chaleur_signature"])
        self.assertIn("OB-chaleur_signature", {x["id"] for x in bons.liste_alertes(self.cx, "ouverte")})
        self.assertIn("Fin de la sourdine", bons.historique(self.cx, "OB")[0]["texte"])

    def test_derive_nee_en_sourdine_aucun_bon_prepare(self):
        declarations.creer(self.cx, "OB", {"type": "sourdine", "cause": "chaleur_signature", "debut": self.j(-3),
                                          "fin": self.j(10), "motif": "Chaudière en cours de réglage"})
        res = service.analyser(self.cx)
        self.assertNotIn("OB-chaleur_signature", res["nouvelles"])
        self.assertEqual(self.cx.execute("SELECT count(*) FROM bon WHERE alerte_id = 'OB-chaleur_signature'").fetchone()[0], 0)
        with self.assertRaisesRegex(bons.ErreurBon, "sourdine"):
            bons.creer_bon(self.cx, "OB-chaleur_signature")
        self.assertIn("en sourdine jusqu'au", " ".join(e["texte"] for e in bons.historique(self.cx, "OB")))
        # supprimer la déclaration rend l'alerte tout de suite
        declarations.supprimer(self.cx, declarations.liste(self.cx, "OB")[0]["id"])
        self.assertIn("OB-chaleur_signature", {x["id"] for x in bons.liste_alertes(self.cx, "ouverte")})

    def test_une_sourdine_ne_vaut_qu_a_partir_de_sa_date(self):
        self.declarer("OA", type="sourdine", cause="elec_nuit", debut=self.j(-1), fin=self.j(30))
        self.assertIn("sourdine", self.alertes()["OA-elec_nuit"])
        avant = self.alertes(jusqua=self.jour - pd.Timedelta(days=2))  # rejeu à une date antérieure à la déclaration
        self.assertNotIn("sourdine", avant["OA-elec_nuit"])

    def test_saisie_refusee_sans_motif_sans_fin_ou_regle_inconnue(self):
        for d in ({"type": "sourdine", "cause": "chaleur_signature", "fin": self.j(5), "motif": " "},
                  {"type": "sourdine", "cause": "chaleur_signature", "motif": "x"},
                  {"type": "sourdine", "cause": "inconnue", "fin": self.j(5), "motif": "x"},
                  {"type": "sourdine", "cause": "chaleur_signature", "fin": self.j(-5), "motif": "x"},
                  {"type": "travaux", "debut": self.j(0), "motif": "x"},
                  {"type": "changement", "debut": "12.11.2026", "motif": "x"},
                  {"type": "changement", "debut": self.j(0), "point_id": "T8_EAU", "motif": "x"},  # compteur d'un autre immeuble
                  {"type": "pause", "debut": self.j(0), "motif": "x"}):
            with self.assertRaises(declarations.ErreurDeclaration, msg=d):
                declarations.creer(self.cx, "OB", d)
        with self.assertRaises(declarations.ErreurDeclaration):
            declarations.creer(self.cx, "ZZ", {"type": "travaux", "debut": self.j(0), "fin": self.j(1), "motif": "x"})


class TestTravauxEtVacance(Exemple):
    def test_regles_d_energie_suspendues_fuites_et_donnees_maintenues(self):
        self.declarer("T8", type="travaux", debut=self.j(-5), fin=self.j(20))
        self.declarer("R41", type="vacance", debut=self.j(-40), fin=self.j(0))
        # T8 : rendement de la PAC et panne solaire suspendus, fuite d'eau maintenue ; R41 : compteur muet maintenu
        self.assertEqual(set(self.alertes()), ATTENDUES - {"T8-pac_cop", "T8-solaire_panne", "R41-chaleur_vide"})

    def test_periode_a_venir_sans_effet(self):
        self.declarer("T8", type="travaux", debut=self.j(1), fin=self.j(20))
        self.assertEqual(set(self.alertes()), ATTENDUES)

    def test_jours_de_la_periode_retires_des_series_d_energie_seulement(self):
        self.declarer("OB", type="vacance", debut="2026-08-10", fin="2026-09-20")
        ref = {"immeubles": [{"id": "OB", "points": [{"id": "CHAL", "fluide": "chaleur"}, {"id": "EAU", "fluide": "eau"},
                                                     {"id": "GAZ", "fluide": "gaz"}, {"id": "ELEC", "fluide": "electricite"}]}]}
        h = pd.Series(1.0, index=pd.date_range("2026-07-01 01:00", "2026-11-01", freq="h"))
        jours = pd.Series(1.0, index=pd.date_range("2026-07-01", "2026-10-31", freq="D"))
        mois = pd.Series(1.0, index=pd.period_range("2026-05", "2026-10", freq="M"))
        series, journ, mensuelles = {"CHAL": h, "EAU": h}, {"ELEC": jours}, {"GAZ": mois}
        declarations.preparer(self.cx, ref, pd.Timestamp("2026-11-11 06:00"), None, {}, series, journ, mensuelles)
        manquants = series["CHAL"][series["CHAL"].isna()].index
        self.assertEqual((manquants[0], manquants[-1]), (pd.Timestamp("2026-08-10 00:00"), pd.Timestamp("2026-09-20 23:00")))
        self.assertEqual(int(series["EAU"].isna().sum()), 0)  # l'eau reste entière : la fuite se voit pendant les travaux
        self.assertEqual(len(journ["ELEC"]), len(jours) - 42)
        self.assertNotIn(pd.Timestamp("2026-08-10"), journ["ELEC"].index)
        self.assertEqual([str(m) for m in mensuelles["GAZ"].index], ["2026-05", "2026-06", "2026-07", "2026-10"])

    def test_vacance_passee_exclue_de_la_reference_du_chauffage(self):
        """Immeuble à moitié chauffé pendant 80 jours de vacance, puis réoccupé : sans déclaration, la référence apprise
        pendant la vacance fait passer le retour à la normale pour une dérive ; déclarée, elle n'y est plus."""
        text = heures(150, lambda t: 8.0 + 1.5 * np.sin(t.day_of_year / 5))
        chaleur = (16.0 - text) * 5.0
        debut, fin = FIN - pd.Timedelta(days=120), FIN - pd.Timedelta(days=41)
        vacance = (chaleur.index >= debut) & (chaleur.index < fin + pd.Timedelta(days=1))
        chaleur[vacance] *= 0.5
        r = moteur.det_chaleur_signature(chaleur, text, FIN, P)
        self.assertGreaterEqual(r["persistance"], 30)  # fausse dérive : tous les jours depuis la réoccupation
        self.declarer("OB", type="vacance", debut=str(debut.date()), fin=str(fin.date()))
        series = {"CHAL": chaleur}
        declarations.preparer(self.cx, {"immeubles": [{"id": "OB", "points": [{"id": "CHAL", "fluide": "chaleur"}]}]},
                              FIN, None, {}, series, {}, {})
        self.assertIsNone(moteur.det_chaleur_signature(series["CHAL"], text, FIN, P))
        jours_juges = moteur.signature_attendue(series["CHAL"], text, FIN, P).index
        self.assertFalse(((jours_juges >= debut) & (jours_juges <= fin)).any())


class TestChangement(Exemple):
    def test_consigne_modifiee_la_reference_ne_remonte_pas_avant(self):
        # courbe de chauffe relevée volontairement la veille du début de la « dérive » : plus de fausse alerte
        self.declarer("OB", type="changement", debut="2026-10-30", motif="Courbe de chauffe relevée (plaintes de froid)")
        self.assertEqual(set(self.alertes()), ATTENDUES - {"OB-chaleur_signature"})

    def test_reference_posterieure_insuffisante_pas_de_jugement_puis_reprise(self):
        # 100 jours d'été et d'automne après le changement : aucun jour aussi froid en référence, rien n'est extrapolé
        d = self.declarer("OB", type="changement", debut=self.j(-100))
        self.assertNotIn("OB-chaleur_signature", self.alertes())
        declarations.supprimer(self.cx, d["id"])
        # changement ancien (un hiver entier de référence depuis) : la dérive est de nouveau jugée et détectée
        self.declarer("OB", type="changement", debut=self.j(-330))
        self.assertEqual(set(self.alertes()), ATTENDUES)

    def test_electricite_de_nuit_attend_des_nuits_de_reference_posterieures(self):
        d = self.declarer("OA", type="changement", point_id="OA_ELEC", debut=self.j(-25), motif="Compteur remplacé")
        self.assertEqual(set(self.alertes()), ATTENDUES - {"OA-elec_nuit"})
        declarations.supprimer(self.cx, d["id"])
        self.declarer("OA", type="changement", point_id="OA_ELEC", debut=self.j(-60), motif="Compteur remplacé")
        self.assertEqual(set(self.alertes()), ATTENDUES)

    def test_changement_a_venir_ou_sur_un_autre_compteur_sans_effet(self):
        self.declarer("OB", type="changement", debut=self.j(1))
        self.declarer("OB", type="changement", point_id="OB_EAU", debut="2026-10-30")
        self.assertEqual(set(self.alertes()), ATTENDUES)

    def test_series_coupees_au_changement(self):
        self.declarer("OB", type="changement", point_id="OB_CHAL", debut="2026-08-10")
        ref = {"immeubles": [{"id": "OB", "points": [{"id": "OB_CHAL", "fluide": "chaleur"}, {"id": "OB_EAU", "fluide": "eau"}]}]}
        h = pd.Series(1.0, index=pd.date_range("2026-07-01 01:00", "2026-11-01", freq="h"))
        mois = pd.Series(1.0, index=pd.period_range("2024-01", "2026-10", freq="M"))
        series, journ = {"OB_CHAL": h, "OB_EAU": h}, {"OB_CHAL": h.resample("D").sum()}
        mensuelles = {"OB_CHAL": mois, "OB_EAU": mois}
        declarations.preparer(self.cx, ref, pd.Timestamp("2026-11-11 06:00"), None, {}, series, journ, mensuelles)
        self.assertEqual(series["OB_CHAL"].index[0], pd.Timestamp("2026-08-11 00:00"))  # le jour du changement est écarté
        self.assertEqual(journ["OB_CHAL"].index[0], pd.Timestamp("2026-08-11"))
        self.assertEqual(str(mensuelles["OB_CHAL"].index[0]), "2026-09")  # premier mois complet après le changement
        self.assertEqual((len(series["OB_EAU"]), len(mensuelles["OB_EAU"])), (len(h), len(mois)))  # autre compteur : intact


class TestIndexReculeAuChangementDeCompteur(Exemple):
    def setUp(self):
        super().setUp()
        # compteur d'eau des Vergers remplacé le 20.10.2026 : le nouvel index repart 500 m³ plus bas
        self.cx.execute("UPDATE mesure SET valeur = valeur - 500 WHERE point_id = 'VG_EAU' AND ts >= '2026-10-20T10:00:00Z'")

    def test_recul_non_declare_reste_un_defaut_de_donnees(self):
        a = self.alertes()["VG-donnees-VG_EAU"]
        self.assertEqual(a["cause"], "donnees_index")
        self.assertIn("sans changement de compteur déclaré", a["constat"])
        # un changement déclaré un autre jour, ou sans désigner le compteur, n'excuse pas le recul
        self.declarer("VG", type="changement", point_id="VG_EAU", debut="2026-10-18", motif="Compteur remplacé")
        self.declarer("VG", type="changement", debut="2026-10-20", motif="Consigne modifiée")
        self.assertIn("VG-donnees-VG_EAU", self.alertes())

    def test_recul_le_jour_du_changement_declare_plus_d_alerte(self):
        self.declarer("VG", type="changement", point_id="VG_EAU", debut="2026-10-20", motif="Compteur remplacé")
        self.assertEqual(set(self.alertes()), ATTENDUES)
        # rejeu : la veille du changement, la déclaration ne vaut pas encore (et l'index n'a pas encore reculé)
        self.assertNotIn("VG-donnees-VG_EAU", self.alertes(jusqua=pd.Timestamp("2026-10-19")))
        # un second recul, un autre jour, reste signalé
        self.cx.execute("UPDATE mesure SET valeur = valeur - 50 WHERE point_id = 'VG_EAU' AND ts >= '2026-11-02T10:00:00Z'")
        self.assertIn("reculé 1 fois", self.alertes()["VG-donnees-VG_EAU"]["constat"])


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cx = base_exemple("declarations-api")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        cx.close()
        cls.srv, cls.app = serveur.creer_serveur(chemin, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def json(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        entetes = {"Host": f"127.0.0.1:{self.port}", "X-Vigie": "1", "Content-Type": "application/json"}
        c.request(methode, chemin, body=json.dumps(corps) if corps is not None else None, headers=entetes)
        r = c.getresponse()
        donnees = json.loads(r.read())
        c.close()
        return r.status, donnees

    def test_declarer_lister_supprimer_avec_trace_dans_l_historique(self):
        self.assertEqual(self.json("POST", "/api/analyser")[0], 200)
        statut, r = self.json("POST", "/api/immeubles/OB/declarations",
                              {"type": "sourdine", "cause": "chaleur_signature", "fin": "2026-12-31",
                               "motif": "Réglage en cours avec le chauffagiste", "auteur": "B. Exemple"})
        self.assertEqual(statut, 200)
        d = r["declarations"][0]
        self.assertEqual((d["type"], d["etat"], d["auteur"]), ("sourdine", "en_cours", "B. Exemple"))
        self.assertIn("jusqu'au 31.12.2026", d["libelle"])
        statut, r = self.json("POST", "/api/immeubles/OB/declarations",
                              {"type": "travaux", "debut": "2027-01-10", "fin": "2027-02-10", "motif": "Réfection de la chaufferie"})
        self.assertEqual([(x["type"], x["etat"]) for x in r["declarations"]], [("travaux", "a_venir"), ("sourdine", "en_cours")])
        statut, f = self.json("GET", "/api/immeubles/OB/fiche")
        self.assertEqual(len(f["declarations"]["declarations"]), 2)
        self.assertEqual({a["suivi"] for a in f["alertes"]}, {"sourdine"})
        self.assertIn("Sourdine de la règle « Chauffage trop fort pour la météo » jusqu'au 31.12.2026",
                      " ".join(e["texte"] for e in f["historique"]))
        self.assertEqual(self.json("GET", "/api/alertes?statut=sourdine")[1]["alertes"][0]["id"], "OB-chaleur_signature")
        statut, r = self.json("POST", "/api/alertes/OB-chaleur_signature/bon", {})
        self.assertEqual(statut, 200)  # le bon préparé avant la sourdine reste consultable
        statut, r = self.json("POST", "/api/immeubles/OB/declarations", {"type": "sourdine", "cause": "chaleur_signature"})
        self.assertEqual(statut, 400)
        self.assertIn("Motif", r["erreur"])
        statut, r = self.json("DELETE", f"/api/declarations/{d['id']}")
        self.assertEqual((statut, [x["type"] for x in r["declarations"]]), (200, ["travaux"]))
        self.assertEqual(self.json("DELETE", f"/api/declarations/{d['id']}")[0], 400)
        statut, f = self.json("GET", "/api/immeubles/OB/fiche")
        self.assertIn("Déclaration supprimée", f["historique"][0]["texte"])
        self.assertNotEqual({a["suivi"] for a in f["alertes"]}, {"sourdine"})


if __name__ == "__main__":
    unittest.main()
