"""Chapitres 2 à 4 du document PDF : chaîne de calcul, données des fluides, données météo."""
from vigie import moteur

from . import pdf_mise_en_page as M
from .pdf import nb


# ---------------------------------------------------------------- 2. chaîne de calcul


def chaine(c):
    P = c.ref["parametres"]
    out = c.h1(2, "Chaîne de calcul et principes")
    out.append(c.p(
        "Une analyse part des mesures brutes en base et produit des alertes structurées. Toutes les grandeurs "
        "(kWh, m³, CHF, CO₂) sont calculées par le moteur ; aucun texte généré ne crée ni ne modifie un chiffre. "
        "L'ordre des étapes est fixe :"))
    lignes = [["Étape", "Ce qui est fait", "Règle de prudence"],
              ["1. Séries horaires", "Index → différences ; intervalles sommés à l'heure ; instantanés moyennés. "
               "Heure en fin d'intervalle, UTC. Relevé journalier : série journalière à part.", "Valeur négative "
               "« suspecte » exclue ; différence d'index à travers un trou et relevé plus grossier que l'heure attribués "
               "à aucune heure ; jamais d'interpolation pour décider."],
              ["2. Qualité d'abord", "Compteur muet, complétude sur 30 jours, index qui recule, valeurs négatives.",
               "Un point en défaut produit UNE alerte « Données » et aucune alerte énergie."],
              ["3. Attendu", f"Appris AVANT la fenêtre d'analyse de {P['fenetre_analyse_jours']} jours : nuits de "
               "référence, signature énergétique, modèle horaire de PAC. Chauffage et PAC : même saison de l'an passé "
               "+ 60 jours récents quand l'historique le permet.", "Gelé avant le début d'une dérive déjà en alerte."],
              ["4. Détecteurs", "Écart à l'attendu ou à un seuil absolu, selon le profil (Habité, Partiel, Vide, "
               "Travaux) et les règles réglées.", "Persistance obligatoire : un pic isolé n'est jamais une alerte."],
              ["5. Chiffrage", "Dérive constatée depuis le début (tous les fluides) et rythme par 30 jours ; "
               "projection séparée sur 12 mois si rien n'est fait.", "La projection est une hypothèse étiquetée "
               "(climat normal, dérive constante), jamais un déclencheur ; tarifs et CO₂ = valeurs d'EXEMPLE."],
              ["6. Priorisation", "Score = rythme mensuel constaté (CHF) × confiance × urgence (× 1,5 si sinistre) ; "
               "la projection n'y entre pas.",
               f"Rythme &lt; {nb(moteur.seuil_enjeu_mois(P), 2)} CHF par mois masqué, sauf sinistre ou données."]]
    out += c.tableau(lignes, [30 * M.mm, 72 * M.mm, M.UTILE - 102 * M.mm], "Étapes d'une analyse")
    out.append(c.h3("Conventions communes"))
    out += c.puces([
        "<b>Une alerte par cause et par immeuble</b> (identifiant immeuble-cause) ; les défauts de données d'un même "
        "point sont regroupés en une seule alerte.",
        "<b>Jour jugé</b> : jour civil UTC des heures en fin d'intervalle ; le jour en cours (incomplet) n'est jamais "
        f"jugé. Un jour n'est jugé que si au moins {moteur.JOUR_HEURES_MIN} heures sur 24 sont mesurées, et ses seuils "
        "sont alors comparés au prorata des heures mesurées.",
        f"<b>Nuit</b> : heures dont la fin tombe dans ]{P['heures_nuit'][0]} h ; {P['heures_nuit'][1]} h] UTC, soit "
        "1 h-5 h UTC (2 h-6 h l'hiver et 3 h-7 h l'été en heure de Genève), donc 4 relevés horaires par nuit.",
        "<b>Persistance</b> : nombre de jours (ou de nuits) consécutifs jugés au-delà du seuil, comptés depuis le "
        "dernier jour complet. Un jour ou une nuit non jugé (données insuffisantes) est sauté : il ne casse pas la "
        "série et ne la prolonge pas."])
    return out


# ---------------------------------------------------------------- 3. données des fluides


NOMS_FLUIDES = {"chaleur": "Chaleur (chaufferie)", "cad": "Chauffage à distance (CAD)", "gaz": "Gaz (chaudière)",
                "eau": "Eau froide", "eau_chaude": "Eau chaude sanitaire",
                "electricite": "Électricité générale", "meteo": "Température extérieure",
                "pac_chaleur": "PAC — chaleur totale", "pac_chaleur_chauffage": "PAC — chaleur chauffage",
                "pac_chaleur_ecs": "PAC — chaleur eau chaude", "pac_electricite": "PAC — électricité"}
