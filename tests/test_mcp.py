"""Serveur MCP : protocole JSON-RPC sur stdio, outils en lecture seule, chiffres identiques à ceux de l'API."""
import io
import json
import os
import re
import unittest

from commun import ATTENDUES, RACINE, base_exemple

from vigie import bons, mcp, serveur, service


def _chemin(nom):
    cx = base_exemple(nom)
    chemin = cx.execute("PRAGMA database_list").fetchone()[2]
    service.analyser(cx, automatiser=False)
    cx.close()
    return chemin


class TestMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = serveur.Application(_chemin("mcp"))

    @classmethod
    def tearDownClass(cls):
        cls.app.cx.close()

    def appel(self, nom, **arguments):
        r = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": nom, "arguments": arguments}})["result"]
        return r["isError"], json.loads(r["content"][0]["text"])

    def test_initialisation_et_liste_des_outils(self):
        r = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                   "params": {"protocolVersion": "2025-03-26"}})["result"]
        self.assertEqual(r["protocolVersion"], "2025-03-26")
        self.assertIn("tools", r["capabilities"])
        inconnue = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                          "params": {"protocolVersion": "1999-01-01"}})["result"]
        self.assertEqual(inconnue["protocolVersion"], mcp.VERSIONS[0])
        outils = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({o["name"] for o in outils}, set(mcp.FONCTIONS))
        for o in outils:
            self.assertEqual(o["inputSchema"]["type"], "object")
            self.assertTrue(o["annotations"]["readOnlyHint"])

    def test_notification_sans_reponse_et_methode_inconnue(self):
        self.assertIsNone(mcp.traiter(self.app, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        r = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        self.assertEqual(r["error"]["code"], -32601)
        r = mcp.traiter(self.app, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "effacer"}})
        self.assertEqual(r["error"]["code"], -32602)

    def test_alertes_identiques_a_celles_de_la_base(self):
        erreur, r = self.appel("lister_alertes")
        self.assertFalse(erreur)
        en_base = bons.liste_alertes(self.app.cx, "ouverte")
        self.assertEqual([a["id"] for a in r["alertes"]], [a["id"] for a in en_base])
        self.assertEqual({a["id"] for a in r["alertes"]}, ATTENDUES)
        for resume, a in zip(r["alertes"], en_base):
            self.assertEqual(resume["chf_mois"], a["chf_mois"])  # règle 5 : le chiffre du moteur, tel quel
        _, critiques = self.appel("lister_alertes", gravite="Critique", immeuble_id="R41")
        self.assertEqual([a["id"] for a in critiques["alertes"]], ["R41-chaleur_vide"])
        _, detail = self.appel("lire_alerte", id="R41-chaleur_vide")
        self.assertEqual(detail, json.loads(json.dumps(next(a for a in en_base if a["id"] == "R41-chaleur_vide"),
                                                       default=str)))

    def test_erreurs_de_saisie_rendues_a_l_assistant(self):
        for nom, arguments in (("lire_alerte", {"id": "inconnue"}), ("lire_immeuble", {"id": "inconnu"}),
                               ("lister_alertes", {"statut": "partout"}), ("lire_alerte", {}),
                               ("etat", {"base": "autre.db"})):
            erreur, r = self.appel(nom, **arguments)
            self.assertTrue(erreur, nom)
            self.assertIn("erreur", r)

    def test_lectures_du_parc_des_regles_et_de_l_etat(self):
        _, e = self.appel("etat")
        self.assertEqual(e["kpis"]["alertes"], len(ATTENDUES))
        self.assertNotIn("acces", e)
        _, p = self.appel("lire_parc")
        immeubles = {im["id"]: im for ad in p["adresses"] for im in ad["immeubles"]}
        self.assertIn("T8", immeubles)
        self.assertTrue(immeubles["T8"]["compteurs"])
        _, f = self.appel("lire_immeuble", id="T8")
        self.assertEqual(f["immeuble"]["id"], "T8")
        self.assertTrue(f["alertes"])
        _, r = self.appel("lister_regles")
        self.assertIn("eau_nuit", {x["id"] for x in r["regles"]})
        for nom in ("lister_bons", "lire_rejeu"):
            self.assertFalse(self.appel(nom)[0], nom)

    def test_analyse_a_blanc_ne_modifie_pas_la_base(self):
        cx = self.app.cx
        compter = lambda: [cx.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("alerte", "bon", "evenement")]
        avant, analyse = compter(), cx.execute("SELECT valeur FROM parametre WHERE cle = 'derniere_analyse'").fetchone()
        erreur, r = self.appel("analyser_a_blanc")
        self.assertFalse(erreur)
        self.assertEqual({a["id"] for a in r["alertes"]}, ATTENDUES)
        self.assertEqual((r["absentes_de_la_base"], r["plus_detectees"], r["enregistre"]), ([], [], False))
        self.assertEqual(compter(), avant)
        self.assertEqual(cx.execute("SELECT valeur FROM parametre WHERE cle = 'derniere_analyse'").fetchone(), analyse)

    def test_boucle_stdio_une_reponse_par_ligne(self):
        entree = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{illisible\n'
                            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                          "params": {"name": "lire_alerte", "arguments": {"id": "T8-eau_nuit"}}}).encode()
                            + b"\n")
        sortie = io.BytesIO()
        mcp.servir(_chemin("mcp-stdio"), entree, sortie)
        lignes = [json.loads(x) for x in sortie.getvalue().decode("utf-8").splitlines()]
        self.assertEqual([x["id"] for x in lignes], [1, None, 2])
        self.assertEqual(lignes[0]["result"], {})
        self.assertEqual(lignes[1]["error"]["code"], -32700)
        self.assertIn("Tilleuls", lignes[2]["result"]["content"][0]["text"])  # accents non échappés, UTF-8


class TestDocumentationApi(unittest.TestCase):
    def test_chaque_route_et_chaque_outil_est_documente(self):
        with open(os.path.join(RACINE, "docs", "API.md"), encoding="utf-8") as f:
            doc = re.sub(r"\{[^}]*\}", "{}", f.read())
        app = serveur.Application(_chemin("mcp-doc"))
        try:
            for methode, motif, _ in app.routes:
                self.assertIn("`" + methode + " " + re.sub(r"\([^)]*\)", "{}", motif) + "`", doc)
        finally:
            app.cx.close()
        for nom in mcp.FONCTIONS:
            self.assertIn(f"`{nom}`", doc)


if __name__ == "__main__":
    unittest.main()
