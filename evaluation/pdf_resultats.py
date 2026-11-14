"""Chapitres 7 et 8 du document PDF : protocole d'évaluation et résultats (campagne horaire, 12 mois)."""
from . import pdf_mise_en_page as M
from .campagne import AGE_BALAYAGE, AGE_DELAI, NOMINALE, ROBUSTE, VARIANTES
from .pdf import (CLIMAT, NOMS, ORDRE, amp, biais, chiffrage, courbe, delai, ecart_principal, erreur_med, fausses, nb,
                  pas_detection, pas_fausses, pct, plage, robuste, seuil50)

SEUILS_NOMINAUX = {"eau_nuit": 20, "eau_vide": 50, "chaleur_signature": 0.10, "chaleur_vide": None,
                   "cad_signature": 0.10, "cad_vide": None, "gaz_signature": 0.10, "gaz_vide": None,
                   "elec_nuit": 0.20, **{k: 0.15 for k in ("pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune")}}


def protocole(c):
    camp = c.camp or {}
    out = c.h1(7, "Protocole d'évaluation")
    out.append(c.p(
        "Les détecteurs sont évalués sur des consommations <b>simulées</b> dont la vérité est connue. Un simulateur "
        "paramétrable (evaluation/simulateur.py) reprend les lois du générateur d'exemple (tableau du chapitre 3) et "
        "ajoute l'<b>ampleur</b> et la <b>date de début</b> de la dérive, des défauts de données et des variantes de "
        "robustesse. Chaque scénario couvre <b>12 mois d'historique relevés à l'heure</b> et est simulé deux fois avec "
        "les <b>mêmes tirages aléatoires</b>, avec et sans dérive : la différence donne l'excès réel, heure par heure, "
        "sans approximation (vérité calculée sur les relevés horaires sans défaut, quel que soit le pas évalué)."))
    out.append(c.p(
        "Chaque scénario passe par la <b>chaîne réelle</b> de Vigie : base SQLite temporaire en mémoire, import CSV "
        "par db.importer_mesures (contrôles de qualité compris), référentiel par db.referentiel, puis "
        "moteur.analyser avec les règles par défaut. Les bases de travail du projet (vigie.db, vigie_demo.db) et le "
        "dossier sorties/ ne sont jamais touchés. La version « avant » de l'expérience de chiffrage est la copie figée "
        "du moteur V0.2.0 (evaluation/reference/moteur_v0_2_0.py), alimentée par les mêmes relevés horaires."))
    lignes = [["Expérience", "Ce qui varie", "Graines", "Mesure"],
              ["Balayage d'ampleur", "13 détecteurs (PAC : 4 comptages ; CAD, gaz) × 10 à 12 ampleurs × météo fictive et réelle "
               "(détecteurs sensibles à la météo)", "12", "probabilité de détection, seuil effectif, chiffrage, confiance"],
              ["Délai et maintien", f"dérive franche démarrant {AGE_DELAI} jours avant la fin ; analyse quotidienne "
               "au fil des jours avec suivi des alertes", "10", "délai de première alerte, perte éventuelle de l'alerte"],
              ["Immeubles sains suivis", "6 types d'immeubles sans dérive, analysés chaque jour pendant 61 jours", "6",
               "fausses alertes par immeuble-jour"],
              ["Exemples officiels", "generer_demo (relevés horaires, 120 jours) : standard (5 immeubles) et grand (21) "
               "× météo fictive et réelle", "20", "fausses alertes, dérives manquées"],
              ["Immeubles sains", "6 types × météo fictive et réelle, une analyse", "30", "fausses alertes"],
              ["Robustesse", f"{len(VARIANTES)} variantes (lacunes, passerelle coupée, bruit, chasses d'eau, "
               "occupation, historique court, vague de froid) × dérive ≈ 1,5 à 2,5 × seuil et immeuble sain", "10",
               "détection, fausses alertes, chiffrage"],
              ["Qualité des données", "compteur muet, complétude, recul d'index, valeurs négatives (dérive active)",
               "10", "alerte Données, blocage des alertes énergie"],
              ["Pas de relevé", "même dérive (ampleurs de robustesse et nominale) et immeuble sain, relevés horaires "
               "puis journaliers", "10", "ce qui est perdu au pas journalier"],
              ["Chiffrage", "13 détecteurs, ampleur nominale, dérive de 14 jours, fin d'analyse au 15 de chaque mois "
               "d'octobre 2025 à avril 2026 (réelle) et fin fictive ; 30 jours simulés après l'analyse ; moteur actuel "
               "et V0.2.0", "6", "dérive constatée ÷ réel, rythme ÷ mois suivant, projection ÷ années réelles, base du "
               "score ÷ coût réel"]]
    out += c.tableau(lignes, [28 * M.mm, 76 * M.mm, 13 * M.mm, M.UTILE - 117 * M.mm],
                     f"Plan d'expériences ({nb(camp.get('scenarios'))} scénarios, moteur actuel)",
                     alignements=["g", "g", "d", "g"])
    out.append(c.h3("Définitions"))
    out += c.puces([
        "<b>Probabilité de détection</b> : part des graines où l'alerte de la cause visée est levée à la date "
        "d'analyse ; intervalle de confiance à 95 % de Wilson.",
        "<b>Seuil effectif</b> : ampleur à laquelle la probabilité atteint 50 % (resp. 90 %), par interpolation "
        "linéaire entre deux ampleurs testées. Il intègre la persistance, le bruit, le filtre d'enjeu minimal et "
        "les biais éventuels de l'attendu.",
        "<b>Délai</b> : âge de la dérive (jours entre son début et la date d'analyse) à la première alerte. "
        "<b>Perte</b> : premier âge, après la détection, où l'alerte n'est plus levée alors que la dérive continue.",
        "<b>Écart au réel du chiffrage</b> (montant affiché ÷ réalité − 1) : chauffage et PAC, excès mesuré depuis le "
        "début détecté ÷ excès réel cumulé depuis le début RÉEL de la dérive ; eau et électricité, montant annuel ÷ "
        "excès réel d'une année (dérive constante) ; V0.2.0, montant annuel (× 210 ou × 365 jours) ÷ excès que la "
        "même dérive aurait sur une année de Genève (température GVE 2016-2025). <b>Rythme</b> : montant mensuel ÷ "
        "excès réel des 30 jours suivants − 1.",
        "<b>Fausse alerte</b> : toute alerte sur un immeuble sans dérive injectée, ou de cause différente de la "
        "dérive injectée."])
    ages = sorted(set(AGE_BALAYAGE.values()))
    out.append(c.p(
        f"Ampleurs nominales : {', '.join(f'{NOMS[d]} {amp(d, NOMINALE[d])}' for d in ORDRE[:5])}, PAC "
        f"{amp('pac_totale', NOMINALE['pac_totale'])} de rendement en moins. Âge de la dérive au balayage : "
        f"{' ou '.join(str(a) for a in ages)} jours selon la persistance du détecteur."))
    return out