PROFILS = {"Habite": "habités", "Partiel": "partiellement occupés", "Vide": "vide", "Travaux": "en travaux"}


def donnees_fluides(c):
    pts = c.d["points"]
    out = c.h1(3, "Données des fluides")
    out.append(c.p(
        "Le format d'import est <font face='Mono'>ts,point_id,valeur</font>, horodatage UTC ISO en fin d'intervalle. "
        "Chaque point de mesure déclare une <b>nature</b>, qui fixe la façon d'en tirer une consommation horaire, et "
        "un <b>pas</b> nominal, qui sert au calcul de la complétude, à reconnaître une heure incomplète ou un trou "
        "entre deux index, et à décider quelles règles peuvent s'en servir. Les unités sont normalisées à l'import "
        "(kWh, m³, °C). <b>Les données arrivent au mieux à l'heure</b> : le pas par défaut d'un compteur est de "
        f"{moteur.PAS_HORAIRE} minutes pour tous les fluides."))
    lignes = [["Nature", "Exemples", "Série horaire utilisée par les détecteurs"],
              ["index", "Eau froide (m³), gaz (m³ ou kWh)", "Différence entre relevés horaires successifs. Différence "
               "négative = recul d'index (alerte Données) ; différence à travers un trou de plus de 1,5 pas (90 min "
               "au pas horaire) attribuée à aucune heure."],
              ["intervalle", "Électricité, chaleur, CAD, PAC (kWh)", "Valeur du relevé horaire (pas plus fin, accepté : "
               "heure retenue seulement si tous ses pas sont présents)."],
              ["instantane", "Température extérieure (°C)", "Moyenne des valeurs de l'heure ; valeur négative admise."]]
    out += c.tableau(lignes, [24 * M.mm, 42 * M.mm, M.UTILE - 66 * M.mm], "Natures de points et passage à l'heure")
    lignes = [["Fluide", "Nature", "Pas", "Unité", "Points", "Mesures", "Plage des valeurs brutes"]]
    for ligne in pts["lignes"]:
        if ligne["etat"] != "actif":
            continue
        unite = ligne["unite"].replace("degC", "°C").replace("m3", "m³")
        plage = f"{nb(ligne['vmin'], 2)} à {nb(ligne['vmax'], 2)}" + (" (index)" if ligne["nature"] == "index" else "")
        lignes.append([NOMS_FLUIDES.get(ligne["fluide"], ligne["fluide"]), ligne["nature"], f"{ligne['pas_min']} min",
                       unite, nb(ligne["points"]), nb(ligne["mesures"]), plage])
    actifs = [x for x in pts["lignes"] if x["etat"] == "actif"]
    lignes.append(["Total (12 mois)", "", "", "", nb(sum(x["points"] for x in actifs)), nb(pts["mesures"]),
                   f"{nb(pts['rejets'])} rejet à l'import, {nb(pts['suspectes'])} valeur suspecte"])
    out += c.tableau(lignes, [40 * M.mm, 18 * M.mm, 15 * M.mm, 12 * M.mm, 13 * M.mm, 21 * M.mm, M.UTILE - 119 * M.mm],
                     "Points de mesure du grand exemple (25 immeubles, graine 42, météo fictive, 12 mois) — "
                     "consommations simulées, relevés horaires", alignements=["g", "g", "d", "g", "d", "d", "g"],
                     total=True)
    imm = ", ".join(f"{nb(x['n'])} {PROFILS.get(x['profil'], x['profil'])}" for x in pts["immeubles"])
    out.append(c.p(
        f"Le grand exemple compte 25 immeubles ({imm}) à 24 adresses ; deux sont raccordés au chauffage à distance et "
        "deux chauffés au gaz, à de vraies adresses genevoises géocodées exactement. Un compteur d'eau chaude reste "
        "« à connecter » et n'est pas analysé. L'exemple officiel et la campagne couvrent 12 mois : les graphiques mois "
        "et année des fiches montrent le cycle été / hiver, et la référence « même saison de l'an passé » s'applique."))
    out.append(c.p(
        f"<b>CAD et gaz.</b> Le CAD est relevé par le compteur de chaleur de la sous-station (kWh livrés, intervalle). Le "
        "gaz d'une chaudière est relevé en m³ (index) ou en kWh ; un relevé en m³ est converti en kWh par le pouvoir "
        f"calorifique supérieur du référentiel (gaz_pcs_kwh_par_m3 = {nb(c.ref['parametres'].get('gaz_pcs_kwh_par_m3'), 1)} "
        "kWh/m³, valeur d'EXEMPLE à remplacer par celle du distributeur) ; sans ce paramètre, aucune alerte énergie "
        "n'est calculée sur ce compteur. Les deux fluides reprennent les règles de la chaleur (signature, immeuble vide)."))
    out.append(c.h3("Ce que permet chaque pas de temps"))
    lignes = [["Pas du relevé", "Règles utilisables", "Ce qui est perdu"],
              ["Horaire (60 min), cas de référence", "Toutes : fuite de nuit, eau et chauffage d'un immeuble vide, "
               "signature, électricité de nuit, PAC", "—"],
              ["Plus fin que l'heure (accepté)", "Toutes, après passage à l'heure", "— (aucune donnée de ce type "
               "n'est attendue)"],
              ["Journalier (1 440 min)", "Eau d'un immeuble vide, chauffage d'un immeuble vide, signature de chauffage "
               "(jour entier, sans abaissement nocturne visible)", "Fuite de nuit, électricité de nuit, PAC (rendement "
               "jugé heure par heure) : mesuré au § 8.6"],
              ["Température plus grossière que l'heure", "Aucune règle dépendant de la météo", "Signature et PAC"]]
    out += c.tableau(lignes, [42 * M.mm, 70 * M.mm, M.UTILE - 112 * M.mm], "Règles utilisables selon le pas du "
                     "relevé ; l'interface signale un compteur plus grossier que l'heure (« pas trop grossier »)")
    out.append(c.h3("Lois de simulation (générateur d'exemple et simulateur de la campagne)"))
    lignes = [["Fluide", "Loi simulée (L = logements, occ = taux d'occupation, T = température, h = heure UTC)", "Bruit"],
              ["Chaleur (heure)", "0,22·L·max(0 ; 16 − T)·r + 0,12·L, avec r = 0,8 de 22 h à 5 h (abaissement nocturne)",
               "× U(0,95 ; 1,05)"],
              ["PAC (heure)", "chaleur 0,22·L·(0,6 + 0,4·occ)·max(0 ; 16 − T)·r + eau chaude 0,12·L·occ ; électricité = "
               "chauffage ÷ (3,4 + 0,04·(T − 5)) + eau chaude ÷ (2,6 + 0,03·(T − 5)), cumulée sur l'heure",
               "× U(0,95 ; 1,05) ; électricité × U(0,97 ; 1,03) par quart"],
              ["Électricité (relevé horaire)", "base + jour × présence(h), présence = sin((h − 6)/17·π) de 6 h à 23 h, 0 "
               "la nuit ; simulée par quart d'heure puis cumulée sur l'heure", "× U(0,93 ; 1,07) par quart"],
              ["Eau (index horaire)", "12,5·L·profil(h)·occ, pointes à 7 h 30 et 19 h 30, 0 entre 1 h et 5 h ; chasse "
               "d'eau de nuit avec une probabilité de 0,15 par quart d'heure, 0 à 40 l/h ; index lu à l'heure pleine",
               "× U(0,85 ; 1,15)"],
              ["CAD (heure)", "chaleur livrée = loi de la chaleur", "× U(0,95 ; 1,05)"],
              ["Gaz (index horaire)", "gaz (m³) = loi de la chaleur ÷ rendement 0,92 ÷ PCS 10,5 kWh/m³", "idem"],
              ["Immeuble vide", "chaleur hors-gel = 0,12 × marche normale ; eau = chasses de nuit seulement ; talon "
               "hors-gel déclaré 200 kWh/jour", "idem"]]
    out += c.tableau(lignes, [29 * M.mm, M.UTILE - 66 * M.mm, 37 * M.mm],
                     "Lois des consommations simulées (fictives) : simulées par quart d'heure quand l'usage l'exige "
                     "(chasses d'eau, présence), toujours RELEVÉES à l'heure")
    return out


