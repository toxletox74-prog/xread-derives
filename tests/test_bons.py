"""Suivi des alertes, choix du prestataire, bons de travaux et envoi (faux serveur : aucun courriel réel)."""
import email
import unittest

from commun import base_exemple

from vigie import bons, db, moteur, parc, service


def alertes(cx):
    return moteur.analyser(cx, db.referentiel(cx, service.defauts()))[0]


class TestSuiviAlertes(unittest.TestCase):
    def setUp(self):
        self.cx = base_exemple("suivi")
        self.a = alertes(self.cx)

    def test_une_derive_qui_dure_reste_une_seule_alerte(self):
        self.assertEqual(len(bons.synchroniser_alertes(self.cx, self.a)), 7)
        self.assertEqual(bons.synchroniser_alertes(self.cx, self.a), [])
        self.assertEqual(self.cx.execute("SELECT count(*) FROM alerte").fetchone()[0], 7)

    def test_derive_disparue_puis_revenue(self):
        bons.synchroniser_alertes(self.cx, self.a)
        bons.synchroniser_alertes(self.cx, [a for a in self.a if a["id"] != "T8-eau_nuit"])
        self.assertEqual(db.lignes(self.cx, "SELECT statut FROM alerte WHERE id = 'T8-eau_nuit'")[0]["statut"], "resolue")
        self.assertEqual(bons.synchroniser_alertes(self.cx, self.a), ["T8-eau_nuit"])

    def test_retour_du_gestionnaire_et_taux_de_pertinence(self):
        bons.synchroniser_alertes(self.cx, self.a)
        bons.enregistrer_retour(self.cx, "T8-eau_nuit", "pertinente")
        bons.enregistrer_retour(self.cx, "OA-elec_nuit", "fausse_alerte")
        self.assertEqual(bons.pertinence(self.cx)["taux"], 0.5)
        with self.assertRaises(bons.ErreurBon):
            bons.enregistrer_retour(self.cx, "T8-eau_nuit", "peut-etre")


class TestBons(unittest.TestCase):
    def setUp(self):
        self.cx = base_exemple("bons")
        bons.synchroniser_alertes(self.cx, alertes(self.cx))

    def test_prestataire_dedie_a_l_immeuble_passe_avant_celui_du_parc(self):
        self.assertEqual(bons.choisir_prestataire(self.cx, "Concierge", "T8")["nom"], "Conciergerie des Tilleuls")
        self.assertEqual(bons.choisir_prestataire(self.cx, "Concierge", "R41")["nom"], "Conciergerie générale")
        self.assertIsNone(bons.choisir_prestataire(self.cx, "Ventilation", "T8"))

    def test_bon_adresse_au_bon_metier_avec_les_chiffres_du_moteur(self):
        bon, cree = bons.creer_bon(self.cx, "T8-eau_nuit")
        self.assertTrue(cree)
        self.assertEqual(bon["prestataire"], "Sanitaire Exemple SA")
        self.assertEqual(bon["destinataire"], "depannage@sanitaire-exemple.example")
        donnees = db.lignes(self.cx, "SELECT donnees FROM alerte WHERE id = 'T8-eau_nuit'")[0]["donnees"]
        self.assertIn("95 l/h", donnees)
        self.assertIn("95 l/h", bon["corps"])
        self.assertRegex(bon["numero"], r"^BT-\d{4}-0001$")

    def test_un_seul_bon_ouvert_par_alerte(self):
        b1, _ = bons.creer_bon(self.cx, "T8-eau_nuit")
        b2, cree = bons.creer_bon(self.cx, "T8-eau_nuit")
        self.assertFalse(cree)
        self.assertEqual(b1["id"], b2["id"])
        bons.modifier_bon(self.cx, b1["id"], {"statut": "termine"})
        _, cree = bons.creer_bon(self.cx, "T8-eau_nuit")
        self.assertTrue(cree)

    def test_sans_partenaire_du_metier_le_bon_va_au_concierge(self):
        parc.enregistrer_regle(self.cx, "elec_nuit", {"metier": "Ventilation"})
        bons.synchroniser_alertes(self.cx, alertes(self.cx))
        bon, _ = bons.creer_bon(self.cx, "OA-elec_nuit")
        self.assertEqual((bon["destinataire_type"], bon["destinataire"]),
                         ("concierge", "concierge.ormeaux@regie-exemple.example"))
        self.assertTrue(any("Aucun partenaire" in j["texte"] for j in bon["journal"]))

    def test_sans_aucun_destinataire_le_bon_reste_a_completer(self):
        parc.enregistrer_regle(self.cx, "elec_nuit", {"metier": "Ventilation"})
        self.cx.execute("UPDATE prestataire SET actif = 0 WHERE metier = 'Concierge'")
        self.cx.execute("UPDATE immeuble SET concierge_email = NULL")  # ni concierge sur la fiche
        self.cx.commit()
        bons.synchroniser_alertes(self.cx, alertes(self.cx))
        bon, _ = bons.creer_bon(self.cx, "OA-elec_nuit")
        self.assertIsNone(bon["destinataire"])
        with self.assertRaises(bons.ErreurBon):
            bons.fichier_eml(bon, bons.lire_messagerie(self.cx))

    def test_bon_envoye_ne_se_modifie_plus(self):
        bon, _ = bons.creer_bon(self.cx, "T8-eau_nuit")
        bons.modifier_bon(self.cx, bon["id"], {"statut": "envoye"})
        with self.assertRaises(bons.ErreurBon):
            bons.modifier_bon(self.cx, bon["id"], {"corps": "autre texte"})

    def test_fichier_eml_pret_pour_outlook(self):
        bon, _ = bons.creer_bon(self.cx, "R41-chaleur_vide")
        m = email.message_from_bytes(bons.fichier_eml(bon, bons.lire_messagerie(self.cx)))
        self.assertEqual(m["X-Unsent"], "1")
        self.assertEqual(m["To"], "technique@chauffage-exemple.example")
        self.assertIn(bon["numero"], m["Subject"])


