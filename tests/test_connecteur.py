"""Connexion API des compteurs : clé protégée, appel au fournisseur, import, démonstration (sans accès Internet)."""
import http.client
import http.server
import json
import threading
import unittest
from datetime import datetime, timezone

from commun import base_exemple, base_vide

from vigie import connecteur, db, parc, secret, serveur, service

MAINTENANT = datetime(2026, 11, 13, 7, 30, tzinfo=timezone.utc)
CLE = "cle-secrete-du-fournisseur-1234"


def base_reliee(nom):
    """Base du petit exemple (sans mesures) où OA_ELEC est relié à l'API sous l'identifiant EXT-42."""
    cx = base_vide(nom)
    db.charger_referentiel(cx, service.defauts())
    cx.execute("UPDATE point_mesure SET source = ?, identifiant = 'EXT-42' WHERE id = 'OA_ELEC'", (connecteur.SOURCE_API,))
    cx.commit()
    return cx


class FauxFournisseur:
    def __init__(self, reponse):
        self.reponse, self.appels = reponse, []

    def __call__(self, url, entetes):
        self.appels.append((url, entetes))
        return json.dumps(self.reponse).encode()


@unittest.skipUnless(secret.DISPONIBLE, "protection Windows (DPAPI) indisponible")
class TestCle(unittest.TestCase):
    def test_cle_protegee_jamais_stockee_ni_rendue_en_clair(self):
        cx = base_reliee("api-cle")
        e = connecteur.enregistrer(cx, {"url_base": "https://api.exemple.ch/v1", "cle": CLE, "actif": True})
        self.assertEqual(e["cle"], {"presente": True, "origine": "poste", "masque": "••••1234"})
        brut = " ".join(v for (v,) in cx.execute("SELECT valeur FROM parametre"))
        self.assertNotIn(CLE, brut)
        self.assertNotIn(CLE, json.dumps(e))
        self.assertEqual(connecteur.cle(cx), CLE)
        self.assertFalse(connecteur.supprimer_cle(cx)["cle"]["presente"])

    def test_adresse_et_cle_controlees(self):
        cx = base_reliee("api-controles")
        for d in ({"url_base": "http://api.exemple.ch"}, {"url_base": "https://user:mdp@api.exemple.ch"},
                  {"url_base": "ftp://api.exemple.ch"}, {"cle": "abc\r\nX-Autre: 1"}, {"chemin": "/mesures"},
                  {"auth_nom": "X API Key"}, {"actif": True}):
            with self.subTest(d=d), self.assertRaises(connecteur.ErreurConnecteur):
                connecteur.enregistrer(cx, d)
        self.assertEqual(connecteur.enregistrer(cx, {"url_base": "http://127.0.0.1:8765/demo"})["url_base"],
                         "http://127.0.0.1:8765/demo")  # http accepté sur ce poste seulement


@unittest.skipUnless(secret.DISPONIBLE, "protection Windows (DPAPI) indisponible")
class TestSynchronisation(unittest.TestCase):
    def test_format_du_fournisseur_et_import_controle(self):
        cx = base_reliee("api-synchro")
        connecteur.enregistrer(cx, {"url_base": "https://api.exemple.ch/v1", "cle": CLE, "actif": True,
                                    "json_liste": "data.values", "json_ts": "t", "json_valeur": "v"})
        faux = FauxFournisseur({"data": {"values": [
            {"t": "2026-11-12T07:00:00Z", "v": 1.5},
            {"t": 1794470400, "v": "2,5"},          # secondes depuis 1970 (12.11.2026 08:00 UTC), virgule décimale
            {"t": "12.11.2026 09:00", "v": 3}]}})   # horodatage non ISO : rejeté, signalé
        r = connecteur.synchroniser(cx, faux, MAINTENANT)
        self.assertEqual((r["importees"], r["rejets"], r["statut"]), (2, 1, "ok"))
        url, entetes = faux.appels[0]
        self.assertIn("/v1/points/EXT-42/mesures?debut=2026-11-06T07%3A00%3A00Z&fin=2026-11-13T07%3A00%3A00Z", url)
        self.assertEqual(entetes, {"X-API-Key": CLE})
        self.assertNotIn(CLE, url)
        self.assertEqual(db.lignes(cx, "SELECT ts, valeur FROM mesure WHERE point_id = 'OA_ELEC' ORDER BY ts"),
                         [{"ts": "2026-11-12T07:00:00Z", "valeur": 1.5}, {"ts": "2026-11-12T08:00:00Z", "valeur": 2.5}])
        # Relevé suivant : depuis la dernière valeur moins le recouvrement (2 h), pas tout l'historique
        connecteur.synchroniser(cx, faux, MAINTENANT)
        self.assertIn("debut=2026-11-12T06%3A00%3A00Z", faux.appels[-1][0])

    def test_cle_en_parametre_et_bearer(self):
        cx = base_reliee("api-auth")
        connecteur.enregistrer(cx, {"url_base": "https://api.exemple.ch", "cle": CLE, "auth": "parametre", "auth_nom": "api_key"})
        faux = FauxFournisseur({"mesures": []})
        connecteur.tester(cx, faux, MAINTENANT)
        self.assertTrue(faux.appels[0][0].endswith("&api_key=" + CLE))
        connecteur.enregistrer(cx, {"auth": "bearer"})
        connecteur.tester(cx, faux, MAINTENANT)
        self.assertEqual(faux.appels[1][1], {"Authorization": "Bearer " + CLE})

    def test_sans_compteur_relie_message_clair(self):
        cx = base_vide("api-sans-point")
        db.charger_referentiel(cx, service.defauts())
        connecteur.enregistrer(cx, {"url_base": "https://api.exemple.ch", "cle": CLE})
        with self.assertRaisesRegex(connecteur.ErreurConnecteur, "Parc"):
            connecteur.synchroniser(cx, FauxFournisseur({"mesures": []}), MAINTENANT)

    def test_automatique_selon_la_frequence(self):
        cfg = {**connecteur.CONFIG_DEFAUT, "actif": True, "auto": True, "url_base": "https://x.ch", "intervalle_h": 1}
        self.assertTrue(connecteur.a_synchroniser(cfg, MAINTENANT))
        self.assertFalse(connecteur.a_synchroniser({**cfg, "derniere_synchro": "2026-11-13T07:00:00Z"}, MAINTENANT))
        self.assertTrue(connecteur.a_synchroniser({**cfg, "derniere_synchro": "2026-11-13T06:00:00Z"}, MAINTENANT))
        self.assertFalse(connecteur.a_synchroniser({**cfg, "auto": False}, MAINTENANT))


