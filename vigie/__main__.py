"""Vigie — ligne de commande.

  python -m vigie interface              ouvre l'interface de gestion (http://127.0.0.1:8765)
  python -m vigie interface --demo       idem sur la base d'exemple (vigie_demo.db)
  python -m vigie demo                   recrée l'exemple (24 adresses, 12 mois) : consommations simulées, météo réelle
  python -m vigie demo --petit           exemple réduit (5 immeubles, 4 adresses)
  python -m vigie demo --meteo-fictive   idem avec une température fictive (hors ligne)
  python -m vigie evaluer                précision / rappel (météo fictive, référence de validation)
  python -m vigie evaluer --meteo-reelle précision / rappel avec la vraie météo de Genève
  python -m vigie evaluer --grand        précision / rappel sur le grand exemple (24 adresses, 15 dérives)
  python -m vigie importer mesures.csv   importe un fichier de mesures (ts,point_id,valeur) dans vigie.db
  python -m vigie analyser               lance la détection sur vigie.db et écrit les sorties
  python -m vigie meteo [--station=GVE]  met à jour la température extérieure MétéoSuisse dans vigie.db
  python -m vigie importer-patrimoine classeur.xlsx [--apercu]
                                         importe sites, bâtiments, compteurs et relevés mensuels dans vigie.db
  python -m vigie importer-courbes fichier.csv [...] [--apercu]
                                         importe des courbes au jour, à l'heure ou au quart d'heure (et le calendrier
                                         d'un classeur .xlsx du même lot)
  python -m vigie meteo-periode AAAA-MM-JJ AAAA-MM-JJ
                                         charge la météo horaire MétéoSuisse d'une période passée dans vigie.db
  python -m vigie rejouer AAAA-MM-JJ AAAA-MM-JJ [--pas=1]
                                         rejoue la détection jour après jour sur la période et liste les épisodes
  python -m vigie reprendre-prestataires ancienne_base.db
                                         reprend la liste des prestataires d'une autre base Vigie dans vigie.db
  python -m vigie mcp [--demo]           serveur MCP en lecture seule pour un assistant IA (stdio, voir docs/API.md)
"""
import os
import sys

from . import db, rapport, service

BASE = os.path.join(service.RACINE, "vigie.db")
BASE_DEMO = os.path.join(service.RACINE, "vigie_demo.db")
ATTENDUES = {"T8-eau_nuit", "T8-pac_cop", "R41-chaleur_vide", "OA-elec_nuit", "OB-chaleur_signature",
             "T8-solaire_panne", "R41-donnees-R41_ECS"}


def _afficher(res):
    print(f"\nAnalyse au {res['donnees_au']} — {len(res['alertes'])} alertes\n")
    for a in res["alertes"]:
        impact = "" if a["gravite"] == "Données" else rapport.enjeu(a)[0]
        print(f" {a['rang']:>2}. [{a['gravite']:<8}] {a['immeuble']:<24} {a['titre'][:58]:<58} {impact}")
    if res.get("bons") and res["bons"]["crees"]:
        print(f"\nBons de travaux créés : {', '.join(res['bons']['crees'])}")
    print(f"\nSorties : {service.SORTIE}/rapport.html, alertes.json, alertes.csv")


def creer_demo(chemin=BASE_DEMO, graine=42, meteo_reelle=True, taille="grand"):
    if os.path.exists(chemin):
        try:
            os.remove(chemin)
        except PermissionError:
            sys.exit("La base d'exemple est utilisée par l'interface Vigie : fermez la fenêtre de Vigie, puis relancez.")
    cx = db.connecter(chemin)
    info = service.charger_exemple(cx, graine, meteo_reelle=meteo_reelle, taille=taille)
    print(f"Exemple {taille} — données : {info['mesures']} mesures (consommations simulées, météo {info['meteo']}), "
          f"import {info['lot']} : {info['importees']} mesures, {info['rejets']} rejets")
    if info["avertissement"]:
        print("  " + info["avertissement"])
    return cx


def evaluer(meteo_reelle=False, taille="standard"):
    """Précision / rappel contre les dérives injectées, sur une base d'exemple neuve (temporaire)."""
    import shutil
    import tempfile

    from . import moteur
    dossier = tempfile.mkdtemp(prefix="vigie-eval-")
    sortie, service.SORTIE = service.SORTIE, dossier
    try:
        cx = db.connecter(os.path.join(dossier, "eval.db"))
        info = service.charger_exemple(cx, meteo_reelle=meteo_reelle, taille=taille)
        alertes, _ = moteur.analyser(cx, db.referentiel(cx, service.defauts()))
        cx.close()
    finally:
        service.SORTIE = sortie
        shutil.rmtree(dossier, ignore_errors=True)
    attendues = ATTENDUES | (set(service.exemple_grand()["derives_attendues"]) if taille == "grand" else set())
    trouvees = {a["id"] for a in alertes}
    vp = len(attendues & trouvees)
    print(f"Exemple {taille} · météo {info['meteo']} · dérives injectées : {len(attendues)} · alertes levées : {len(trouvees)}")
    if info["avertissement"]:
        print("  " + info["avertissement"])
    print(f"Précision (alertes justes / alertes levées) : {vp / max(1, len(trouvees)):.0%}")
    print(f"Rappel (dérives trouvées / dérives injectées) : {vp / len(attendues):.0%}")
    for x in sorted(trouvees - attendues):
        print("  fausse alerte :", x)
    for x in sorted(attendues - trouvees):
        print("  dérive manquée :", x)


