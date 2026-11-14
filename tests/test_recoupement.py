"""Recoupement des alertes au niveau du parc : cause commune à plusieurs immeubles (météo ou calendrier)."""
import unittest

from commun import base_exemple

from vigie import bons, db, moteur, recoupement, service

P = service.defauts()["parametres"]


def alerte(immeuble, debut, cause="chaleur_signature", sinistre=False, gravite="Élevée"):
    return {"id": f"{immeuble}-{cause}", "immeuble_id": immeuble, "cause": cause, "debut": debut, "sinistre": sinistre,
            "gravite": gravite, "constat": "Constat.", "confiance": 0.8}


def juges(n, cause="chaleur_signature"):
    return {(f"S{i:02d}", cause) for i in range(1, n + 1)}


class TestCauseCommune(unittest.TestCase):
    def test_groupe_detecte_et_alertes_marquees_sans_etre_supprimees(self):
        # fin juin : 4 immeubles sur 10 jugés entrent en alerte en 3 jours, chaleur, CAD et gaz confondus
        a = [alerte("S01", "2025-06-24", "cad_signature"), alerte("S02", "2025-06-24"),
             alerte("S03", "2025-06-25", "gaz_signature"), alerte("S04", "2025-06-27"),
             alerte("S05", "2025-05-02")]  # dérive plus ancienne : hors du groupe
        recoupement.marquer(a, juges(10) | {("S01", "cad_signature"), ("S03", "gaz_signature")}, P)
        self.assertEqual(len(a), 5)
        for x in a[:4]:
            self.assertEqual(x["cause_commune"], {"famille": "signature de chauffage", "immeubles": 4, "juges": 10,
                                                  "du": "2025-06-24", "au": "2025-06-27"})
            self.assertIn("4 immeubles en alerte les mêmes jours : effet probable de météo ou de calendrier, "
                          "à vérifier avant d'agir.", x["constat"])
            self.assertEqual(x["confiance"], 0.4)
        self.assertNotIn("cause_commune", a[4])
        self.assertEqual((a[4]["constat"], a[4]["confiance"]), ("Constat.", 0.8))

    def test_pas_de_marque_pour_un_seul_immeuble_ni_pour_trois(self):
        a = [alerte("S01", "2025-06-24"), alerte("S02", "2025-06-24"), alerte("S03", "2025-06-24")]
        self.assertEqual(recoupement.groupes(a[:1], juges(10), P), {})
        self.assertEqual(recoupement.groupes(a, juges(10), P), {})
        # deux compteurs du même immeuble ne font pas deux immeubles
        a.append(alerte("S03", "2025-06-24", "gaz_signature"))
        self.assertEqual(recoupement.groupes(a, juges(10), P), {})

    def test_pas_de_marque_quand_les_debuts_sont_etales(self):
        a = [alerte(f"S{i:02d}", f"2025-06-{j:02d}") for i, j in ((1, 2), (2, 7), (3, 12), (4, 17), (5, 22))]
        self.assertEqual(recoupement.groupes(a, juges(10), P), {})
        # la fenêtre se compte du premier au dernier début : 4 jours d'écart avec une fenêtre de 3 jours
        a = [alerte(f"S{i:02d}", f"2025-06-{j:02d}") for i, j in ((1, 20), (2, 21), (3, 22), (4, 24))]
        self.assertEqual(recoupement.groupes(a, juges(10), P), {})

    def test_pas_de_marque_quand_la_part_du_parc_est_trop_faible(self):
        a = [alerte(f"S{i:02d}", "2025-06-24") for i in range(1, 5)]
        self.assertEqual(recoupement.groupes(a, juges(48), P), {})  # 4 sur 48 jugés : moins de 10 %
        self.assertEqual(len(recoupement.groupes(a, juges(40), P)), 4)  # 4 sur 40 : 10 %

    def test_familles_distinctes_sinistres_et_donnees_jamais_concernes(self):
        # 2 signatures + 2 PAC : deux familles, aucun groupe ; fuites et alertes Données simultanées : jamais marquées
        a = [alerte("S01", "2025-06-24"), alerte("S02", "2025-06-24"),
             alerte("S03", "2025-06-24", "pac_cop"), alerte("S04", "2025-06-24", "pac_cop")]
        a += [alerte(f"S{i:02d}", "2025-06-24", "eau_nuit", sinistre=True, gravite="Critique") for i in range(1, 6)]
        a += [dict(alerte(f"S{i:02d}", None, "donnees_silence", gravite="Données")) for i in range(1, 6)]
        self.assertEqual(recoupement.groupes(a, juges(5) | juges(5, "pac_cop") | juges(5, "eau_nuit"), P), {})

    def test_seuils_lus_dans_les_parametres(self):
        a = [alerte("S01", "2025-06-20"), alerte("S02", "2025-06-26")]
        reglage = {**P, "cause_commune_immeubles_min": 2, "cause_commune_fenetre_jours": 7, "cause_commune_confiance": 0.25}
        recoupement.marquer(a, juges(10), reglage)
        self.assertEqual([x["confiance"] for x in a], [0.2, 0.2])


class TestCauseCommuneDansLeMoteur(unittest.TestCase):
    """Sur l'exemple : aucune dérive injectée n'est marquée ; une alerte marquée perd en score et n'a pas de bon automatique."""

    @classmethod
    def setUpClass(cls):
        cls.cx = base_exemple("recoupement")
        cls.ref = db.referentiel(cls.cx, service.defauts())
        cls.alertes = moteur.analyser(cls.cx, cls.ref)[0]

    def test_derives_independantes_de_l_exemple_non_marquees(self):
        self.assertEqual([a["id"] for a in self.alertes if a.get("cause_commune")], [])

    def test_alerte_marquee_score_abaisse_et_pas_de_bon_automatique(self):
        # seuils abaissés pour marquer la signature de chauffage de l'exemple (1 immeuble sur 4 jugés)
        ref = {**self.ref, "parametres": {**self.ref["parametres"], "cause_commune_immeubles_min": 1}}
        marquees = {a["id"]: a for a in moteur.analyser(self.cx, ref)[0]}
        avant = {a["id"]: a for a in self.alertes}
        self.assertEqual(set(marquees), set(avant))  # aucune alerte supprimée
        a = marquees["OB-chaleur_signature"]
        self.assertEqual(a["cause_commune"]["juges"], 4)
        self.assertLess(a["score"], 0.6 * avant["OB-chaleur_signature"]["score"])
        for aid in ("T8-eau_nuit", "R41-chaleur_vide", "R41-donnees-R41_ECS"):  # sinistre, immeuble vide, données
            self.assertNotIn("cause_commune", marquees[aid])
            self.assertEqual(marquees[aid]["score"], avant[aid]["score"])
        nouvelles = bons.synchroniser_alertes(self.cx, list(marquees.values()))
        db.ecrire_parametre(self.cx, "automatisation", {"mode": "brouillon", "gravite_min": "Modérée", "inclure_donnees": True})
        bons.automatiser(self.cx, nouvelles)
        self.assertIsNone(bons.bon_ouvert(self.cx, "OB-chaleur_signature"))
        self.assertIsNotNone(bons.bon_ouvert(self.cx, "T8-eau_nuit"))
        bon, cree = bons.creer_bon(self.cx, "OB-chaleur_signature")  # le bon manuel reste possible
        self.assertTrue(cree)
        self.assertIn("effet probable de météo ou de calendrier", bon["corps"])


if __name__ == "__main__":
    unittest.main()