def _ligne_synthese(c, det):
    h = c.h
    s50f, s50r = seuil50(h, det, "fictive"), seuil50(h, det, "reelle")
    d = delai(h, det, "fictive") or {}
    kf, nf = fausses(h, det, "fictive")
    kr, nr = fausses(h, det, "reelle")
    e = ecart_principal(chiffrage(h, det, "reelle" if det in CLIMAT else "fictive"))
    kj, nj = pas_detection(h, det, 1440)
    kh, nh = pas_detection(h, det, 60)
    nominal = SEUILS_NOMINAUX[det]
    return [NOMS[det], "1,5 × talon" if nominal is None else amp(det, nominal),
            amp(det, s50f), "—" if courbe(h, det, "reelle") is None else amp(det, s50r),
            nb((d.get("delai_j") or {}).get("mediane")), f"{nb(kf)} / {nb(nf)}", f"{nb(kr)} / {nb(nr)}",
            pct((e or {}).get("mediane"), 1, True), f"{nb(kh)} → {nb(kj)} / {nb(nh)}"]


def tableau_synthese(c):
    lignes = [["Détecteur", "Seuil règle", "Seuil effectif 50 % fictive", "Seuil eff. 50 % réelle", "Délai médian (j)",
               "Fausses alertes fictive", "Fausses alertes réelle", "Écart chiffrage médian", "Détectées horaire → journalier"]]
    lignes += [_ligne_synthese(c, d) for d in ORDRE]
    return c.tableau(lignes, [32 * M.mm, 15 * M.mm, 18 * M.mm, 17 * M.mm, 14 * M.mm, 18 * M.mm, 18 * M.mm, 17 * M.mm,
                              M.UTILE - 149 * M.mm],
                     "Synthèse par détecteur, relevés horaires, 12 mois. Fausses alertes : alertes de la cause sur "
                     "analyses d'immeubles sains (30 graines + suivi quotidien de 61 jours) ; écart de chiffrage : "
                     "médiane du montant affiché ÷ réalité − 1 (expérience de chiffrage, météo réelle pour chauffage et "
                     "PAC) ; dernière colonne : dérives détectées au pas horaire puis journalier ; chaleur_vide : "
                     "ampleur = facteur de marche (hors-gel 0,12)", alignements=["g"] + ["d"] * 8, police=7.1)


