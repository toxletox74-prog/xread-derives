"""Import d'un classeur patrimoine (sites, bâtiments, compteurs, relevés mensuels) et de ses courbes fines."""
import os
import sqlite3
import unittest

from commun import RACINE, base_vide

from vigie import courbes, db, excel, geo, moteur, parc, patrimoine, serveur, service

MOIS = [f"{a}-{m:02d}" for a in (2024, 2025) for m in range(1, 13)]
CLASSEUR_REEL = os.path.join(RACINE, "donnees", "patrimoine.xlsx")


def classeur():
    """Petit classeur au format du lot communal : 2 sites, 3 bâtiments, des défauts volontaires dans les mesures."""
    mesures = [["mois", "id_compteur", "id_site", "fluide", "mesure", "valeur", "unite", "energie_kwh", "qualite"]]
    for m in MOIS:
        mesures.append([m, "S01-EL", "S01", "électricité", "soutirage", 1000, "kWh", 1000, "mesuré"])
        if m >= "2024-07":
            mesures.append([m, "S01-CAD", "S01", "chaleur à distance", "consommation", 744, "kWh", 744, "mesuré"])
        else:  # gaz jusqu'en juin 2024 : valeur négative en mars, énergie incohérente en avril
            v, e = (-50, -550) if m == "2024-03" else (100, 9999 if m == "2024-04" else 1100)
            mesures.append([m, "S01-GZ", "S01", "gaz", "consommation", v, "m3", e, "mesuré"])
        qualite = {"2024-05": "manquant", "2024-07": "estimé"}.get(m, "mesuré")
        mesures.append([m, "S02-PV", "S02", "électricité solaire", "production",
                        None if qualite == "manquant" else 500, "kWh", None if qualite == "manquant" else 500, qualite])
    mesures += [["2024-06", "S01-EL", "S01", "électricité", "soutirage", 1000, "kWh", 1000, "mesuré"],   # doublon
                ["2024-02", "S02-MZ", "S02", "mazout", "livraison", 5000, "litre", 50000, "mesuré"],
                ["2024-02", "S02-MZ", "S02", "mazout", "livraison", 2000, "litre", 20000, "mesuré"],     # 2e livraison
                ["2025-01", "S99-EL", "S99", "électricité", "soutirage", 10, "kWh", 10, "mesuré"]]       # inconnu
    return excel.ecrire_xlsx({
        "Lisez-moi": [["Ville-Test · Jeu de données"]],
        "Batiments": [["id_batiment", "id_site", "nom_site", "quartier", "typologie", "nom_batiment", "annee_construction",
                       "annee_renovation", "sre_m2", "niveaux", "label", "logements", "ouverture", "x_km", "y_km", "remarque"],
                      ["S01-B1", "S01", "Mairie", "Centre", "Administration", "Hôtel de ville", 1912, 1998, 2600, 3, "", "", "", 2.0, 2.7, ""],
                      ["S01-B2", "S01", "Mairie", "Centre", "Administration", "Annexe", 1975, "", 900, 2, "", "", "", 2.0, 2.7, ""],
                      ["S02-B1", "S02", "École du Lac", "Rive", "École primaire", "École", 2001, "", 3000, 2, "Minergie", "", "", 1.0, 0.5, ""]],
        "Installations": [["id_installation", "id_site", "type", "libelle", "vecteur", "puissance_kw", "mise_en_service", "retrait", "remarque"],
                          ["S01-I1", "S01", "chaudiere_gaz", "Chaudière à gaz", "gaz", 380, "2005-01", "2024-06", ""],
                          ["S01-I2", "S01", "sous_station_cad", "Sous-station CAD", "chaleur à distance", 300, "2024-07", "", ""],
                          ["S02-I1", "S02", "pv", "Installation photovoltaïque", "soleil", 40, "2019-05", "", "kWc"]],
        "Compteurs": [["id_compteur", "id_site", "libelle", "fluide", "unite", "niveau", "mesure", "parent", "fournisseur_donnee", "releve", "debut", "fin"],
                      ["S01-EL", "S01", "Électricité générale", "électricité", "kWh", "général", "soutirage", "", "SIR", "automatique, mensuel", "", ""],
                      ["S01-GZ", "S01", "Gaz naturel", "gaz", "m3", "général", "consommation", "", "SIR", "automatique, mensuel", "2005-01", "2024-06"],
                      ["S01-CAD", "S01", "Chaleur à distance", "chaleur à distance", "kWh", "général", "consommation", "", "SIR", "automatique, mensuel", "2024-07", ""],
                      ["S02-PV", "S02", "Production photovoltaïque", "électricité solaire", "kWh", "production", "production", "", "commune", "automatique, mensuel", "2019-05", ""],
                      ["S02-MZ", "S02", "Mazout (livraisons)", "mazout", "litre", "livraison", "livraison", "", "fournisseur", "bon de livraison", "", ""]],
        "Mesures": mesures,
        "Ref_Climat": [["mois", "temperature_moy_c", "degres_jours_20_12", "rayonnement_kwh_m2", "ensoleillement_h"],
                       ["2025-01", 2.3, 548, 30.9, 49]],
        "Ref_Conversion": [["vecteur", "mois", "facteur", "unite", "source"]] + [["gaz", m, 11, "kWh par m³", "test"] for m in MOIS]
                          + [["mazout", "toujours", 10, "kWh par litre", "test"]],
    })


