"""Production solaire (photovoltaïque) : baisse excessive de production à ensoleillement égal.

Principe (chiffres calculés ici, jamais par un LLM, règle 5) :
1. Ensoleillement de chaque jour = rayonnement global MESURÉ par MétéoSuisse (gre000h0, W/m² → kWh/m²), sommé sur les
   heures où la production ET le rayonnement sont mesurés (aucune heure comblée, règle 4).
2. Production attendue d'un jour = production des JOURNÉES COMPARABLES de l'historique : même saison (± 30 jours de la
   même date, l'an passé ou juste avant la fenêtre d'analyse) et même ensoleillement (± 15 %, à défaut ± 25 ou ± 35 %). Médiane de leur
   rendement (kWh produits par kWh/m² reçu), corrigée de la DÉCOTE PRÉVUE des modules entre leur date et le jour jugé
   ((1 − décote)^années). Sans historique comparable : référence nominale = production prévue de l'installation,
   décotée selon son âge, au prorata de l'ensoleillement du jour sur l'ensoleillement annuel normal de Genève.
3. Jour jugé : terminé, au moins 18 heures mesurées, assez ensoleillé (≥ 0,6 kWh/m²), sans gel (neige possible sur
   les modules), avec au moins 5 journées comparables. Persistance comptée en jours ensoleillés.
4. Qualification de la dérive :
   - arrêt : production quasi nulle malgré le soleil (onduleur, disjoncteur, interrupteur DC, réseau) ;
   - panne : chute BRUTALE (l'essentiel de la baisse en quelques jours ensoleillés) : cellules ou modules
     défectueux, diode de dérivation, chaîne (string) hors service, connecteur ;
   - dégradation : baisse PROGRESSIVE au-delà de la décote prévue (encrassement, vieillissement anormal, ombrage).
   La répartition de la perte au fil de la journée (matin, midi, après-midi) oriente le diagnostic.
5. Chiffrage : production perdue = Σ (attendu − mesuré) depuis le début, sur les heures mesurées ; rythme mensuel =
   perte moyenne par jour × 30 ; projection 12 mois = perte relative × production prévue décotée (hypothèse).
"""
import math

import numpy as np
import pandas as pd

from .chiffrage import RYTHME_JOURS_MAX

ENSOLEILLE_MIN_KWH_M2 = 0.6   # en dessous, la production est trop faible pour conclure (jour non jugé)
SAISON_J = 30                 # journées comparables : ± 30 jours autour de la même date
SAISONS_ELARGIES = (60, 90)   # à défaut (première année, référence gelée par une alerte ouverte) : ± 60 puis ± 90 jours
ECARTS_RAYONNEMENT = (0.15, 0.25, 0.35)  # et ensoleillement proche de celui du jour : ± 15 %, à défaut ± 25 % ou ± 35 %
ANALOGUES_MIN = 5
ANALOGUES_MAX = 15
JOUR_HEURES_MIN = 18          # comme les autres règles journalières (moteur.JOUR_HEURES_MIN)
GEL_C = 0.5                   # jour de température moyenne ≤ 0,5 °C : neige possible sur les modules, non jugé
RUPTURE = 0.10                # chute totale minimale (10 points de rendement) pour parler de chute brutale
PART_SAUT = 0.6               # brutale : au moins 60 % de la chute totale se produit d'un coup au début (3 jours jugés)
SEMAINE_ENSOLEILLEE = 7       # jours jugés qui donnent le niveau d'avant et le niveau actuel
RECENT_MAX_J = 21             # dernier jour jugé plus ancien (rayonnement absent, ciel couvert) : pas de conclusion
DEGRADATION_DEFAUT = 0.5      # % par an (garantie usuelle des modules : 0,4 à 0,8 %/an), si non renseignée
CRETE_TOLEREE = 1.25          # production horaire > 1,25 × puissance crête : défaut d'échelle ou d'unité (Données)
CAUSES = ("solaire_arret", "solaire_panne", "solaire_degradation")