class TestEnvoi(unittest.TestCase):
    def setUp(self):
        self.cx = base_exemple("envoi")
        self.envoyes = []
        self.faux_envoi = lambda m, messagerie, mdp: self.envoyes.append((m, mdp))

    def configurer_smtp(self):
        db.ecrire_parametre(self.cx, "messagerie", {**bons.MESSAGERIE_DEFAUT, "smtp_hote": "smtp.exemple.example",
                                                    "expediteur_email": "gestion@regie-exemple.example",
                                                    "copie_a": "archives@regie-exemple.example"})

    def test_envoi_impossible_sans_messagerie(self):
        bons.synchroniser_alertes(self.cx, alertes(self.cx))
        bon, _ = bons.creer_bon(self.cx, "T8-eau_nuit")
        with self.assertRaisesRegex(bons.ErreurBon, "messagerie"):
            bons.envoyer_bon(self.cx, bon["id"], envoi=self.faux_envoi)
        self.assertEqual(self.envoyes, [])

    def test_envoi_smtp_passe_le_bon_a_envoye(self):
        self.configurer_smtp()
        bons.synchroniser_alertes(self.cx, alertes(self.cx))
        bon, _ = bons.creer_bon(self.cx, "T8-eau_nuit")
        r = bons.envoyer_bon(self.cx, bon["id"], "secret", envoi=self.faux_envoi)
        self.assertEqual(r["statut"], "envoye")
        m, mdp = self.envoyes[0]
        self.assertEqual((m["To"], m["Cc"], mdp),
                         ("depannage@sanitaire-exemple.example", "archives@regie-exemple.example", "secret"))

    def test_automatisation_brouillon_selon_la_gravite(self):
        nouvelles = bons.synchroniser_alertes(self.cx, alertes(self.cx))
        r = bons.automatiser(self.cx, nouvelles, envoi=self.faux_envoi)
        # Élevée et plus + données : 6 bons (dont la panne solaire de T8) ; la dérive modérée (OA) reste à la main
        self.assertEqual(len(r["crees"]), 6)
        self.assertIsNone(bons.bon_ouvert(self.cx, "OA-elec_nuit"))
        self.assertEqual(self.envoyes, [])

    def test_automatisation_envoi_et_mode_manuel(self):
        self.configurer_smtp()
        db.ecrire_parametre(self.cx, "automatisation", {"mode": "envoi", "gravite_min": "Critique", "inclure_donnees": False})
        nouvelles = bons.synchroniser_alertes(self.cx, alertes(self.cx))
        r = bons.automatiser(self.cx, nouvelles, envoi=self.faux_envoi)
        self.assertEqual(len(r["envoyes"]), 2)  # les deux alertes critiques
        db.ecrire_parametre(self.cx, "automatisation", {"mode": "manuel", "gravite_min": "Modérée", "inclure_donnees": True})
        self.assertEqual(bons.automatiser(self.cx, ["OA-elec_nuit"], envoi=self.faux_envoi)["crees"], [])