class Redirige(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/redirige"):
            self.send_response(302)
            self.send_header("Location", "https://ailleurs.example/vol")
        else:
            self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class TestReseau(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Redirige)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_redirection_refusee_la_cle_ne_part_pas_ailleurs(self):
        with self.assertRaisesRegex(connecteur.ErreurConnecteur, "autre adresse"):
            connecteur.telecharger(self.base + "/redirige", {"X-API-Key": CLE})

    def test_cle_refusee_message_sans_la_cle(self):
        with self.assertRaises(connecteur.ErreurConnecteur) as e:
            connecteur.telecharger(self.base + "/mesures?api_key=" + CLE, {})
        self.assertIn("401", str(e.exception))
        self.assertNotIn(CLE, str(e.exception))


@unittest.skipUnless(secret.DISPONIBLE, "protection Windows (DPAPI) indisponible")
class TestDemonstration(unittest.TestCase):
    """Bout en bout : Vigie sert le fournisseur de démonstration et le relève par sa propre connexion API."""

    def req(self, methode, chemin, entetes=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        c.request(methode, chemin, headers={"Host": f"127.0.0.1:{self.port}", "X-Vigie": "1", **(entetes or {})})
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return r.status, d

    def test_demo_bout_en_bout(self):
        self.assertIn(connecteur.SOURCE_API, parc.SOURCES)
        cx = base_exemple("api-demo")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        avant = dict(cx.execute("SELECT point_id, max(ts) FROM mesure GROUP BY point_id"))
        cx.close()
        srv, _ = serveur.creer_serveur(chemin, port=0)
        self.port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            code, _d = self.req("GET", "/demo-fournisseur/points/OA_EAU/mesures?debut=2026-01-01T00:00:00Z"
                                "&fin=2026-01-02T00:00:00Z", {"X-API-Key": "mauvaise"})
            self.assertEqual(code, 401)
            code, d = self.req("POST", "/api/connecteur/demo")
            self.assertEqual(code, 200, d)
            self.assertGreater(d["relies"], 10)
            self.assertNotIn(connecteur.DEMO_CLE, json.dumps(d))
            code, t = self.req("POST", "/api/connecteur/tester")
            self.assertEqual(code, 200, t)
            self.assertGreater(t["valeurs"], 0)
            code, s = self.req("POST", "/api/connecteur/synchroniser")
            self.assertEqual(code, 200, s)
            self.assertEqual((s["statut"], s["rejets"]), ("ok", 0), s)
            self.assertGreater(s["importees"], 0)
        finally:
            srv.shutdown()
            srv.server_close()
        cx = db.connecter(chemin)
        apres = dict(cx.execute("SELECT point_id, max(ts) FROM mesure GROUP BY point_id"))
        self.assertGreater(apres["OA_EAU"], avant["OA_EAU"])  # relevés prolongés jusqu'à l'heure actuelle
        index = [v for (v,) in cx.execute("SELECT valeur FROM mesure WHERE point_id = 'OA_EAU' ORDER BY ts")]
        self.assertTrue(all(b >= a for a, b in zip(index, index[1:])))  # un index ne fait que croître (règle 2)
        cx.close()


if __name__ == "__main__":
    unittest.main()