PAYEUR = "Propriétaire (installation solaire)"
TEXTES = {
    "solaire_arret": dict(fluide="Solaire", gravite="Élevée", sinistre=False,
        titre="Installation solaire à l'arrêt malgré le soleil",
        constat="Depuis {persistance} {unite}, l'installation ({kwc}) ne produit que {mesure} en moyenne, au lieu de "
                "{attendu}. {diagnostic}",
        consigne="Contrôler l'onduleur (affichage, code d'erreur, redémarrage), le disjoncteur et l'interrupteur DC, "
                 "puis la liaison au réseau. Si l'onduleur est en défaut : intervention de l'installateur solaire.",
        prestataire="Installateur solaire", delai="48 h", payeur=PAYEUR),
    "solaire_panne": dict(fluide="Solaire", gravite="Élevée", sinistre=False,
        titre="Solaire : chute brutale de production (panne probable)",
        constat="Depuis {persistance} {unite}, l'installation ({kwc}) produit en moyenne {mesure} au lieu de "
                "{attendu}. Décote prévue des modules déjà déduite ({decote}). {forme} {diagnostic}",
        consigne="Faire contrôler les chaînes de modules (courant et tension de chaque string), les connecteurs, les "
                 "diodes de dérivation et rechercher les cellules défectueuses (thermographie). Vérifier les "
                 "messages de l'onduleur.",
        prestataire="Installateur solaire", delai="1 semaine", payeur=PAYEUR),
    "solaire_degradation": dict(fluide="Solaire", gravite="Modérée", sinistre=False,
        titre="Solaire : production en baisse au-delà de la décote prévue",
        constat="Depuis {persistance} {unite}, l'installation ({kwc}) produit en moyenne {mesure} au lieu de "
                "{attendu}. C'est au-delà de la décote prévue des modules ({decote}). {forme} {diagnostic}",
        consigne="Faire nettoyer et inspecter les modules (encrassement, feuilles, mousse, fientes), vérifier "
                 "l'absence d'ombrage nouveau et faire mesurer les chaînes si la baisse persiste après nettoyage.",
        prestataire="Installateur solaire", delai="1 mois", payeur=PAYEUR),
}

_COMMUN = dict(fluide_point="solaire", active=True, profils=["Habite", "Partiel", "Vide"],
               unite_persistance="jours ensoleillés", metier="Solaire")
REGLES = {
    "solaire_arret": dict(_COMMUN, libelle="Solaire : installation à l'arrêt", seuil=10.0,
        unite_seuil="% de l'attendu au maximum", seuil_min=1, seuil_max=50,
        aide_seuil="Production (en % de l'attendu à ensoleillement égal) en dessous de laquelle l'installation est "
                   "jugée à l'arrêt.", persistance=2),
    "solaire_panne": dict(_COMMUN, libelle="Solaire : chute brutale de production (panne)", seuil=15.0,
        unite_seuil="% sous l'attendu (décote déduite)", seuil_min=3, seuil_max=80,
        aide_seuil="Perte de production tolérée à ensoleillement égal, décote annuelle des modules déjà déduite. "
                   "Une perte apparue d'un coup signale une panne (cellules, chaîne, connecteur).", persistance=3),
    "solaire_degradation": dict(_COMMUN, libelle="Solaire : production en baisse au-delà de la décote", seuil=10.0,
        unite_seuil="% sous l'attendu (décote déduite)", seuil_min=3, seuil_max=80,
        aide_seuil="Perte tolérée quand la baisse s'installe progressivement (encrassement, vieillissement anormal, "
                   "ombrage), ou quand une baisse brutale reste sous le seuil de panne.", persistance=7),
}


# Défaut de l'onduleur : entre le lever et le coucher du soleil (rayonnement de la station météo > 0), la production
# tombe à zéro ENTRE deux relevés producteurs. Jugé au pas de temps du compteur (quart d'heure ou heure), sur les
# ONDULEUR_FENETRE_J derniers jours ; déclaré dès la première coupure (persistance réglable).
CAUSE_ONDULEUR = "solaire_onduleur"
ONDULEUR_FENETRE_J = 7
TEXTES[CAUSE_ONDULEUR] = dict(fluide="Solaire", gravite="Élevée", sinistre=False,
    titre="Solaire : l'onduleur décroche en plein jour",
    constat="Sur les 7 derniers jours, l'installation ({kwc}) a cessé de produire entre le lever et le coucher du "
            "soleil alors qu'elle produisait juste avant et juste après : {mesure}. {detail}",
    consigne="Relever le journal et les codes d'erreur de l'onduleur (surtension du réseau, défaut d'isolement, "
             "surchauffe, redémarrages), contrôler le disjoncteur et les protections côté alternatif et continu. Si "
             "les coupures se répètent : intervention de l'installateur solaire.",
    prestataire="Installateur solaire", delai="1 semaine", payeur=PAYEUR)
