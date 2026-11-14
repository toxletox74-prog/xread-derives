"""Coordonnées des adresses et carte du parc (géocodeur simulé : aucun accès réseau)."""
import os
import sqlite3
import unittest

from commun import DOSSIER, base_exemple, base_vide

from vigie import db, geo, parc


def reponse(*resultats):
    """Fausse réponse du géocodeur fédéral : [(libellé, lat, lon), …]."""
    return lambda texte: [{"attrs": {"label": lab, "lat": lat, "lon": lon}} for lab, lat, lon in resultats]


class TestGeocodage(unittest.TestCase):
    def test_adresse_exacte_retenue(self):
        r = geo.geocoder("Rue du Rhône 41", "1204 Genève",
                         reponse(("Rue du Rhône 41 <b>1204 Genève</b>", 46.203815, 6.149499)))
        self.assertEqual(r, (46.203815, 6.149499, "Rue du Rhône 41 1204 Genève"))

    def test_rue_voisine_ou_autre_numero_refuses(self):
        """Le service renvoie une autre rue pour une adresse inconnue : jamais de point faux sur la carte."""
        voisines = reponse(("Chemin des Trévisans 8 <b>1213 Onex</b>", 46.17, 6.10),
                           ("Chemin des Tilleuls 10 <b>1213 Onex</b>", 46.17, 6.10),
                           ("Chemin des Tilleuls 8 <b>1214 Vernier</b>", 46.21, 6.08))
        self.assertIsNone(geo.geocoder("Chemin des Tilleuls 8", "1213 Onex", voisines))

    def test_accents_et_casse_sans_importance(self):
        r = geo.geocoder("route de chene 102", "1224 Chêne-Bougeries",
                         reponse(("Route de Chêne 102 <b>1224 Chêne-Bougeries</b>", 46.198639, 6.180411)))
        self.assertIsNotNone(r)

    def test_coordonnees_hors_suisse_refusees(self):
        with self.assertRaises(geo.ErreurGeo):
            geo.valider_coordonnees("48.85", "2.35")  # Paris
        self.assertEqual(geo.valider_coordonnees("46,2038", "6,1495"), (46.2038, 6.1495))

    def test_localisation_du_parc_et_introuvables(self):
        cx = base_vide("geo-parc")
        for i, (rue, npa) in enumerate((("Rue du Rhône 41", "1204 Genève"), ("Rue Imaginaire 3", "1200 Genève"))):
            parc.enregistrer_immeuble(cx, {"id": f"G{i}", "nom": f"G{i}", "rue": rue, "npa_localite": npa})

        def faux(texte):
            if "Rhône" in texte:
                return reponse(("Rue du Rhône 41 1204 Genève", 46.203815, 6.149499))(texte)
            return []
        bilan = geo.geocoder_parc(cx, faux, pause_s=0)
        self.assertEqual((len(bilan["localisees"]), len(bilan["introuvables"])), (1, 1))
        # une adresse introuvable n'est pas redemandée automatiquement, seulement sur demande
        self.assertEqual(geo.geocoder_parc(cx, faux, pause_s=0)["traitees"], 0)
        self.assertEqual(geo.geocoder_parc(cx, faux, pause_s=0, reessayer=True)["traitees"], 1)

    def test_coordonnees_manuelles_prioritaires(self):
        cx = base_vide("geo-manuel")
        parc.enregistrer_immeuble(cx, {"id": "M1", "nom": "M1", "rue": "Rue Imaginaire 3", "npa_localite": "1200 Genève",
                                       "latitude": "46,2", "longitude": "6,15"})
        ad = db.lignes(cx, "SELECT lat, lon, geo_source FROM adresse")[0]
        self.assertEqual(ad, {"lat": 46.2, "lon": 6.15, "geo_source": "manuel"})
        self.assertEqual(geo.geocoder_parc(cx, reponse(), pause_s=0, reessayer=True)["traitees"], 0)

    def test_coordonnees_aberrantes_refusees_a_la_saisie(self):
        with self.assertRaisesRegex(parc.ErreurSaisie, "hors de Suisse"):
            parc.valider_immeuble({"id": "M1", "nom": "M1", "rue": "Rue 1", "npa_localite": "1200 Genève",
                                   "latitude": "0", "longitude": "0"})


class TestMigrationEtExemple(unittest.TestCase):
    def test_base_existante_sans_colonnes_de_coordonnees_migree(self):
        chemin = os.path.join(DOSSIER, "ancienne.db")
        ancienne = sqlite3.connect(chemin)
        ancienne.execute("CREATE TABLE adresse (id TEXT PRIMARY KEY, rue TEXT NOT NULL, npa_localite TEXT NOT NULL)")
        ancienne.execute("INSERT INTO adresse VALUES ('a', 'Rue du Rhône 41', '1204 Genève')")
        ancienne.commit()
        ancienne.close()
        cx = db.connecter(chemin)
        self.assertEqual(db.lignes(cx, "SELECT rue, lat, geo_source FROM adresse"),
                         [{"rue": "Rue du Rhône 41", "lat": None, "geo_source": None}])

    def test_grand_exemple_24_adresses_15_derives_sans_fausse_alerte(self):
        from commun import ATTENDUES

        from vigie import moteur, service
        cx = base_vide("grand-exemple")
        info = service.charger_exemple(cx, taille="grand")
        self.assertEqual(info["rejets"], 0)
        # 20 adresses d'origine + 4 adresses réelles (CAD et gaz, géocodées exactement)
        self.assertEqual(cx.execute("SELECT count(*) FROM adresse").fetchone()[0], 24)
        self.assertEqual(cx.execute("SELECT count(*) FROM adresse WHERE lat IS NULL").fetchone()[0], 0)
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        attendues = ATTENDUES | set(service.exemple_grand()["derives_attendues"])
        self.assertEqual({a["id"] for a in alertes}, attendues)
        self.assertEqual(db.lignes(cx, "SELECT etat FROM point_mesure WHERE id = 'G12_ECS'")[0]["etat"], "a_connecter")

    def test_exemple_localise_hors_ligne(self):
        cx = base_exemple("geo-exemple")
        sources = {r["rue"]: r["geo_source"] for r in db.lignes(cx, "SELECT rue, geo_source FROM adresse")}
        self.assertEqual(sources["Rue du Rhône 41"], "geo.admin.ch")
        self.assertEqual(sources["Chemin des Tilleuls 8"], "exemple")  # adresse fictive : position approximative
        self.assertEqual(cx.execute("SELECT count(*) FROM adresse WHERE lat IS NULL").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
