"""Génère un jeu de données d'exemple (12 mois) au format d'import Vigie.

Format CSV : ts (UTC, ISO, fin d'intervalle), point_id, valeur
Toutes les séries sont relevées au PAS HORAIRE (les données réelles arrivent au mieux à l'heure) : l'eau et
l'électricité sont simulées par quart d'heure (chasses d'eau, présence) puis relevées à l'heure pleine (index lu à
l'heure, électricité cumulée sur l'heure) ; mêmes tirages aléatoires et mêmes dérives qu'au pas de 15 min.
Les consommations sont SIMULÉES sur 12 mois (cycle annuel été / hiver du chauffage, du CAD, du gaz et des PAC). La
température extérieure est soit fictive (par défaut, hors ligne : cycle annuel, minimum mi-janvier), soit RÉELLE
(12 mois MétéoSuisse passés en paramètre) : le chauffage, le CAD, le gaz et la PAC réagissent alors à la vraie météo.

Dérives injectées (mêmes cas que la maquette), datées par rapport à la fin de la période :
  - T8  eau      : fuite continue +95 l/h depuis 5 nuits
  - T8  PAC      : rendement qui chute de 3,4 à ~2,6 sur 24 jours
  - R41 chaleur  : immeuble Vide, chauffage repassé en marche normale depuis 9 jours
  - R41 ECS      : données lacunaires puis compteur muet depuis 3 jours
  - OA  élec     : +1,1 kW la nuit (22 h – 6 h) depuis 14 nuits
  - OB  chaleur  : +14 % à température égale depuis 12 jours
  - T8  solaire  : une chaîne de modules sur quatre hors service depuis 14 jours (−25 %, panne) ; OA solaire sain
Rayonnement global : réel (MétéoSuisse GVE, gre000h0) avec la météo réelle, sinon fictif ; tirage aléatoire propre au
soleil, pour que les autres séries restent identiques.
Grand exemple (config/exemple_grand.json) : immeubles PAC (G01-G16) et immeubles au chauffage à distance ou au gaz
(G17-G20) ; dérives G02 PAC, G05 fuite, G08 électricité de nuit, G18 CAD et G20 gaz (signature +18 % depuis 12 jours),
et solaire : G06 panne (−25 %), G03 encrassement progressif, G14 onduleur à l'arrêt.
"""
import csv
import math
import random
from datetime import datetime, timedelta

FIN = datetime(2026, 11, 11, 6, 0)   # fin de la série fictive (UTC)
JOURS = 365                          # 12 mois d'historique : la référence « même saison l'an passé » joue
PCS_GAZ = 10.5                       # kWh par m³ (valeur d'EXEMPLE du référentiel, gaz_pcs_kwh_par_m3)
RENDEMENT_CHAUDIERE = 0.92           # gaz consommé = chaleur ÷ rendement (simulation)


def temperature_fictive(t, debut):
    """Température FICTIVE (hors ligne) : cycle annuel (2 à 19 °C en moyenne journalière, minimum mi-janvier), cycle
    journalier ±4 °C (maximum à 15 h UTC) et variation lente ±2,5 °C. Même loi que evaluation/simulateur.py."""
    d = (t - debut).total_seconds() / 86400
    saison = 10.5 - 8.5 * math.cos(2 * math.pi * (t.timetuple().tm_yday - 20) / 365.25)
    jour = 4 * math.sin((t.hour - 9) / 24 * 2 * math.pi)
    lente = 2.5 * math.sin(d / 6.0)
    return saison + jour + lente


def fin_reelle(temperatures):
    """Dernier 06:00 UTC couvert par la série réelle : la fin de période garde le même calage que la série fictive."""
    derniere = max(temperatures)
    fin = derniere.replace(hour=6, minute=0, second=0, microsecond=0)
    return fin if derniere >= fin else fin - timedelta(days=1)


COMPTAGES_PAC = {"totale": "T8_PAC_CHAL", "chauffage": "T8_PAC_CHAUF", "ecs": "T8_PAC_ECS", "aucune": None}

