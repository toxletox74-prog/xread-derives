"""Chapitres 9, 10 et annexes du document PDF : révisions du moteur, limites et recommandations, paramètres,
reproduction. Point d'entrée de la construction du document : construire()."""
from reportlab.platypus import PageBreak, Spacer

from vigie import moteur

from . import pdf_mise_en_page as M
from .pdf import (NOMS, ORDRE, amp, biais, chiffrage, delai, ecart_principal, nb, pas_detection, pas_fausses, pct,
                  robuste, seuil50)


def _q(res, defaut, niveau):
    return (res or {}).get("qualite", {}).get(f"{defaut}|{niveau}") or {}


def _b15(c, modele, met, version):
    return ((c.b_15 or {}).get("resume", {}).get(f"{modele}|{met}|{version}") or {}).get("moyenne")


def _fiches(c, revs):
    out = []
    for code, titre, constat, correction, mesure in revs:
        out.append(c.h3(f"{code} · {titre}"))
        out.append(M.tableau([["<b>Constat</b>", constat], ["<b>Correction</b>", correction],
                              ["<b>Mesure</b>", mesure]], [34 * M.mm, M.UTILE - 34 * M.mm], c.s, entete=0))
        out.append(Spacer(1, 4))
    return out


def revisions(c):
    out = c.h1(9, "Révisions apportées au moteur")
    out.append(c.p(
        "Chaque révision répond à un défaut mesuré ou à une hypothèse de données corrigée ; aucune règle du projet "
        "n'est assouplie. R1 à R7 ont été mesurées par la campagne précédente (pas de 15 minutes, 120 jours, copie figée "
        "V0.2.0 contre moteur révisé, mêmes scénarios et mêmes graines) ; elles restent en place et sont revérifiées au "
        "pas horaire par la campagne actuelle (chapitre 8). R8 à R12 répondent aux nouvelles hypothèses : données au "
        "mieux horaires, un an d'historique, aucune annualisation du chauffage et des PAC. R13 à R15 séparent la "
        "projection de la dérive constatée, ajoutent le CAD et le gaz et portent l'exemple officiel à 12 mois."))
    out += c.h2("9.1", "Révisions R1 à R7 (campagne précédente, pas de 15 minutes)")
    out += _revisions_15min(c)
    out += c.h2("9.2", "Révisions R8 à R12 (pas horaire, un an d'historique, chiffrage mesuré)")
    out += _revisions_horaires(c)
    out += c.h2("9.3", "Révisions R13 à R15 (projection séparée, CAD et gaz, exemple sur 12 mois)")
    out += _revisions_fluides(c)
    v = c.v or {}
    lignes = [["Contrôle de livraison", "Résultat"]]
    for e in v.get("evaluations", []):
        lignes.append([e["commande"], f"précision {nb(e['precision'])} %, rappel {nb(e['rappel'])} % · {e['resume']}"])
    t = v.get("tests") or {}
    lignes.append(["python -m unittest discover -s tests", f"{nb(t.get('tests'))} tests, {'tous verts' if t.get('ok') else 'ÉCHEC'}"])
    out.append(Spacer(1, 6))
    out += c.tableau(lignes, [62 * M.mm, M.UTILE - 62 * M.mm], "Validation du moteur révisé (CLAUDE.md § 10) au pas "
                     "horaire ; les évaluations « --meteo-reelle » utilisent la série MétéoSuisse du jour", police=7.4)
    return out


