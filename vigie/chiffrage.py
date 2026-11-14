"""Chiffrage des dérives : dérive CONSTATÉE, rythme mensuel et PROJECTION si rien n'est fait.

Tous les chiffres (kWh, m³, CHF, CO₂) sont calculés ici, jamais par un LLM (règle 5).

1. Dérive constatée (déclencheur des actions, montrée au prestataire) : excès réellement mesuré depuis le début de la
   dérive. Chauffage, CAD, gaz et PAC : Σ (mesuré − attendu) heure par heure sur les heures mesurées. Eau d'un immeuble
   vide : volume mesuré (attendu ≈ 0). Fuite de nuit et électricité de nuit : excès constaté la nuit (débit ou
   puissance au-dessus de la référence) × heures mesurées depuis le début. Aucune heure manquante n'est comblée.
2. Rythme mensuel (priorisation) : excès moyen par jour des 30 derniers jours de dérive au plus × 30 jours. Même
   définition pour tous les fluides : c'est la base du score.
3. Projection sur 12 mois si rien n'est fait (information, jamais déclencheur, jamais dans le score ni la gravité) :
   eau et électricité, dérive constante (excès par jour × 365) ; chauffage, CAD, gaz et PAC, climat NORMAL de Genève
   (degrés-jours base 16 °C moyens 2016-2025 des vraies données MétéoSuisse GVE, référentiel `climat_reference`) :
   excès relatif constaté × consommation attendue d'une année normale. Sans ces paramètres : pas de projection.
"""
import pandas as pd

JOURS_AN = 365
JOURS_MOIS = 30
RYTHME_JOURS_MAX = 30
DJ_MIN_PROJECTION = 1.0  # immeuble vide : sous 1 DJ/jour pendant la dérive, pas de projection par degré-jour
VECTEURS_CHAUFFAGE = {"chaleur": "chaleur", "cad": "cad", "gaz": "gaz",  # préfixe de cause -> vecteur de coût
                      "solaire": "solaire"}  # production solaire perdue : valeur du kWh solaire (EXEMPLE)


def vecteur(cause):
    """Vecteur de coût et de CO₂ d'une cause : chaleur, cad, gaz, solaire, sinon électricité (l'eau en m³)."""
    return VECTEURS_CHAUFFAGE.get(cause.split("_")[0], "electricite")


def chiffrage_mesure(exces_jour, heures_jour, debut, exces_24h):
    """Dérive constatée d'une dérive liée au climat (chauffage, CAD, gaz, PAC).

    exces_jour : somme, jour par jour, de (mesuré − attendu) sur les heures mesurées (jour en cours compris) ;
    heures_jour : heures mesurées de chaque jour ; exces_24h : excès des jours JUGÉS de la dérive, ramené à 24 h
    (rythme). Seuls les jours à partir du début de la dérive comptent.
    """
    garde = exces_jour.index >= pd.Timestamp(debut)
    rythme = exces_24h.iloc[-RYTHME_JOURS_MAX:]
    return {"chiffrage": "mesure", "kwh_mesure": max(0.0, float(exces_jour[garde].sum())),
            "heures_mesurees": int(heures_jour[garde].sum()), "kwh_j": max(0.0, float(rythme.mean())),
            "jours_rythme": int(len(rythme))}


def heures_depuis(serie, debut):
    """Heures mesurées (valeurs connues) d'une série horaire depuis le début de la dérive."""
    return int(serie[serie.index >= pd.Timestamp(debut)].notna().sum())


# ---------------------------------------------------------------- projection (hypothèse : climat normal)


def climat_normal(P):
    """(degrés-jours base 16 °C d'une année normale, dont part de nuit) ou None si non renseigné."""
    dj = (P or {}).get("dj16_annuel_normal")
    if not dj or float(dj) <= 0:
        return None
    return float(dj), float(P.get("dj16_nuit_annuel_normal") or 0.0)


def projection_proportionnelle(exces_relatif, constante_j, par_dj, par_dj_nuit, P):
    """Dérive proportionnelle (signature, PAC) : excès relatif × consommation attendue d'une année normale,
    attendu = constante × 365 + par DJ × DJ annuels (+ part de nuit × DJ de nuit annuels)."""
    climat = climat_normal(P)
    if climat is None or exces_relatif is None:
        return None
    attendu_an = JOURS_AN * constante_j + par_dj * climat[0] + par_dj_nuit * climat[1]
    return max(0.0, exces_relatif) * max(0.0, attendu_an)