def resultats(c):
    h = c.h
    out = c.h1(8, "Résultats")
    out.append(c.p(
        "Les résultats ci-dessous sont ceux du moteur actuel, sur relevés horaires et 12 mois d'historique. La synthèse "
        "par détecteur figure au tableau 1 (chapitre 1). Les détecteurs indépendants de la météo (eau, électricité) ne "
        "sont évalués qu'en météo fictive, sauf pour le chiffrage."))
    # 8.1 détection
    out += c.h2("8.1", "Probabilité de détection selon l'ampleur")
    lignes = [["Détecteur", "Météo", "Seuil 50 %", "Seuil 90 %", "Fausses sur sains (ampleur 0)", "Âge (j)"]]
    for det in ORDRE:
        for met in ("fictive", "reelle"):
            b = courbe(h, det, met)
            if not b:
                continue
            lignes.append([NOMS[det], met, amp(det, b["seuil50"]), amp(det, b["seuil90"]),
                           f"{nb(b['fausses_sur_sains'])} / {nb(b['courbe'][0]['n'])}", nb(AGE_BALAYAGE[det])])
    out += c.tableau(lignes, [44 * M.mm, 18 * M.mm, 28 * M.mm, 28 * M.mm, 32 * M.mm, M.UTILE - 150 * M.mm],
                     "Seuils effectifs au pas horaire (12 graines par ampleur ; chaleur_vide : la première ampleur, "
                     "0,12, est le hors-gel normal)", alignements=["g", "g", "d", "d", "d", "d"])
    out.extend(c.figure("detection_amplitude.png", "Probabilité de détection selon l'ampleur de la dérive, relevés "
                        "horaires, météo fictive (bleu) et réelle (orange) ; bande : intervalle de confiance à 95 %.",
                        largeur=M.UTILE))
    out.append(c.p(_lecture_detection(c)))
    # 8.2 délai
    out += c.h2("8.2", "Délai de détection et maintien de l'alerte")
    out.extend(c.figure("delai_detection.png", "Part des graines en alerte selon l'âge de la dérive, analyse "
                        "quotidienne avec suivi des alertes, relevés horaires."))
    lignes = [["Détecteur", "Météo", "Délai médian (min-max)", "Jamais détectée", "Perte de l'alerte"]]
    for det in ORDRE:
        for met in ("fictive", "reelle"):
            d = delai(h, det, met)
            if not d:
                continue
            q = d.get("delai_j") or {}
            pp = d.get("perte_j") or {}
            lignes.append([NOMS[det], met, f"{nb(q.get('mediane'))} ({nb(q.get('min'))}-{nb(q.get('max'))})" if q else "—",
                           f"{nb(d['jamais'])} / {nb(d['n'])}",
                           f"{nb(pp.get('mediane'))} j ({nb(d['n_perte'])}/{nb(d['n'])})" if pp else "aucune"])
    out += c.tableau(lignes, [46 * M.mm, 18 * M.mm, 40 * M.mm, 30 * M.mm, M.UTILE - 134 * M.mm],
                     f"Délai (jours depuis le début de la dérive) et perte de l'alerte sur {AGE_DELAI} jours "
                     "d'observation, dérive d'ampleur nominale", alignements=["g", "g", "d", "d", "d"])
    out.append(c.p(_lecture_delai(c)))
    # 8.3 fausses alertes
    out += c.h2("8.3", "Fausses alertes sur immeubles sains")
    gen = h["generateur"]
    lignes = [["Exemple officiel", "Météo", "Graines", "Dérives attendues / graine", "Fausses alertes",
               "Dérives manquées", "Précision", "Rappel"]]
    for k in ("standard|fictive", "standard|reelle", "grand|fictive", "grand|reelle"):
        g = gen.get(k)
        if g:
            lignes.append([g["taille"], g["meteo"], nb(g["graines"]), nb(g["attendues_par_graine"]),
                           nb(g["fausses_total"]), nb(g["manquees_total"]), pct(g["precision"]), pct(g["rappel"])])
    out += c.tableau(lignes, [26 * M.mm, 18 * M.mm, 16 * M.mm, 30 * M.mm, 22 * M.mm, 22 * M.mm, 18 * M.mm,
                              M.UTILE - 152 * M.mm],
                     "Exemples officiels régénérés au pas horaire (vigie/generer_demo.py), 20 graines par configuration",
                     alignements=["g", "g", "d", "d", "d", "d", "d", "d"])
    lignes = [["Immeuble sain simulé", "Météo", "Analyses ponctuelles", "Avec alerte", "Immeubles-jours suivis",
               "Jours avec alerte"]]
    from .pdf import TYPE_DELAI
    for typ, det in (("Chaufferie habitée", "eau_nuit"), ("Immeuble vide", "chaleur_vide"), ("PAC chaleur totale", "pac_totale"),
                     ("PAC chauffage seul", "pac_chauffage"), ("PAC eau chaude seule", "pac_ecs"),
                     ("PAC électricité seule", "pac_aucune"), ("CAD, immeuble habité", "cad_signature"),
                     ("CAD, immeuble vide", "cad_vide"), ("Gaz, immeuble habité", "gaz_signature"),
                     ("Gaz, immeuble vide", "gaz_vide")):
        for met in ("fictive", "reelle"):
            s = h["sain"].get(f"{det}|{met}") or {}
            ds = h["delai_sain"].get(f"{TYPE_DELAI[det]}|{met}") or {}
            lignes.append([typ, met, nb(s.get("n")), nb(s.get("avec_alerte")), nb(ds.get("immeubles_jours")),
                           nb(ds.get("jours_avec_alerte"))])
    out += c.tableau(lignes, [40 * M.mm, 18 * M.mm, 28 * M.mm, 22 * M.mm, 32 * M.mm, M.UTILE - 140 * M.mm],
                     "Immeubles sains simulés au pas horaire (toutes causes confondues)",
                     alignements=["g", "g", "d", "d", "d", "d"])
    out.append(c.p(_lecture_fausses(c)))
    # 8.4 robustesse
    out += c.h2("8.4", "Robustesse")
    out.extend(c.figure("robustesse.png", "Part des dérives détectées selon la variante, relevés horaires (dérives "
                        "d'ampleur 1,5 à 2,5 × seuil ; chaleur_vide : facteur de marche 0,5)."))
    out += _table_robustesse(c)
    out.append(c.p(_lecture_robustesse(c)))
    # 8.5 qualité
    out += c.h2("8.5", "Qualité des données")
    out.extend(c.figure("qualite_donnees.png", "Alerte « Données » et alerte énergie sur le même point selon "
                        "l'ampleur du défaut, relevés horaires ; trait gris : seuil de la règle.", largeur=M.UTILE))
    out += _table_qualite(c)
    # 8.6 pas journalier
    out += c.h2("8.6", "Ce que l'on perd avec un pas plus grossier (journalier)")
    out += _table_pas(c)
    out.extend(c.figure("pas_journalier.png", "Dérives détectées au pas horaire et au pas journalier (mêmes dérives, "
                        "mêmes tirages ; ampleurs de robustesse et nominale ; météo fictive et réelle)."))
    out.append(c.p(_lecture_pas(c)))
    # 8.7 chiffrage
    out += c.h2("8.7", "Justesse de la dérive constatée, de la projection, et comparabilité des scores")
    out += _table_chiffrage(c)
    out.extend(c.figure("chiffrage.png", "Montant ÷ réalité − 1, fins d'analyse d'octobre 2025 à avril 2026 (vraie "
                        "température GVE, 6 graines par mois) : V0.2.0 annualisé (gris), dérive constatée (bleu), "
                        "projection 12 mois ÷ réalisé des années 2016-2025 (orange)."))
    out.extend(c.figure("chiffrage_mois.png", "Écart médian au réel selon le mois de fin d'analyse, chauffage et PAC : "
                        "V0.2.0 annualisé, dérive constatée et projection (÷ année normale)."))
    out.append(c.p(_lecture_chiffrage(c)))
    out += _table_projection(c)
    out.append(c.p(_lecture_projection(c)))
    out += _table_score(c)
    out.append(c.p(_lecture_score(c)))
    # 8.8 biais
    out += c.h2("8.8", "Biais de l'attendu et choix de la période de référence")
    out += _table_biais(c)
    out.extend(c.figure("biais_attendu.png", "Biais de l'attendu sur immeubles sains (14 derniers jours, 12 mois "
                        "d'historique ; barre = moyenne, trait = minimum-maximum)."))
    out.append(c.p(_lecture_biais(c)))
    # 8.9 confiance
    out += c.h2("8.9", "Confiance")
    out.extend(c.figure("confiance.png", "Confiance moyenne des alertes levées selon l'ampleur rapportée au seuil."))
    confs = [x["confiance_moy"] for b in h["balayage"].values() for x in b["courbe"] if x["confiance_moy"]]
    out.append(c.p(
        f"La confiance moyenne des alertes levées va de {nb(min(confs), 2)} à {nb(max(confs), 2)} et croît avec "
        "l'ampleur et la persistance : elle ordonne les alertes mais ne mesure pas une probabilité d'être juste. Elle "
        "devra être recalibrée avec les retours du gestionnaire (Pertinente / Déjà connue / Fausse alerte)."))
    return out