class TestClasseur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cx = base_vide("patrimoine")
        cls.apercu = patrimoine.importer(cls.cx, classeur())
        cls.vide_apres_apercu = service.parc_vide(cls.cx)
        cls.r = patrimoine.importer(cls.cx, classeur(), True)

    def test_apercu_sans_ecriture_puis_import(self):
        self.assertTrue(self.vide_apres_apercu)
        self.assertEqual((self.apercu["sites"], self.apercu["batiments"], self.apercu["installations"]),
                         ({"total": 2, "nouveaux": 2}, 3, 3))
        self.assertEqual((self.r["applique"], self.r["commune"], self.r["periode"]), (True, "Ville-Test", ["2024-01", "2025-12"]))
        self.assertEqual(self.r["erreurs"], [])

    def test_site_devient_immeuble_et_les_batiments_gardent_leur_identifiant(self):
        im = db.lignes(self.cx, "SELECT id, nom, sre_m2, typologie, quartier FROM immeuble ORDER BY id")
        self.assertEqual(im[0], {"id": "S01", "nom": "Mairie", "sre_m2": 3500.0, "typologie": "Administration", "quartier": "Centre"})
        self.assertEqual([r[0] for r in self.cx.execute("SELECT id FROM batiment ORDER BY id")], ["S01-B1", "S01-B2", "S02-B1"])
        ad = db.lignes(self.cx, "SELECT rue, npa_localite, x_km, y_km, geo_source FROM adresse WHERE rue = 'Mairie'")[0]
        self.assertEqual(ad, {"rue": "Mairie", "npa_localite": "Quartier Centre · Ville-Test", "x_km": 2.0, "y_km": 2.7,
                              "geo_source": "plan"})
        fiche = parc.fiche(self.cx, "S01")
        self.assertEqual((fiche["immeuble"]["technique"]["chauffage"], len(fiche["batiments"]), len(fiche["installations"])),
                         ("Chauffage à distance (CAD)", 2, 2))

    def test_les_sites_recoivent_des_coordonnees_gps_calculees_depuis_le_plan_et_enregistrees(self):
        ads = db.lignes(self.cx, "SELECT x_km, y_km, lat, lon, geo_source, geo_label FROM adresse ORDER BY x_km, y_km")
        self.assertEqual(len(ads), 2)
        for a in ads:                                                    # coordonnées en base, en Suisse
            self.assertEqual((a["geo_source"], a["geo_label"]), ("plan", geo.LABEL_PLAN))
            self.assertTrue(geo.dans_bornes(a["lat"], a["lon"]))
        ouest, est = ads
        self.assertAlmostEqual((ouest["lat"] + est["lat"]) / 2, geo.PLAN_CENTRE[0], places=5)   # milieu du plan
        self.assertAlmostEqual((ouest["lon"] + est["lon"]) / 2, geo.PLAN_CENTRE[1], places=5)
        self.assertAlmostEqual((est["lon"] - ouest["lon"]) * 77.05, est["x_km"] - ouest["x_km"], places=3)  # distances gardées
        self.assertAlmostEqual((est["lat"] - ouest["lat"]) * 111.2, est["y_km"] - ouest["y_km"], places=3)
        self.assertEqual(geo.placer_plan(self.cx), 0)                    # déjà placés : rien n'est recalculé
        self.assertEqual(geo.geocoder_parc(self.cx)["traitees"], 0)       # jamais envoyés au géocodeur
        carte = serveur.Application.lire_carte(type("A", (), {"cx": self.cx})(), None)
        self.assertEqual((carte["plan_reporte"], carte["non_localisees"]), (2, 0))

    def test_position_saisie_a_la_main_jamais_remplacee_par_le_plan(self):
        cx = base_vide("patrimoine-gps")
        patrimoine.importer(cx, classeur(), True)
        aid = cx.execute("SELECT id FROM adresse WHERE rue = 'Mairie'").fetchone()[0]
        geo.enregistrer(cx, aid, 46.2, 6.15, "manuel")
        patrimoine.importer(cx, classeur(), True)                        # nouvel import du même classeur
        self.assertEqual(cx.execute("SELECT lat, lon, geo_source FROM adresse WHERE id = ?", (aid,)).fetchone(),
                         (46.2, 6.15, "manuel"))
        self.assertEqual(cx.execute("SELECT count(*) FROM adresse WHERE lat IS NULL").fetchone()[0], 0)

    def test_compteurs_mensuels_bornes_de_service_et_solaire(self):
        pts = {p["id"]: p for p in db.lignes(self.cx, "SELECT * FROM point_mesure")}
        self.assertEqual((pts["S01-EL"]["fluide"], pts["S01-EL"]["pas_min"], pts["S01-EL"]["etat"]), ("electricite", db.PAS_MENSUEL, "actif"))
        self.assertEqual((pts["S01-GZ"]["etat"], pts["S01-GZ"]["service_fin"]), ("inactif", "2024-06"))  # retiré : hors service
        self.assertEqual((pts["S02-MZ"]["nature"], pts["S02-MZ"]["unite"]), ("livraison", "l"))
        self.assertEqual((pts["S02-PV"]["fluide"], pts["S02-PV"]["puissance_crete_kwc"], pts["S02-PV"]["mise_en_service"]),
                         ("solaire", 40.0, 2019))

    def test_releves_horodates_a_la_fin_du_mois_et_defauts_traces(self):
        mesure = lambda pid, mois: self.cx.execute(  # noqa: E731
            "SELECT valeur, qualite FROM mesure WHERE point_id = ? AND ts = ?", (pid, patrimoine.ts_fin_mois(mois))).fetchone()
        self.assertEqual(patrimoine.ts_fin_mois("2025-12"), "2026-01-01T00:00:00Z")
        self.assertEqual(mesure("S01-EL", "2024-06"), (1000.0, "valide"))        # doublon identique : une seule mesure
        self.assertEqual(mesure("S01-GZ", "2024-03"), (-50.0, "suspecte"))       # négative : gardée, exclue des calculs
        self.assertIsNone(mesure("S02-PV", "2024-05"))                           # manquant : jamais comblé
        self.assertEqual(mesure("S02-PV", "2024-07"), (500.0, "estimee"))
        self.assertEqual(mesure("S02-MZ", "2024-02"), (7000.0, "valide"))        # deux livraisons du mois additionnées
        self.assertEqual(self.r["anomalies_par_type"], {
            "compteur inconnu": 1, "doublon": 1, "valeur négative": 1, "relevé manquant": 1, "relevé estimé": 1,
            "livraisons du même mois": 1, "énergie incohérente": 1})
        self.assertEqual(self.cx.execute("SELECT count(*) FROM anomalie_import").fetchone()[0], 7)
        self.assertEqual(self.cx.execute("SELECT valeur FROM reference WHERE serie = 'degres_jours_20_12'").fetchone()[0], 548)

    def test_moteur_sans_fausse_alerte_sur_un_parc_mensuel(self):
        alertes, fin = moteur.analyser(self.cx, db.referentiel(self.cx, service.defauts()))
        self.assertEqual(str(fin), "2026-01-01 00:00:00")
        self.assertEqual([a["id"] for a in alertes], [])  # ni « muet » ni « incomplet » : mensuel, livraisons, hors service

    def test_graphique_rattache_le_releve_au_mois_ecoule(self):
        s = serveur.serie_consommation(self.cx, "S01-EL", "mois")
        self.assertEqual((len(s["valeurs"]), s["valeurs"][-1]["periode"], s["valeurs"][-1]["valeur"]), (24, "2025-12", 1000.0))
        pv = {v["periode"]: v for v in serveur.serie_consommation(self.cx, "S02-PV", "mois")["valeurs"]}
        self.assertEqual((pv["2024-05"]["valeur"], pv["2024-07"]["estimee"]), (None, True))

    def test_classeur_sans_les_feuilles_attendues_refuse(self):
        with self.assertRaisesRegex(patrimoine.ErreurPatrimoine, "Batiments"):
            patrimoine.importer(self.cx, excel.ecrire_xlsx({"Feuil1": [["a"], [1]]}))