def periode(cmd, argv):
    """Météo d'une période passée, ou rejeu de la détection sur une période (dates AAAA-MM-JJ)."""
    from datetime import datetime

    from . import meteo, rejeu
    try:
        debut, fin = (datetime.strptime(a, "%Y-%m-%d") for a in [x for x in argv[2:] if not x.startswith("--")][:2])
    except ValueError:
        sys.exit(f"Indiquez la période : python -m vigie {cmd} 2025-01-01 2025-12-31")
    cx = db.connecter(BASE)
    if cmd == "meteo-periode":
        try:
            b = meteo.charger_periode(cx, debut, fin.replace(hour=23))
        except meteo.ErreurMeteo as e:
            sys.exit(f"Météo : {e}")
        print(f"Météo {b['station']} : {b['meteo']} heures de température, {b['rayonnement']} heures de rayonnement")
        return
    pas = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--pas=")), 1)
    suivi = lambda jour, n: print(f"  {jour:%d.%m.%Y} : {n} alertes", flush=True) if jour.day == 1 else None  # noqa: E731
    r = rejeu.rejouer(cx, db.referentiel(cx, service.defauts()), debut, fin, pas, suivi)
    chemin = rejeu.enregistrer(cx, r, service.SORTIE)
    print(f"Rejeu du {r['debut']} au {r['fin']} : {r['analyses']} analyses, {len(r['episodes'])} épisodes")
    for e in r["episodes"]:
        fin_e = e["disparu_le"] or "en cours à la fin"
        print(f"  {e['detecte_le']}  {e['immeuble_id']:<4} {e['cause']:<20} [{e['gravite']:<8}] début {e['debut']}, "
              f"fin {fin_e}, {e['jours_en_alerte']} j en alerte · {e['titre']}")
    print(f"Épisodes : {chemin}")
    # Les alertes encore en cours à la dernière date rejouée sont ouvertes dans la base, comme si Vigie avait tourné
    # toute la période : leur référence reste gelée à leur début pour les analyses suivantes.
    from . import bons
    bons.synchroniser_alertes(cx, r["alertes_finales"])
    print(f"Alertes en cours à la fin du rejeu : {len(r['alertes_finales'])} ouvertes dans la base")
    _afficher(service.analyser(cx))


def _fichiers(argv, usage):
    fichiers = [a for a in argv[2:] if not a.startswith("--")]
    absents = [f for f in fichiers if not os.path.exists(f)]
    if not fichiers or absents:
        sys.exit(usage + ("" if not absents else " — introuvable : " + ", ".join(absents)))
    return fichiers


def importer_patrimoine(argv):
    """Classeur patrimoine -> vigie.db. --apercu : contrôle sans rien écrire."""
    from . import patrimoine
    fichier = _fichiers(argv, "Indiquez le classeur : python -m vigie importer-patrimoine classeur.xlsx [--apercu]")[0]
    with open(fichier, "rb") as f:
        contenu = f.read()
    try:
        r = patrimoine.importer(db.connecter(BASE), contenu, "--apercu" not in argv, service.SORTIE)
    except (patrimoine.ErreurPatrimoine, ValueError) as e:
        sys.exit(f"Classeur patrimoine : {e}")
    m = r["mesures"]
    print(f"{'Import' if r['applique'] else 'Aperçu (rien écrit)'} — {r['commune']}, {r['periode'][0]} à {r['periode'][1]}")
    print(f"  {r['sites']['total']} sites ({r['sites']['nouveaux']} nouveaux), {r['batiments']} bâtiments, "
          f"{r['installations']} installations")
    print(f"  {r['compteurs']['total']} compteurs ({r['compteurs']['actifs']} en service, "
          f"{r['compteurs']['hors_service']} hors service)")
    print(f"  {m['a_importer']} relevés sur {m['lues']} lignes : {m['rejetees']} rejetées, {m['manquantes']} manquants, "
          f"{m['doublons']} doublons, {m['estimees']} estimés, {m['suspectes']} suspects")
    print(f"  {r['references']} références (climat, conversions, CO₂) · {len(r['erreurs'])} erreurs de structure")
    for e in r["erreurs"][:20]:
        print(f"    {e['feuille']} ligne {e['ligne']} : {e['message']}")
    _afficher_anomalies(r)