# ---------------------------------------------------------------- tableaux et lectures


def _lecture_detection(c):
    h = c.h
    t = [f"{NOMS[d]} {amp(d, seuil50(h, d, 'fictive'))}" for d in ("eau_nuit", "eau_vide", "elec_nuit",
                                                                     "chaleur_signature", "pac_totale")]
    return ("<b>Lecture.</b> Au pas horaire, les seuils effectifs à 50 % restent proches des seuils des règles là où "
            "l'attendu est juste : " + ", ".join(t) + " (météo fictive). Le chauffage d'un immeuble vide dépend de la "
            "météo du moment : avec la vraie température de novembre, il faut un facteur de marche de "
            f"{amp('chaleur_vide', seuil50(h, 'chaleur_vide', 'reelle'))} pour dépasser 1,5 × le talon "
            f"({amp('chaleur_vide', seuil50(h, 'chaleur_vide', 'fictive'))} en météo fictive).")


def _lecture_delai(c):
    h = c.h
    dv = lambda d, m="fictive": ((delai(h, d, m) or {}).get("delai_j") or {}).get("mediane")  # noqa: E731
    pertes = sum((delai(h, d, m) or {}).get("n_perte", 0) for d in ORDRE for m in ("fictive", "reelle"))
    jamais = [f"{NOMS[d]} ({'réelle' if m == 'reelle' else m}) {nb(x['jamais'])}/{nb(x['n'])}"
              for d in ORDRE for m in ("fictive", "reelle") if (x := delai(h, d, m)) and x["jamais"]]
    return ("<b>Lecture.</b> Le délai est d'abord fixé par la persistance : "
            f"{nb(dv('eau_nuit'))} nuits pour la fuite, {nb(dv('elec_nuit'))} pour l'électricité de nuit, "
            f"{nb(dv('chaleur_signature'))} jours pour la signature et {nb(dv('pac_totale'))} pour une PAC avec "
            f"chaleur comptée ; l'eau d'un immeuble vide est repérée en {nb(dv('eau_vide'))} jours. "
            + (f"Dérives jamais détectées en {AGE_DELAI} jours : " + " ; ".join(jamais) + ". " if jamais
               else f"Toutes les dérives nominales sont détectées dans les {AGE_DELAI} jours. ")
            + (f"Pertes d'alerte en cours de dérive : {nb(pertes)} au total (référence gelée, R7)." if pertes else
               "Aucune alerte n'est perdue tant que la dérive dure (référence gelée, R7)."))