REGLES[CAUSE_ONDULEUR] = dict(_COMMUN, libelle="Solaire : coupures de l'onduleur en plein jour", seuil=1.0,
    unite_seuil="relevé(s) à zéro entre deux relevés producteurs", seuil_min=1, seuil_max=96,
    aide_seuil="Durée minimale d'une coupure, en nombre de relevés à zéro (1 relevé = un quart d'heure ou une heure "
               "selon le compteur), entre le lever et le coucher du soleil donnés par le rayonnement de la station météo.",
    persistance=1, unite_persistance="jour(s) avec coupure sur 7 jours")


# ---------------------------------------------------------------- installation


def installation(p):
    """Caractéristiques utiles d'un point de mesure solaire (valeurs absentes : None)."""
    def nombre(cle):
        try:
            v = float(p.get(cle))
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None
    d = nombre("degradation_pct_an")
    return {"kwc": nombre("puissance_crete_kwc"), "prevue": nombre("production_prevue_kwh_an"),
            "annee": nombre("mise_en_service"), "decote": (DEGRADATION_DEFAUT if d is None else d) / 100}


def age_ans(inst, t):
    """Années d'utilisation au jour t (mise en service supposée en milieu d'année), jamais négatif ; None si inconnue."""
    if inst["annee"] is None:
        return None
    return max(0.0, t.year + (t.dayofyear - 1) / 365.25 - (inst["annee"] + 0.5))


def facteur_nominal(inst, P):
    """Fonction t -> kWh attendus par kWh/m² reçu selon la production prévue décotée par l'âge ; None sans données."""
    normal = (P or {}).get("rayonnement_annuel_normal_kwh_m2")
    if not inst["prevue"] or not normal:
        return None

    def f(t):
        return inst["prevue"] * (1 - inst["decote"]) ** (age_ans(inst, t) or 0.0) / float(normal)
    return f


# ---------------------------------------------------------------- attendu à ensoleillement égal


def jours_solaires(s_kwh, ray_h, text_h, fin, journalier=False):
    """Par jour : production p (kWh) et ensoleillement g (kWh/m²) sur les heures où les deux sont mesurés, n heures,
    et `ensoleille` (jour terminé, assez complet, assez ensoleillé, sans gel). Retourne (jours, heures).
    `journalier` : `s_kwh` est une production relevée au jour ; l'ensoleillement du jour vient de la station
    horaire, et la répartition de la perte dans la journée (diagnostic) n'est pas disponible."""
    if journalier:
        g = ray_h.dropna().resample("D")
        j = pd.DataFrame({"p": s_kwh, "g": g.sum() / 1000.0, "heures": g.count()}).dropna()
        j = j[(j["p"] >= 0) & (j["heures"] >= JOUR_HEURES_MIN)].drop(columns="heures")
        if j.empty:
            return None, pd.DataFrame(columns=["p", "g"])
        j["n"] = 24
        gel = pd.Series(False, index=j.index)
        if text_h is not None:
            gel = (text_h.resample("D").mean().reindex(j.index) <= GEL_C).fillna(False).astype(bool)
        j["gel"] = gel
        j["ensoleille"] = (j.index < fin.normalize()) & (j["g"] >= ENSOLEILLE_MIN_KWH_M2) & ~gel
        return j, pd.DataFrame(columns=["p", "g"])
    h = pd.DataFrame({"p": s_kwh, "g": ray_h}).dropna()
    h = h[h["p"] >= 0]
    if h.empty:
        return None, h
    j = h.resample("D").agg({"p": "sum", "g": "sum"})
    j["n"] = h["p"].resample("D").count()
    j = j[j["n"] > 0].copy()
    j["g"] = j["g"] / 1000.0
    gel = pd.Series(False, index=j.index)
    if text_h is not None:
        gel = (text_h.resample("D").mean().reindex(j.index) <= GEL_C).fillna(False).astype(bool)
    j["gel"] = gel
    j["ensoleille"] = (j["n"] >= JOUR_HEURES_MIN) & (j.index < fin.normalize()) & (j["g"] >= ENSOLEILLE_MIN_KWH_M2) & ~gel
    return j, h


