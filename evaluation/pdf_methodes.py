"""Chapitres 5 et 6 du document PDF : méthodes de détection par fluide, chiffrage, confiance et priorisation."""
from reportlab.platypus import KeepTogether, Spacer

from vigie import moteur

from . import pdf_mise_en_page as M
from .pdf import nb, pct


def _regle(cause):
    return moteur.regles_effectives({})[cause]


def _fiche(c, cause, lignes_formule, texte, ajouts=None):
    r = _regle(cause)
    out = []
    lignes = [["Seuil par défaut", f"{nb(r['seuil'], 1 if r['seuil'] % 1 else 0)} {r['unite_seuil']}"],
              ["Persistance", f"{r['persistance']} {r['unite_persistance']}"],
              ["Profils surveillés", ", ".join(r["profils"]).replace("Habite", "Habité")],
              ["Gravité · métier · délai", f"{r['gravite']} · {r['metier']} · {r['delai']}"
               + (" · risque de sinistre (× 1,5 au score)" if r["sinistre"] else "")]]
    for a, b in (ajouts or []):
        lignes.append([a, b])
    out.append(c.p(texte))
    out.append(KeepTogether([M.formule(lignes_formule, c.s), Spacer(1, 5),
                             M.tableau([[f"<b>{a}</b>", b] for a, b in lignes], [40 * M.mm, M.UTILE - 40 * M.mm], c.s,
                                       entete=0)]))
    out.append(Spacer(1, 6))
    return out


REFERENCE = [
    f"référence    = même saison l'an passé (fenêtre décalée de 365 j, ± {moteur.SAISON_MARGE_J} j)",
    f"               + {moteur.RECENT_J} jours avant la fenêtre ;  repli : tout ce qui précède la fenêtre"]