# ---------------------------------------------------------------- soleil (rayonnement et production photovoltaïque)
LATITUDE, LONGITUDE = 46.25, 6.13  # Genève-Cointrin


def cos_zenith(t):
    """Cosinus de l'angle zénithal du soleil à Genève à l'instant t (UTC naïf ; équation du temps négligée)."""
    j = t.timetuple().tm_yday
    decl = math.radians(23.45) * math.sin(2 * math.pi * (284 + j) / 365)
    heure_solaire = t.hour + t.minute / 60 + LONGITUDE / 15
    omega = math.radians(15 * (heure_solaire - 12))
    phi = math.radians(LATITUDE)
    return math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(omega)


def rayonnement_fictif(heures, rnd):
    """Rayonnement global FICTIF (W/m², moyenne de l'heure qui se termine à t) : ciel clair (modèle de Haurwitz) ×
    nébulosité tirée par jour (45 % de jours clairs, 30 % de passages nuageux, 25 % de jours couverts)."""
    out, jour, k = {}, None, 1.0
    for t in heures:
        milieu = t - timedelta(minutes=30)
        if milieu.date() != jour:
            jour, u = milieu.date(), rnd.random()
            k = rnd.uniform(0.75, 1.0) if u < 0.45 else rnd.uniform(0.4, 0.75) if u < 0.75 else rnd.uniform(0.08, 0.35)
        cz = cos_zenith(milieu)
        clair = 1098 * cz * math.exp(-0.057 / cz) if cz > 0.01 else 0.0
        out[t] = round(clair * k * rnd.uniform(0.9, 1.1), 1)
    return out


def production_solaire(pid, spec_pv, ajoute, heures, ray, temp, jours_avant_fin, rnd, derive=None):
    """Production horaire d'une installation photovoltaïque (kWh, fin d'intervalle) à partir du rayonnement global.

    Modules inclinés (gain d'inclinaison plus fort en hiver), rendement 86 %, pertes de température (−0,4 %/°C de
    cellule au-dessus de 25 °C), décote annuelle des modules depuis la mise en service, onduleur limité à 90 % de la
    puissance crête. Dérives : « panne » = une chaîne de modules sur quatre hors service depuis 14 jours (−25 %) ;
    « arret » = onduleur à l'arrêt depuis 6 jours ; « degradation » = encrassement progressif (jusqu'à −22 % sur 35 jours).
    """
    kwc, annee = spec_pv["puissance_crete_kwc"], spec_pv["mise_en_service"]
    decote = spec_pv.get("degradation_pct_an", 0.5) / 100
    for t in heures:
        g = ray.get(t, 0.0)
        j = t.timetuple().tm_yday
        inclinaison = 0.88 + 0.12 * math.cos(2 * math.pi * (j - 355) / 365)
        age = max(0.0, t.year + (j - 1) / 365.25 - (annee + 0.5))
        cellule = temp[t] + g / 800 * 25
        p = kwc * g / 1000 * 0.86 * inclinaison * (1 - 0.004 * (cellule - 25)) * (1 - decote) ** age
        p = min(p, 0.9 * kwc) * rnd.uniform(0.97, 1.03)
        d = jours_avant_fin(t)
        if derive == "panne" and d <= 14:
            p *= 0.75
        elif derive == "arret" and d <= 6:
            p = 0.0
        elif derive == "degradation" and d <= 35:
            p *= 1 - 0.22 * (35 - d) / 35
        elif derive == "coupures" and t.hour == 12 and int(d) in (1, 3):
            p = 0.0  # onduleur qui décroche une heure en plein jour, deux jours de la dernière semaine
        ajoute(t, pid, max(0.0, p))


def _releve_horaire(ajoute, pid):
    """Compteur relevé à l'heure : cumule les quarts d'heure simulés et écrit la consommation à l'heure pleine."""
    cumul = [0.0]

    def quart(t, v):
        cumul[0] += v
        if t.minute == 0:
            ajoute(t, pid, cumul[0])
            cumul[0] = 0.0
    return quart