def attendu_jours(j, limite, inst, nominal):
    """Ajoute à `j` : att (production attendue), mode (historique, approche, nominale), nb (journées comparables) et
    juge (jour ensoleillé avec une référence fiable). Seuls les jours ensoleillés AVANT `limite` servent de référence."""
    ref = j[j["ensoleille"] & (j.index < limite)]
    rg, rr = ref["g"].to_numpy(), (ref["p"] / ref["g"]).to_numpy()
    rdoy, rt = ref.index.dayofyear.to_numpy(), ref.index
    att, mode, nb = [], [], []
    for t, g in zip(j.index, j["g"]):
        saison = np.abs((t.dayofyear - rdoy + 182) % 365 - 182)  # écart en jours à la même date (toute année)
        m = (saison <= SAISON_J) & (rt != t)
        for elargie in SAISONS_ELARGIES:  # référence gelée sans la même saison l'an passé : saison élargie par paliers
            if m.sum() >= ANALOGUES_MIN:
                break
            m = (saison <= elargie) & (rt != t)
        if g > 0 and m.sum() >= ANALOGUES_MIN:
            ecart = np.abs(rg[m] - g) / g
            ordre = np.lexsort((saison[m], ecart))  # ensoleillement le plus proche, puis date la plus proche
            for tolerance in ECARTS_RAYONNEMENT:  # les plus proches d'abord : ± 15 %, sinon ± 25 %, sinon ± 35 %
                proches = ordre[ecart[ordre] <= tolerance][:ANALOGUES_MAX]
                if len(proches) >= ANALOGUES_MIN:
                    break
            comparable = len(proches) >= ANALOGUES_MIN
            # Jour sans assez de jumeaux : attendu indicatif (chiffrage), jamais jugé. La référence nominale n'est pas
            # mêlée à l'historique : elle ignore l'orientation des modules saison par saison et fausserait la forme de
            # la baisse (brutale ou progressive).
            if not comparable:
                proches = ordre[:ANALOGUES_MIN]
            ans = np.asarray((t - rt[m][proches]).days, dtype=float) / 365.25
            att.append(float(np.median(rr[m][proches] * (1 - inst["decote"]) ** ans)) * g)
            mode.append("historique" if comparable else "approche")
            nb.append(len(proches))
        elif g > 0 and nominal is not None:
            att.append(nominal(t) * g)
            mode.append("nominale")
            nb.append(0)
        else:
            att.append(np.nan)
            mode.append(None)
            nb.append(0)
    j["att"], j["mode"], j["nb"] = att, mode, nb
    j["juge"] = j["ensoleille"] & j["mode"].isin(["historique", "nominale"]) & (j["att"] > 0)
    return j


# ---------------------------------------------------------------- qualification


def repartition(h, j, jours):
    """Perte relative (1 − mesuré / attendu) le matin, à midi et l'après-midi, sur les jours donnés."""
    if h.empty:  # production relevée au jour : pas de détail dans la journée
        return {}
    ratio = (j["att"] / j["g"].where(j["g"] > 0)).reindex(h.index.normalize())
    hh = h.assign(att=ratio.to_numpy() * h["g"].to_numpy() / 1000.0)
    hh = hh[hh.index.normalize().isin(jours) & (hh["att"] > 0)]
    heure = hh.index.hour  # fin d'intervalle UTC ; midi solaire de Genève ≈ 11 h 35 UTC
    out = {}
    for nom, masque in (("matin", heure <= 11), ("midi", (heure >= 12) & (heure <= 13)), ("après-midi", heure >= 14)):
        part = hh[masque]
        if part["att"].sum() > 0:
            out[nom] = 1 - part["p"].sum() / part["att"].sum()
    return out


def pourcent(x):
    return f"{x * 100:.0f} %".replace("-", "−")