def _revisions_15min(c):
    ap, av = c.ap, c.av
    pas = "passerelle coupée 20 h-4 h (4 nuits)"
    f_av = robuste(av, pas, "eau_nuit", True) or {}
    f_ap = robuste(ap, pas, "eau_nuit", True) or {}
    l5 = lambda r, d: robuste(r, "lacunes 5 %", d) or {}  # noqa: E731
    l2 = lambda r, d: robuste(r, "lacunes 2 %", d) or {}  # noqa: E731
    dv = lambda r, d, m="fictive": ((delai(r, d, m) or {}).get("perte_j") or {}).get("mediane")  # noqa: E731
    np_ = lambda r, d, m="fictive": (delai(r, d, m) or {}).get("n_perte")  # noqa: E731
    return _fiches(c, [
        ("R1", "charger_series — index à travers un trou",
         "L'écart d'index après un trou de relevés cumule toute la consommation du trou et était attribué à la "
         "première heure suivante. Une passerelle coupée de 20 h à 4 h simulait ainsi une fuite critique.",
         "Différence d'index non attribuée quand l'écart entre relevés dépasse 1,5 pas (règle 4 : aucune décision "
         "sur une valeur reconstituée). Au pas horaire : écart de plus de 90 minutes.",
         f"Immeuble sain, passerelle coupée 4 nuits : fausses alertes de fuite {nb((f_av.get('par_cause') or {}).get('eau_nuit', 0))}"
         f"/{nb(f_av.get('n'))} → {nb((f_ap.get('par_cause') or {}).get('eau_nuit', 0))}/{nb(f_ap.get('n'))}."),
        ("R2", "charger_series — heure incomplète",
         "Une heure à laquelle manquait un relevé de 15 min était sommée sur 3 quarts et jugée comme une heure entière "
         "(sous-estimée de 25 %).",
         "Une heure n'a de valeur que si tous ses pas sont présents ; au pas horaire, un relevé par heure.",
         f"Électricité de nuit, 5 % de relevés perdus : détection {nb(l5(av, 'elec_nuit').get('detectees'))}/"
         f"{nb(l5(av, 'elec_nuit').get('n'))} → {nb(l5(ap, 'elec_nuit').get('detectees'))}/{nb(l5(ap, 'elec_nuit').get('n'))} ; "
         f"complétude 9 % : {nb(_q(av, 'completude', 0.09).get('alerte_energie'))}/10 → "
         f"{nb(_q(ap, 'completude', 0.09).get('alerte_energie'))}/10."),
        ("R3", "det_eau_nuit — nuit lacunaire",
         "Le minimum d'une nuit réduite à une heure n'est pas un minimum de nuit.",
         "Une nuit n'est jugée que si au moins 3 heures sur 4 sont mesurées ; les autres sont sautées.",
         "Inclus dans la mesure de R1 (contrôle séparé de la campagne précédente : aucune fausse fuite avec R2 et R3)."),
        ("R4", "det_eau_vide — jour en cours",
         "Le jour en cours (6 h de données à 6 h UTC) était jugé comme un jour entier : il restait sous 50 l et "
         "cassait la persistance.",
         "Jour en cours exclu, comme pour la chaleur.",
         f"Seuil effectif 50 % : {amp('eau_vide', seuil50(av, 'eau_vide', 'fictive'))} → "
         f"{amp('eau_vide', seuil50(ap, 'eau_vide', 'fictive'))} (règle : 50 l/jour)."),
        ("R5", "jours lacunaires — eau_vide, chaleur_vide, signature",
         "Un jour auquel manquaient des heures était comparé à un seuil ou à un attendu de 24 h : la persistance "
         "cassait dès 2 % de relevés perdus.",
         f"Jour jugé si au moins {moteur.JOUR_HEURES_MIN} h sur 24 sont mesurées ; seuil au prorata des heures "
         "mesurées ; signature ajustée et comparée sur les heures mesurées (q = a·n/24 + b·Σdh/24).",
         f"Signature, 2 % de relevés perdus : {nb(l2(av, 'chaleur_signature').get('detectees'))}/10 → "
         f"{nb(l2(ap, 'chaleur_signature').get('detectees'))}/10 ; 5 % : "
         f"{nb(l5(av, 'chaleur_signature').get('detectees'))}/10 → {nb(l5(ap, 'chaleur_signature').get('detectees'))}/10."),
        ("R6", "signature_attendue et pac_attendu — abaissement nocturne",
         "La chaleur par degré est plus faible la nuit. Une référence de fin d'été, froide surtout la nuit, "
         "sous-estimait le chauffage de novembre : immeubles sains au-dessus de l'attendu.",
         "Terme pour la part de nuit (22 h-5 h UTC) dans la signature (DJ_nuit) et dans la part chauffage estimée des "
         f"PAC, seulement si la référence contient au moins {moteur.HEURES_JOUR_FROIDES_MIN} heures de jour sous 14 °C ; "
         "coefficient de nuit de la signature borné (−b ≤ c ≤ 0).",
         f"Biais sur immeuble sain, 120 jours : PAC eau chaude seule {pct(_b15(c, 'pac_ecs', 'fictive', 'avant'), 1, True)} → "
         f"{pct(_b15(c, 'pac_ecs', 'fictive', 'apres'), 1, True)} (fictive) ; signature "
         f"{pct(_b15(c, 'chaleur_signature', 'reelle', 'avant'), 1, True)} → "
         f"{pct(_b15(c, 'chaleur_signature', 'reelle', 'apres'), 1, True)} (réelle). Au pas horaire sur 12 mois : § 8.8."),
        ("R7", "analyser et references_gelees — référence gelée",
         "Une dérive qui dure entre dans la période de référence : elle devient « normale », l'alerte disparaît et "
         "passe à « résolue » sans réparation.",
         "Tant qu'une alerte est ouverte (et non jugée « fausse alerte »), la référence de son détecteur s'arrête au "
         "début de la dérive ; repli sur la référence habituelle si elle est trop courte.",
         f"Perte de l'alerte, électricité de nuit : {nb(np_(av, 'elec_nuit'))}/10 graines vers {nb(dv(av, 'elec_nuit'))} j → "
         f"{nb(np_(ap, 'elec_nuit'))}/10 ; signature {nb(np_(av, 'chaleur_signature'))}/10 → "
         f"{nb(np_(ap, 'chaleur_signature'))}/10 (observation sur 60 jours).")])