def _lecture_fausses(c):
    h = c.h
    from .pdf import fausses_toutes
    kf, nf = fausses_toutes(h, "fictive")
    kr, nr = fausses_toutes(h, "reelle")
    gen = h["generateur"]
    return (f"<b>Lecture.</b> {nb(kf + kr)} fausse(s) alerte(s) sur {nb(nf + nr)} analyses d'immeubles sains simulés "
            f"et {nb(sum(g['fausses_total'] for g in gen.values()))} sur les {nb(sum(g['graines'] for g in gen.values()))} "
            "exemples officiels régénérés au pas horaire. Ce résultat vaut pour les lois simulées : un parc réel "
            "comporte des usages que la simulation ne reproduit pas (§ 10).")


def _table_robustesse(c):
    h = c.h
    from .campagne import SAINS as sains
    lignes = [["Variante", f"Dérives détectées ({len(ORDRE)} détecteurs × 10 graines)",
               "Alertes énergie sur immeubles sains (alertes / immeubles)"]]
    for v in VARIANTES:
        k = sum((robuste(h, v, d) or {}).get("detectees", 0) for d in ORDRE)
        n = sum((robuste(h, v, d) or {}).get("n", 0) for d in ORDRE)
        f = sum(sum(c2 for cause, c2 in ((robuste(h, v, d, True) or {}).get("par_cause") or {}).items()
                    if not cause.startswith("donnees")) for d in sains)
        n_s = sum((robuste(h, v, d, True) or {}).get("n", 0) for d in sains)
        lignes.append([v, f"{nb(k)} / {nb(n)}", f"{nb(f)} / {nb(n_s)}"])
    return c.tableau(lignes, [70 * M.mm, 54 * M.mm, M.UTILE - 124 * M.mm],
                     "Robustesse au pas horaire (alertes énergie ; les alertes « Données » attendues sur les lacunes de "
                     "10 % ne sont pas comptées comme fausses)", alignements=["g", "d", "d"])


def _causes(r):
    pc = r.get("par_cause") or {}
    if not pc:
        return "aucune alerte"
    return ", ".join(f"{k} {nb(v)}/{nb(r.get('n'))}" for k, v in sorted(pc.items()))


def _lecture_robustesse(c):
    h = c.h
    simples = ["lacunes 2 %", "lacunes 5 %", "passerelle coupée 20 h-4 h (4 nuits)", "météo lacunaire 10 %",
               "bruit × 2", "bruit × 3", "chasses d'eau de nuit × 3", "vague de froid −8 °C (10 j)"]
    manques, fa = [], []
    for v in simples:
        for d in ORDRE:
            r = robuste(h, v, d) or {}
            if r and r["detectees"] < r["n"]:
                manques.append(f"{NOMS[d]} avec « {v} » : {nb(r['detectees'])}/{nb(r['n'])}")
        for d in __import__("evaluation.campagne", fromlist=["SAINS"]).SAINS:
            r = robuste(h, v, d, True) or {}
            k = sum(n for cause, n in (r.get("par_cause") or {}).items() if not cause.startswith("donnees"))
            if k:
                fa.append(f"« {v} » ({NOMS[d]}) {nb(k)}/{nb(r['n'])}")
    occ = robuste(h, "occupation 50 % → 90 % (J-10)", "eau_nuit", True) or {}
    occ_pac = robuste(h, "occupation 50 % → 90 % (J-10)", "pac_aucune", True) or {}
    baisse = ", ".join(f"{NOMS[d]} {nb((robuste(h, 'occupation 100 % → 60 % (J-10)', d) or {}).get('detectees'))}/10"
                       for d in ("chaleur_signature", "elec_nuit", "pac_ecs", "pac_aucune"))
    courts = ", ".join(f"{v} : signature {nb((robuste(h, v, 'chaleur_signature') or {}).get('detectees'))}/10, PAC "
                       f"électricité seule {nb((robuste(h, v, 'pac_aucune') or {}).get('detectees'))}/10"
                       for v in ("historique 45 j", "historique 90 j", "historique 180 j"))
    l10 = robuste(h, "lacunes 10 %", "eau_nuit") or {}
    return ("<b>Lecture.</b> Au pas horaire, les lacunes jusqu'à 5 %, la passerelle coupée la nuit, la météo "
            "lacunaire, le bruit doublé ou triplé, des chasses d'eau trois fois plus fréquentes et une vague de froid "
            + ("ne provoquent aucune fausse alerte" if not fa else "provoquent ces fausses alertes : " + " ; ".join(fa))
            + (" et ne font manquer aucune détection" if not manques else " ; détections manquées : " + " ; ".join(manques))
            + ". À 10 % de relevés perdus, la complétude passe sous 90 % : l'alerte « Données » prend le pas, comme "
            f"prévu (fuite signalée {nb(l10.get('detectees'))} fois sur {nb(l10.get('n'))}). Deux situations restent "
            "hors de portée d'un attendu appris sur l'historique. <b>Un changement d'occupation non déclaré</b> : un "
            f"passage de 50 à 90 % d'occupation produit sur un immeuble sain {_causes(occ)} (chaufferie) et "
            f"{_causes(occ_pac)} (PAC électricité seule) ; une baisse de 100 à 60 % masque des dérives ({baisse}). "
            f"<b>Un historique court</b> ({courts}) : sans la saison précédente, la référence est apprise sur la seule "
            "période antérieure à la fenêtre, avec ses limites (moins de 30 jours pour la signature, pas assez "
            "d'heures froides pour les PAC sans compteur de chauffage).")