def diagnostic(cause, rep):
    """Piste de diagnostic d'après la forme de la perte au fil de la journée."""
    if cause == "solaire_arret":
        return "Production quasi nulle toute la journée : onduleur à l'arrêt ou en défaut, disjoncteur ou interrupteur DC ouvert."
    if len(rep) < 2:
        return ""
    detail = ", ".join(f"{k} {pourcent(v)}" for k, v in rep.items())
    pire = max(rep, key=rep.get)
    if max(rep.values()) - min(rep.values()) <= 0.10:
        quoi = ("de cellules ou de modules défectueux, d'une diode de dérivation ou d'une chaîne (string) de modules hors "
                "service" if cause == "solaire_panne" else "d'un encrassement des modules ou d'un vieillissement anormal")
        return f"Perte répartie sur toute la journée ({detail}) : typique {quoi}."
    if pire == "midi":
        return f"Perte surtout aux heures de fort ensoleillement ({detail}) : limitation ou surchauffe de l'onduleur."
    moment = "le matin" if pire == "matin" else "l'après-midi"
    return (f"Perte surtout {moment} ({detail}) : ombrage nouveau (végétation, construction) ou chaîne de modules "
            "d'une même orientation.")


def jours_sous(q, seuil_bas):
    """Jours jugés consécutifs en fin de série sous `seuil_bas` (ratio mesuré / attendu)."""
    n = 0
    for v in reversed(q.to_numpy()):
        if v >= seuil_bas:
            break
        n += 1
    return n


def rupture(q, debut, chute_min=RUPTURE):
    """Chute brutale (marche) ou progressive (pente) ? None si on ne peut pas en juger (< 3 jours jugés avant le début).

    Le rendement relatif d'une installation saine vaut 1 (mesuré = attendu). Chute totale = niveau sain (1, ou la semaine
    ensoleillée d'avant le début si elle était meilleure) − niveau des derniers jours. Brutale quand l'essentiel de cette
    chute (au moins PART_SAUT) se produit d'un coup au début : médiane des 3 jours jugés d'avant − médiane des 3 premiers
    jours sous le seuil. Une pente a déjà perdu une partie de sa chute avant de franchir le seuil, et n'en perd ensuite
    qu'une petite part en quelques jours."""
    avant, apres = q[q.index < debut], q[q.index >= debut]
    if len(avant) < 3 or apres.empty:
        return None
    sain = max(1.0, float(avant.iloc[-SEMAINE_ENSOLEILLEE:].median()))
    chute = sain - float(apres.iloc[-SEMAINE_ENSOLEILLEE:].median())
    if chute < chute_min:
        return False
    saut = float(avant.iloc[-3:].median() - apres.iloc[:3].median())
    return saut >= PART_SAUT * chute


def qualifier(q, regles, maintenir=None):
    """(cause, jours ensoleillés) de la dérive en cours, ou None. Priorité : arrêt, panne, dégradation.

    Une baisse brutale est une panne ; une baisse progressive (ou brutale mais sous le seuil de panne), une
    dégradation. Faute de semaine de comparaison avant le début (ciel couvert, données récentes), une baisse au-delà du
    seuil de panne est traitée comme une panne. `maintenir` = cause d'une alerte déjà ouverte : tant que son seuil et
    sa persistance tiennent, elle garde sa qualification (pas de va-et-vient entre panne et dégradation)."""
    r = regles.get("solaire_arret")
    if r and jours_sous(q, r["seuil"] / 100) >= r["persistance"]:
        return "solaire_arret", jours_sous(q, r["seuil"] / 100)
    if maintenir in ("solaire_panne", "solaire_degradation") and regles.get(maintenir):
        n = jours_sous(q, 1 - regles[maintenir]["seuil"] / 100)
        if n >= regles[maintenir]["persistance"]:
            return maintenir, n
    rp, rd = regles.get("solaire_panne"), regles.get("solaire_degradation")
    seuils = [x["seuil"] for x in (rp, rd) if x]
    if not seuils:
        return None
    n_large = jours_sous(q, 1 - min(seuils) / 100)  # début de la baisse : premier jour sous le seuil le plus bas
    if not n_large:
        return None
    brutale = rupture(q, q.index[-n_large], min(RUPTURE, rp["seuil"] / 100) if rp else RUPTURE)
    if rp:
        n_p = jours_sous(q, 1 - rp["seuil"] / 100)
        if n_p >= rp["persistance"] and brutale is not False:
            return "solaire_panne", n_p
    if rd:  # baisse progressive, ou brutale mais sous le seuil de panne : jamais laissée sans alerte
        n_d = jours_sous(q, 1 - rd["seuil"] / 100)
        if n_d >= rd["persistance"]:
            return "solaire_degradation", n_d
    return None


# ---------------------------------------------------------------- détecteur