def _revisions_horaires(c):
    h = c.h
    gen = h["generateur"]
    fa_gen = sum(v["fausses_total"] for v in gen.values())
    fn_gen = sum(v["manquees_total"] for v in gen.values())
    n_gen = sum(v["graines"] for v in gen.values())
    l5 = sum((robuste(h, "lacunes 5 %", d) or {}).get("detectees", 0) for d in ORDRE)
    n5 = sum((robuste(h, "lacunes 5 %", d) or {}).get("n", 0) for d in ORDRE)
    sig_av, sig_ap = chiffrage(c.hav, "chaleur_signature"), chiffrage(h, "chaleur_signature")
    pac_av, pac_ap = chiffrage(c.hav, "pac_aucune"), chiffrage(h, "pac_aucune")
    base_av = [(chiffrage(c.hav, d).get("ecart_base_score") or {}).get("mediane") for d in ORDRE]
    base_ap = [(chiffrage(h, d).get("ecart_base_score") or {}).get("mediane") for d in ORDRE]
    base_av, base_ap = [x for x in base_av if x is not None], [x for x in base_ap if x is not None]
    garde = [NOMS[d] for d in ("eau_vide", "chaleur_vide", "chaleur_signature")]
    kj = sum(pas_detection(h, d, 1440)[0] for d in ("eau_vide", "chaleur_vide", "chaleur_signature"))
    nj = sum(pas_detection(h, d, 1440)[1] for d in ("eau_vide", "chaleur_vide", "chaleur_signature"))
    kh = sum(pas_detection(h, d, 60)[0] for d in ("eau_vide", "chaleur_vide", "chaleur_signature"))
    fj = sum(pas_fausses(h, d, 1440)[0] for d in ORDRE)
    nfj = sum(pas_fausses(h, d, 1440)[1] for d in ORDRE)
    b_sig_s = biais(c.b, "pac_totale", "reelle", "saison")
    b_sig_a = biais(c.b, "pac_totale", "reelle", "anterieure")
    return _fiches(c, [
        ("R8", "pas horaire partout (parc, référentiel, générateur, moteur)",
         "Aucune donnée n'arrive au quart d'heure : les compteurs d'électricité, de PAC et d'eau étaient déclarés à "
         "15 min, le générateur et le simulateur produisaient des quarts d'heure, et le « pas trop grossier » visait "
         "l'électricité au-delà de 15 min.",
         "Pas par défaut et pas maximal de 60 min pour tous les fluides (vigie/parc.py), pas_min = 60 dans les "
         "référentiels, séries relevées à l'heure (index lu à l'heure pleine, intervalles cumulés sur l'heure) avec les "
         "mêmes dérives ; avertissement « pas trop grossier » qui dit ce qui est perdu, fluide par fluide.",
         f"Exemples officiels au pas horaire : {nb(fa_gen)} fausse alerte et {nb(fn_gen)} dérive manquée sur "
         f"{nb(n_gen)} régénérations ; lacunes de 5 % : {nb(l5)}/{nb(n5)} dérives détectées ; 4 évaluations à 100 %."),
        ("R9", "chiffrage mesuré du chauffage et des PAC",
         "« Excès du jour × 210 jours » (et toute projection par degrés-jours) extrapole une année à partir de "
         "quelques jours : l'erreur dépend du mois de détection.",
         "Signature, immeuble vide chauffé et PAC : excès cumulé heure par heure (mesuré − attendu, heures mesurées "
         "seulement) depuis le début de la dérive, et rythme mensuel au climat des 30 derniers jours au plus ; plus "
         "de champs « par an ». Eau et électricité : par an (× 365), juste pour ces dérives constantes.",
         f"Écart médian au réel (vraie météo, oct. à avr.) : signature {pct((sig_av.get('ecart_annuel') or {}).get('mediane'), 0, True)} "
         f"→ {pct((ecart_principal(sig_ap) or {}).get('mediane'), 1, True)} ; PAC électricité seule "
         f"{pct((pac_av.get('ecart_annuel') or {}).get('mediane'), 0, True)} → "
         f"{pct((ecart_principal(pac_ap) or {}).get('mediane'), 1, True)} (§ 8.7)."),
        ("R10", "référence d'un an : même saison de l'an passé",
         "Avec un an d'historique, l'attendu peut être appris sur des journées de même saison au lieu de « tout ce "
         "qui précède la fenêtre ».",
         f"Référence = fenêtre d'analyse décalée d'un an (± {moteur.SAISON_MARGE_J} jours) + {moteur.RECENT_J} jours "
         "avant la fenêtre, si la saison de l'an passé suffit (30 jours jugés pour la signature, 20 jours d'heures et "
         "240 heures froides pour les PAC selon le comptage) ; sinon repli sur toute la période antérieure. Le mode "
         "retenu est inscrit dans l'alerte (champ reference).",
         f"Biais sur immeuble sain, PAC chaleur totale (réelle) : {pct(b_sig_a.get('moyenne'), 2, True)} "
         f"({pct(b_sig_a.get('min'), 1, True)} à {pct(b_sig_a.get('max'), 1, True)}) avec la période antérieure, "
         f"{pct(b_sig_s.get('moyenne'), 2, True)} ({pct(b_sig_s.get('min'), 1, True)} à "
         f"{pct(b_sig_s.get('max'), 1, True)}) avec la même saison (§ 8.8)."),
        ("R11", "priorisation par le rythme mensuel",
         "Le score partait des CHF/an : × 365 pour l'eau et l'électricité, × 210 pour le chauffage et les PAC ; "
         "les fluides n'étaient pas comparés sur la même base.",
         "Score = CHF par 30 jours aux conditions actuelles × confiance × urgence (× 1,5 si sinistre) ; enjeu "
         f"minimal en CHF par mois ({nb(moteur.seuil_enjeu_mois(c.ref['parametres']), 2)}, équivalent exact de "
         "100 CHF/an pour l'eau et l'électricité ; un ancien réglage en CHF/an est converti au prorata).",
         f"Base du score ÷ coût réel des 30 jours suivants, médianes par détecteur : de {nb(min(base_av), 1) if base_av else '—'} "
         f"à {nb(max(base_av), 1) if base_av else '—'} avant, de {nb(min(base_ap), 2) if base_ap else '—'} à "
         f"{nb(max(base_ap), 2) if base_ap else '—'} après (§ 8.7)."),
        ("R12", "relevés journaliers",
         "Un relevé journalier était sommé dans une seule heure (minuit) : sans effet visible car les jours n'avaient "
         "pas 18 heures mesurées, mais aucune règle ne pouvait s'en servir, et un relevé par jour risquait l'alerte "
         "« compteur muet » à 24 h.",
         "Relevé journalier attribué à aucune heure ; série journalière à part, utilisée par l'eau et le chauffage "
         "d'un immeuble vide et par la signature ; compteur muet au-delà de deux pas.",
         f"Au pas journalier : {', '.join(garde)} détectées {nb(kj)} fois sur {nb(nj)} (au pas horaire : {nb(kh)}) ; {nb(fj)} alerte énergie sur "
         f"{nb(nfj)} immeubles sains ; fuite de nuit, électricité de nuit et PAC non surveillées (§ 8.6).")])


