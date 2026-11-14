"""Serveur local : pages, API, protections (hôte, en-tête X-Vigie), erreurs lisibles."""
import http.client
import json
import threading
import unittest

from commun import base_exemple

from vigie import excel, serveur


class TestServeur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cx = base_exemple("serveur")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        cx.close()
        cls.srv, _ = serveur.creer_serveur(chemin, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, methode, chemin, corps=None, entetes=None, hote=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": hote or f"127.0.0.1:{self.port}", **(entetes or {})}
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps)
            h["Content-Type"] = "application/json"
        if methode != "GET" and "X-Vigie" not in h:
            h["X-Vigie"] = "1"
        c.request(methode, chemin, body=corps, headers=h)
        r = c.getresponse()
        donnees = r.read()
        c.close()
        return r.status, r.getheader("Content-Type") or "", donnees

    def json(self, *args, **kw):
        statut, _, d = self.req(*args, **kw)
        return statut, json.loads(d)

    def test_second_vigie_sur_le_meme_port_refuse(self):
        cx = base_exemple("serveur-double")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        cx.close()
        with self.assertRaises(OSError):
            serveur.creer_serveur(chemin, port=self.port)

    def test_carte_du_parc_couleur_selon_le_probleme_le_plus_grave(self):
        self.json("POST", "/api/analyser")
        statut, c = self.json("GET", "/api/carte")
        self.assertEqual(statut, 200)
        par_rue = {a["rue"]: a for a in c["adresses"]}
        self.assertEqual(par_rue["Rue du Rhône 41"]["etat"], "Critique")
        self.assertEqual(par_rue["Avenue des Ormeaux 15"]["etat"], "Élevée")  # Ormeaux B l'emporte sur A (Modérée)
        self.assertEqual(par_rue["Route de Chêne 102"]["etat"], "OK")
        self.assertEqual(c["adresses"][0]["etat"], "Critique")  # liste triée par criticité
        self.assertTrue(c["tuiles"].startswith("https://wmts.geo.admin.ch"))
        statut, _ = self.json("PUT", f"/api/adresses/{par_rue['Route de Chêne 102']['id']}/coordonnees",
                              {"lat": "46.2", "lon": "200"})
        self.assertEqual(statut, 400)

    def test_politique_de_securite_autorise_seulement_les_tuiles_swisstopo(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        csp = c.getresponse().getheader("Content-Security-Policy")
        c.close()
        self.assertIn("img-src 'self' data: https://wmts.geo.admin.ch", csp)
        self.assertIn("default-src 'self'", csp)

    def test_meteo_de_la_base_d_exemple_protegee(self):
        statut, m = self.json("GET", "/api/meteo")
        self.assertEqual((statut, m["source"], m["auto"]), (200, "exemple", False))
        self.assertIn("https://www.meteoswiss.admin.ch/", " ".join(m["liens"].values()))
        statut, r = self.json("POST", "/api/meteo/maj")
        self.assertEqual(statut, 400)
        self.assertIn("exemple", r["erreur"])

    def test_page_d_accueil_et_fichiers_web(self):
        statut, type_mime, corps = self.req("GET", "/")
        self.assertEqual(statut, 200)
        self.assertIn("text/html", type_mime)
        self.assertIn(b"app.js", corps)
        for f in ("/app.js", "/outils.js", "/pages_parc.js", "/app.css"):
            self.assertEqual(self.req("GET", f)[0], 200, f)

    def test_chemin_hors_du_dossier_web_refuse(self):
        for chemin in ("/../vigie.db", "/%2e%2e/config/referentiel.json", "/serveur.py", "/web/app.js"):
            self.assertEqual(self.req("GET", chemin)[0], 404, chemin)

    def test_hote_etranger_refuse(self):
        self.assertEqual(self.req("GET", "/api/etat", hote="attaquant.example")[0], 403)

    def test_ecriture_sans_en_tete_x_vigie_refusee(self):
        statut, _ = self.json("POST", "/api/analyser", entetes={"X-Vigie": "0"})
        self.assertEqual(statut, 403)

    def test_etat_et_analyse(self):
        statut, r = self.json("POST", "/api/analyser")
        self.assertEqual((statut, r["alertes"]), (200, 7))
        statut, e = self.json("GET", "/api/etat")
        # d'autres tests de la classe peuvent avoir ajouté des immeubles (sans mesures, donc sans alerte)
        self.assertGreaterEqual(e["immeubles"], 5)
        self.assertEqual((e["kpis"]["alertes"], e["kpis"]["critiques"]), (7, 2))
        self.assertTrue(e["tarifs_exemple"])

    def test_saisie_invalide_renvoie_un_message_lisible(self):
        statut, r = self.json("POST", "/api/immeubles", {"id": "X 1", "nom": "", "rue": "", "npa_localite": ""})
        self.assertEqual(statut, 400)
        self.assertIn("Code immeuble", r["erreur"])

    def test_creation_d_immeuble_et_compteur(self):
        statut, _ = self.json("POST", "/api/immeubles", {"id": "NV1", "nom": "Nouveau", "rue": "Rue Neuve 1",
                                                         "npa_localite": "1200 Genève", "profil": "Vide"})
        self.assertEqual(statut, 200)
        statut, r = self.json("POST", "/api/compteurs", {"id": "NV1_EAU", "immeuble_id": "NV1", "fluide": "eau",
                                                         "pas_min": "1440"})
        self.assertEqual(statut, 200)
        self.assertTrue(any("grossier" in a for a in r["avertissements"]))
        _, p = self.json("GET", "/api/parc")
        self.assertIn("NV1", [im["id"] for ad in p["adresses"] for im in ad["immeubles"]])

    def test_import_excel_en_deux_temps(self):
        contenu = excel.ecrire_xlsx({"Immeubles": [["immeuble_id", "nom", "rue", "npa_localite"],
                                                   ["XL1", "Depuis Excel", "Rue Excel 1", "1201 Genève"]]})
        statut, r = self.json("POST", "/api/import/parc?appliquer=0", contenu)
        self.assertEqual((statut, r["immeubles"]["nouveaux"], r["applique"]), (200, 1, False))
        _, r = self.json("POST", "/api/import/parc?appliquer=1", contenu)
        self.assertTrue(r["applique"])
        statut, _, corps = self.req("GET", "/api/export/parc")
        self.assertEqual(statut, 200)
        self.assertIn("XL1", str(excel.lire_xlsx(corps)["Immeubles"]))

    def test_exemple_refuse_si_le_parc_n_est_pas_vide(self):
        statut, r = self.json("POST", "/api/exemple")
        self.assertEqual(statut, 400)
        self.assertIn("base vide", r["erreur"])

    def test_bon_eml_telechargeable(self):
        self.json("POST", "/api/analyser")
        _, b = self.json("POST", "/api/alertes/T8-eau_nuit/bon", {})
        statut, type_mime, corps = self.req("GET", f"/api/bons/{b['bon']['id']}/eml")
        self.assertEqual(statut, 200)
        self.assertIn("message/rfc822", type_mime)
        self.assertIn(b"X-Unsent: 1", corps)

    def test_serie_journaliere_pour_la_courbe(self):
        statut, r = self.json("GET", "/api/serie/T8_EAU?jours=30")
        self.assertEqual(statut, 200)
        self.assertGreaterEqual(len(r["jours"]), 30)
        self.assertTrue(all(j["valeur"] is None or j["valeur"] >= 0 for j in r["jours"]))


if __name__ == "__main__":
    unittest.main()
