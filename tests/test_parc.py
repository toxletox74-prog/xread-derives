"""Parc, import Excel et règles réglables par le gestionnaire."""
import io
import unittest

from commun import ATTENDUES, base_exemple, base_vide

from vigie import db, excel, moteur, parc, service


def classeur(immeubles=(), compteurs=(), prestataires=()):
    return excel.ecrire_xlsx({
        "Immeubles": [["immeuble_id", "nom", "rue", "npa_localite", "profil", "taux_occupation", "logements"], *immeubles],
        "Compteurs": [["point_id", "immeuble_id", "fluide", "libelle", "pas_min", "connexion", "etat"], *compteurs],
        "Prestataires": [["nom", "metier", "email", "immeubles"], *prestataires],
    })


def analyser(cx):
    alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
    return alertes


class TestExcel(unittest.TestCase):
    def test_aller_retour_conserve_textes_nombres_et_cases_vides(self):
        contenu = excel.ecrire_xlsx({"Feuille é": [["a", "b", "c"], ["Rhône <41> & co", 12, None], [None, 3.5, "x"]]})
        lu = excel.lire_xlsx(contenu)
        self.assertEqual(lu["Feuille é"], [["a", "b", "c"], ["Rhône <41> & co", 12], [None, 3.5, "x"]])

    def test_fichier_qui_n_est_pas_un_classeur_est_refuse(self):
        with self.assertRaises(excel.ErreurExcel):
            excel.lire_xlsx(b"ceci n'est pas un zip")


class TestValidation(unittest.TestCase):
    def test_code_immeuble_avec_espace_refuse(self):
        with self.assertRaisesRegex(parc.ErreurSaisie, "Code immeuble"):
            parc.valider_immeuble({"id": "T 8", "nom": "x", "rue": "r", "npa_localite": "1200 Genève"})

    def test_immeuble_partiel_sans_taux_refuse_et_taux_en_pourcent_converti(self):
        base = {"id": "VG", "nom": "x", "rue": "r", "npa_localite": "1200 Genève", "profil": "partiel"}
        with self.assertRaisesRegex(parc.ErreurSaisie, "taux"):
            parc.valider_immeuble(base)
        self.assertAlmostEqual(parc.valider_immeuble({**base, "taux_occupation": "40"})["taux_occupation"], 0.4)

    def test_profil_saisi_en_francais_courant(self):
        for saisie, attendu in (("Habité", "Habite"), ("vacant", "Vide"), ("Rénovation", "Travaux")):
            im = parc.valider_immeuble({"id": "A", "nom": "x", "rue": "r", "npa_localite": "n", "profil": saisie})
            self.assertEqual(im["profil"], attendu)

    def test_compteur_libelle_courant_complete_par_les_valeurs_par_defaut(self):
        p = parc.valider_point({"id": "A_EAU", "immeuble_id": "A", "fluide": "Eau froide", "etat": "à connecter"}, {"A"})
        # pas par défaut : horaire (aucune donnée n'arrive plus finement que l'heure)
        self.assertEqual((p["fluide"], p["unite"], p["nature"], p["pas_min"], p["etat"]),
                         ("eau", "m3", "index", 60, "a_connecter"))

    def test_compteur_d_un_immeuble_inconnu_refuse(self):
        with self.assertRaisesRegex(parc.ErreurSaisie, "Immeuble inconnu"):
            parc.valider_point({"id": "Z_EAU", "immeuble_id": "Z", "fluide": "eau"}, {"A"})

    def test_pas_journalier_sur_l_eau_signale_comme_trop_grossier(self):
        p = parc.valider_point({"id": "A_EAU", "immeuble_id": "A", "fluide": "eau", "pas_min": 1440}, {"A"})
        self.assertTrue(any("trop grossier" in a for a in parc.avertissements_point(p)))

    def test_email_prestataire_invalide_refuse(self):
        with self.assertRaisesRegex(parc.ErreurSaisie, "e-mail"):
            parc.valider_prestataire({"nom": "X", "metier": "Sanitaire", "email": "pas-un-mail"}, set())


