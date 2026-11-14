"""Température MétéoSuisse : conversion, import, protection de la base d'exemple (sans accès réseau)."""
import threading
import unittest
from datetime import datetime, timedelta, timezone

from commun import base_exemple, base_vide

from vigie import db, meteo, serveur

ENTETE = "station_abbr;reference_timestamp;tre200h0;tre200hn;ure200h0\n"
MAINTENANT = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)


def fichier(lignes):
    return ENTETE + "".join(f"{st};{ts};{v};0;80\n" for st, ts, v in lignes)


class FauxMeteoSuisse:
    """Remplace le téléchargement : renvoie un contenu par type de fichier et note les URL demandées."""

    def __init__(self, recent, now, historique=None):
        self.contenus = {"_h_recent": recent, "_h_now": now, "_h_historical": historique}
        self.demandes = []

    def __call__(self, url):
        self.demandes.append(url)
        for cle, contenu in self.contenus.items():
            if cle in url:
                if contenu is None:
                    raise meteo.ErreurMeteo("404")
                return contenu
        raise AssertionError(url)


class TestConversion(unittest.TestCase):
    def test_horodatage_suisse_converti_en_iso_utc_fin_d_intervalle(self):
        r = meteo.convertir(fichier([("GVE", "11.11.2026 23:00", "9.2")]), "GVE")
        self.assertEqual(r, [("2026-11-11T23:00:00Z", 9.2)])

    def test_heures_manquantes_implausibles_ou_autre_station_ecartees(self):
        r = meteo.convertir(fichier([("GVE", "11.11.2026 20:00", ""), ("GVE", "11.11.2026 21:00", "99"),
                                     ("BER", "11.11.2026 22:00", "5"), ("GVE", "11.11.2026 23:00", "-3.5")]), "GVE")
        self.assertEqual(r, [("2026-11-11T23:00:00Z", -3.5)])

    def test_format_inattendu_refuse(self):
        with self.assertRaises(meteo.ErreurMeteo):
            meteo.convertir("a;b\n1;2\n", "GVE")

    def test_urls_officielles(self):
        u = meteo.urls("GVE", MAINTENANT)
        self.assertEqual(u["recent"], "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/gve/ogd-smn_gve_h_recent.csv")
        self.assertTrue(u["historique"].endswith("ogd-smn_gve_h_historical_2020-2029.csv"))