def _afficher_anomalies(r):
    for t, n in r["anomalies_par_type"].items():
        print(f"    anomalie « {t} » : {n}")
    if r.get("fichier_anomalies"):
        print(f"  Trace des anomalies : {r['fichier_anomalies']}")


def importer_courbes(argv):
    """Courbes fines (CSV) et calendrier (.xlsx) -> vigie.db. --apercu : contrôle sans rien écrire."""
    from . import courbes, patrimoine
    usage = "Indiquez les fichiers : python -m vigie importer-courbes courbe.csv [autre.csv classeur.xlsx] [--apercu]"
    cx = db.connecter(BASE)
    for fichier in _fichiers(argv, usage):
        with open(fichier, "rb") as f:
            contenu = f.read()
        try:
            r = courbes.importer(cx, contenu, os.path.basename(fichier), "--apercu" not in argv, service.SORTIE)
        except (patrimoine.ErreurPatrimoine, ValueError) as e:
            sys.exit(f"Courbes : {e}")
        print(f"{'Import' if r['applique'] else 'Aperçu (rien écrit)'} — {r['fichier']} : {len(r['series'])} séries, "
              f"{r['compteurs']} compteurs, {r['mesures']} mesures, {r['references']} références")
        for s in r["series"]:
            print(f"    {s['id']:<18} {s['valeurs']:>6} valeurs  {s['periode'][0]} à {s['periode'][1]}  "
                  f"total {s['total']:.0f} {s['unite']}" + (f"  ({s['mois_en_ecart']} mois en écart)" if s["mois_en_ecart"] else ""))
        _afficher_anomalies(r)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "interface"
    if cmd == "interface":
        from . import serveur
        demo = "--demo" in argv
        if demo and not os.path.exists(BASE_DEMO):
            creer_demo().close()
        port = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--port=")), 8765)
        serveur.lancer(BASE_DEMO if demo else BASE, port=port, ouvrir="--sans-navigateur" not in argv)
    elif cmd == "mcp":
        import contextlib

        from . import mcp
        demo = "--demo" in argv
        if demo and not os.path.exists(BASE_DEMO):
            with contextlib.redirect_stdout(sys.stderr):  # la sortie standard est réservée au protocole
                creer_demo().close()
        mcp.servir(BASE_DEMO if demo else BASE)
    elif cmd == "demo":
        cx = creer_demo(meteo_reelle="--meteo-fictive" not in argv, taille="standard" if "--petit" in argv else "grand")
        _afficher(service.analyser(cx))
    elif cmd == "importer":
        if len(argv) < 3:
            print("Indiquez le fichier : python -m vigie importer mesures.csv")
            return
        cx = db.connecter(BASE)
        ok, rejets, lot = db.importer_csv(cx, argv[2])
        print(f"Import {lot} : {ok} mesures, {len(rejets)} rejets")
        for ligne, motif in rejets[:20]:
            print(f"  ligne {ligne} : {motif}")
    elif cmd == "meteo":
        from . import meteo
        cx = db.connecter(BASE)
        station = next((a.split("=", 1)[1] for a in argv if a.startswith("--station=")), None)
        try:
            if station:
                meteo.ecrire_config(cx, {"station": station})
            r = meteo.mettre_a_jour(cx)
        except meteo.ErreurMeteo as e:
            sys.exit(f"Météo : {e}")
        print(f"Météo {meteo.lire_config(cx)['station']} : {r['heures']} heures lues ({', '.join(r['fichiers'])}), "
              f"dernière mesure {r['derniere_mesure']} (UTC) -> point {r['point_id']}")
    elif cmd in ("meteo-periode", "rejouer"):
        periode(cmd, argv)
    elif cmd == "importer-patrimoine":
        importer_patrimoine(argv)
    elif cmd == "importer-courbes":
        importer_courbes(argv)
    elif cmd == "reprendre-prestataires":
        if len(argv) < 3 or not os.path.exists(argv[2]):
            sys.exit("Indiquez la base d'origine : python -m vigie reprendre-prestataires ancienne_base.db")
        from . import parc
        b = parc.reprendre_prestataires(db.connecter(BASE), argv[2])
        print(f"Prestataires repris : {b['repris']} ({b['deja_presents']} déjà présents)")
        for p in b["repartis"]:
            print(f"  {p['nom']} ({p['metier']}) : {p['immeubles']} immeubles, quartiers {', '.join(p['quartiers']) or '—'}")
    elif cmd == "analyser":
        _afficher(service.analyser(db.connecter(BASE)))
    elif cmd == "evaluer":
        # Référence de validation (CLAUDE.md §10) : météo fictive, reproductible et hors ligne.
        # --meteo-reelle : même évaluation avec la vraie météo de Genève-Cointrin.
        evaluer(meteo_reelle="--meteo-reelle" in argv, taille="grand" if "--grand" in argv else "standard")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