def det_solaire(s_kwh, ray_h, text_h, fin, P, point, regles, ref_avant=None, maintenir=None, journalier=False):
    """Détecteur solaire. `regles` = règles effectives des causes actives ; `maintenir` = cause de l'alerte solaire
    déjà ouverte sur ce compteur. Retourne (cause, résultat) ou None."""
    from .moteur import limite_reference
    inst = installation(point)
    if not regles:
        return None
    j, h = jours_solaires(s_kwh, ray_h, text_h, fin, journalier)
    if j is None:
        return None
    j = attendu_jours(j, limite_reference(fin, P, ref_avant), inst, facteur_nominal(inst, P))
    q = (j["p"] / j["att"])[j["juge"]]
    if q.empty or q.index[-1] < fin.normalize() - pd.Timedelta(days=RECENT_MAX_J):
        return None  # aucun jour ensoleillé jugé récemment (rayonnement absent, ciel couvert) : pas de conclusion
    res = qualifier(q, regles, maintenir)
    if res is None:
        return None
    cause, n = res
    return cause, resultat(cause, j.loc[q.index[-n:]], j, h, inst, fin, n, q)


def resultat(cause, der, j, h, inst, fin, n, q):
    """Champs de l'alerte : constat, chiffrage (perte constatée, rythme mensuel, projection)."""
    debut = der.index[0]
    perte_rel = 1 - der["p"].sum() / der["att"].sum()
    rep = repartition(h, j, der.index)
    # Production perdue sur les jours mesurés depuis le début, ensoleillés ou non, sur les heures mesurées ; les jours
    # de gel (neige possible sur les modules) ne sont pas comptés
    suivi = j[(j.index >= debut) & j["att"].notna() & ~j["gel"]]
    termines = suivi[(suivi.index < fin.normalize()) & (suivi["n"] >= JOUR_HEURES_MIN)]
    rythme = ((termines["att"] - termines["p"]) * 24 / termines["n"]).iloc[-RYTHME_JOURS_MAX:]
    age = age_ans(inst, debut)
    proj = max(0.0, perte_rel) * inst["prevue"] * (1 - inst["decote"]) ** (age or 0.0) if inst["prevue"] else None
    modes = der["mode"].value_counts()
    historique = modes.get("historique", 0) >= modes.get("nominale", 0)
    kwc = f"{inst['kwc']:g} kWc".replace(".", ",") if inst["kwc"] else "puissance crête non renseignée"
    decote = f"{inst['decote'] * 100:.1f} %/an".replace(".", ",")
    if age is not None:
        decote += f", {age:.0f} ans d'utilisation"
    # Mesuré et attendu dans la même unité (kWh par jour ensoleillé, moyenne des jours de la dérive), écart relatif
    mesure = f"{der['p'].mean():.0f} kWh par jour ({-perte_rel * 100:+.0f} %)".replace("-", "−")
    if cause == "solaire_arret":
        mesure = f"{der['p'].mean():.1f} kWh par jour".replace(".", ",")
    attendu = f"{der['att'].mean():.0f} kWh par jour à ensoleillement égal, d'après " + (
        f"{int(der['nb'].median())} journées comparables de même saison"
        if historique else "la production prévue de l'installation")
    # Une panne est une chute brutale, constatée à l'ouverture de l'alerte : la phrase suit la qualification retenue,
    # même quand le début recalculé d'une alerte maintenue ne montre plus la marche.
    brutale = cause == "solaire_panne" or rupture(q, debut, 0.0) is not False
    forme = "La baisse est apparue d'un coup." if brutale else "La baisse s'est installée progressivement."
    return {"persistance": n, "unite": "jours ensoleillés", "debut": str(debut.date()), "mesure": mesure, "forme": forme,
            "attendu": attendu, "kwc": kwc, "decote": decote, "diagnostic": diagnostic(cause, rep),
            "repartition": {k: round(v, 3) for k, v in rep.items()}, "perte_relative": round(float(perte_rel), 3),
            "force": min(1.0, max(0.0, perte_rel) * 3),
            "reference": "journées comparables" if historique else "production prévue",
            "chiffrage": "mesure", "kwh_mesure": max(0.0, float((suivi["att"] - suivi["p"]).sum())),
            "heures_mesurees": int(suivi["n"].sum()),
            "kwh_j": max(0.0, float(rythme.mean())) if len(rythme) else 0.0, "jours_rythme": int(len(rythme)),
            "kwh_proj": proj, "hypothese": "production prévue de l'installation, décote annuelle des modules déduite"}


