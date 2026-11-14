"""Détecteurs complémentaires (V0.3) : eau au pas journalier, retour du chauffage à distance, injection solaire.

Tous les chiffres sont calculés ici (règle 5). Comme les autres règles : référence apprise AVANT la fenêtre d'analyse
(ou avant le début d'une dérive déjà en alerte), persistance obligatoire, aucune heure ni aucun jour comblé.

- `eau_talon`  Eau relevée au jour : le NIVEAU DE BASE (minimum glissant de 7 jours, qui contient toujours un week-end)
               dépasse nettement celui de la référence. Une fuite coule tous les jours : elle relève ce minimum, alors
               qu'un pic d'usage (remplissage d'un bassin, manifestation) ne le change pas. Au pas horaire, la règle
               `eau_nuit` reste la référence ; celle-ci ne tourne que sur les compteurs journaliers.
- `cad_retour` Sous-station de chauffage à distance : la température de RETOUR dépasse l'attendu à température
               extérieure égale (régression sur la référence). Signe d'une vanne ou d'un débit mal réglés : même énergie,
               plus de débit, écart aller-retour qui s'effondre. Dérive non chiffrée en kWh.
- `donnees_injection`  Défaut de données : l'injection au réseau reste nulle des jours entiers alors que l'installation
               solaire produit plus que tous les jours sans injection de la référence.
"""
import numpy as np
import pandas as pd

EAU_FENETRE_J = 7            # minimum glissant sur 7 jours : contient toujours un week-end
EAU_SEUIL_L_J = 480.0        # hausse minimale du niveau de base : 20 l/h en continu, comme la règle eau_nuit
EAU_REF_JOURS_MIN = 30
CAD_REF_JOURS_MIN = 30
CAD_JOUR_HEURES_MIN = 18
INJECTION_REF_JOURS_MIN = 20
INJECTION_MARGE = 1.5        # production au-delà de 1,5 × la plus forte journée sans injection de la référence

TEXTES = {
    "eau_talon": dict(fluide="Eau froide", gravite="Élevée", sinistre=True,
        titre="Eau : consommation de base en hausse (fuite probable)",
        constat="Depuis {persistance} {unite}, l'immeuble consomme au moins {mesure}, même les jours creux, alors que "
                "son niveau de base était de {attendu}.",
        consigne="Rechercher un écoulement permanent : chasses d'eau, robinets de purge, arrosage, adoucisseur, soupape "
                 "du chauffe-eau, conduite enterrée. Relever le compteur à la fermeture pour confirmer.",
        prestataire="Concierge, puis entreprise sanitaire", delai="48 h", payeur="Charges (eau)"),
    "cad_retour": dict(fluide="Chauffage à distance (CAD)", gravite="Modérée", sinistre=False, non_chiffre=True,
        titre="CAD : retour trop chaud à la sous-station",
        constat="Depuis {persistance} {unite}, l'eau repart au réseau à {mesure} alors que l'attendu est {attendu}. "
                "{detail}",
        consigne="Contrôler la vanne de régulation de la sous-station (bloquée ouverte, moteur débrayé), un by-pass "
                 "ouvert, la vitesse des pompes et l'équilibrage du circuit secondaire. Un retour trop chaud dégrade "
                 "le réseau et peut être pénalisé par le fournisseur de chaleur.",
        prestataire="Chauffagiste, puis fournisseur CAD si besoin", delai="2 semaines",
        payeur="Propriétaire (contrat de chauffage à distance)"),
}
REGLES = {
    "eau_talon": dict(libelle="Eau au jour : niveau de base en hausse", fluide_point="eau", active=True,
        profils=["Habite", "Partiel", "Travaux"], seuil=100.0, unite_seuil="% au-dessus du niveau de base de référence",
        seuil_min=10, seuil_max=500,
        aide_seuil="Hausse tolérée du minimum de consommation sur 7 jours (et au moins 480 l/jour, soit 20 l/h en "
                   "continu). Règle des compteurs relevés au jour ; à l'heure, c'est la fuite de nuit qui s'applique.",
        persistance=3, unite_persistance="jours", metier="Sanitaire"),
    "cad_retour": dict(libelle="CAD : retour trop chaud à la sous-station", fluide_point="cad_temperature_retour",
        active=True, profils=["Habite", "Partiel", "Vide"], seuil=5.0, unite_seuil="°C au-dessus de l'attendu",
        seuil_min=1, seuil_max=30,
        aide_seuil="Écart toléré entre la température de retour mesurée et l'attendu à température extérieure égale.",
        persistance=7, unite_persistance="jours", metier="Chauffagiste"),
}
TEXTE_INJECTION = "Injection nulle malgré la production solaire"