if __name__ == "__main__":
    unittest.main()


class TestFicheEtSuivi(unittest.TestCase):
    """Fiche technique : destinataire concierge / partenaire, retour d'incident, historique, consommation."""

    def setUp(self):
        self.cx = base_exemple("fiche")
        bons.synchroniser_alertes(self.cx, alertes(self.cx))

    def test_destinataire_concierge_ou_partenaire_et_retour_d_incident(self):
        bon, _ = bons.creer_bon(self.cx, "T8-eau_nuit")
        self.assertEqual((bon["destinataire_type"], bon["destinataire_nom"]), ("partenaire", "Sanitaire Exemple SA"))
        bon = bons.changer_destinataire(self.cx, bon["id"], "concierge")
        self.assertEqual(bon["destinataire"], "concierge.tilleuls@regie-exemple.example")
        self.assertIn("Conciergerie des Tilleuls", bon["corps"])
        self.assertEqual([a for a in bons.liste_alertes(self.cx) if a["id"] == "T8-eau_nuit"][0]["suivi"], "en_attente")
        with self.assertRaises(bons.ErreurBon):  # pas de retour sur un brouillon
            bons.enregistrer_retour_incident(self.cx, bon["id"], "resolu", "Chasse d'eau réparée.")
        bons.modifier_bon(self.cx, bon["id"], {"statut": "envoye"})
        suivi = lambda: [a for a in bons.liste_alertes(self.cx) if a["id"] == "T8-eau_nuit"][0]["suivi"]  # noqa: E731
        self.assertEqual(suivi(), "bon_envoye")
        bon = bons.enregistrer_retour_incident(self.cx, bon["id"], "resolu", "Chasse d'eau du 3e réparée.")
        self.assertEqual((bon["statut"], bon["retour_resultat"]), ("retour", "resolu"))
        self.assertEqual(suivi(), "retour_incident")
        with self.assertRaises(bons.ErreurBon):  # bon envoyé : destinataire figé
            bons.changer_destinataire(self.cx, bon["id"], "partenaire")

    def test_historique_horodate(self):
        bon, _ = bons.creer_bon(self.cx, "R41-chaleur_vide")
        bons.modifier_bon(self.cx, bon["id"], {"statut": "envoye"})
        textes = [e["texte"] for e in bons.historique(self.cx, "R41")]
        self.assertTrue(any(t.startswith("Alerte critique") for t in textes))
        self.assertTrue(any("Marqué comme envoyé" in t for t in textes))
        self.assertTrue(all(e["le"].endswith("Z") for e in bons.historique(self.cx, "R41")))

    def test_partenaires_par_fluide_et_fiche(self):
        f = parc.fiche(self.cx, "T8")
        metiers = {p["libelle"]: p["metier"] for p in f["partenaires"]}
        self.assertEqual(metiers["Eau froide"], "Sanitaire")
        self.assertEqual(metiers["Pompe à chaleur"], "Frigoriste")
        self.assertEqual(f["immeuble"]["concierge"], "Conciergerie des Tilleuls")
        parc.enregistrer_fiche(self.cx, "T8", {"technique": {"annee_construction": "1978", "chauffage": "PAC air/eau"}})
        self.assertEqual(parc.fiche(self.cx, "T8")["immeuble"]["technique"],
                         {"annee_construction": 1978, "chauffage": "PAC air/eau"})
        with self.assertRaises(parc.ErreurSaisie):
            parc.enregistrer_fiche(self.cx, "T8", {"technique": {"chauffage": "Fusion nucléaire"}})

    def test_consommation_jour_mois_annee(self):
        from vigie import serveur
        jour = serveur.serie_consommation(self.cx, "T8_EAU", "jour")
        mois = serveur.serie_consommation(self.cx, "T8_EAU", "mois")
        annee = serveur.serie_consommation(self.cx, "T8_EAU", "annee")
        self.assertEqual(len(jour["valeurs"]), 90)
        self.assertGreaterEqual(len(mois["valeurs"]), 4)
        # 12 mois d'exemple = 13 mois civils arrondis chacun au millième : écart d'arrondi toléré au centième
        self.assertAlmostEqual(mois["total"], annee["total"], delta=0.01)
        with self.assertRaises(parc.ErreurSaisie):
            serveur.serie_consommation(self.cx, "T8_EAU", "semaine")