def _elec_eau(spec, ajoute, quarts, jours_avant_fin, rnd):
    """Électricité générale et eau froide d'un immeuble du grand exemple (relevés horaires)."""
    gid, logements = spec["id"], spec["logements"]
    occ = spec.get("taux_occupation") or 1.0
    travaux = spec["profil"] == "Travaux"
    derive = spec.get("simulation", {}).get("derive")
    nuit = lambda t: t.hour >= 22 or t.hour < 6  # noqa: E731

    # Électricité générale (simulée par 15 min, relevée à l'heure) ; G08 : +30 % la nuit depuis 14 nuits
    base_kw, jour_kw = 0.10 * logements * occ, 0.30 * logements * occ * (0.4 if travaux else 1.0)
    heure = _releve_horaire(ajoute, f"{gid}_ELEC")
    for t in quarts:
        hh = t.hour + t.minute / 60
        presence = max(0.0, math.sin((hh - 6) / 17 * math.pi)) if 6 <= hh <= 23 else 0.0
        if travaux:  # chantier : journée ouvrée seulement
            presence = 1.0 if 7 <= hh < 17 else 0.0
        p = base_kw + jour_kw * presence
        if derive == "elec_nuit" and jours_avant_fin(t) <= 14 and nuit(t):
            p += 0.3 * base_kw
        heure(t, p * 0.25 * rnd.uniform(0.93, 1.07))

    # Eau froide (index lu à l'heure pleine, écoulement simulé par 15 min) ; G05 : fuite continue +60 l/h depuis 5 nuits
    index = 2000.0 + rnd.uniform(0, 800)
    for t in quarts:
        hh = t.hour + t.minute / 60
        profil = 0.02 + 1.2 * math.exp(-((hh - 7.5) ** 2) / 2) + 1.0 * math.exp(-((hh - 19.5) ** 2) / 3) + 0.4
        if 1 <= hh < 5:
            profil = 0.0
        l_h = logements * 12.5 * profil * occ * (0.15 if travaux else 1.0) * rnd.uniform(0.85, 1.15)
        if 1 <= hh < 5 and rnd.random() < 0.15:
            l_h = rnd.uniform(0, 40)
        if derive == "fuite" and jours_avant_fin(t) <= 4 + 8 / 24:
            l_h += 60.0
        index += l_h / 4 / 1000
        if t.minute == 0:
            ajoute(t, f"{gid}_EAU", index)


def _immeuble_chaudiere(spec, ajoute, heures, quarts, temp, jours_avant_fin, graine):
    """Immeuble chauffé par le chauffage à distance (chaleur livrée, kWh) ou par une chaudière à gaz (index en m³).

    Chaleur = chauffage selon la météo (abaissement nocturne) + eau chaude ; gaz = chaleur ÷ rendement ÷ PCS. Dérive
    « signature » : +18 % de chaleur à météo égale depuis 12 jours (courbe de chauffe déréglée).
    """
    rnd = random.Random(graine)
    gid, logements = spec["id"], spec["logements"]
    sim = spec.get("simulation", {})
    k, ecs = logements * 0.22, logements * 0.12
    index = 5000.0 + rnd.uniform(0, 2000)
    for t in heures:
        reduit = 0.8 if (t.hour >= 22 or t.hour < 5) else 1.0
        f = rnd.uniform(0.95, 1.05) * (1.18 if sim.get("derive") == "signature" and jours_avant_fin(t) <= 12 else 1.0)
        q = (k * max(0.0, 16 - temp[t]) * reduit + ecs) * f
        if sim["chauffage"] == "cad":
            ajoute(t, f"{gid}_CAD", q)
        else:
            index += q / RENDEMENT_CHAUDIERE / PCS_GAZ
            ajoute(t, f"{gid}_GAZ", index)
    _elec_eau(spec, ajoute, quarts, jours_avant_fin, rnd)


