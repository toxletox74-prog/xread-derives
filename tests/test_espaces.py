"""Espaces des services tiers : clé API, base isolée, import et analyse, routes interdites, MCP sur HTTP."""
import contextlib
import http.client
import io
import json
import os
import sqlite3
import threading
import unittest

from commun import DOSSIER, base_exemple

from vigie import __main__ as cli
from vigie import espaces, serveur


class TestEspaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cx = base_exemple("espaces")
        cls.base = cx.execute("PRAGMA database_list").fetchone()[2]
        cx.close()
        cls.dossier = os.path.join(DOSSIER, "espaces-tiers")
        reg = espaces.Espaces(cls.dossier)
        cls.cle_a, cls.cle_b = reg.creer("alpha", "Service A"), reg.creer("beta")
        cls.srv, cls.app = serveur.creer_serveur(cls.base, port=0, dossier_espaces=cls.dossier)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, methode, chemin, corps=None, cle=None, entetes=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        h = {"Host": "127.0.0.1", **(entetes or {})}
        if cle:
            h["Authorization"] = f"Bearer {cle}"
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps).encode()
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=corps, headers=h)
        r = c.getresponse()
        d = r.read()
        c.close()
        return r.status, (json.loads(d) if d else None)

    def mcp(self, message, cle=None):
        return self.req("POST", "/mcp", message, cle=cle or self.cle_a)

    def _remplir_alpha(self):
        """Le service A importe le parc et les relevés de l'exemple, puis lance l'analyse, sans en-tête X-Vigie."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        c.request("GET", "/api/export/parc", headers={"Host": "127.0.0.1"})
        classeur = c.getresponse().read()
        c.close()
        statut, r = self.req("POST", "/api/import/parc?appliquer=1", classeur, cle=self.cle_a)
        self.assertEqual(statut, 200, r)
        source = sqlite3.connect(self.base)
        lignes = source.execute("SELECT ts, point_id, valeur FROM mesure").fetchall()
        source.close()
        csv = "ts,point_id,valeur\n" + "".join(f"{t},{p},{v}\n" for t, p, v in lignes)
        statut, r = self.req("POST", "/api/import/mesures", csv.encode(), cle=self.cle_a)
        self.assertEqual(statut, 200, r)
        self.assertGreater(r["importees"], 1000)
        return self.req("POST", "/api/analyser", cle=self.cle_a)

    def test_espace_isole_import_analyse_et_mcp(self):
        alertes_principales = self.req("GET", "/api/alertes?statut=toutes")[1]["alertes"]
        statut, r = self._remplir_alpha()
        self.assertEqual(statut, 200, r)
        self.assertGreater(r["alertes"], 0)
        alertes_a = self.req("GET", "/api/alertes", cle=self.cle_a)[1]["alertes"]
        self.assertTrue(alertes_a)
        # l'espace B et la base principale ne voient rien de ce que A a importé ou calculé
        self.assertTrue(self.req("GET", "/api/etat", cle=self.cle_b)[1]["parc_vide"])
        self.assertEqual(self.req("GET", "/api/alertes", cle=self.cle_b)[1]["alertes"], [])
        self.assertEqual(self.req("GET", "/api/alertes?statut=toutes")[1]["alertes"], alertes_principales)
        # sorties de l'analyse dans le dossier de l'espace, pas dans sorties/ du projet
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "alpha", "sorties", "alertes.json")))

        # MCP sur HTTP : mêmes alertes que l'API, pour l'espace de la clé
        statut, init = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "test", "version": "1"}}})
        self.assertEqual((statut, init["result"]["serverInfo"]["name"]), (200, "xread-derives"))
        self.assertEqual(self.mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}), (202, None))
        statut, outils = self.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("lister_alertes", {o["name"] for o in outils["result"]["tools"]})
        _, appel = self.mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "lister_alertes", "arguments": {}}})
        ids = [a["id"] for a in json.loads(appel["result"]["content"][0]["text"])["alertes"]]
        self.assertEqual(ids, [a["id"] for a in alertes_a])
        _, appel_b = self.mcp({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                               "params": {"name": "lister_alertes", "arguments": {}}}, cle=self.cle_b)
        self.assertEqual(json.loads(appel_b["result"]["content"][0]["text"])["alertes"], [])
        statut, lot = self.mcp([{"jsonrpc": "2.0", "id": 5, "method": "ping"},
                                {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual((statut, lot), (200, [{"jsonrpc": "2.0", "id": 5, "result": {}}]))

    def test_cle_obligatoire_et_revocation(self):
        self.assertEqual(self.req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0], 401)
        self.assertEqual(self.req("GET", "/api/etat", cle="vgk_inconnue")[0], 401)
        self.assertEqual(self.req("GET", "/api/etat", cle="pas-une-cle")[0], 401)
        self.assertEqual(self.req("GET", "/mcp", cle=self.cle_a)[0], 405)
        cle = espaces.Espaces(self.dossier).creer("gamma")
        self.assertEqual(self.req("GET", "/api/etat", cle=cle)[0], 200)
        self.assertEqual(espaces.Espaces(self.dossier).revoquer("gamma"), 1)
        self.assertEqual(self.req("GET", "/api/etat", cle=cle)[0], 401)
        # le registre ne garde que l'empreinte de la clé
        registre = sqlite3.connect(os.path.join(self.dossier, "registre.db"))
        stocke = [r[0] for r in registre.execute("SELECT empreinte FROM cle")]
        registre.close()
        self.assertNotIn(cle, stocke)

    def test_cle_mcp_de_la_base_principale(self):
        x = {"X-Vigie": "1"}
        self.assertIsNone(self.req("GET", "/api/mcp")[1]["cle_creee"])
        statut, r = self.req("POST", "/api/mcp/cle", entetes=x)
        self.assertEqual((statut, r["chemin"]), (200, "/mcp"))
        cle = r["cle"]
        self.assertIsNotNone(self.req("GET", "/api/mcp")[1]["cle_creee"])
        # la clé ouvre /mcp sur la base principale (mêmes alertes que l'API), et rien d'autre
        _, appel = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "lister_alertes", "arguments": {"statut": "toutes"}}}, cle=cle)
        ids = [a["id"] for a in json.loads(appel["result"]["content"][0]["text"])["alertes"]]
        self.assertEqual(ids, [a["id"] for a in self.req("GET", "/api/alertes?statut=toutes")[1]["alertes"]])
        self.assertEqual(self.req("GET", "/api/etat", cle=cle)[0], 403)
        self.assertEqual(self.req("POST", "/api/analyser", cle=cle)[0], 403)
        # une nouvelle clé remplace l'ancienne ; la révocation coupe tout
        nouvelle = self.req("POST", "/api/mcp/cle", entetes=x)[1]["cle"]
        ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        self.assertEqual(self.mcp(ping, cle=cle)[0], 401)
        self.assertEqual(self.mcp(ping, cle=nouvelle)[0], 200)
        self.assertEqual(self.req("DELETE", "/api/mcp/cle", entetes=x)[1]["revoquees"], 1)
        self.assertEqual(self.mcp(ping, cle=nouvelle)[0], 401)
        # réservé : sans session derrière un serveur frontal, et jamais pour la clé d'un espace
        self.assertEqual(self.req("GET", "/api/mcp", entetes={"X-Forwarded-For": "203.0.113.9"})[0], 401)
        self.assertEqual(self.req("POST", "/api/mcp/cle", cle=self.cle_b)[0], 403)
        with self.assertRaises(espaces.ErreurEspace):
            espaces.Espaces(self.dossier).creer(espaces.PRINCIPAL)

    def test_routes_reservees_a_l_interface(self):
        for methode, chemin in (("GET", "/api/reglages"), ("PUT", "/api/reglages"), ("POST", "/api/connecteur/tester"),
                                ("GET", "/api/connecteur"), ("POST", "/api/bons/1/envoyer"), ("POST", "/api/session"),
                                ("POST", "/api/exemple")):
            self.assertEqual(self.req(methode, chemin, {}, cle=self.cle_b)[0], 403, chemin)
        # sans clé, l'interface garde ses protections : écriture sans X-Vigie refusée
        self.assertEqual(self.req("POST", "/api/analyser")[0], 403)

    def test_espace_consultable_depuis_l_interface_en_lecture_seule(self):
        voir = {espaces.ENTETE_CONSULTATION: "beta"}
        # par défaut, aucun espace n'est consultable sans clé
        self.assertEqual(self.req("GET", "/api/espaces")[1]["espaces"], [])
        self.assertEqual(self.req("GET", "/api/etat", entetes=voir)[0], 404)
        ancien = os.environ.get("VIGIE_ESPACES_CONSULTABLES")
        os.environ["VIGIE_ESPACES_CONSULTABLES"] = "beta, inexistant"
        try:
            self.assertEqual(self.req("GET", "/api/espaces")[1]["espaces"], [{"id": "beta", "nom": "beta"}])
            statut, etat = self.req("GET", "/api/etat", entetes=voir)
            self.assertEqual(statut, 200)
            self.assertTrue(etat["parc_vide"])                       # la base de beta, pas la base principale
            self.assertFalse(self.req("GET", "/api/etat")[1]["parc_vide"])
            for methode, chemin in (("POST", "/api/analyser"), ("PUT", "/api/reglages"), ("GET", "/api/reglages"),
                                    ("GET", "/api/connecteur"), ("GET", "/api/mcp")):
                self.assertEqual(self.req(methode, chemin, {}, entetes={**voir, "X-Vigie": "1"})[0], 403, chemin)
            self.assertEqual(self.req("GET", "/api/etat", entetes={espaces.ENTETE_CONSULTATION: "alpha"})[0], 404)
            self.assertEqual(self.req("GET", "/api/etat", entetes={espaces.ENTETE_CONSULTATION: "inexistant"})[0], 404)
        finally:
            if ancien is None:
                os.environ.pop("VIGIE_ESPACES_CONSULTABLES")
            else:
                os.environ["VIGIE_ESPACES_CONSULTABLES"] = ancien

    def test_identifiant_d_espace_et_ligne_de_commande(self):
        with self.assertRaises(espaces.ErreurEspace):
            espaces.Espaces(self.dossier).creer("../evasion")
        with self.assertRaises(espaces.ErreurEspace):
            espaces.Espaces(self.dossier).creer("Majuscules")
        dossier = os.path.join(DOSSIER, "espaces-cli")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            cli.espace(["vigie", "espace", "creer", "delta", "--nom=Service D"], dossier)
            cli.espace(["vigie", "espace", "revoquer", "delta"], dossier)
        self.assertIn(espaces.PREFIXE, sortie.getvalue())  # la clé est affichée une fois, à la création
        (ligne,) = espaces.Espaces(dossier).lister()
        self.assertEqual((ligne["espace"], ligne["nom"]), ("delta", "Service D"))
        self.assertIsNotNone(ligne["revoquee"])


if __name__ == "__main__":
    unittest.main()