def methodes(c):
    P = c.ref["parametres"]
    out = c.h1(5, "Méthodes de détection par fluide")
    out.append(c.p(
        "Chaque détecteur est décrit par sa règle, sa formule, ses paramètres par défaut (réglables par le gestionnaire "
        "dans les bornes prévues) et son chiffrage. Toutes les formules s'appliquent aux <b>relevés horaires</b>. "
        "Notations : <i>q</i> consommation, <i>h</i> heure, <i>j</i> jour jugé, <i>T</i> température extérieure "
        "horaire, <i>dh</i> = max(0 ; 16 − T) degrés-heures, <i>DJ</i> = moyenne journalière de <i>dh</i>."))
    out.extend(c.figure("methodes_illustration.png", "Deux détecteurs sur des scénarios simulés au pas horaire : à "
                        "gauche la signature énergétique apprise sur la référence (même saison de l'an passé + 60 jours) "
                        "et une dérive de +15 % ; à droite le débit horaire minimum de chaque nuit et une fuite de "
                        "35 l/h (orange : nuit au-delà du seuil)."))
    # ---- eau
    out += c.h2("5.1", "Eau froide")
    out.append(c.h3("Fuite de nuit — eau_nuit"))
    out += _fiche(c, "eau_nuit", [
        "débit_h      = Δindex(h) × 1000   (relevés horaires successifs)   [l/h]",
        "min_nuit(n)  = min { débit_h : h ∈ ]1 h ; 5 h] (heure de Zurich) de la nuit n }   (4 relevés)",
        "nuit jugée   si au moins 3 heures sur 4 mesurées",
        "alerte       si min_nuit > seuil pendant P nuits jugées consécutives",
        "référence    = médiane des min_nuit des 30 nuits avant la série en alerte",
        "excès        = médiane(min_nuit de la série) − référence      [l/h]",
        "m³/jour      = excès × 24 / 1000 ;  m³/an = × 365 ;  m³/mois = × 30"],
        "Une fuite (chasse d'eau, robinet, colonne) coule en continu, y compris aux heures où l'immeuble ne consomme "
        "rien. Le minimum des débits horaires de la nuit l'isole des chasses d'eau ponctuelles : une seule heure de "
        "nuit sans écoulement suffit à ramener le minimum vers zéro. Au pas horaire, un relevé perdu rend inconnues "
        "les deux heures qui l'encadrent ; la nuit reste jugée si 3 heures sur 4 sont connues. Au pas journalier, le "
        "débit de nuit n'existe pas : la règle ne peut pas tourner.")
    out.append(c.h3("Eau dans un immeuble vide — eau_vide"))
    out += _fiche(c, "eau_vide", [
        "V(j)         = Σ débit_h du jour j, sur nh(j) heures mesurées  [l]   (relevé journalier : nh = 24)",
        "jour jugé    si nh(j) ≥ 18 et j < jour en cours",
        "alerte       si V(j) > seuil × nh(j)/24 pendant P jours jugés consécutifs",
        "l/jour       = moyenne de V(j) × 24/nh(j) sur la série ;  par an × 365, par mois × 30"],
        "Un immeuble déclaré vide ne doit pas consommer d'eau : le seuil est absolu, il n'y a pas d'attendu appris. "
        "La règle fonctionne aussi au pas journalier.")
    # ---- chaleur
    out += c.h2("5.2", "Chaleur, chauffage à distance (CAD) et gaz")
    out.append(c.p(
        "Les mêmes règles s'appliquent à trois compteurs de chauffage : la chaleur produite par une chaufferie "
        "(causes chaleur_*), la chaleur livrée par le chauffage à distance à la sous-station (cad_*) et l'énergie du gaz "
        "d'une chaudière (gaz_*, m³ convertis en kWh par le pouvoir calorifique). Tous trois suivent la météo de la même "
        "façon (le gaz vaut la chaleur divisée par le rendement de la chaudière) : signature, seuil, persistance et "
        "gravité sont identiques, et la campagne le vérifie (chapitre 8). Seuls changent le texte, le tarif, le facteur "
        "CO₂ et la consigne (CAD : régulation de la sous-station, puis fournisseur si le défaut est côté réseau ; gaz : "
        "réglage du brûleur). Le métier est le chauffagiste pour les trois."))
    out.append(c.h3("Chauffage trop fort pour la météo — chaleur_signature"))
    out += _fiche(c, "chaleur_signature", REFERENCE + [
        "               (au moins 30 jours jugés dans la saison de l'an passé pour l'utiliser)",
        "modèle       q(j) = a + b·DJ(j) [+ c·DJnuit(j)]   (moindres carrés)",
        "             DJnuit = part des degrés-heures entre 22 h et 5 h ; terme retenu seulement si",
        "             ≥ 120 heures de jour sous 14 °C en référence et −b ≤ c ≤ 0",
        "ajustement   sur les heures mesurées : q = a·nh/24 + b·Σdh/24 + c·Σdh_nuit/24",
        "ratio(j)     = chaleur mesurée / attendu sur les mêmes heures",
        "alerte       si ratio > 1 + seuil pendant P jours jugés consécutifs",
        "chiffrage    excès mesuré = Σ (q(h) − attendu(h)) des heures mesurées depuis le début",
        "             rythme = moyenne((ratio − 1) × attendu 24 h) des 30 derniers jours au plus × 30"],
        "La signature énergétique relie la chaleur journalière aux degrés-jours (base 16 °C). Une courbe de chauffe "
        "déréglée, une sonde extérieure défaillante ou une consigne relevée se traduisent par une chaleur supérieure à "
        "l'attendu à météo égale. Au pas journalier, la même signature est ajustée sur les jours entiers (le terme de "
        "nuit reste estimé à partir de la température horaire).")
    out.append(c.h3("Chauffage normal dans un immeuble vide — chaleur_vide"))
    out += _fiche(c, "chaleur_vide", [
        "Q(j)         = chaleur du jour j sur nh(j) heures mesurées   (relevé journalier : nh = 24)",
        "alerte       si Q(j) > facteur × talon × nh(j)/24 pendant P jours jugés consécutifs",
        "chiffrage    excès mesuré = Σ (q(h) − talon/24) des heures mesurées depuis le début",
        "             rythme = moyenne(Q(j) × 24/nh(j) − talon) des 30 derniers jours au plus × 30",
        "sans talon hors-gel déclaré : règle non exécutée (aucun seuil inventé)"],
        "Le talon hors-gel est déclaré par immeuble (kWh/jour). La règle ne dépend pas de la météo : elle repère un "
        "retour en marche normale, pas une dérive fine.")
    # ---- électricité
    out += c.h2("5.3", "Électricité")
    out.append(c.h3("Consommation de nuit en hausse — elec_nuit"))
    out += _fiche(c, "elec_nuit", [
        "P_nuit(n)    = puissance moyenne des relevés horaires de 1 h à 5 h, heure de Zurich (kWh/h = kW)",
        "référence    = médiane des P_nuit des nuits J-50 à J-20",
        "             (alerte ouverte → 30 nuits avant le début de la dérive)",
        "alerte       si P_nuit / référence > 1 + seuil pendant P nuits consécutives",
        "excès        = moyenne de la puissance 22 h-6 h de la série − médiane de référence 22 h-6 h  [kW]",
        "kWh/jour     = excès × 8 h ;  par an × 365, par mois × 30"],
        "Éclairage des communs ou du garage resté allumé, ventilation bloquée en grande vitesse, équipement oublié : la "
        "puissance de nuit monte alors que l'occupation n'a pas changé. La règle demande le pas horaire.")
    # ---- PAC
    out += c.h2("5.4", "Pompes à chaleur")
    out.append(c.p(
        "L'électricité horaire d'une PAC vaut à peu près chaleur ÷ rendement, et l'inverse du rendement varie presque "
        "linéairement avec la température extérieure. Le modèle horaire, appris par moindres carrés sur la référence "
        f"(même saison de l'an passé + {moteur.RECENT_J} jours récents si l'historique le permet ; au moins 20 jours "
        "d'heures de fonctionnement), s'adapte au comptage de chaleur disponible :"))
    lignes = [["Comptage", "Variables explicatives de l'électricité horaire", "Condition supplémentaire"],
              ["Chaleur totale", "Q, Q·T", "—"],
              ["Chauffage seul", "Q_chauffage, Q_chauffage·T, constante (eau chaude)", "—"],
              ["Eau chaude seule", "Q_ecs, Q_ecs·T, dh, dh·T [+ dh·nuit, dh·T·nuit]",
               f"≥ {moteur.PAC_HEURES_CHAUFFE_MIN} heures sous 14 °C en référence"],
              ["Aucun (électricité seule)", "constante, dh, dh·T [+ dh·nuit, dh·T·nuit]",
               f"≥ {moteur.PAC_HEURES_CHAUFFE_MIN} heures sous 14 °C en référence"]]
    out += c.tableau(lignes, [36 * M.mm, 80 * M.mm, M.UTILE - 116 * M.mm],
                     "Modèle de l'électricité horaire d'une PAC selon le comptage (termes entre crochets : si ≥ 120 "
                     "heures de jour sous 14 °C en référence)")
    out += _fiche(c, "pac_cop", [
        "e_att(h)     = X(h) · β,  β appris sur la référence ;  heures où toutes les séries sont mesurées",
        "ratio(j)     = Σ e_att / Σ e   (jours avec e_att > 1 kWh, jour en cours exclu)",
        "alerte       si ratio < 1 − seuil pendant P jours consécutifs",
        "chiffrage    excès mesuré = Σ (e(h) − e_att(h)) des heures mesurées depuis le début",
        "             rythme = moyenne((e − e_att) × 24/nh) des 30 derniers jours au plus × 30",
        "constat      chaleur totale comptée : rendement mesuré Σq/Σe et attendu Σq/Σe_att"],
        "Le seuil s'exprime en perte de rendement : électricité attendue ÷ électricité mesurée. La règle demande le pas "
        "horaire (électricité et chaleur), car la température de l'heure de production compte.")
    # ---- qualité
    out += c.h2("5.5", "Qualité des données (avant toute alerte énergie)")
    lignes = [["Contrôle", "Règle", "Paramètre"],
              ["Compteur muet", "dernière mesure plus ancienne que la fin des données de plus de (au moins deux pas "
               "pour un compteur journalier)", f"{P['silence_max_heures']} h"],
              ["Complétude", "mesures reçues sur 30 jours ÷ mesures attendues (30 j × 24 h × 60 / pas) inférieure à",
               pct(P["completude_min"])],
              ["Index qui recule", "au moins une différence d'index négative sans changement de compteur déclaré", "—"],
              ["Valeurs négatives", "valeur négative sur un index ou une consommation : marquée « suspecte » à "
               "l'import, exclue des calculs", "—"]]
    out += c.tableau(lignes, [32 * M.mm, M.UTILE - 62 * M.mm, 30 * M.mm], "Contrôles de qualité : un point en "
                     "défaut produit une seule alerte « Données » (métier Télérelève) et aucune alerte énergie",
                     alignements=["g", "g", "d"])
    return out