def _revisions_fluides(c):
    from .pdf import CLIMAT, chiffrage as ch
    h = c.h
    med = lambda d, cle: ((ch(h, d).get(cle) or {}).get("mediane"))  # noqa: E731
    sig = [d for d in CLIMAT if not d.endswith("_vide")]
    pc = [x for x in (med(d, "ecart_proj") for d in sig) if x is not None]
    ann = [ch(h, d).get("ecart_proj_annees") for d in sig if ch(h, d).get("ecart_proj_annees")]
    gen = h["generateur"]
    grand = [g for k, g in gen.items() if k.startswith("grand")]
    from .pdf import courbe, delai, fausses
    lignes_fl = []
    for d in ("cad_signature", "gaz_signature", "cad_vide", "gaz_vide"):
        kf, nf = fausses(h, d, "fictive")
        kr, nr = fausses(h, d, "reelle")
        s50 = (courbe(h, d, "fictive") or {}).get("seuil50")
        dl = ((delai(h, d, "fictive") or {}).get("delai_j") or {}).get("mediane")
        lignes_fl.append(f"{NOMS[d]} : seuil 50 % {amp(d, s50)}, délai {nb(dl)} j, fausses alertes {nb(kf + kr)}/{nb(nf + nr)}")
    return _fiches(c, [
        ("R13", "projection séparée de la dérive constatée",
         "Le déclencheur des actions doit rester la dérive mesurée ; une estimation de ce que coûterait la dérive si "
         "rien n'est fait reste utile, à condition d'être présentée comme une hypothèse.",
         "Champs *_proj et libellé « projection » : 12 mois, dérive constante (eau, électricité) ou climat normal de "
         f"Genève ({nb(c.ref['parametres'].get('dj16_annuel_normal'), 1)} DJ16/an, MétéoSuisse GVE 2016-2025 : chauffage, "
         "CAD, gaz, PAC). Jamais dans le score, la gravité, le seuil ni le texte du bon ; le bon transmet la dérive "
         "constatée (kWh ou m³, sans CHF).",
         "Projection des signatures et PAC ÷ année normale : écart médian "
         + (f"{pct(min(pc), 0, True)} à {pct(max(pc), 0, True)}" if pc else "—") + " ; ÷ réalisé des années 2016-2025 : "
         + (f"{pct(min(x['min'] for x in ann), 0, True)} à {pct(max(x['max'] for x in ann), 0, True)}" if ann else "—")
         + " (§ 8.7). Un test vérifie qu'une autre hypothèse de climat change la projection, pas le score."),
        ("R14", "chauffage à distance (CAD) et gaz",
         "Le parc compte des immeubles raccordés au chauffage à distance et des chaudières à gaz : le gaz n'était suivi "
         "que pour la qualité des données, le CAD était confondu avec la chaleur.",
         "Fluide « cad » (kWh livrés) ; gaz en kWh ou en m³ converti par le PCS du référentiel (valeur d'exemple) ; "
         "causes cad_signature, cad_vide, gaz_signature, gaz_vide reprenant les règles de la chaleur (seuil, "
         "persistance, gravité), consignes propres, métier Chauffagiste ; tarifs et facteurs CO₂ d'EXEMPLE.",
         " ; ".join(lignes_fl) + " (§ 8)."),
        ("R15", "exemple officiel sur 12 mois",
         "L'exemple couvrait 120 jours : la référence « même saison de l'an passé » ne jouait pas et les graphiques "
         "mois et année de la fiche n'avaient pas de cycle annuel.",
         "generer_demo produit 12 mois de relevés horaires pour tous les compteurs (météo réelle GVE sur 12 mois, ou "
         "température fictive à cycle annuel), dérives en fin de période ; grand exemple porté à 25 immeubles et "
         "24 adresses (2 CAD, 2 gaz, géocodés exactement), avec une dérive CAD et une dérive gaz.",
         f"Exemple grand régénéré {nb(sum(g['graines'] for g in grand))} fois : {nb(sum(g['fausses_total'] for g in grand))} "
         f"fausse alerte, {nb(sum(g['manquees_total'] for g in grand))} dérive manquée ; référence « saison » utilisée "
         "(test). Temps mesurés : voir annexe B.")])