def _table_qualite(c):
    h = c.h
    noms = {"silence": ("Compteur muet (eau)", "h sans donnée"), "completude": ("Complétude (électricité)", "relevés perdus"),
            "recul": ("Index qui recule (eau)", "reculs"), "negatifs": ("Valeurs négatives (électricité)", "valeurs")}
    lignes = [["Défaut", "Ampleur", "Alerte Données", "Alerte énergie du point", "Énergie malgré Données"]]
    for v in sorted(h["qualite"].values(), key=lambda x: (list(noms).index(x["defaut"]), x["niveau"])):
        niv = pct(v["niveau"]) if v["defaut"] == "completude" else nb(v["niveau"])
        lignes.append([noms[v["defaut"]][0], f"{niv} {noms[v['defaut']][1] if v['defaut'] != 'completude' else ''}",
                       f"{nb(v['alerte_donnees'])} / {nb(v['n'])}", f"{nb(v['alerte_energie'])} / {nb(v['n'])}",
                       nb(v["energie_malgre_donnees"])])
    return c.tableau(lignes, [50 * M.mm, 30 * M.mm, 28 * M.mm, 36 * M.mm, M.UTILE - 144 * M.mm],
                     "Qualité d'abord : un point en défaut ne produit jamais d'alerte énergie (dérive nominale active "
                     "sur le point ; 10 graines ; relevés horaires)", alignements=["g", "d", "d", "d", "d"], police=7.4)


