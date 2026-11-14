"""Analyse automatique : déclenchement, fil de fond, état visible, mot de passe SMTP manquant signalé."""
import http.client
import json
import os
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from commun import base_exemple

from vigie import bons, db, planification, serveur, service

REQ = SimpleNamespace(headers={})  # requête sans en-tête : accès direct au poste

MAINTENANT = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)
AUTO = {**bons.AUTOMATISATION_DEFAUT, "analyse_auto": True, "analyse_intervalle_h": 6}


def application(nom):
    cx = base_exemple(nom)
    chemin = cx.execute("PRAGMA database_list").fetchone()[2]
    cx.close()
    return serveur.Application(chemin)


class TestDeclencheur(unittest.TestCase):
    def test_desactivee_par_defaut(self):
        self.assertFalse(bons.AUTOMATISATION_DEFAUT["analyse_auto"])
        self.assertIsNone(planification.declencheur(bons.AUTOMATISATION_DEFAUT, None, True, MAINTENANT))

    def test_due_selon_l_intervalle_ou_un_nouveau_releve(self):
        self.assertEqual(planification.declencheur(AUTO, None, False, MAINTENANT), "intervalle")
        recente, ancienne = {"le": "2026-11-13T02:00:01Z"}, {"le": "2026-11-13T02:00:00Z"}
        self.assertIsNone(planification.declencheur(AUTO, recente, False, MAINTENANT))
        self.assertEqual(planification.declencheur(AUTO, ancienne, False, MAINTENANT), "intervalle")
        self.assertEqual(planification.declencheur(AUTO, recente, True, MAINTENANT), "relevé API")