def limites(c):
    h = c.h
    occ = robuste(h, "occupation 50 % → 90 % (J-10)", "eau_nuit", True) or {}
    lignes = [["Limite mesurée ou connue", "Effet", "Recommandation"],
              ["Pas journalier", "Fuite de nuit, électricité de nuit et PAC non surveillées (§ 8.6)",
               "Exiger le pas horaire pour l'eau, l'électricité et les PAC (export DLMS horaire, M-Bus, LoRaWAN)."],
              ["Chiffrage mesuré depuis le début détecté", "La part de dérive antérieure (dérive progressive, jours "
               "sous le seuil) n'est pas comptée ; heures manquantes non comblées", "Montant prudent assumé ; "
               "l'afficher comme « au moins »."],
              ["Rythme mensuel au climat des derniers jours", "S'écarte du mois suivant réel quand la saison change "
               "(§ 8.7)", "Le présenter comme un ordre de grandeur courant, jamais multiplié par 12."],
              ["Immeuble vide : excès = mesure − talon déclaré", "Chiffrage prudent (sous-estimé) car la consommation "
               "hors-gel réelle est sous le talon", "Apprendre une signature hors-gel sur les jours en hors-gel de "
               "l'historique."],
              ["Changement d'occupation non déclaré", f"Fausses alertes ({_causes(occ)}) ou dérives masquées",
               "Périodes déclarées (occupation, travaux, vacance) avec rupture de référence à la date déclarée."],
              ["Historique de moins d'un an", "Repli sur la période antérieure ; pas de conclusion sous 30 jours de "
               "référence (signature), 20 jours ou 240 heures froides (PAC)", "Conserver 12 mois de mesures et de "
               "météo (400 jours prévus pour la météo)."],
              ["Nuit et abaissement en heures UTC", "Fenêtres décalées d'une heure entre l'hiver et l'été (heure de "
               "Genève)", "Fenêtres en heure locale (Europe/Zurich) et horaire d'abaissement réglable par immeuble."],
              ["Fuite sous 20 l/h", "Jamais détectée par la règle de nuit (seuil absolu)", "Ajouter un critère relatif "
               "au minimum de nuit habituel de l'immeuble."],
              ["Confiance non calibrée", "Indice d'ordre, pas une probabilité", "Recalibrer par immeuble avec les "
               "retours du gestionnaire et suivre le taux de pertinence réel."],
              ["Consommations simulées, lois linéaires", "L'avantage de la référence « même saison » n'est pas "
               "démontrable sur ces lois ; pas de saisonnalité électrique ni d'usages atypiques", "Rejouer la "
               "campagne sur un historique réel annoté (interventions connues)."],
              ["Projection (hypothèse)", "S'écarte du réalisé d'une année réelle (§ 8.7) ; suppose la dérive "
               "maintenue 12 mois", "L'afficher comme ordre de grandeur, jamais comme engagement ni déclencheur."],
              ["CAD et gaz : PCS et tarifs d'exemple", "Chiffrage du gaz dépendant du PCS déclaré ; tarifs CAD et gaz "
               "d'exemple", "Saisir le PCS facturé et les tarifs des contrats (SIG, fournisseur CAD)."],
              ["CAD : sous-station du fournisseur", "Le chauffagiste ne peut pas toujours intervenir côté réseau",
               "Ajouter un métier « fournisseur CAD » quand des contrats le précisent."]]
    out = c.h1(10, "Limites et recommandations")
    out += c.tableau(lignes, [42 * M.mm, 58 * M.mm, M.UTILE - 100 * M.mm], "Limites restantes et recommandations",
                     police=7.5)
    out.append(M.encadre(
        "Les tarifs et facteurs CO₂ utilisés dans ce document sont les valeurs d'EXEMPLE du référentiel ; toutes les "
        "consommations sont simulées. Les chiffres de ce document qualifient la méthode de calcul ; ils ne décrivent "
        "aucun immeuble réel.", c.s, fond=M.ORANGE_PALE, trait=M.ORANGE))
    return out


