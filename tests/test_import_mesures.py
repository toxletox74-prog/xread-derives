"""Import des relevés : CSV (séparateur , ou ;) et classeur Excel .xlsx (feuille « mesures »)."""
import io
import os
import unittest

from commun import RACINE, base_vide

from vigie import db, excel, service

EXEMPLES = os.path.join(RACINE, "exemple de données fluides")


def base_avec_points(nom, grand=False):
    """Base vide avec le parc d'exemple (standard, ou grand : + immeubles PAC, CAD et gaz)."""
    cx = base_vide(nom)
    ref = service.defauts()
    if grand:
        ref = {**ref, "immeubles": ref["immeubles"] + service.exemple_grand()["immeubles"]}
    db.charger_referentiel(cx, ref)
    return cx


def mesures(cx, pid):
    return cx.execute("SELECT ts, valeur, qualite FROM mesure WHERE point_id = ? ORDER BY ts", (pid,)).fetchall()


class TestImportExcel(unittest.TestCase):
    def test_texte_iso_et_date_excel_sont_lus_en_utc(self):
        cx = base_avec_points("xlsx-dates")
        contenu = excel.ecrire_xlsx({"Notes": [["libre"]], "mesures": [
            ["ts", "point_id", "valeur"],
            ["2026-11-12T08:00:00+01:00", "OA_ELEC", 12.5],   # heure de Genève avec décalage : convertie en UTC
            [46338.333333333336, "OA_ELEC", 13],               # date Excel 12.11.2026 08:00, lue en UTC
            [None, None, None],                                # ligne vide ignorée
        ]})
        ok, rejets, _ = db.importer_xlsx(cx, contenu)
        self.assertEqual((ok, rejets), (2, []))
        self.assertEqual(mesures(cx, "OA_ELEC"), [("2026-11-12T07:00:00Z", 12.5, "valide"),
                                                  ("2026-11-12T08:00:00Z", 13.0, "valide")])

    def test_lignes_fautives_rejetees_avec_leur_numero(self):
        cx = base_avec_points("xlsx-rejets")
        contenu = excel.ecrire_xlsx({"mesures": [["ts", "point_id", "valeur"],
                                                 ["12.11.2026 07:00", "OA_ELEC", 1],
                                                 ["2026-11-12T07:00:00Z", "INCONNU", 1]]})
        ok, rejets, _ = db.importer_xlsx(cx, contenu)
        self.assertEqual(ok, 0)
        self.assertEqual([n for n, _ in rejets], [2, 3])

    def test_colonnes_manquantes_refusees(self):
        cx = base_avec_points("xlsx-entetes")
        with self.assertRaises(excel.ErreurExcel):
            db.importer_xlsx(cx, excel.ecrire_xlsx({"mesures": [["date", "compteur", "kWh"]]}))


class TestImportCsv(unittest.TestCase):
    def test_point_virgule_virgule_decimale_et_decalage_horaire(self):
        cx = base_avec_points("csv-fr")
        flux = io.StringIO("ts;point_id;valeur\n2026-11-12T08:00:00+01:00;OA_ELEC;12,5\n")
        self.assertEqual(db.importer_mesures(cx, flux)[:2], (1, []))
        self.assertEqual(mesures(cx, "OA_ELEC"), [("2026-11-12T07:00:00Z", 12.5, "valide")])


def fichiers_exemple():
    """Relevés d'exemple présents sur ce poste : ils ne sont pas publiés dans le dépôt, seuls les modèles vides le sont."""
    if not os.path.isdir(EXEMPLES):
        return []
    return [n for n in sorted(os.listdir(EXEMPLES))
            if n.endswith((".csv", ".xlsx")) and not n.startswith("modele_vide")]


@unittest.skipUnless(fichiers_exemple(), "relevés d'exemple absents (non publiés dans le dépôt)")
class TestFichiersExemple(unittest.TestCase):
    """Les relevés de « exemple de données fluides » s'importent sans aucun rejet dans le grand exemple."""

    def test_csv_et_excel_sans_rejet(self):
        cx = base_avec_points("exemples-fluides", grand=True)
        for nom in fichiers_exemple():
            chemin = os.path.join(EXEMPLES, nom)
            if nom.endswith(".csv"):
                ok, rejets, _ = db.importer_csv(cx, chemin)
            else:
                with open(chemin, "rb") as f:
                    ok, rejets, _ = db.importer_xlsx(cx, f.read())
            with self.subTest(fichier=nom):
                self.assertGreater(ok, 0)
                self.assertEqual(rejets, [])


if __name__ == "__main__":
    unittest.main()