class TestAnalyseAutomatique(unittest.TestCase):
    def setUp(self):
        self.app = application("planification")
        self.addCleanup(self.app.cx.close)
        self.envois = []

    def faux_envoi(self, m, messagerie, mot_de_passe):
        self.envois.append(m["To"])

    def activer(self, **reglages):
        db.ecrire_parametre(self.app.cx, "automatisation", {**AUTO, **reglages})

    def test_rien_tant_que_le_reglage_est_decoche(self):
        self.assertIsNone(planification.verifier(self.app, True, MAINTENANT))
        self.assertIsNone(db.lire_parametre(self.app.cx, planification.PARAM))
        self.assertIsNone(db.lire_parametre(self.app.cx, "derniere_analyse"))

    def test_analyse_et_etat_enregistre(self):
        self.activer()
        etat = planification.verifier(self.app, False, MAINTENANT, self.faux_envoi)
        self.assertEqual((etat["statut"], etat["declencheur"], etat["le"]), ("ok", "intervalle", "2026-11-13T08:00:00Z"))
        self.assertIn("7 alerte(s), 7 nouvelle(s)", etat["message"])
        self.assertEqual(db.lire_parametre(self.app.cx, planification.PARAM), etat)
        self.assertEqual(len(bons.liste_alertes(self.app.cx, "ouverte")), 7)
        self.assertEqual(self.envois, [])  # mode « brouillon » : aucun courriel
        # intervalle non écoulé : rien ; nouveau relevé API : analyse relancée
        self.assertIsNone(planification.verifier(self.app, False, MAINTENANT))
        self.assertEqual(planification.verifier(self.app, True, MAINTENANT)["declencheur"], "relevé API")

    def test_erreur_visible_sans_arreter_le_fil(self):
        self.activer()
        with mock.patch.object(service, "analyser", side_effect=RuntimeError("base abîmée")), \
                mock.patch("traceback.print_exc"):
            etat = planification.verifier(self.app, False, MAINTENANT)
        self.assertEqual(etat["statut"], "erreur")
        self.assertIn("base abîmée", etat["message"])
        self.assertEqual(db.lire_parametre(self.app.cx, planification.PARAM)["statut"], "erreur")
        self.assertFalse(self.app.verrou.locked())

    def test_envoi_automatique_sans_mot_de_passe_signale(self):
        self.activer(mode="envoi", gravite_min="Critique", inclure_donnees=False)
        db.ecrire_parametre(self.app.cx, "messagerie", {**bons.MESSAGERIE_DEFAUT, "smtp_hote": "smtp.exemple.example",
                                                        "expediteur_email": "regie@exemple.example",
                                                        "smtp_utilisateur": "regie"})
        with mock.patch.dict(os.environ):
            os.environ.pop(bons.ENV_MOT_DE_PASSE, None)
            self.assertTrue(self.app.etat(REQ)["smtp_mot_de_passe_manquant"])
            self.assertTrue(self.app.lire_reglages(None)["mot_de_passe_manquant"])

            def sans_mot_de_passe(m, messagerie, mot_de_passe):  # ce que fait l'envoi réel, sans réseau
                if not mot_de_passe:
                    raise bons.ErreurBon("Mot de passe de messagerie manquant (Réglages › Messagerie).")
            etat = planification.verifier(self.app, False, MAINTENANT, sans_mot_de_passe)
            self.assertEqual(etat["statut"], "attention")
            self.assertIn("Mot de passe de messagerie manquant", etat["message"])
            self.app.mot_de_passe = "secret"
            self.assertFalse(self.app.etat(REQ)["smtp_mot_de_passe_manquant"])
            self.app.mot_de_passe = None
            os.environ[bons.ENV_MOT_DE_PASSE] = "secret"
            self.assertFalse(self.app.etat(REQ)["smtp_mot_de_passe_manquant"])
        # le mot de passe n'est jamais écrit en base
        self.assertNotIn("secret", json.dumps(db.lignes(self.app.cx, "SELECT * FROM parametre"), ensure_ascii=False))

    def test_pas_d_avertissement_hors_envoi_automatique(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(bons.ENV_MOT_DE_PASSE, None)
            self.assertFalse(self.app.etat(REQ)["smtp_mot_de_passe_manquant"])  # mode « brouillon », SMTP non configuré
            self.activer(mode="envoi")
            self.assertFalse(self.app.etat(REQ)["smtp_mot_de_passe_manquant"])  # envoi, mais SMTP non configuré

    def test_fil_de_fond_analyse_puis_s_arrete(self):
        self.activer()
        arret, releve = threading.Event(), threading.Event()
        releve.set()
        with mock.patch("builtins.print"):
            fil = threading.Thread(target=planification.analyse_automatique, args=(self.app, arret, releve, 0.05, 0))
            fil.start()
            for _ in range(600):  # attend la première analyse (au plus 60 s), sans délai fixe
                with self.app.verrou:
                    etat = db.lire_parametre(self.app.cx, planification.PARAM)
                if etat or arret.wait(0.1):
                    break
            arret.set()
            fil.join(60)
        self.assertFalse(fil.is_alive())
        self.assertEqual((etat["statut"], etat["declencheur"]), ("ok", "relevé API"))
        self.assertFalse(releve.is_set())

    def test_fil_de_fond_s_arrete_proprement_sans_rien_lancer(self):
        arret = threading.Event()
        fil = threading.Thread(target=planification.analyse_automatique, args=(self.app, arret, None, 3600, 0))
        fil.start()
        arret.set()
        fil.join(5)
        self.assertFalse(fil.is_alive())
        self.assertIsNone(db.lire_parametre(self.app.cx, planification.PARAM))

    def test_releve_api_automatique_signale_les_nouvelles_mesures(self):
        from vigie import connecteur
        arret, releve = threading.Event(), threading.Event()
        cfg = {"actif": True, "auto": True, "url_base": "https://x.example", "derniere_synchro": None}
        for importees, attendu in ((0, False), (12, True)):
            def synchroniser(cx, importees=importees):
                arret.set()  # un seul tour de boucle
                return {"message": "relevé simulé", "importees": importees}
            arret.clear()
            with mock.patch.object(connecteur, "lire_config", return_value={**connecteur.CONFIG_DEFAUT, **cfg}), \
                    mock.patch.object(connecteur, "synchroniser", side_effect=synchroniser), mock.patch("builtins.print"):
                serveur.connecteur_automatique(self.app.chemin, arret, 0, 0, releve)
            self.assertEqual(releve.is_set(), attendu)


class TestReglagesAnalyseAutomatique(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cx = base_exemple("planification-api")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        cx.close()
        cls.srv, cls.app = serveur.creer_serveur(chemin, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.app.cx.close()

    def json(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(methode, chemin, body=json.dumps(corps) if corps is not None else None,
                  headers={"Host": f"127.0.0.1:{self.port}", "X-Vigie": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return r.status, d

    def test_reglage_enregistre_valide_et_conserve(self):
        base = {"mode": "brouillon", "gravite_min": "Élevée", "inclure_donnees": True}
        statut, r = self.json("GET", "/api/reglages")
        self.assertEqual((statut, r["automatisation"]["analyse_auto"], r["analyse_auto"]), (200, False, None))
        statut, r = self.json("PUT", "/api/reglages", {"automatisation": {**base, "analyse_auto": True,
                                                                          "analyse_intervalle_h": "12"}})
        self.assertEqual((statut, r["automatisation"]["analyse_auto"], r["automatisation"]["analyse_intervalle_h"]),
                         (200, True, 12))
        for invalide in (0, 169, "souvent"):
            statut, r = self.json("PUT", "/api/reglages", {"automatisation": {**base, "analyse_intervalle_h": invalide}})
            self.assertEqual(statut, 400, invalide)
            self.assertIn("Fréquence de l'analyse automatique", r["erreur"])
        # un envoi sans ces champs (ancien écran) ne désactive pas l'analyse automatique
        statut, r = self.json("PUT", "/api/reglages", {"automatisation": base})
        self.assertEqual((r["automatisation"]["analyse_auto"], r["automatisation"]["analyse_intervalle_h"]), (True, 12))
        statut, e = self.json("GET", "/api/etat")
        self.assertEqual((statut, e["smtp_mot_de_passe_manquant"]), (200, False))


if __name__ == "__main__":
    unittest.main()