class TestCourbes(unittest.TestCase):
    def setUp(self):
        self.cx = base_vide("courbes")
        patrimoine.importer(self.cx, classeur(), True)

    def test_courbe_journaliere_reliee_au_compteur_mensuel_et_comparee_a_lui(self):
        jours = [(1, 31, 1000 / 31), (2, 28, 1200 / 28), (3, 31, 1000 / 31)]  # février : +20 % sur le relevé mensuel
        csv = "date;id_compteur;id_site;fluide;valeur;unite\n" + "".join(
            f"2025-{m:02d}-{j:02d};S01-EL;S01;électricité;{v:.6f};kWh\n" for m, n, v in jours for j in range(1, n + 1))
        csv += "2025-07-01;S01-EL;S01;électricité;30;kWh\n2025-01-05;S77-EL;S77;électricité;1;kWh\n"
        r = courbes.importer(self.cx, csv.encode(), "jour.csv", True)
        p = db.lignes(self.cx, "SELECT * FROM point_mesure WHERE id = 'S01-EL-JOUR'")[0]
        self.assertEqual((p["pas_min"], p["parent_id"], p["identifiant"], p["fluide"]), (1440, "S01-EL", "S01-EL", "electricite"))
        ts = [r[0] for r in self.cx.execute("SELECT ts FROM mesure WHERE point_id = 'S01-EL-JOUR' ORDER BY ts")]
        self.assertEqual(ts[0], "2025-01-01T23:00:00Z")     # fin du jour civil de Genève, en UTC (hiver)
        self.assertEqual(ts[-1], "2025-07-01T22:00:00Z")    # (été)
        ecarts = [a for a in r["anomalies"] if a["type"] == "écart avec le relevé mensuel"]
        self.assertEqual([(a["objet"], a["periode"]) for a in ecarts], [("S01-EL-JOUR", "2025-02")])
        self.assertIn("+20,0 %", ecarts[0]["detail"])
        self.assertEqual(r["anomalies_par_type"]["compteur inconnu"], 1)
        self.assertEqual(r["anomalies_par_type"]["pas sans relevé"], 1)  # trou entre le 31 mars et le 1er juillet
        # le compteur mensuel n'a pas bougé, rien n'est compté deux fois
        self.assertEqual(self.cx.execute("SELECT count(*) FROM mesure WHERE point_id = 'S01-EL'").fetchone()[0], 24)

    def test_courbe_horaire_debut_d_intervalle_et_grandeurs_du_chauffage_a_distance(self):
        lignes = ["horodatage;id_compteur;id_site;energie_kwh;debit_m3_h;t_aller_c;t_retour_c"]
        for h in range(744):
            j, heure = divmod(h, 24)
            energie = 5.0 if h in (10, 11, 12) else 1.0  # trois heures où l'énergie contredit débit × écart de température
            lignes.append(f"2025-01-{j + 1:02d}T{heure:02d}:00:00+01:00;S01-CAD;S01;{energie};0.1;80.0;71.4")
        r = courbes.importer(self.cx, "\n".join(lignes).encode(), "cad.csv", True)
        ids = [x[0] for x in self.cx.execute("SELECT id FROM point_mesure WHERE parent_id = 'S01-CAD' ORDER BY id")]
        self.assertEqual(ids, ["S01-CAD-DEBIT", "S01-CAD-HEURE", "S01-CAD-TALLER", "S01-CAD-TRETOUR"])
        premiere = self.cx.execute("SELECT min(ts), count(*) FROM mesure WHERE point_id = 'S01-CAD-HEURE'").fetchone()
        self.assertEqual(premiere, ("2025-01-01T00:00:00Z", 744))  # 00:00+01:00 → fin d'intervalle 01:00+01:00 = 00:00Z
        self.assertEqual(self.cx.execute("SELECT nature, unite FROM point_mesure WHERE id = 'S01-CAD-DEBIT'").fetchone(),
                         ("instantane", "m3/h"))
        self.assertIn("3 heures", next(a["detail"] for a in r["anomalies"] if a["type"] == "bilan thermique incohérent"))
        # un nouvel import du même fichier remplace sa trace d'anomalies au lieu de la doubler
        avant = self.cx.execute("SELECT count(*) FROM anomalie_import").fetchone()[0]
        courbes.importer(self.cx, "\n".join(lignes).encode(), "cad.csv", True)
        self.assertEqual(self.cx.execute("SELECT count(*) FROM anomalie_import").fetchone()[0], avant)

    def test_la_serie_la_plus_fine_est_celle_que_le_moteur_analyse(self):
        csv = "date;id_compteur;id_site;fluide;valeur;unite\n" + "".join(
            f"2025-12-{j:02d};S01-EL;S01;électricité;32.258;kWh\n" for j in range(1, 32))
        courbes.importer(self.cx, csv.encode(), "jour.csv", True)
        ref = db.referentiel(self.cx, service.defauts())
        im = next(i for i in ref["immeubles"] if i["id"] == "S01")
        ids = {p["fluide"]: p["id"] for p in sorted(im["points"], key=lambda p: -p["pas_min"])}
        self.assertEqual(ids["electricite"], "S01-EL-JOUR")

    def test_fichier_sans_les_colonnes_attendues_refuse(self):
        with self.assertRaisesRegex(patrimoine.ErreurPatrimoine, "colonnes attendues"):
            courbes.importer(self.cx, b"a;b\n1;2\n", "autre.csv")
        with self.assertRaisesRegex(patrimoine.ErreurPatrimoine, "aucune feuille de courbes"):
            courbes.importer(self.cx, excel.ecrire_xlsx({"Feuil1": [["a"], [1]]}), "autre.xlsx")

    def test_classeur_de_courbes_au_quart_d_heure_lu_comme_le_csv_et_recharge(self):
        def lignes(coupure):
            out = [["horodatage", "id_compteur", "id_site", "energie_kwh"]]
            for q in range(96):
                h, m = divmod(q * 15, 60)
                valeur = 0 if q in coupure else ("1.500" if 32 <= q < 68 else "0.000")  # nombre ou texte, comme Excel
                out.append([f"2025-01-01T{h:02d}:{m:02d}:00+01:00", "S02-PV", "S02", valeur])
            return out
        csv = "\n".join(";".join(str(c) for c in ligne) for ligne in lignes(()))
        courbes.importer(self.cx, csv.encode(), "pv.csv", True)
        requete = "SELECT ts, valeur FROM mesure WHERE point_id = 'S02-PV-15MIN' ORDER BY ts"
        du_csv = self.cx.execute(requete).fetchall()
        self.assertEqual((len(du_csv), du_csv[0][0], sum(v for _t, v in du_csv)), (96, "2024-12-31T23:15:00Z", 54.0))
        # le même relevé rechargé depuis un classeur, deux quarts d'heure remis à zéro vers midi
        r = courbes.importer(self.cx, excel.ecrire_xlsx({"Feuil1": lignes((48, 49))}), "pv.xlsx", True)
        du_classeur = self.cx.execute(requete).fetchall()
        self.assertEqual((r["mesures"], [s["id"] for s in r["series"]]), (96, ["S02-PV-15MIN"]))
        self.assertEqual([t for t, _v in du_classeur], [t for t, _v in du_csv])   # mêmes horodatages : remplacées
        self.assertEqual(dict(du_classeur)["2025-01-01T11:15:00Z"], 0.0)          # 12:00 → fin d'intervalle 12:15
        self.assertEqual(sum(v for _t, v in du_classeur), 51.0)
        # une seule trace d'anomalies par série : celle du dernier fichier chargé
        fichiers = {x[0] for x in self.cx.execute("SELECT feuille FROM anomalie_import WHERE objet = 'S02-PV-15MIN'")}
        self.assertLessEqual(fichiers, {"pv.xlsx"})