def _immeuble_pac(spec, ajoute, heures, quarts, temp, jours_avant_fin, graine):
    """Immeuble chauffé par PAC : électricité générale, PAC (électricité + chaleur selon le comptage), eau froide.

    `spec` = entrée de config/exemple_grand.json (logements, profil, taux d'occupation, comptage PAC, dérive).
    """
    rnd = random.Random(graine)
    gid, logements = spec["id"], spec["logements"]
    occ = spec.get("taux_occupation") or 1.0
    travaux = spec["profil"] == "Travaux"
    sim = spec.get("simulation", {})
    derive, comptage = sim.get("derive"), sim.get("pac_mesure", "totale")

    # PAC (horaire) : chauffage selon la météo + eau chaude ; rendement plus faible pour l'eau chaude
    k, ecs = logements * 0.22 * (0.6 + 0.4 * occ), logements * 0.12 * occ * (0.15 if travaux else 1.0)
    points_chaleur = {"totale": f"{gid}_PAC_CHAL", "chauffage": f"{gid}_PAC_CHAUF", "ecs": f"{gid}_PAC_ECS"}
    for t in heures:
        text = temp[t]
        reduit = 0.8 if (t.hour >= 22 or t.hour < 5) else 1.0
        f = rnd.uniform(0.95, 1.05)
        q_ch, q_ecs = k * max(0.0, 16 - text) * reduit * f, ecs * f
        valeurs = {"totale": q_ch + q_ecs, "chauffage": q_ch, "ecs": q_ecs}
        if comptage in points_chaleur:
            ajoute(t, points_chaleur[comptage], valeurs[comptage])
        j = jours_avant_fin(t)
        deg = 1.0 - (1 - 2.6 / 3.4) * (24 - j) / 24 if (derive == "pac" and j <= 24) else 1.0
        e = q_ch / ((3.4 + 0.04 * (text - 5)) * deg) + q_ecs / ((2.6 + 0.03 * (text - 5)) * deg)
        ajoute(t, f"{gid}_PAC_ELEC", sum(e / 4 * rnd.uniform(0.97, 1.03) for _ in range(4)))  # relevé horaire
    _elec_eau(spec, ajoute, quarts, jours_avant_fin, rnd)


def generer(chemin, graine=42, temperatures=None, point_meteo="METEO_TEXT", sans=(), pac_mesure="totale",
            supplementaires=None, rayonnement=None, point_rayonnement="RAYON_FICTIF"):
    """`temperatures` = {datetime UTC naïf (fin d'heure): °C} réelles ; None = température fictive.

    `sans` = dérives à ne pas injecter (ex. {"pac"}, {"solaire"}) : sert à vérifier l'absence de fausse alerte.
    `pac_mesure` = chaleur PAC comptée : "totale", "chauffage", "ecs" ou "aucune" (l'électricité l'est toujours).
    `supplementaires` = immeubles du grand exemple (config/exemple_grand.json), simulés en plus des 5 de base.
    `rayonnement` = {datetime UTC naïf : W/m²} réel ; None = rayonnement fictif (point `point_rayonnement`).
    """
    lignes = _generer(graine, temperatures, point_meteo, sans, pac_mesure, supplementaires, rayonnement,
                      point_rayonnement)
    lignes.sort()
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "point_id", "valeur"])
        w.writerows(lignes)
    return len(lignes)


# Installations solaires du petit exemple (mêmes valeurs que config/referentiel.json) : T8 perd une chaîne de modules
PV_STANDARD = {"T8_PV": ({"puissance_crete_kwc": 30.0, "mise_en_service": 2019, "degradation_pct_an": 0.5}, "panne"),
               "OA_PV": ({"puissance_crete_kwc": 45.0, "mise_en_service": 2016, "degradation_pct_an": 0.5}, None)}