def _consecutifs(cond):
    n = 0
    for v in reversed(list(cond)):
        if not v:
            break
        n += 1
    return n


def fr(x, decimales=1):
    return f"{x:.{decimales}f}".replace(".", ",")


def det_eau_talon(s_m3, fin, P, seuil_pct=100.0, persistance=3, journalier=True, ref_avant=None):
    """Niveau de base de l'eau (minimum glissant de 7 jours, en litres par jour) comparé à celui de la référence."""
    from .moteur import jours_mesures, limite_reference
    d, _nh = jours_mesures(s_m3 * 1000, fin, journalier)
    talon = d.rolling(EAU_FENETRE_J).min().dropna()
    ref = talon[talon.index < limite_reference(fin, P, ref_avant)]
    if len(ref) < EAU_REF_JOURS_MIN:
        return None
    base = float(ref.median())
    limite_haute = max(base * (1 + seuil_pct / 100), base + EAU_SEUIL_L_J)
    n = _consecutifs(talon > limite_haute)
    if n < persistance:
        return None
    der = talon.iloc[-n:]
    # Début au plus tôt : premier jour de la première fenêtre de 7 jours entièrement au-dessus du niveau de base
    debut = der.index[0] - pd.Timedelta(days=EAU_FENETRE_J - 1)
    exces_l_j = float(der.mean() - base)
    jours = int((d.index >= debut).sum())
    return {"persistance": n, "unite": "jours", "debut": str(debut.date()),
            "mesure": f"{der.mean():.0f} l/jour", "attendu": f"{base:.0f} l/jour",
            "m3_j": exces_l_j / 1000, "force": min(1.0, exces_l_j / max(base, EAU_SEUIL_L_J)),
            "m3_mesure": exces_l_j * jours / 1000, "heures_mesurees": jours * 24}


def det_cad_retour(t_aller_h, t_retour_h, text_h, fin, P, seuil_k=5.0, persistance=7, ref_avant=None):
    """Température de retour journalière comparée à l'attendu à température extérieure égale."""
    from .moteur import limite_reference
    h = pd.DataFrame({"ta": t_aller_h, "tr": t_retour_h, "t": text_h}).dropna()
    if h.empty:
        return None
    j = h.resample("D").mean()
    complets = h["tr"].resample("D").count() >= CAD_JOUR_HEURES_MIN
    j = j[complets & (j.index < fin.normalize())].dropna()
    ref = j[j.index < limite_reference(fin, P, ref_avant)]
    if len(ref) < CAD_REF_JOURS_MIN or len(j) == len(ref):
        return None
    (a, b), *_ = np.linalg.lstsq(np.c_[np.ones(len(ref)), ref["t"]], ref["tr"].to_numpy(), rcond=None)
    attendu = a + b * j["t"]
    n = _consecutifs((j["tr"] - attendu) > seuil_k)
    if n < persistance:
        return None
    der, att = j.iloc[-n:], attendu.iloc[-n:]
    ecart_ref = float((ref["ta"] - ref["tr"]).median())
    ecart = float((der["ta"] - der["tr"]).mean())
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
            "mesure": f"{fr(der['tr'].mean())} °C", "attendu": f"{fr(att.mean())} °C à température extérieure égale",
            "detail": f"L'écart entre l'aller et le retour n'est plus que de {fr(ecart)} °C (référence : {fr(ecart_ref)} °C).",
            "force": min(1.0, float((der["tr"] - att).mean()) / 15), "heures_mesurees": n * 24}