def _table_pas(c):
    h = c.h
    lignes = [["Détecteur", "Ampleur robustesse : horaire → journalier", "Ampleur nominale : horaire → journalier",
               "Alertes sur sains : horaire → journalier", "Écart chiffrage journalier (médiane)"]]
    for det in ORDRE:
        kr_h, nr_h = pas_detection(h, det, 60, [ROBUSTE[det]])
        kr_j, _ = pas_detection(h, det, 1440, [ROBUSTE[det]])
        kn_h, nn_h = pas_detection(h, det, 60, [NOMINALE[det]])
        kn_j, _ = pas_detection(h, det, 1440, [NOMINALE[det]])
        fh, nfh = pas_fausses(h, det, 60)
        fj, _ = pas_fausses(h, det, 1440)
        errs = [r["erreur_chiffrage"] for k, r in (h.get("pas") or {}).items()
                if r["det"] == det and r["pas"] == 1440 and not r["sain"] and r["erreur_chiffrage"]]
        med = errs[0]["mediane"] if len(errs) == 1 else (sorted(e["mediane"] for e in errs)[len(errs) // 2] if errs else None)
        lignes.append([NOMS[det], f"{nb(kr_h)} → {nb(kr_j)} / {nb(nr_h)}", f"{nb(kn_h)} → {nb(kn_j)} / {nb(nn_h)}",
                       f"{nb(fh)} → {nb(fj)} / {nb(nfh)}", pct(med, 1, True)])
    return c.tableau(lignes, [38 * M.mm, 34 * M.mm, 34 * M.mm, 34 * M.mm, M.UTILE - 140 * M.mm],
                     "Même dérive relevée à l'heure puis une fois par jour (10 graines par ampleur et par météo)",
                     alignements=["g", "d", "d", "d", "d"], police=7.4)


def _lecture_pas(c):
    h = c.h
    perdus = [NOMS[d] for d in ORDRE if pas_detection(h, d, 1440)[0] == 0 and pas_detection(h, d, 60)[0] > 0]
    gardes = [NOMS[d] for d in ORDRE if pas_detection(h, d, 1440)[0] > 0]
    fj = sum(pas_fausses(h, d, 1440)[0] for d in ORDRE)
    nfj = sum(pas_fausses(h, d, 1440)[1] for d in ORDRE)
    return ("<b>Lecture.</b> Au pas journalier, ces dérives ne sont plus détectées du tout : " + ", ".join(perdus)
            + ". Ce n'est pas un réglage : le débit de nuit, la puissance de nuit et le rendement heure par heure "
            "n'existent pas dans un total journalier, qui ne dit pas à quelle heure l'eau a coulé ni à quelle "
            "température la chaleur a été produite. Restent surveillées : " + ", ".join(gardes) + ". Aucune donnée "
            f"journalière n'est attribuée à une heure : {nb(fj)} alerte(s) énergie sur {nb(nfj)} analyses d'immeubles "
            "sains relevés une fois par jour. L'interface signale tout compteur plus grossier que l'heure.")


def _table_chiffrage(c):
    lignes = [["Détecteur", "Avant (V0.2.0) : CHF/an ÷ réel − 1", "Dérive constatée ÷ réel cumulé − 1",
               "Rythme mensuel ÷ mois suivant − 1"]]
    for det in ORDRE:
        av, ap = chiffrage(c.hav, det), chiffrage(c.h, det)
        lignes.append([NOMS[det], plage(av.get("ecart_annuel")), plage(ap.get("ecart_mesure")), plage(ap.get("ecart_mois"))])
    out = c.tableau(lignes, [36 * M.mm, 44 * M.mm, 48 * M.mm, M.UTILE - 128 * M.mm],
                    "Écart au réel, médiane (minimum à maximum), fins d'analyse d'octobre 2025 à avril 2026, vraie "
                    "température GVE (6 graines × 7 mois) ; dérive de 14 jours, ampleur nominale ; « — » : la copie "
                    "V0.2.0 n'a pas de règle CAD ni gaz", alignements=["g", "d", "d", "d"], police=7.3)
    lignes = [["Détecteur", "Avant (V0.2.0)", "Dérive constatée", "Rythme mensuel"]]
    for det in ORDRE:
        av, ap = chiffrage(c.hav, det, "fictive"), chiffrage(c.h, det, "fictive")
        lignes.append([NOMS[det], plage(av.get("ecart_annuel")), plage(ap.get("ecart_mesure")), plage(ap.get("ecart_mois"))])
    out += c.tableau(lignes, [36 * M.mm, 44 * M.mm, 48 * M.mm, M.UTILE - 128 * M.mm],
                     "Même mesure en météo fictive (fin fictive, 6 graines)", alignements=["g", "d", "d", "d"],
                     police=7.3)
    return out


def _table_projection(c):
    lignes = [["Détecteur", "Hypothèse", "Projection ÷ année normale − 1", "Projection ÷ réalisé de chaque année "
               "2016-2025 − 1"]]
    for det in ORDRE:
        r = chiffrage(c.h, det)
        hyp = "climat normal" if det in CLIMAT else "dérive constante"
        q = r.get("ecart_proj_annees")
        lignes.append([NOMS[det], hyp, plage(r.get("ecart_proj")),
                       "—" if not q else f"{pct(q['min'], 0, True)} à {pct(q['max'], 0, True)}"])
    return c.tableau(lignes, [36 * M.mm, 26 * M.mm, 52 * M.mm, M.UTILE - 114 * M.mm],
                     "Justesse de la projection sur 12 mois (vraie température GVE, 6 graines × 7 mois) : réalisé = "
                     "excès que la même dérive aurait produit chaque année réelle de Genève, lois du simulateur",
                     alignements=["g", "g", "d", "d"], police=7.3)


def _table_score(c):
    lignes = [["Détecteur", "Avant : CHF/an ÷ coût réel des 30 jours suivants", "Après : CHF/mois constaté ÷ coût réel "
               "des 30 jours suivants"]]
    for det in ORDRE:
        av, ap = chiffrage(c.hav, det).get("ecart_base_score"), chiffrage(c.h, det).get("ecart_base_score")
        f = lambda q: "—" if not q else f"{nb(q['mediane'], 2)} ({nb(q['min'], 2)} à {nb(q['max'], 2)})"  # noqa: E731
        lignes.append([NOMS[det], f(av), f(ap)])
    return c.tableau(lignes, [44 * M.mm, 63 * M.mm, M.UTILE - 107 * M.mm],
                     "Base du score rapportée au coût réel des 30 jours qui suivent l'analyse, médiane (min à max), "
                     "vraie température GVE : une base comparable entre fluides donne le même rapport pour tous",
                     alignements=["g", "d", "d"], police=7.4)


def _etendue(xs, nd):
    """« a à b » en pourcentage signé, ou une seule valeur si les deux coïncident à l'arrondi."""
    if not xs:
        return "—"
    a, b = pct(min(xs), nd, True), pct(max(xs), nd, True)
    return a if a == b else f"{a} à {b}"


def _med(r, cle):
    return (r.get(cle) or {}).get("mediane")


def _lecture_chiffrage(c):
    av = {d: _med(chiffrage(c.hav, d), "ecart_annuel") for d in ORDRE}
    ap = {d: _med(chiffrage(c.h, d), "ecart_mesure") for d in ORDRE}
    av_c = [av[d] for d in CLIMAT if av[d] is not None]
    sig = [ap[d] for d in CLIMAT if not d.endswith("_vide") and ap[d] is not None]
    vide = [ap[d] for d in CLIMAT if d.endswith("_vide") and ap[d] is not None]
    const = [ap[d] for d in ORDRE if d not in CLIMAT and ap[d] is not None]
    rm = [x for d in CLIMAT for x in ((chiffrage(c.h, d).get("ecart_mois") or {}).get("min"),
                                      (chiffrage(c.h, d).get("ecart_mois") or {}).get("max")) if x is not None]
    f = lambda xs, nd=1: _etendue(xs, nd)  # noqa: E731
    return ("<b>Lecture.</b> L'ancienne annualisation s'écartait du réel de " + f(av_c, 0) + " en médiane selon le "
            "détecteur, et beaucoup plus selon le mois. La dérive constatée ne projette rien : pour les signatures "
            "(chaleur, CAD, gaz) et les PAC, son écart médian au réel cumulé va de " + f(sig) + ", sans dépendance "
            "marquée au mois. Pour l'immeuble vide chauffé (chaleur, CAD, gaz), elle reste sous-estimée (" + f(vide, 0) +
            ") : l'excès est compté au-dessus du talon déclaré, plus élevé que la consommation hors-gel réelle. Pour "
            "l'eau et l'électricité, constaté = excès constaté la nuit × heures mesurées : écart médian de " + f(const) +
            " (pour l'immeuble vide, les chasses d'eau de nuit simulées sont comptées dans l'excès, l'attendu étant "
            "« ≈ 0 l/jour »). Le rythme mensuel suppose un mois au climat des derniers jours : pour le chauffage et les "
            "PAC, il s'écarte du mois suivant réel de " + f(rm, 0) + " selon le mois de détection.")


def _lecture_projection(c):
    pc = [_med(chiffrage(c.h, d), "ecart_proj") for d in CLIMAT if not d.endswith("_vide")]
    pc = [x for x in pc if x is not None]
    ann = [chiffrage(c.h, d).get("ecart_proj_annees") for d in CLIMAT if not d.endswith("_vide")]
    ann = [x for x in ann if x]
    pv = [_med(chiffrage(c.h, d), "ecart_proj") for d in CLIMAT if d.endswith("_vide")]
    pv = [x for x in pv if x is not None]
    pk = [_med(chiffrage(c.h, d), "ecart_proj") for d in ORDRE if d not in CLIMAT]
    pk = [x for x in pk if x is not None]
    f = lambda xs, nd=0: _etendue(xs, nd)  # noqa: E731
    return ("<b>Lecture.</b> Pour les signatures et les PAC, la projection au climat normal s'écarte de l'excès d'une "
            "année normale de " + f(pc) + " en médiane ; rapportée au réalisé de chaque année réelle 2016-2025, elle "
            "s'en écarte de " + (f"{pct(min(x['min'] for x in ann), 0, True)} à {pct(max(x['max'] for x in ann), 0, True)}"
                                 if ann else "—") +
            " : c'est l'ordre de grandeur de l'incertitude d'une projection, qui vient de l'estimation de l'ampleur sur "
            "quelques jours et du climat de l'année, d'où son statut d'hypothèse. Pour l'immeuble vide chauffé, la "
            "projection par degré-jour s'écarte de " + f(pv) + " (talon déclaré, comme pour le constaté). Pour l'eau "
            "et l'électricité, la projection d'une dérive constante s'écarte de " + f(pk, 1) + ".")


def _lecture_score(c):
    base_av = [_med(chiffrage(c.hav, d), "ecart_base_score") for d in ORDRE]
    base_ap = [_med(chiffrage(c.h, d), "ecart_base_score") for d in ORDRE]
    base_av, base_ap = [x for x in base_av if x is not None], [x for x in base_ap if x is not None]
    return ("<b>Comparabilité du score.</b> La base du score avant révision (CHF/an) valait, selon le détecteur, de "
            f"{nb(min(base_av), 1) if base_av else '—'} à {nb(max(base_av), 1) if base_av else '—'} fois le coût réel "
            "du mois suivant : les fluides n'étaient pas comparés sur la même base. Le rythme mensuel constaté vaut de "
            f"{nb(min(base_ap), 2) if base_ap else '—'} à {nb(max(base_ap), 2) if base_ap else '—'} fois ce coût, pour "
            "tous les détecteurs dont le CAD et le gaz : la base mesurée suffit à rendre les scores comparables, sans "
            "recourir à la projection.")


def _table_biais(c):
    lignes = [["Modèle", "Météo", "V0.2.0", "Actuel, référence antérieure (repli)", "Actuel, même saison + 60 j (défaut)"]]
    noms = {"chaleur_signature": "Signature chaleur", "pac_totale": "PAC chaleur totale",
            "pac_chauffage": "PAC chauffage seul", "pac_ecs": "PAC eau chaude seule", "pac_aucune": "PAC électricité seule"}
    for m, lib in noms.items():
        for met in ("fictive", "reelle"):
            cel = []
            for v in ("avant", "anterieure", "saison"):
                r = biais(c.b, m, met, v)
                cel.append(f"{pct(r.get('moyenne'), 2, True)} ({pct(r.get('min'), 1, True)} à {pct(r.get('max'), 1, True)})"
                           if "moyenne" in r else "—")
            lignes.append([lib, met, *cel])
    return c.tableau(lignes, [34 * M.mm, 16 * M.mm, 38 * M.mm, 41 * M.mm, M.UTILE - 129 * M.mm],
                     "Biais de l'attendu sur immeubles sains (mesuré ÷ attendu − 1 sur les 14 derniers jours) : "
                     "moyenne (min à max), 10 graines × 7 fins d'analyse (réelle) ou 10 graines (fictive)",
                     alignements=["g", "g", "d", "d", "d"], police=7.2)


def _lecture_biais(c):
    abs_moy = lambda v: [biais(c.b, m, met, v).get("abs_moyen") for m in ("chaleur_signature", "pac_totale",  # noqa: E731
                         "pac_chauffage", "pac_ecs", "pac_aucune") for met in ("fictive", "reelle")]
    a, s = [x for x in abs_moy("anterieure") if x is not None], [x for x in abs_moy("saison") if x is not None]
    av = [x for x in abs_moy("avant") if x is not None]
    return ("<b>Lecture.</b> Avec 12 mois d'historique, l'attendu du moteur actuel est sans biais notable avec les deux "
            f"périodes de référence : écart absolu moyen de {pct(min(a), 2)} à {pct(max(a), 2)} avec toute la période "
            f"antérieure, de {pct(min(s), 2)} à {pct(max(s), 2)} avec la même saison de l'an passé et les 60 jours "
            f"récents (V0.2.0 : {pct(min(av), 2)} à {pct(max(av), 2)}). La même saison est retenue par défaut : elle est "
            "au moins aussi juste sur ces lois simulées, et sur un parc réel elle compare des journées de même "
            "durée, de même usage et de même régime de chauffe, ce que les lois linéaires du simulateur ne peuvent pas "
            "départager.")