class TestMiseAJour(unittest.TestCase):
    def test_premiere_mise_a_jour_cree_le_point_et_charge_l_historique(self):
        cx = base_vide("meteo")
        faux = FauxMeteoSuisse(recent=fichier([("GVE", "10.11.2026 23:00", "8.0"), ("GVE", "11.11.2026 23:00", "9.0")]),
                               now=fichier([("GVE", "11.11.2026 23:00", "9.2"), ("GVE", "12.11.2026 05:00", "7.5")]),
                               historique=fichier([("GVE", "01.10.2026 00:00", "12.0")]))
        r = meteo.mettre_a_jour(cx, faux, MAINTENANT)
        self.assertEqual((r["point_id"], r["heures"], r["derniere_mesure"]), ("METEO_GVE", 4, "2026-11-12T05:00:00Z"))
        self.assertTrue(any("historical" in u for u in faux.demandes))
        mesures = dict(cx.execute("SELECT ts, valeur FROM mesure WHERE point_id = 'METEO_GVE'").fetchall())
        self.assertEqual(mesures["2026-11-11T23:00:00Z"], 9.2)  # « now », plus récent, l'emporte
        ref = db.referentiel(cx, {"parametres": {}, "tarifs": {}, "facteurs_co2_kg_par_kwh": {}})
        self.assertEqual(ref["meteo"]["id"], "METEO_GVE")
        self.assertEqual(meteo.lire_config(cx)["statut"], "ok")

    def test_historique_absent_n_empeche_pas_la_mise_a_jour(self):
        cx = base_vide("meteo-sans-histo")
        faux = FauxMeteoSuisse(recent=fichier([("GVE", "11.11.2026 23:00", "9.0")]), now=fichier([]), historique=None)
        self.assertEqual(meteo.mettre_a_jour(cx, faux, MAINTENANT)["fichiers"], ["recent", "now"])

    def test_echec_reseau_note_et_signale(self):
        cx = base_vide("meteo-echec")

        def panne(url):
            raise meteo.ErreurMeteo("MétéoSuisse injoignable")
        with self.assertRaises(meteo.ErreurMeteo):
            meteo.mettre_a_jour(cx, panne, MAINTENANT)
        self.assertEqual(meteo.lire_config(cx)["statut"], "erreur")
        self.assertEqual(cx.execute("SELECT count(*) FROM mesure").fetchone()[0], 0)

    def test_base_d_exemple_jamais_remplacee(self):
        cx = base_exemple("meteo-exemple")
        with self.assertRaisesRegex(meteo.ErreurMeteo, "exemple"):
            meteo.mettre_a_jour(cx, FauxMeteoSuisse(recent="", now=""), MAINTENANT)
        self.assertEqual(db.lignes(cx, "SELECT etat FROM point_mesure WHERE id = 'METEO_TEXT'")[0]["etat"], "actif")

    def test_exemple_sur_meteo_reelle_n_ajoute_que_les_heures_nouvelles(self):
        cx = base_vide("meteo-exemple-reel-maj")
        pid = meteo.point_meteo(cx, "GVE")
        cx.executemany("INSERT INTO mesure VALUES (?, ?, ?, 'valide', 'exemple')",
                       [("2026-11-11T22:00:00Z", pid, 5.0), ("2026-11-11T23:00:00Z", pid, 6.0)])
        db.ecrire_parametre(cx, "meteo", {**meteo.CONFIG_DEFAUT, "source": "exemple", "auto": False, "point_id": pid,
                                          "statut": "exemple_reel"})
        cx.commit()
        self.assertFalse(meteo.etat(cx)["exemple_fictif"])
        faux = FauxMeteoSuisse(recent=fichier([("GVE", "11.11.2026 23:00", "9.0")]),  # correction d'une heure passée
                               now=fichier([("GVE", "12.11.2026 05:00", "7.5")]))
        r = meteo.mettre_a_jour(cx, faux, MAINTENANT)
        self.assertEqual((r["heures"], r["derniere_mesure"]), (1, "2026-11-12T05:00:00Z"))
        mesures = dict(cx.execute("SELECT ts, valeur FROM mesure WHERE point_id = ?", (pid,)).fetchall())
        self.assertEqual(mesures["2026-11-11T23:00:00Z"], 6.0)  # l'heure qui a servi à la simulation n'est pas réécrite
        self.assertEqual(mesures["2026-11-12T05:00:00Z"], 7.5)
        self.assertEqual(meteo.mettre_a_jour(cx, faux, MAINTENANT)["heures"], 0)  # déjà à jour
        with self.assertRaises(meteo.ErreurMeteo):
            meteo.ecrire_config(cx, {"station": "BER"})  # la station de l'exemple ne change pas
        self.assertTrue(meteo.ecrire_config(cx, {"station": "GVE", "auto": True})["auto"])

    def test_meteo_plus_recente_que_les_compteurs_ne_les_rend_pas_muets(self):
        from commun import ATTENDUES

        from vigie import moteur, service
        cx = base_exemple("meteo-en-avance")
        ref = db.referentiel(cx, service.defauts())
        avant, fin = moteur.analyser(cx, ref)
        pid = ref["meteo"]["id"]
        heures = [(fin + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in range(1, 73)]
        cx.executemany("INSERT INTO mesure VALUES (?, ?, 8.0, 'valide', 'test')", [(ts, pid) for ts in heures])
        cx.commit()
        apres, fin2 = moteur.analyser(cx, ref)
        self.assertEqual(fin2, fin)
        self.assertEqual({a["id"] for a in apres}, {a["id"] for a in avant})
        self.assertEqual({a["id"] for a in apres}, ATTENDUES)
        self.assertEqual(db.etat_points(cx)[1], fin.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_station_invalide_refusee(self):
        with self.assertRaises(meteo.ErreurMeteo):
            meteo.ecrire_config(base_vide("meteo-station"), {"station": "G1"})

    def test_exemple_sur_meteo_reelle_sans_heure_comblee(self):
        from datetime import timedelta

        from vigie import service
        # série synthétique calée sur aujourd'hui (l'exemple couvre 12 mois : le chargement lit 375 jours)
        fin = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        debut = fin - timedelta(days=380)
        trou = (fin - timedelta(days=20)).replace(hour=3)  # une heure non mesurée par la station
        lignes = [("GVE", (debut + timedelta(hours=h)).strftime("%d.%m.%Y %H:%M"), f"{12 + 6 * ((h % 24) / 24):.1f}")
                  for h in range(0, 380 * 24 + 1) if debut + timedelta(hours=h) != trou]
        faux = FauxMeteoSuisse(recent=fichier(lignes), now=fichier([]), historique=fichier([]))
        cx = base_vide("exemple-reel")
        reel = meteo.temperatures_reelles(telecharger_fn=faux)
        info = service.charger_exemple(cx, meteo_reelle=True, telecharger_fn=faux)
        self.assertEqual(info["meteo"], "réelle", info["avertissement"])
        cfg = meteo.lire_config(cx)
        self.assertEqual((cfg["source"], cfg["auto"], cfg["statut"], cfg["point_id"]), ("exemple", False, "exemple_reel", "METEO_GVE"))
        self.assertEqual(db.lignes(cx, "SELECT etat FROM point_mesure WHERE id = 'METEO_TEXT'")[0]["etat"], "inactif")
        self.assertIsNone(cx.execute("SELECT 1 FROM mesure WHERE point_id = 'METEO_GVE' AND ts = ?",
                                     (trou.strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone())  # le trou reste un trou
        self.assertTrue(reel)

    def test_exemple_repli_sur_meteo_fictive_si_meteosuisse_injoignable(self):
        from vigie import service

        def panne(url):
            raise meteo.ErreurMeteo("injoignable")
        info = service.charger_exemple(base_vide("exemple-panne"), meteo_reelle=True, telecharger_fn=panne)
        self.assertEqual(info["meteo"], "fictive")
        self.assertIn("injoignable", info["avertissement"])

    def test_fil_automatique_s_arrete_proprement(self):
        cx = base_vide("meteo-fil")
        chemin = cx.execute("PRAGMA database_list").fetchone()[2]
        meteo.ecrire_config(cx, {"auto": False})
        arret = threading.Event()
        fil = threading.Thread(target=serveur.meteo_automatique, args=(chemin, arret, 3600, 0))
        fil.start()
        arret.set()
        fil.join(5)
        self.assertFalse(fil.is_alive())


if __name__ == "__main__":
    unittest.main()