def coupures(s_kwh, ray_h):
    """Coupures de jour : suites de relevés à zéro ENCADRÉES par deux relevés producteurs, entre le lever et le coucher
    du soleil (heures où le rayonnement de la station est > 0). `s_kwh` au pas du compteur, `ray_h` horaire (UTC, fin
    d'intervalle). La nuit, l'aube avant le premier relevé producteur et une journée entière à l'arrêt n'en sont pas.
    Retourne [{jour, de, a (fins du premier et du dernier relevé à zéro), pas, kwh (estimation)}]."""
    s = s_kwh.dropna()
    if s.empty:
        return []
    de_jour = s[ray_h.reindex(s.index.ceil("h")).to_numpy() > 0]
    out = []
    for jour, g in de_jour.groupby(de_jour.index.normalize()):
        v = g.to_numpy()
        producteurs = np.flatnonzero(v > 0)
        if len(producteurs) < 2:
            continue
        i, dernier = producteurs[0], producteurs[-1]
        while i < dernier:
            if v[i] > 0:
                i += 1
                continue
            k = i
            while v[k] <= 0:  # s'arrête au plus tard sur le dernier relevé producteur
                k += 1
            # production non réalisée, ESTIMÉE par la moyenne des deux relevés qui encadrent la coupure (affichage)
            out.append({"jour": jour, "de": g.index[i], "a": g.index[k - 1], "pas": int(k - i),
                        "kwh": float((v[i - 1] + v[k]) / 2 * (k - i))})
            i = k
    return out


def det_onduleur(s_kwh, ray_h, fin, point, seuil_pas=1, persistance=1):
    """Défaut de l'onduleur sur les ONDULEUR_FENETRE_J derniers jours : au moins `persistance` jour(s) avec une coupure
    d'au moins `seuil_pas` relevés à zéro entre deux relevés producteurs, du lever au coucher du soleil."""
    s = s_kwh[s_kwh.index > fin - pd.Timedelta(days=ONDULEUR_FENETRE_J)].dropna()
    c = [x for x in coupures(s, ray_h) if x["pas"] >= int(seuil_pas)]
    jours = sorted({x["jour"] for x in c})
    if not c or len(jours) < persistance:
        return None
    pas_min = int(pd.Series(s.index).diff().dt.total_seconds().median() / 60)
    minutes = sum(x["pas"] for x in c) * pas_min
    inst = installation(point)
    locale = lambda t: pd.Timestamp(t, tz="UTC").tz_convert("Europe/Zurich")  # noqa: E731
    der = c[-1]
    debut_coupure = locale(der["de"] - pd.Timedelta(minutes=pas_min))
    kwh = sum(x["kwh"] for x in c)
    return {"persistance": len(jours), "unite": "jour(s) avec coupure sur 7 jours", "debut": str(jours[0].date()),
            "mesure": f"{len(c)} coupure{'s' if len(c) > 1 else ''} ({minutes} minutes à zéro)",
            "attendu": "aucune coupure entre le lever et le coucher du soleil",
            "kwc": f"{inst['kwc']:g} kWc".replace(".", ",") if inst["kwc"] else "puissance crête non renseignée",
            "detail": f"Dernière coupure : le {debut_coupure:%d.%m.%Y} de {debut_coupure:%H:%M} à {locale(der['a']):%H:%M} "
                      f"(heure de Genève). Environ {kwh:.0f} kWh non produits, estimés d'après les relevés qui encadrent "
                      "chaque coupure.",
            "force": min(1.0, len(jours) / 3), "chiffrage": "mesure", "kwh_mesure": kwh,
            "heures_mesurees": int(s.notna().sum() * pas_min / 60), "kwh_j": kwh / ONDULEUR_FENETRE_J,
            "jours_rythme": ONDULEUR_FENETRE_J, "kwh_proj": kwh / ONDULEUR_FENETRE_J * 365,
            "hypothese": "coupures au même rythme que sur les 7 derniers jours"}


def crete_depassee(s_kwh, kwc, debut):
    """Heures (après `debut`) où la production dépasse la puissance crête tolérée : défaut d'échelle ou d'unité."""
    if not kwc or s_kwh is None:
        return 0
    s = s_kwh[s_kwh.index > debut]
    return int((s > CRETE_TOLEREE * float(kwc)).sum())