class TestImportExcel(unittest.TestCase):
    def setUp(self):
        self.cx = base_vide("import")

    def test_apercu_n_ecrit_rien_et_signale_les_lignes_refusees(self):
        contenu = classeur(
            immeubles=[["IMM01", "Résidence test", "Rue Test 1", "1200 Genève", "Habité", None, 12],
                       ["IMM 02", "Code invalide", "Rue Test 2", "1200 Genève", "Habité", None, 4]],
            compteurs=[["IMM01_EAU", "IMM01", "Eau froide", "Eau générale", 15, "LoRaWAN", ""],
                       ["IMM09_EAU", "IMM09", "eau", "Orphelin", 15, "LoRaWAN", ""]],
            prestataires=[["Sanitaire Test", "sanitaire", "test@entreprise.example", "*"]])
        r = parc.importer_parc_excel(self.cx, contenu, appliquer=False)
        self.assertEqual((r["immeubles"]["nouveaux"], r["compteurs"]["nouveaux"], r["prestataires"]["nouveaux"]), (1, 1, 1))
        self.assertEqual(sorted((e["feuille"], e["ligne"]) for e in r["erreurs"]), [("Compteurs", 3), ("Immeubles", 3)])
        self.assertEqual(self.cx.execute("SELECT count(*) FROM immeuble").fetchone()[0], 0)

    def test_application_puis_reimport_identique_ne_change_rien(self):
        contenu = classeur(
            immeubles=[["IMM01", "Résidence test", "Rue Test 1", "1200 Genève", "Vide", None, 12]],
            compteurs=[["IMM01_CHAL", "IMM01", "chauffage", "Chaleur", 60, "M-Bus", "actif"]],
            prestataires=[["Chauffage Test", "Chauffagiste", "chauffage@entreprise.example", "IMM01"]])
        parc.importer_parc_excel(self.cx, contenu, appliquer=True)
        self.assertEqual(db.lignes(self.cx, "SELECT profil FROM immeuble WHERE id = 'IMM01'")[0]["profil"], "Vide")
        self.assertEqual(db.lignes(self.cx, "SELECT fluide, etat FROM point_mesure")[0], {"fluide": "chaleur", "etat": "actif"})
        r = parc.importer_parc_excel(self.cx, contenu, appliquer=False)
        self.assertEqual((r["immeubles"]["inchanges"], r["compteurs"]["inchanges"], r["prestataires"]["inchanges"]), (1, 1, 1))

    def test_export_puis_reimport_du_parc_d_exemple_est_neutre(self):
        cx = base_exemple("export")
        r = parc.importer_parc_excel(cx, parc.exporter_parc_excel(cx), appliquer=False)
        self.assertEqual(r["erreurs"], [])
        for k in ("immeubles", "compteurs", "prestataires"):
            self.assertEqual((r[k]["nouveaux"], r[k]["modifies"]), (0, 0), k)

    def test_reimport_partiel_ne_remet_pas_les_valeurs_par_defaut(self):
        cx = base_exemple("reimport")
        # Classeur réduit : pas de colonne profil ni talon, périmètre absent, cellule vide
        partiel = excel.ecrire_xlsx({
            "Immeubles": [["immeuble_id", "nom"], ["R41", "Immeuble Rhône 41 (renommé)"]],
            "Prestataires": [["nom", "metier", "email"],
                             ["Conciergerie des Tilleuls", "Concierge", "concierge.tilleuls@regie-exemple.example"]],
            "Compteurs": [["point_id", "immeuble_id", "fluide", "connexion"], ["T8_EAU", "T8", "eau", ""]],
        })
        r = parc.importer_parc_excel(cx, partiel, appliquer=True)
        self.assertEqual(r["erreurs"], [])
        im = db.lignes(cx, "SELECT nom, profil, talon_horsgel_kwh_j FROM immeuble WHERE id = 'R41'")[0]
        self.assertEqual((im["nom"], im["profil"], im["talon_horsgel_kwh_j"]), ("Immeuble Rhône 41 (renommé)", "Vide", 200))
        pr = db.lignes(cx, "SELECT perimetre FROM prestataire WHERE nom = 'Conciergerie des Tilleuls'")[0]
        self.assertEqual(pr["perimetre"], "T8")
        pt = db.lignes(cx, "SELECT source, pas_min FROM point_mesure WHERE id = 'T8_EAU'")[0]
        self.assertEqual((pt["source"], pt["pas_min"]), ("wM-Bus OMS · relais LoRaWAN", 60))  # pas du référentiel

    def test_classeur_sans_feuille_connue_refuse(self):
        with self.assertRaisesRegex(parc.ErreurSaisie, "Immeubles"):
            parc.importer_parc_excel(self.cx, excel.ecrire_xlsx({"Feuil1": [["a"]]}))