def _soleil(ajoute, heures, temp, jours_avant_fin, graine, sans, supplementaires, rayonnement, point_rayonnement):
    """Rayonnement (réel ou fictif) et production des installations solaires (tirage aléatoire propre au soleil : les
    autres séries de l'exemple restent identiques à celles d'avant l'ajout du solaire)."""
    rnd = random.Random(f"{graine}-soleil")
    if rayonnement:
        ray = {t: rayonnement[t] for t in heures if t in rayonnement}  # heures réellement mesurées (jamais comblées)
    else:
        ray = rayonnement_fictif(heures, rnd)
    for t, v in ray.items():
        ajoute(t, point_rayonnement, v)
    installations = [(pid, spec, derive) for pid, (spec, derive) in PV_STANDARD.items()]
    for im in supplementaires or ():
        for p in im["points"]:
            if p["fluide"] == "solaire":
                installations.append((p["id"], p, im.get("simulation", {}).get("solaire")))
    for pid, spec, derive in installations:
        production_solaire(pid, spec, ajoute, heures, ray, temp, jours_avant_fin, random.Random(f"{graine}-{pid}"),
                           None if "solaire" in sans else derive)


def _generer(graine, temperatures, point_meteo, sans, pac_mesure, supplementaires, rayonnement, point_rayonnement):
    rnd = random.Random(graine)
    fin = fin_reelle(temperatures) if temperatures else FIN
    debut = fin - timedelta(days=JOURS)
    lignes = []
    heures = [debut + timedelta(hours=h) for h in range(1, JOURS * 24 + 1)]
    quarts = [debut + timedelta(minutes=15 * q) for q in range(1, JOURS * 96 + 1)]

    if temperatures:
        # Mesures météo : uniquement les heures réellement mesurées (jamais comblées, règle 4)
        reelles = {t: temperatures[t] for t in heures if t in temperatures}
        if len(reelles) < 0.9 * len(heures):
            raise ValueError("Série météo réelle trop lacunaire pour simuler 12 mois.")
        # Entrée de la SIMULATION des consommations seulement : une heure manquante reprend la précédente
        temp, derniere = {}, next(iter(reelles.values()))
        for t in heures:
            derniere = reelles.get(t, derniere)
            temp[t] = derniere
    else:
        temp = {t: temperature_fictive(t, debut) + rnd.gauss(0, 0.6) for t in heures}
        reelles = temp

    def ajoute(t, pid, v):
        lignes.append((t.strftime("%Y-%m-%dT%H:%M:%SZ"), pid, round(v, 4)))

    for t, v in reelles.items():
        ajoute(t, point_meteo, v)

    def jours_avant_fin(t):
        return (fin - t).total_seconds() / 86400

    # ---------- Chaleur (horaire) ----------
    def chaleur(pid, logements, facteur=lambda t: 1.0, pac=None):
        k = logements * 0.22
        for t in heures:
            text = temp[t]
            reduit = 0.8 if (t.hour >= 22 or t.hour < 5) else 1.0
            ecs = logements * 0.12
            f = facteur(t) * rnd.uniform(0.95, 1.05)
            q_chauffage, q_ecs = k * max(0.0, 16 - text) * reduit * f, ecs * f
            ajoute(t, pid, q_chauffage + q_ecs)
            if pac:
                pac_ch, pac_ecs = 0.6 * q_chauffage, 0.6 * q_ecs
                for nom, valeur in (("totale", pac_ch + pac_ecs), ("chauffage", pac_ch), ("ecs", pac_ecs)):
                    if pac_mesure == nom:
                        ajoute(t, COMPTAGES_PAC[nom], valeur)
                # Rendement plus faible pour l'eau chaude (température de sortie plus élevée)
                cop_ch = (3.4 + 0.04 * (text - 5)) * pac[1](t)
                cop_ecs = (2.6 + 0.03 * (text - 5)) * pac[1](t)
                e = pac_ch / cop_ch + pac_ecs / cop_ecs
                ajoute(t, pac[2], sum(e / 4 * rnd.uniform(0.97, 1.03) for _ in range(4)))  # relevé horaire

    def cop_degrade(t):
        j = jours_avant_fin(t)
        if j > 24 or "pac" in sans:
            return 1.0
        return 1.0 - (1 - 2.6 / 3.4) * (24 - j) / 24

    chaleur("T8_CHAL", 24, pac=(None, cop_degrade, "T8_PAC_ELEC"))

    def r41(t):
        j = jours_avant_fin(t)
        if j > 30:
            return 1.0
        if j > 9:
            return 0.12  # hors-gel
        return 1.0      # chaufferie repassée en mode normal : défaut

    chaleur("R41_CHAL", 20, r41)
    chaleur("OA_CHAL", 36)
    chaleur("OB_CHAL", 30, lambda t: 1.14 if jours_avant_fin(t) <= 12 else 1.0)
    chaleur("VG_CHAL", 28, lambda t: 0.75)

    # ---------- Électricité (simulée par 15 min, relevée à l'heure) ----------
    def elec(pid, base_kw, jour_kw, extra=lambda t: 0.0, facteur=1.0):
        heure = _releve_horaire(ajoute, pid)
        for t in quarts:
            h = t.hour + t.minute / 60
            occ = max(0.0, math.sin((h - 6) / 17 * math.pi)) if 6 <= h <= 23 else 0.0
            p = (base_kw + jour_kw * occ) * facteur + extra(t)
            heure(t, p * 0.25 * rnd.uniform(0.93, 1.07))

    elec("T8_ELEC", 3.0, 9.0)
    elec("R41_ELEC", 1.2, 0.0)
    nuit_oa = lambda t: 1.1 if (jours_avant_fin(t) <= 14 and (t.hour >= 22 or t.hour < 6)) else 0.0
    elec("OA_ELEC", 3.5, 12.0, nuit_oa)
    elec("OB_ELEC", 3.2, 10.0)
    elec("VG_ELEC", 2.5, 8.0, facteur=0.6)

    # ---------- Eau froide (index m3 lu à l'heure pleine, écoulement simulé par 15 min) ----------
    def eau(pid, logements, fuite=lambda t: 0.0, facteur=1.0):
        index = 1000.0 + rnd.uniform(0, 500)
        for t in quarts:
            h = t.hour + t.minute / 60
            profil = 0.02 + 1.2 * math.exp(-((h - 7.5) ** 2) / 2) + 1.0 * math.exp(-((h - 19.5) ** 2) / 3) + 0.4
            if 1 <= h < 5:
                profil = 0.0
            l_h = logements * 12.5 * profil * facteur * rnd.uniform(0.85, 1.15)
            if 1 <= h < 5 and rnd.random() < 0.15:
                l_h = rnd.uniform(0, 40)  # une chasse d'eau occasionnelle
            l_h += fuite(t)
            index += l_h / 4 / 1000
            if t.minute == 0:
                ajoute(t, pid, index)

    eau("T8_EAU", 24, lambda t: 95.0 if fin - t <= timedelta(days=4, hours=8) else 0.0)
    eau("R41_EAU", 20, facteur=0.0)
    eau("OA_EAU", 36)
    eau("OB_EAU", 30)
    eau("VG_EAU", 28, facteur=0.4)

    # ---------- ECS R41 : lacunes puis silence ----------
    for t in heures:
        j = jours_avant_fin(t)
        if j <= 3:
            continue
        if j <= 30 and rnd.random() < 0.21:
            continue
        ajoute(t, "R41_ECS", 0.01 * rnd.uniform(0.5, 1.5))

    # ---------- Grand exemple : immeubles chauffés par PAC (tirage aléatoire propre à chacun) ----------
    for spec in supplementaires or ():
        fn = _immeuble_chaudiere if spec.get("simulation", {}).get("chauffage") in ("cad", "gaz") else _immeuble_pac
        fn(spec, ajoute, heures, quarts, temp, jours_avant_fin, f"{graine}-{spec['id']}")

    # ---------- Soleil : rayonnement global et production photovoltaïque ----------
    _soleil(ajoute, heures, temp, jours_avant_fin, graine, sans, supplementaires, rayonnement, point_rayonnement)
    return lignes