# ---------------------------------------------------------------- 4. données météo


def donnees_meteo(c):
    r, f = c.d["meteo_reelle"], c.d["meteo_fictive_campagne"]
    lg = c.d["meteo_longue"]
    jours = c.d.get("historique_jours", 365)
    out = c.h1(4, "Données météo")
    out.append(c.p(
        "La température extérieure gouverne deux règles : la signature de chauffage et le rendement des PAC. La source "
        "réelle est <b>MétéoSuisse, données ouvertes SwissMetNet, station Genève-Cointrin (GVE)</b>, colonne "
        "<font face='Mono'>tre200h0</font> (température de l'air à 2 m, moyenne horaire, UTC, fin d'intervalle). "
        "Les heures manquantes restent manquantes et les valeurs hors de −45 à 50 °C sont écartées. Pour la campagne, "
        f"les fichiers publics ont été téléchargés une fois, le {c.d['telecharge_le'][:10]}, puis figés "
        "(evaluation/sorties/cache_meteo) : la campagne est reproductible. Aucune donnée de consommation n'est envoyée."))
    lignes = [["Grandeur", "Série réelle GVE", "Série fictive (simulateur)"],
              [f"Période simulée ({nb(jours)} jours, UTC)", f"{r['debut'][:10]} → {r['fin'][:10]}",
               f"{f['debut'][:10]} → {f['fin'][:10]}"],
              ["Heures attendues / présentes", f"{nb(r['heures_attendues'])} / {nb(r['heures_presentes'])}",
               f"{nb(f['heures_attendues'])} / {nb(f['heures_presentes'])}"],
              ["Heures manquantes", nb(r["heures_manquantes"]), nb(f["heures_manquantes"])],
              ["Minimum horaire", f"{nb(r['min'], 1)} °C ({r['min_le'][:10]})", f"{nb(f['min'], 1)} °C"],
              ["Maximum horaire", f"{nb(r['max'], 1)} °C ({r['max_le'][:10]})", f"{nb(f['max'], 1)} °C"],
              ["Moyenne", f"{nb(r['moyenne'], 1)} °C", f"{nb(f['moyenne'], 1)} °C"],
              ["Moyenne journalière min / max", f"{nb(r['jour_min'], 1)} / {nb(r['jour_max'], 1)} °C",
               f"{nb(f['jour_min'], 1)} / {nb(f['jour_max'], 1)} °C"],
              [f"Degrés-jours base 16 °C ({nb(jours)} j)", nb(r["dj16_total"]), nb(f["dj16_total"])],
              ["dont fenêtre d'analyse (30 j)", nb(r["dj16_fenetre_30j"]), nb(f["dj16_fenetre_30j"])],
              ["Heures sous 14 °C avant la fenêtre", nb(r["heures_sous_14_reference"]),
               nb(f["heures_sous_14_reference"])]]
    out += c.tableau(lignes, [62 * M.mm, 58 * M.mm, M.UTILE - 120 * M.mm],
                     "Température utilisée par la campagne (degrés-jours = moyenne journalière de max(0 ; 16 − T horaire))",
                     alignements=["g", "d", "d"])
    out.extend(c.figure("meteo_gve.png", "Température extérieure sur 12 mois : série réelle MétéoSuisse GVE et série "
                        "fictive du simulateur ; zones grisées : périodes de référence du chauffage et de la PAC (même "
                        "saison de l'an passé et 60 jours récents) ; en bas, degrés-jours journaliers de la série réelle."))
    mois = " ; ".join(f"{m['mois'][5:]}.{m['mois'][:4]} : {nb(m['moyenne'], 1)} °C" for m in r["mois"])
    out.append(c.p(
        f"<b>Lecture.</b> Moyennes mensuelles réelles : {mois}. Avec 12 mois d'historique, la référence couvre un hiver "
        f"complet ({nb(r['heures_sous_14_reference'])} heures sous 14 °C avant la fenêtre, contre {nb(moteur.PAC_HEURES_CHAUFFE_MIN)} exigées par la "
        "règle PAC sans compteur de chauffage) : la signature et les PAC n'extrapolent plus vers des journées plus "
        "froides que tout ce qu'elles ont appris, contrairement à la campagne précédente sur 120 jours."))
    out.append(c.p(
        f"Pour l'expérience de chiffrage et la projection, la série a été lue de {lg['debut'][:10]} à {lg['fin'][:10]} "
        f"({nb(lg['heures'])} heures présentes pour {nb(lg['heures_attendues'])} attendues) : chaque fin d'analyse "
        "d'octobre 2025 à avril 2026 dispose de 12 mois d'historique et des 30 jours suivants. Le climat normal de la "
        f"projection est la moyenne des années complètes 2016 à 2025 (fichiers historiques GVE) : "
        f"{nb(c.ref['parametres'].get('dj16_annuel_normal'), 1)} degrés-jours base 16 °C par an, dont "
        f"{nb(c.ref['parametres'].get('dj16_nuit_annuel_normal'), 1)} la nuit (de "
        f"{nb(c.ref['climat_reference']['dj16_min_max_sur_la_periode'][0], 1)} à "
        f"{nb(c.ref['climat_reference']['dj16_min_max_sur_la_periode'][1], 1)} selon l'année) ; chaque année réelle "
        "sert aussi de « réalisé » pour juger la projection (§ 8.7)."))
    return out