def _causes(r):
    pc = r.get("par_cause") or {}
    return ", ".join(f"{k} {nb(v)}/{nb(r.get('n'))}" for k, v in sorted(pc.items())) or "aucune ici"


def annexes(c):
    P = c.ref["parametres"]
    out = [PageBreak()]
    out += c.h1("A", "Annexe — paramètres")
    lignes = [["Règle", "Libellé", "Seuil (bornes)", "Persistance", "Profils", "Gravité · métier"]]
    for cause, r in moteur.regles_effectives({}).items():
        lignes.append([cause, r["libelle"], f"{nb(r['seuil'], 1 if r['seuil'] % 1 else 0)} {r['unite_seuil']} "
                       f"({nb(r['seuil_min'])}-{nb(r['seuil_max'])})", f"{r['persistance']} {r['unite_persistance']}",
                       ", ".join(r["profils"]).replace("Habite", "Habité"), f"{r['gravite']} · {r['metier']}"])
    out += c.tableau(lignes, [24 * M.mm, 44 * M.mm, 36 * M.mm, 17 * M.mm, 25 * M.mm, M.UTILE - 146 * M.mm],
                     "Règles par défaut (vigie/moteur.py, REGLES) — réglables par le gestionnaire dans les bornes",
                     police=7.2)
    lignes = [["Paramètre", "Valeur", "Rôle"],
              ["heures_nuit", f"{P['heures_nuit'][0]} h - {P['heures_nuit'][1]} h UTC", "fenêtre de nuit (eau, électricité)"],
              ["persistance_min_jours", nb(P["persistance_min_jours"]), "référence du calcul de confiance"],
              ["enjeu_min_chf_mois", f"{nb(P['enjeu_min_chf_mois'], 2)} CHF par mois", "alerte masquée en dessous (sauf "
               "sinistre, données) ; = 100 CHF/an × 30/365"],
              ["completude_min", pct(P["completude_min"]), "complétude minimale sur 30 jours"],
              ["silence_max_heures", f"{nb(P['silence_max_heures'])} h", "compteur muet (au moins deux pas)"],
              ["fenetre_analyse_jours", f"{nb(P['fenetre_analyse_jours'])} j", "la référence s'arrête avant"],
              ["dj16_annuel_normal · nuit", f"{nb(P.get('dj16_annuel_normal'), 1)} · {nb(P.get('dj16_nuit_annuel_normal'), 1)}",
               "climat normal de la projection (MétéoSuisse GVE 2016-2025)"],
              ["gaz_pcs_kwh_par_m3", f"{nb(P.get('gaz_pcs_kwh_par_m3'), 1)} kWh/m³", "conversion du gaz (EXEMPLE)"],
              ["PAS_HORAIRE · PAS_JOURNALIER", f"{moteur.PAS_HORAIRE} · {nb(moteur.PAS_JOURNALIER)} min",
               "pas de référence ; relevé journalier (règles journalières)"],
              ["JOURS_AN · JOURS_MOIS · RYTHME_JOURS_MAX", f"{moteur.JOURS_AN} · {moteur.JOURS_MOIS} · "
               f"{moteur.RYTHME_JOURS_MAX} j", "eau et électricité par an ; rythme mensuel"],
              ["SAISON_MARGE_J · RECENT_J", f"{moteur.SAISON_MARGE_J} · {moteur.RECENT_J} j",
               "référence : même saison l'an passé ± marge, + jours récents"],
              ["SIGNATURE_JOURS_MIN", f"{moteur.SIGNATURE_JOURS_MIN} j", "jours jugés pour apprendre la signature"],
              ["JOUR_HEURES_MIN", f"{moteur.JOUR_HEURES_MIN} h", "heures mesurées pour juger un jour"],
              ["NUIT_HEURES_MIN", pct(moteur.NUIT_HEURES_MIN), "heures de nuit mesurées pour juger une nuit"],
              ["NUIT_CHAUFFE", f"{moteur.NUIT_CHAUFFE[0]} h - {moteur.NUIT_CHAUFFE[1]} h UTC", "abaissement nocturne supposé"],
              ["HEURES_JOUR_FROIDES_MIN", nb(moteur.HEURES_JOUR_FROIDES_MIN),
               "heures de jour sous 14 °C pour apprendre la part de nuit"],
              ["PAC_HEURES_REF_MIN", nb(moteur.PAC_HEURES_REF_MIN), "heures de référence minimales (PAC)"],
              ["PAC_HEURES_CHAUFFE_MIN", nb(moteur.PAC_HEURES_CHAUFFE_MIN), "heures sous 14 °C (chauffage non compté)"],
              ["PAC_JOUR_MIN_KWH", f"{nb(moteur.PAC_JOUR_MIN_KWH)} kWh", "jour de PAC non jugé en dessous"]]
    out += c.tableau(lignes, [62 * M.mm, 34 * M.mm, M.UTILE - 96 * M.mm], "Paramètres du référentiel et constantes du "
                     "moteur", police=7.4)
    out += c.h1("B", "Annexe — reproduction")
    out.append(c.p("Depuis le dossier Xread_Derives_V0_2_0, sous PowerShell ou Git Bash "
                   "(<font face='Mono'>PYTHONIOENCODING=utf-8</font>) :"))
    out.append(M.formule([
        "python -m evaluation.campagne --etiquette=horaire                     # moteur actuel, pas horaire, 12 mois",
        "python -m evaluation.campagne --etiquette=horaire_avant --moteur=reference --seulement=chiffrage",
        "python -m evaluation.analyse --etiquette=horaire ; python -m evaluation.analyse --etiquette=horaire_avant",
        "python -m evaluation.climat_gve --ecrire   # climat normal GVE 2016-2025 -> référentiel (projection)",
        "python -m evaluation.donnees      # météo GVE, points des fluides, ancienne annualisation",
        "python -m evaluation.biais        # biais de l'attendu sur immeubles sains (3 versions)",
        "python -m evaluation.validation   # 4 évaluations officielles + tests unitaires",
        "python -m evaluation.figures ; python -m evaluation.pdf"], c.s))
    out.append(Spacer(1, 6))
    lignes = [["Fichier", "Contenu"],
              ["evaluation/sorties/horaire/brut_*.jsonl", "résultats bruts par scénario (alertes complètes)"],
              ["evaluation/sorties/horaire/resume.json", "métriques agrégées ; synthese_detecteurs.csv (séparateur ;)"],
              ["evaluation/sorties/horaire_avant/", "expérience de chiffrage sur la copie figée V0.2.0"],
              ["evaluation/sorties/avant|apres/", "campagne précédente (15 min, 120 jours) des révisions R1-R7"],
              ["evaluation/sorties/donnees.json", "statistiques météo, inventaire des points, ancienne annualisation"],
              ["evaluation/sorties/biais_attendu.json", "biais de l'attendu (biais_attendu_v020_15min.json : R6)"],
              ["evaluation/sorties/validation.json", "évaluations officielles et tests"],
              ["evaluation/sorties/cache_meteo/", "fichiers MétéoSuisse figés (lecture seule, source à citer)"],
              ["evaluation/sorties/figures/", "figures PNG de ce document"],
              ["evaluation/reference/moteur_v0_2_0.py", "copie figée du moteur V0.2.0"]]
    out += c.tableau(lignes, [70 * M.mm, M.UTILE - 70 * M.mm], "Fichiers produits par la campagne", police=7.4)
    camp = c.camp or {}
    t = c.temps or {}
    if t:
        out.append(c.p(
            "<b>Temps mesurés (exemple officiel, 12 mois de relevés horaires, poste de développement)</b> : "
            + " ; ".join(f"{k} : génération {nb(v['generation_s'], 1)} s ({nb(v['mesures'])} mesures), génération + import "
                         f"{nb(v['import_s'], 1)} s, analyse {nb(v['analyse_s'], 1)} s" for k, v in t.items()) + "."))
    out.append(c.p(f"Durée de la campagne « horaire » : {nb((camp.get('duree_s') or 0) / 60)} minutes sur "
                   f"{nb(max(1, (__import__('os').cpu_count() or 2) - 1))} processus. Source météo : MétéoSuisse "
                   "(données ouvertes, utilisation libre avec citation de la source)."))
    return out