class TestPrestataires(unittest.TestCase):
    def test_liste_reprise_d_une_autre_base_et_orphelins_repartis_par_quartier(self):
        ancienne = base_vide("prestataires-source")
        chemin = ancienne.execute("PRAGMA database_list").fetchone()[2]
        ancienne.executemany("INSERT INTO prestataire (nom, metier, email, perimetre) VALUES (?,?,?,?)", [
            ("Sanitaire SA", "Sanitaire", "a@x.example", "*"), ("Élec Nord", "Électricien", "b@x.example", "G01,G02"),
            ("Élec Sud", "Électricien", "c@x.example", "G03"), ("Chauffage SA", "Chauffagiste", "d@x.example", "G01,S02")])
        ancienne.commit()
        ancienne.close()
        cx = base_vide("prestataires-cible")
        patrimoine.importer(cx, classeur(), True)
        bilan = parc.reprendre_prestataires(cx, chemin)
        self.assertEqual((bilan["repris"], bilan["deja_presents"]), (4, 0))
        perimetres = dict(cx.execute("SELECT nom, perimetre FROM prestataire"))
        self.assertEqual(perimetres, {"Sanitaire SA": "*", "Élec Nord": "S01", "Élec Sud": "S02", "Chauffage SA": "S02"})
        self.assertEqual(parc.reprendre_prestataires(cx, chemin)["repris"], 0)  # jamais de doublon
        source = sqlite3.connect(chemin)
        self.assertEqual(source.execute("SELECT count(*) FROM prestataire").fetchone()[0], 4)  # base d'origine intacte
        source.close()