def det_injection_nulle(s_pv_h, s_inj_h, fin, P, persistance=3):
    """Constat (texte) si l'injection reste nulle alors que la production dépasse celle de tous les jours sans
    injection de la référence ; None sinon."""
    from .moteur import JOUR_HEURES_MIN, limite_reference
    h = pd.DataFrame({"pv": s_pv_h, "inj": s_inj_h}).dropna()
    if h.empty:
        return None
    j = h.resample("D").sum()
    j = j[(h["pv"].resample("D").count() >= JOUR_HEURES_MIN) & (j.index < fin.normalize())]
    ref = j[j.index < limite_reference(fin, P)]
    avec = ref[ref["inj"] > 0]
    if len(avec) < INJECTION_REF_JOURS_MIN:
        return None
    sans = ref[ref["inj"] <= 0]
    seuil_pv = INJECTION_MARGE * (float(sans["pv"].max()) if len(sans) else 0.0)
    n = _consecutifs((j["inj"] <= 0) & (j["pv"] > max(seuil_pv, 1.0)))
    if n < persistance:
        return None
    der = j.iloc[-n:]
    part = float(avec["inj"].sum() / avec["pv"].sum())
    return (f"L'injection au réseau est nulle depuis {n} jours (depuis le {der.index[0].strftime('%d.%m.%Y')}) alors que "
            f"l'installation produit {der['pv'].mean():.0f} kWh par jour. Avant, une telle production donnait toujours "
            f"une injection ({part * 100:.0f} % de la production en moyenne) : comptage d'injection à contrôler.")


# ---------------------------------------------------------------- compteurs relevés AU JOUR : électricité, PAC
# À l'heure, l'électricité est jugée la nuit (elec_nuit) et la PAC heure par heure (pac_cop). Au jour, ces deux méthodes
# sont impossibles : l'électricité est comparée aux jours de MÊME TYPE (ouvré, vacances, non ouvré) des semaines de
# référence, et l'électricité de la PAC à sa signature météo journalière (comme le gaz ou la chaleur).
ELEC_REF_JOURS = 56          # 8 semaines de référence avant la fenêtre d'analyse (ou avant le début de la dérive)
ELEC_TYPE_JOURS_MIN = 4      # jours de même type exigés dans la référence, sinon le jour n'est pas jugé

TEXTES.update({
    "elec_jour": dict(fluide="Électricité", gravite="Modérée", sinistre=False,
        titre="Électricité : consommation journalière en hausse",
        constat="Depuis {persistance} {unite}, l'immeuble consomme {mesure} d'électricité par jour par rapport aux jours "
                "de même type (ouvré ou non) des semaines de référence. {detail}",
        consigne="Vérifier la ventilation, l'éclairage et ses minuteries, les équipements laissés en marche et tout "
                 "nouvel équipement. Un relevé à l'heure permettrait de séparer la nuit du jour.",
        prestataire="Concierge", delai="2 semaines", payeur="Charges (électricité des communs)"),
    "pac_signature": dict(fluide="Pompe à chaleur", gravite="Élevée", sinistre=False,
        titre="PAC : électricité trop forte pour la météo",
        constat="Depuis {persistance} {unite}, la pompe à chaleur consomme {mesure} d'électricité par rapport à "
                "l'attendu, à température extérieure comparable.",
        consigne="Contrôler la charge de fluide frigorigène, le dégivrage, l'encrassement de l'évaporateur, l'appoint "
                 "électrique et les consignes de départ et d'eau chaude.",
        prestataire="Frigoriste", delai="1 semaine", payeur="Charges locataires (décompte de chauffage)"),
})
REGLES.update({
    "elec_jour": dict(libelle="Électricité au jour : consommation en hausse", fluide_point="electricite", active=True,
        profils=["Habite", "Partiel"], seuil=20.0, unite_seuil="% au-dessus des jours de même type", seuil_min=5,
        seuil_max=300,
        aide_seuil="Hausse tolérée de la consommation d'un jour par rapport à la médiane des jours de même type (ouvré, "
                   "vacances, non ouvré) des 8 semaines de référence. Règle des compteurs relevés au jour ; à l'heure, "
                   "c'est l'électricité de nuit qui s'applique.",
        persistance=5, unite_persistance="jours", metier="Concierge"),
    "pac_signature": dict(libelle="PAC au jour : électricité trop forte pour la météo", fluide_point="pac_electricite",
        active=True, profils=["Habite", "Partiel", "Vide"], seuil=15.0, unite_seuil="% au-dessus de l'attendu",
        seuil_min=3, seuil_max=100,
        aide_seuil="Écart toléré entre l'électricité de la PAC et l'attendu à température extérieure égale. Règle des "
                   "compteurs relevés au jour ; à l'heure, c'est le rendement heure par heure qui s'applique.",
        persistance=7, unite_persistance="jours", metier="Frigoriste"),
})