def construire():
    from . import pdf as base
    M.polices()
    c = base.Contexte()
    histoire = histoire_complete(c)
    import os
    os.makedirs(os.path.dirname(base.SORTIE_PDF), exist_ok=True)
    M.TOTAL_PAGES[0] = None
    premier = M.Document(base.SORTIE_PDF)
    premier.multiBuild(histoire)  # première construction : sommaire et nombre de pages
    M.TOTAL_PAGES[0] = premier.page
    c = base.Contexte()
    doc = M.Document(base.SORTIE_PDF)
    doc.multiBuild(histoire_complete(c))
    print("PDF écrit :", base.SORTIE_PDF, f"({doc.page} pages)")


def histoire_complete(c):
    from reportlab.platypus import NextPageTemplate

    from . import pdf as base
    from . import pdf_chapitres, pdf_methodes, pdf_resultats
    histoire = [NextPageTemplate("titre")]
    histoire += base.page_titre(c)
    histoire += base.sommaire(c)
    histoire += base.synthese(c)
    histoire += pdf_chapitres.chaine(c)
    histoire += pdf_chapitres.donnees_fluides(c)
    histoire += pdf_chapitres.donnees_meteo(c)
    histoire += pdf_methodes.methodes(c)
    histoire += pdf_methodes.chiffrage(c)
    histoire += pdf_resultats.protocole(c)
    histoire += pdf_resultats.resultats(c)
    histoire += revisions(c)
    histoire += limites(c)
    histoire += annexes(c)
    return histoire