@unittest.skipUnless(os.path.exists(CLASSEUR_REEL), "classeur patrimoine absent du dossier donnees")
class TestLotCommunal(unittest.TestCase):
    def test_lot_communal_complet(self):
        cx = base_vide("lot-communal")
        with open(CLASSEUR_REEL, "rb") as f:
            r = patrimoine.importer(cx, f.read(), True)
        self.assertEqual((r["sites"]["total"], r["batiments"], r["installations"], r["compteurs"]["total"]), (48, 50, 64, 172))
        self.assertEqual((r["mesures"]["lues"], r["mesures"]["a_importer"], r["erreurs"]), (9437, 9433, []))
        self.assertEqual(r["anomalies_par_type"], {"relevé estimé": 4, "relevé manquant": 3, "doublon": 1, "valeur négative": 1})
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        # la PAC de S09 au-dessus de son historique (règle du même mois) et la seule valeur négative du lot
        par_id = {a["id"]: a for a in alertes}
        self.assertLessEqual({"S09-pac_historique", "S47-elec_historique", "S14-donnees-S14-GZ"}, set(par_id))
        pac = par_id["S09-pac_historique"]
        self.assertEqual((pac["mesure"], pac["persistance"], pac["point_id"]), ("+39 %", "12 mois", "S09-PAC"))
        self.assertIn("à chaleur produite égale ; rendement du mois : 3,0 au lieu de 4,2", pac["constat"])


if __name__ == "__main__":
    unittest.main()