def projection_par_dj(exces_jours, dj_jours, P):
    """Chauffage resté en marche (immeuble vide) : excès par degré-jour constaté × DJ d'une année normale."""
    climat = climat_normal(P)
    if climat is None or dj_jours is None or dj_jours.isna().any() or dj_jours.mean() < DJ_MIN_PROJECTION:
        return None
    return max(0.0, float(exces_jours.sum()) / float(dj_jours.sum())) * climat[0]


# ---------------------------------------------------------------- montants et priorisation


def seuil_enjeu_mois(P):
    """Enjeu minimal en CHF par mois (30 jours). Ancien réglage en CHF/an : converti au prorata (× 30/365)."""
    if P.get("enjeu_min_chf_mois") is not None:
        return float(P["enjeu_min_chf_mois"])
    return float(P.get("enjeu_min_chf_an") or 0) * JOURS_MOIS / JOURS_AN


def date_fr(iso):
    a, m, j = str(iso)[:10].split("-")
    return f"{j}.{m}.{a}"


PERIODES = ("an", "mois", "mesure", "proj")
GRANDEURS = ("kwh", "m3", "chf", "co2_t")


def champs_vides(valeur):
    return {f"{g}_{p}": valeur for g in GRANDEURS for p in PERIODES}


def _montants(kwh, m3, prix_kwh, prix_m3, f_co2, suffixe):
    return {f"kwh_{suffixe}": round(kwh), f"m3_{suffixe}": round(m3, 1),
            f"chf_{suffixe}": round(kwh * prix_kwh + m3 * prix_m3), f"co2_t_{suffixe}": round(kwh * f_co2 / 1000, 2)}


def chiffrer(cause, r, tarifs, co2):
    """Champs chiffrés d'une alerte métier.

    *_mesure : dérive constatée depuis le début (libellé `periode`) ; *_mois : rythme par 30 jours ; *_proj : projection
    sur 12 mois si rien n'est fait (libellé `projection`, None si non calculable) ; *_an : eau et électricité seulement
    (= projection d'une dérive constante, conservé pour les exports)."""
    v = vecteur(cause)
    tarif = tarifs.get(v) or tarifs["electricite"]  # vecteur sans tarif enregistré : prix de l'électricité
    prix = (tarif["chf_par_unite"], tarifs["eau"]["chf_par_unite"], co2.get(v, co2.get("electricite", 0.0)))
    kwh_j, m3_j = r.get("kwh_j", 0.0), r.get("m3_j", 0.0)
    out = {**champs_vides(None), **_montants(kwh_j * JOURS_MOIS, m3_j * JOURS_MOIS, *prix, "mois"),
           **_montants(r.get("kwh_mesure", 0.0), r.get("m3_mesure", 0.0), *prix, "mesure"),
           "heures_mesurees": r.get("heures_mesurees"), "jours_rythme": r.get("jours_rythme"),
           "periode": f"depuis le {date_fr(r['debut'])} ({r.get('heures_mesurees')} heures mesurées)"}
    if r.get("chiffrage") == "mesure":  # dérive liée au climat
        out["chiffrage"] = "mesure"
        kwh_p = r.get("kwh_proj")
        hyp = r.get("hypothese") or "climat normal de Genève, MétéoSuisse GVE 2016-2025"
        if kwh_p is None:
            out["projection"] = r.get("sans_projection") or (
                "non calculée (production prévue de l'installation non renseignée)" if r.get("hypothese")
                else "non calculée (climat normal non renseigné ou dérive trop courte en hiver)")
            return out
        out.update(_montants(kwh_p, 0.0, *prix, "proj"))
    else:  # eau, électricité : dérive constante
        out["chiffrage"] = "annuel"
        out.update(_montants(kwh_j * JOURS_AN, m3_j * JOURS_AN, *prix, "proj"))
        out.update(_montants(kwh_j * JOURS_AN, m3_j * JOURS_AN, *prix, "an"))
        hyp = "dérive constante"
    out["projection"] = f"sur 12 mois (hypothèse : {hyp})"
    return out


def score(a, urgence):
    """Priorisation sur la MESURE seule : rythme mensuel constaté (CHF par 30 jours, même définition pour tous les
    fluides) × confiance × urgence × 1,5 si sinistre. La projection n'y entre pas : deux dérives constatées égales ont le
    même score quelle que soit l'hypothèse de projection."""
    return round(a["chf_mois"] * a["confiance"] * urgence[a["gravite"]] * (1.5 if a["sinistre"] else 1.0), 1)