class TestReglesReglables(unittest.TestCase):
    """Les réglages du gestionnaire changent le résultat ; par défaut, résultat identique à la V0.1."""

    def ids(self, cx):
        return {a["id"] for a in analyser(cx)}

    def test_regles_par_defaut_precision_et_rappel_100(self):
        self.assertEqual(self.ids(base_exemple("defaut")), ATTENDUES)

    def test_seuil_releve_supprime_l_alerte_de_fuite(self):
        cx = base_exemple("seuil")
        parc.enregistrer_regle(cx, "eau_nuit", {"seuil": 200})
        self.assertNotIn("T8-eau_nuit", self.ids(cx))

    def test_profil_retire_de_la_regle_supprime_l_alerte_immeuble_vide(self):
        cx = base_exemple("profil")
        parc.enregistrer_regle(cx, "chaleur_vide", {"profils": ["Partiel"]})
        self.assertNotIn("R41-chaleur_vide", self.ids(cx))

    def test_regle_desactivee(self):
        cx = base_exemple("inactive")
        parc.enregistrer_regle(cx, "elec_nuit", {"active": False})
        self.assertEqual(self.ids(cx), ATTENDUES - {"OA-elec_nuit"})

    def test_immeuble_en_travaux_suspend_les_alertes_energie(self):
        cx = base_exemple("travaux")
        im = db.lignes(cx, "SELECT i.*, a.rue, a.npa_localite FROM immeuble i JOIN adresse a ON a.id = i.adresse_id "
                           "WHERE i.id = 'OB'")[0]
        parc.enregistrer_immeuble(cx, {**im, "profil": "Travaux"})
        self.assertNotIn("OB-chaleur_signature", self.ids(cx))

    def test_seuil_hors_bornes_refuse(self):
        with self.assertRaises(parc.ErreurSaisie):
            parc.enregistrer_regle(base_exemple("bornes"), "eau_nuit", {"seuil": -5})

    def test_compteur_a_connecter_ignore_puis_actif_a_la_premiere_mesure(self):
        cx = base_exemple("connexion")
        parc.enregistrer_point(cx, {"id": "OA_GAZ", "immeuble_id": "OA", "fluide": "gaz", "etat": "a_connecter"})
        self.assertEqual(self.ids(cx), ATTENDUES)  # pas d'alerte « Données » sur un compteur pas encore branché
        db.importer_mesures(cx, io.StringIO("ts,point_id,valeur\n2026-11-11T06:00:00Z,OA_GAZ,1000\n"))
        self.assertEqual(db.lignes(cx, "SELECT etat FROM point_mesure WHERE id = 'OA_GAZ'")[0]["etat"], "actif")

    def test_sans_talon_hors_gel_pas_de_seuil_invente(self):
        cx = base_exemple("talon")
        cx.execute("UPDATE immeuble SET talon_horsgel_kwh_j = NULL WHERE id = 'R41'")
        cx.commit()
        self.assertNotIn("R41-chaleur_vide", self.ids(cx))

    def test_import_csv_refuse_horodatage_non_iso_et_valeurs_non_finies(self):
        cx = base_vide("csv")
        parc.enregistrer_immeuble(cx, {"id": "A", "nom": "A", "rue": "Rue A 1", "npa_localite": "1200 Genève"})
        parc.enregistrer_point(cx, {"id": "A_EAU", "immeuble_id": "A", "fluide": "eau", "etat": "actif"})
        csv = ("ts;point_id;valeur\n01.11.2026 00:00:00;A_EAU;1\n2026-11-01T00:15:00Z;A_EAU;nan\n"
               "2026-11-01T00:30:00Z;A_EAU;inf\n2026-11-01T01:45:00+01:00;A_EAU;12,5\n")
        ok, rejets, _ = db.importer_mesures(cx, io.StringIO(csv))
        self.assertEqual((ok, [n for n, _ in rejets]), (1, [2, 3, 4]))
        self.assertEqual(db.lignes(cx, "SELECT ts, valeur FROM mesure"), [{"ts": "2026-11-01T00:45:00Z", "valeur": 12.5}])

    def test_tarif_de_contrat_change_le_cout(self):
        cx = base_exemple("tarif")
        # chauffage : CHF mesurés depuis le début de la dérive (plus d'annualisation) ; eau : CHF/an
        cle = lambda a: a["chf_mesure"] if a["chiffrage"] == "mesure" else a["chf_an"]  # noqa: E731
        avant = {a["id"]: cle(a) for a in analyser(cx)}
        parc.enregistrer_couts(cx, {"tarifs": [{"vecteur": "chaleur", "chf_par_unite": 0.24, "statut": "CONTRAT"}]},
                               service.defauts())
        apres = {a["id"]: cle(a) for a in analyser(cx)}
        self.assertAlmostEqual(apres["R41-chaleur_vide"], 2 * avant["R41-chaleur_vide"], delta=2)
        self.assertEqual(apres["T8-eau_nuit"], avant["T8-eau_nuit"])


if __name__ == "__main__":
    unittest.main()