def det_elec_jour(s_kwh_j, fin, P, seuil_pct=20.0, persistance=5, ref_avant=None, calendrier_lot=None):
    """Électricité relevée au jour : chaque jour comparé à la médiane des jours de même type de la référence."""
    from . import calendrier
    from .moteur import jours_mesures, limite_reference
    d, _heures = jours_mesures(s_kwh_j, fin, True)
    limite = limite_reference(fin, P, ref_avant)
    ref = d[(d.index < limite) & (d.index >= limite - pd.Timedelta(days=ELEC_REF_JOURS))]
    if len(ref) < 3 * ELEC_TYPE_JOURS_MIN:
        return None
    types, types_ref = calendrier.classes(d.index, calendrier_lot), calendrier.classes(ref.index, calendrier_lot)
    attendu = pd.Series(np.nan, index=d.index)
    for t in set(types):
        choisi = next((m for m in calendrier.comparables(types_ref, t) if int(m.sum()) >= ELEC_TYPE_JOURS_MIN), None)
        if choisi is not None:
            attendu[types == t] = float(ref[choisi].median())
    juges = d[(attendu > 0).to_numpy()]  # un type de jour absent de la référence n'est pas jugé
    att = attendu[juges.index]
    n = _consecutifs(juges > att * (1 + seuil_pct / 100))
    if n < persistance:
        return None
    der, a = juges.iloc[-n:], att.iloc[-n:]
    relatif = float(der.sum() / a.sum() - 1)
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()), "mesure": f"{relatif * 100:+.0f} %",
            "attendu": f"{a.mean():.0f} kWh/jour un jour de même type",
            "detail": f"{der.mean():.0f} kWh par jour en moyenne au lieu de {a.mean():.0f} kWh.",
            "kwh_j": max(0.0, float((der - a).mean())), "force": min(1.0, relatif * 2),
            "kwh_mesure": max(0.0, float((der - a).sum())), "heures_mesurees": n * 24}


def regles_au_jour(ids, journ, horaires, text_h, fin, P, R, actif, gel, valide):
    """Candidats (cause, compteur, résultat) des fluides relevés AU JOUR seulement, sans série horaire."""
    from .moteur import det_chaleur_signature
    au_jour = lambda f: valide(f) and ids[f] not in horaires and ids[f] in journ  # noqa: E731
    out = []
    if au_jour("electricite") and actif("elec_jour"):
        r = R["elec_jour"]
        out.append(("elec_jour", ids["electricite"], det_elec_jour(
            journ[ids["electricite"]], fin, P, r["seuil"], r["persistance"], gel("elec_jour"), P.get("calendrier"))))
    if au_jour("pac_electricite") and actif("pac_signature") and text_h is not None:
        r = R["pac_signature"]
        out.append(("pac_signature", ids["pac_electricite"], det_chaleur_signature(
            journ[ids["pac_electricite"]], text_h, fin, P, 1 + r["seuil"] / 100, r["persistance"], gel("pac_signature"),
            True)))
    return out