def chiffrage(c):
    P = c.ref["parametres"]
    t, co2 = c.ref["tarifs"], c.ref["facteurs_co2_kg_par_kwh"]
    clim = c.ref.get("climat_reference") or {}
    out = c.h1(6, "Chiffrage, projection et priorisation")
    out.append(c.p(
        "Chaque alerte porte deux notions séparées. La <b>dérive constatée</b> est ce qui a été mesuré depuis le début "
        "de la dérive : c'est elle qui déclenche l'alerte (écart mesuré ÷ attendu, persistance), qui fixe la priorité et "
        "qui figure dans le bon envoyé au prestataire. La <b>projection</b> estime ce que coûterait la dérive sur "
        "12 mois si rien n'est fait ; elle repose sur une hypothèse affichée avec elle et ne déclenche jamais rien, "
        "ne change jamais la gravité et n'entre pas dans le score."))
    out += c.h2("6.1", "Dérive constatée (mesure)")
    out.append(M.formule([
        "Chauffage, CAD, gaz, PAC (chiffrage « mesure »)",
        "  constaté = Σ (mesuré(h) − attendu(h)) sur les heures mesurées depuis le début,",
        "             jour en cours compris        champs kwh_mesure, chf_mesure, co2_t_mesure",
        "Eau d'un immeuble vide :  constaté = volume mesuré depuis le début (attendu ≈ 0)",
        "Fuite de nuit, électricité de nuit (dérives constantes)",
        "  constaté = excès constaté la nuit (débit ou puissance − référence) × heures mesurées",
        "Tous les fluides — rythme mensuel (base du score)",
        f"  par mois = excès moyen par jour des {moteur.RYTHME_JOURS_MAX} derniers jours de dérive au plus × {moteur.JOURS_MOIS}",
        "CHF = kWh × tarif du vecteur + m³ × tarif de l'eau ;  CO₂ = kWh × facteur du vecteur"], c.s))
    out.append(Spacer(1, 6))
    lignes = [["Vecteur", "Tarif (EXEMPLE)", "Facteur CO₂ (EXEMPLE)"],
              ["Électricité (dont PAC)", f"{nb(t['electricite']['chf_par_unite'], 2)} CHF/kWh",
               f"{nb(co2['electricite'], 2)} kg/kWh"],
              ["Chaleur (chaufferie)", f"{nb(t['chaleur']['chf_par_unite'], 2)} CHF/kWh",
               f"{nb(co2['chaleur'], 2)} kg/kWh (gaz supposé)"],
              ["Chauffage à distance", f"{nb(t['cad']['chf_par_unite'], 2)} CHF/kWh", f"{nb(co2['cad'], 2)} kg/kWh"],
              ["Gaz (kWh PCS)", f"{nb(t['gaz']['chf_par_unite'], 2)} CHF/kWh", f"{nb(co2['gaz'], 2)} kg/kWh"],
              ["Eau", f"{nb(t['eau']['chf_par_unite'], 2)} CHF/m³", "—"]]
    out += c.tableau(lignes, [44 * M.mm, 48 * M.mm, M.UTILE - 92 * M.mm], "Valeurs du référentiel, statut EXEMPLE : "
                     "elles seront remplacées par les contrats et le référentiel retenu (KBOB, par ex.)")
    out.append(c.p(
        "Le montant constaté est une borne prudente : une heure manquante n'est jamais comblée (règle 4) et la part de "
        "la dérive antérieure au début détecté n'est pas comptée. Il est vérifiable : il ne dépend que des mesures, de "
        "l'attendu appris et du début de la dérive. Sa justesse est mesurée au § 8.7."))
    out += c.h2("6.2", "Projection si rien n'est fait (hypothèse)")
    out.append(M.formule([
        "Eau, électricité : projection 12 mois = excès par jour × 365   (hypothèse : dérive constante)",
        "Signature (chaleur, CAD, gaz) :",
        "  projection = (Σ mesuré ÷ Σ attendu − 1 sur la dérive) × (365·a + b·DJ_an + c·DJnuit_an)",
        "PAC : projection = (Σ e ÷ Σ e_att − 1) × (365·u + v·DJ_an), e_att(jour) ≈ u + v·DJ",
        "Immeuble vide : projection = (excès ÷ DJ pendant la dérive) × DJ_an  (si ≥ 1 DJ/jour)",
        f"DJ_an = {nb(P.get('dj16_annuel_normal'), 1)} ; DJnuit_an = {nb(P.get('dj16_nuit_annuel_normal'), 1)}  "
        "(hypothèse : climat normal de Genève)"], c.s))
    out.append(Spacer(1, 6))
    out.append(c.p(
        f"<b>Source du climat normal.</b> {clim.get('source', '—')} ; période {clim.get('periode', '—')} "
        f"({clim.get('annees_retenues', '—')} années complètes) ; {clim.get('definition', '')}. Valeurs écrites dans le "
        "référentiel par <font face='Mono'>python -m evaluation.climat_gve --ecrire</font> (bloc climat_reference). "
        "Sans ces paramètres, la projection du chauffage et des PAC n'est pas calculée (« non calculée ») ; l'alerte, "
        "son montant constaté et sa priorité restent identiques. La projection est affichée « Projection si rien "
        "n'est fait : … (hypothèse : …) », jamais dans le texte du bon envoyé au prestataire. Sa justesse — l'écart "
        "entre le projeté et le réalisé de chaque année réelle 2016-2025 — est mesurée au § 8.7."))
    out += c.h2("6.3", "Confiance, score et priorisation")
    out.append(M.formule([
        f"confiance = min(0,97 ; 0,6 + min(0,2 ; 0,04 × (persistance − {P['persistance_min_jours']})) + 0,15 × force)",
        "            × min(1 ; complétude / 0,97)",
        "force     : eau_nuit excès/100 l/h · signature 4×(ratio−1) · elec_nuit excès/2 kW · PAC 3×(1−ratio)",
        "            eau_vide 0,8 · immeuble vide chauffé 1   (bornée à 1)",
        "score     = rythme mensuel CONSTATÉ (CHF) × confiance × urgence (Critique 3, Élevée 2, Modérée 1)",
        "            × 1,5 si sinistre ;  la projection n'entre pas dans le score",
        f"masquée   si CHF par mois < {nb(moteur.seuil_enjeu_mois(P), 2)}, sauf risque de sinistre ou alerte Données"], c.s))
    out.append(Spacer(1, 6))
    out.append(c.p(
        "<b>Choix et justification.</b> Le score repose sur la mesure seule. Le rythme mensuel constaté a la même "
        "définition pour tous les fluides (coût par 30 jours aux conditions actuelles) : la campagne vérifie qu'il "
        "vaut à peu près le coût réel du mois suivant pour tous les détecteurs (§ 8.7), ce qui rend les scores "
        "comparables. La projection dépend d'une hypothèse (climat, maintien de la dérive) : l'utiliser dans le score "
        "ferait classer différemment deux dérives constatées égales selon l'hypothèse retenue, ce que la règle exclut "
        "(un test vérifie que changer le climat normal change la projection mais ni le score, ni la gravité). Une "
        "combinaison bornée mesure + projection n'a pas été retenue : la campagne montre que la base mesurée suffit à "
        "rendre les fluides comparables, et toute part de projection réintroduirait la dépendance à l'hypothèse. La "
        "confiance reste un indice d'ordonnancement, pas une probabilité calibrée (§ 8.9)."))
    out += c.h2("6.4", "Pourquoi la projection n'est jamais un chiffrage d'alerte")
    ann = [a for a in c.d["annualisation"] if a["grandeur"] == "chaleur"]
    noms = {"10": "oct.", "11": "nov.", "12": "déc.", "1": "janv.", "2": "févr.", "3": "mars", "4": "avr."}
    lignes = [["Saison (GVE)", "DJ base 16"] + list(noms.values())]
    for a in ann:
        lignes.append([a["saison"], nb(a["dj16_saison"])] + [nb(a["rapport_par_mois"][m], 2) for m in noms])
    out += c.tableau(lignes, [26 * M.mm, 20 * M.mm] + [(M.UTILE - 46 * M.mm) / 7] * 7,
                     "Ancienne annualisation V0.2.0 : « excès d'un jour du mois × 210 » ÷ « excès réel sur l'année » "
                     "pour une dérive proportionnelle au chauffage (modèle de chaleur de la campagne, 30 logements, "
                     "température réelle GVE)", alignements=["g", "d"] + ["d"] * 7)
    out.extend(c.figure("annualisation.png", "Biais de l'ancienne annualisation selon le mois de détection (1 = juste)."))
    vals = [v for a in ann for v in a["rapport_par_mois"].values()]
    out.append(c.p(
        f"L'ancienne annualisation donnait, selon le mois de détection, de {pct(min(vals))} à {pct(max(vals))} de "
        "l'excès réel d'une année : une extrapolation présentée comme un chiffrage. La projection actuelle corrige la "
        "saison (climat normal sur toute l'année) mais reste une hypothèse : l'année réelle s'écarte du climat normal "
        "et la dérive peut être réparée ou s'aggraver. C'est pourquoi elle est séparée de la dérive constatée et ne "
        "commande aucune action."))
    return out