# ---------------------------------------------------------------- électricité de nuit à température extérieure égale
# La règle de nuit compare les nuits aux nuits de 20 à 50 jours plus tôt. Mesuré sur 48 courbes au quart d'heure : dans
# un bâtiment dont l'électricité monte avec le froid (PAC, chauffage électrique), elle sonnait chaque début d'hiver
# (14 fausses alertes en décembre). Pour ces sites, la nuit est donc comparée aux nuits de MÊME FROID de la référence.
NUIT_SENSIBLE_R = 0.5      # corrélation minimale entre puissance de nuit et froid de la nuit pour parler de site sensible
NUIT_REF_MIN = 30          # nuits de référence exigées pour en juger
NUIT_DJ_ETENDUE_MIN = 4.0  # et au moins 4 degrés d'écart entre la nuit la plus douce et la plus froide


def elec_nuit_meteo(nuits, heures_larges, text_h, fin, P, seuil, persistance, ref_avant):
    """(site sensible au froid ?, résultat). Site non sensible : (False, None), la règle habituelle s'applique.

    `nuits` : puissance moyenne de chaque nuit (1 h – 5 h) ; `heures_larges` : heures de 22 h à 6 h (chiffrage)."""
    from .chiffrage import heures_depuis
    from .moteur import (COTES_MIN, DJ_COMPARABLE, JOURS_COMPARABLES_MIN, JUGE_RECENT_MAX_J, _attendu_comparable,
                         limite_reference, serie_consecutive_fin)
    h1, h2 = P["heures_nuit"]
    froid = text_h[(text_h.index.hour > h1) & (text_h.index.hour <= h2)]
    dj = (16.0 - froid.groupby(froid.index.date).mean()).clip(lower=0)
    d = pd.DataFrame({"p": nuits, "dj": dj}).dropna()
    d.index = pd.to_datetime(d.index)
    ref = d[d.index < limite_reference(fin, P, ref_avant)]
    if len(ref) < NUIT_REF_MIN or ref["dj"].max() - ref["dj"].min() < NUIT_DJ_ETENDUE_MIN             or not ref["p"].corr(ref["dj"]) >= NUIT_SENSIBLE_R:
        return False, None
    p_ref, dj_ref, attendus = ref["p"].to_numpy(), ref["dj"].to_numpy(), []
    for froid_nuit in d["dj"].to_numpy():
        proches = np.abs(dj_ref - froid_nuit) <= DJ_COMPARABLE
        jugeable = (int(proches.sum()) >= JOURS_COMPARABLES_MIN and int((dj_ref[proches] <= froid_nuit).sum()) >= COTES_MIN
                    and int((dj_ref[proches] >= froid_nuit).sum()) >= COTES_MIN)  # jamais d'extrapolation
        attendus.append(_attendu_comparable(p_ref[proches], dj_ref[proches], froid_nuit) if jugeable else np.nan)
    d["att"] = attendus
    juges = d[d["att"] > 0]
    if juges.empty or (fin.normalize() - juges.index[-1]).days > JUGE_RECENT_MAX_J:
        return True, None  # aucune nuit jugeable récemment : pas de conclusion
    n = serie_consecutive_fin(juges["p"] / juges["att"] > seuil)
    if n < persistance:
        return True, None
    der = juges.iloc[-n:]
    exces_kw = max(0.0, float((der["p"] - der["att"]).mean()))
    debut = der.index[0]
    heures = heures_depuis(heures_larges, debut - pd.Timedelta(hours=2))
    return True, {"persistance": n, "unite": "nuits", "debut": str(debut.date()),
                  "mesure": f"{fr(der['p'].mean())} kW", "attendu": f"{fr(der['att'].mean())} kW à température extérieure égale",
                  "kwh_j": exces_kw * 8, "delta_kw": exces_kw, "force": min(1.0, exces_kw / 2),
                  "kwh_mesure": exces_kw * heures, "heures_mesurees": heures}
