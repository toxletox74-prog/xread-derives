"""Comparaison à l'historique de la même période (V0.3) : gaz, PAC, chauffage à distance, électricité, eau, solaire.

La valeur d'un mois est comparée à celle du MÊME MOIS des années précédentes (médiane des 3 dernières années
connues, 2 au moins). Un écart au-delà du pourcentage réglé, tenu plusieurs mois de suite, est une dérive.

Consommations « à climat égal ». Mesuré sur les relevés du lot communal 2021-2025, un mois plus froid que ses homologues
(octobre 2025 : 180 degrés-jours contre 60 les années d'avant) fait monter TOUS les compteurs de chauffage de +100 à
+300 % sans aucune dérive. La référence est donc corrigée de l'écart de climat entre le mois jugé et ses homologues :

    attendu = référence du même mois + pente × (degrés-jours du mois − degrés-jours du mois de référence)

La pente (unité par degré-jour) est apprise sur l'historique du compteur lui-même (36 mois au plus, 9 au moins) : elle
est nulle pour un compteur qui ne suit pas le climat. Sans degrés-jours du mois ou sans historique suffisant, la
comparaison se fait sans correction et le constat le dit. L'eau n'est jamais corrigée du climat.

Solaire « à ensoleillement égal » : production du mois ÷ rayonnement du mois, comparée au même rendement des années
précédentes, décote annuelle des modules déduite. C'est la référence de plusieurs années qui manque aux courbes
fines tant que la « même saison de l'an passé » n'existe pas.

Garde-fous tirés des mêmes relevés :
- une seule année de référence est trop fragile (les sites fermés début 2021 faisaient paraître 2022 à +60 %) : il en
  faut 2, et avec 2 seulement la plus prudente des deux sert de référence ;
- un changement d'installation du site (chaudière remplacée par une PAC, solaire posé) rend l'historique d'avant
  incomparable : la référence ne remonte jamais avant le dernier changement connu (table `installation`).

Degrés-jours et rayonnement mensuels : séries du lot importé (table `reference`) si elles existent, sinon calculés
depuis la station météo horaire ; jamais un mélange des deux.

Règles absolues respectées : tous les chiffres sont calculés ici (règle 5) ; un mois manquant, estimé ou incomplet
n'est ni comblé ni jugé (règle 4) ; persistance obligatoire, en mois (règle 7) ; la référence ne contient que des
mois ANTÉRIEURS au mois jugé, et antérieurs au début d'une dérive déjà en alerte.
"""
import sqlite3

import numpy as np
import pandas as pd

from .db import PAS_MENSUEL

SOLAIRE = "solaire"
# fluide du compteur -> réglage : cause, correction du climat, grandeur chiffrée, excès minimal par jour
CONSOMMATIONS = {
    "gaz": dict(cause="gaz_historique", climat=True),
    "pac_electricite": dict(cause="pac_historique", climat=True),
    "cad": dict(cause="cad_historique", climat=True),
    "chaleur": dict(cause="chaleur_historique", climat=True),
    "electricite": dict(cause="elec_historique", climat=True),
    "eau": dict(cause="eau_historique", climat=False, grandeur="m3", exces_min_j=0.48),  # 480 l/jour = 20 l/h en continu
}
FLUIDES = {**{fl: c["cause"] for fl, c in CONSOMMATIONS.items()}, SOLAIRE: "solaire_historique"}  # fluide -> cause
# Une règle plus fine (au jour ou à l'heure) déjà en alerte sur le même fluide de l'immeuble : une seule alerte (règle 6)
PLUS_FINES = {"gaz_historique": ("gaz_signature", "gaz_vide"), "pac_historique": ("pac_cop", "pac_signature"),
              "chaleur_historique": ("chaleur_signature", "chaleur_vide"),
              "cad_historique": ("cad_signature", "cad_vide"), "elec_historique": ("elec_nuit", "elec_jour"),
              "eau_historique": ("eau_nuit", "eau_vide", "eau_talon"),
              "solaire_historique": ("solaire_arret", "solaire_panne", "solaire_degradation")}
SERIE_DJ = "degres_jours_20_12"   # degrés-jours mensuels d'un lot importé (table reference)
SERIE_RAYONNEMENT = "rayonnement_kwh_m2"  # rayonnement global mensuel d'un lot importé (kWh/m²)
BASE_DJ = 16.0                    # base des degrés-jours calculés depuis la température horaire
ANNEES_REFERENCE = 3              # mêmes mois retenus : les 3 dernières années connues
ANNEES_MIN = 2                    # une seule année de référence est trop fragile (année de fermeture, de travaux)
ANNEES_RECHERCHE = 10             # jusqu'où remonter (référence gelée d'une dérive ancienne)
MOIS_PENTE = 36                   # historique utilisé pour apprendre la pente par degré-jour
MOIS_PENTE_MIN = 9
MOIS_COMPLET_MIN = 0.9            # part des relevés d'un mois pour l'agréger (courbe plus fine que le mois)
JOUR_HEURES_MIN = 18
RETARD_MAX_MOIS = 2               # dernier mois relevé trop ancien : aucune conclusion
RAYONNEMENT_MIN_MOIS = 40.0       # kWh/m² : en dessous (décembre, janvier), neige et ombres rendent le rendement instable
DECOTE_DEFAUT = 0.005             # décote annuelle des modules si le compteur ne la donne pas
CHALEUR_PAC = "pac_chaleur"       # chaleur produite par la PAC : sert de base à son électricité, sans règle propre
CHALEUR_MIN_MOIS = 50.0           # kWh : en dessous, la PAC n'a presque pas tourné et le rendement du mois ne veut rien dire
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre")

_CHAUFFAGE = dict(gravite="Élevée", sinistre=False, delai="2 semaines", payeur="Charges locataires (décompte de chauffage)")
TEXTES = {
    "gaz_historique": dict(_CHAUFFAGE, fluide="Gaz (chaudière)",
        titre="Gaz : consommation au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, la chaudière consomme {mesure} de gaz par rapport aux mêmes mois des "
                "années précédentes{climat}. {detail}",
        consigne="Rapprocher l'écart des interventions et des changements d'usage depuis son début (horaires, consignes, "
                 "surfaces chauffées), puis contrôler la courbe de chauffe, la consigne de départ, la production d'eau "
                 "chaude et le réglage du brûleur.",
        prestataire="Chauffagiste"),
    "pac_historique": dict(_CHAUFFAGE, fluide="Pompe à chaleur",
        titre="PAC : électricité au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, la pompe à chaleur consomme {mesure} d'électricité par rapport aux mêmes "
                "mois des années précédentes{climat}. {detail}",
        consigne="Rapprocher l'écart des changements d'usage depuis son début, puis contrôler la charge de fluide "
                 "frigorigène, le dégivrage, l'encrassement de l'évaporateur, l'appoint électrique et les consignes de "
                 "départ et d'eau chaude.",
        prestataire="Frigoriste"),
    "cad_historique": dict(_CHAUFFAGE, fluide="Chauffage à distance (CAD)",
        titre="CAD : chaleur livrée au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, la sous-station reçoit {mesure} de chaleur par rapport aux mêmes mois des "
                "années précédentes{climat}. {detail}",
        consigne="Rapprocher l'écart des changements d'usage depuis son début, puis vérifier la courbe de chauffe et la "
                 "régulation de la sous-station (sonde extérieure, consigne de départ, vanne de régulation). Si le défaut "
                 "est côté réseau, le signaler au fournisseur.",
        prestataire="Chauffagiste, puis fournisseur CAD si besoin"),
    "chaleur_historique": dict(_CHAUFFAGE, fluide="Chaleur",
        titre="Chaleur : production au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, la chaufferie produit {mesure} de chaleur par rapport aux mêmes mois des "
                "années précédentes{climat}. {detail}",
        consigne="Rapprocher l'écart des changements d'usage depuis son début, puis vérifier la pente et le décalage de "
                 "la courbe de chauffe, la consigne de départ et la sonde extérieure.",
        prestataire="Chauffagiste"),
    "elec_historique": dict(fluide="Électricité", gravite="Modérée", sinistre=False, delai="2 semaines",
        payeur="Charges (électricité des communs)",
        titre="Électricité : consommation au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, l'immeuble soutire {mesure} d'électricité par rapport aux mêmes mois des "
                "années précédentes{climat}. {detail}",
        consigne="Rapprocher l'écart d'un nouvel équipement ou d'un changement d'horaires depuis son début, puis contrôler "
                 "la ventilation, l'éclairage et ses minuteries, et les équipements laissés en marche. Si l'immeuble a "
                 "une installation solaire, vérifier aussi qu'elle produit normalement.",
        prestataire="Concierge"),
    "eau_historique": dict(fluide="Eau froide", gravite="Élevée", sinistre=True, delai="1 semaine", payeur="Charges (eau)",
        titre="Eau : consommation au-dessus de l'historique du même mois",
        constat="Depuis {persistance} {unite}, l'immeuble consomme {mesure} d'eau par rapport aux mêmes mois des années "
                "précédentes{climat}. {detail}",
        consigne="Rechercher un écoulement permanent : chasses d'eau, robinets de purge, arrosage, adoucisseur, soupape "
                 "du chauffe-eau, conduite enterrée. Rapprocher aussi l'écart d'un changement d'usage depuis son début.",
        prestataire="Concierge, puis entreprise sanitaire"),
    "solaire_historique": dict(fluide="Solaire", gravite="Modérée", sinistre=False, delai="2 semaines",
        payeur="Propriétaire (installation solaire)",
        titre="Solaire : production sous l'historique du même mois",
        constat="Depuis {persistance} {unite}, l'installation produit {mesure} par rapport aux mêmes mois des années "
                "précédentes, à ensoleillement égal et décote prévue des modules déduite. {detail}",
        consigne="Contrôler l'encrassement et l'ombrage des modules (végétation, nouvelle construction), l'état des chaînes "
                 "et de l'onduleur, et relever son journal d'erreurs.",
        prestataire="Installateur solaire"),
}
_REGLE = dict(active=True, profils=["Habite", "Partiel"], seuil=20.0, seuil_min=5, seuil_max=200,
              unite_seuil="% au-dessus du même mois des années précédentes", persistance=2, unite_persistance="mois",
              aide_seuil="Écart toléré entre la consommation du mois et celle du même mois des 3 années précédentes "
                         "(médiane, 2 années au moins), corrigée du climat du mois quand les degrés-jours sont connus. "
                         "Sert surtout aux compteurs relevés une fois par mois, qui n'ont pas d'autre règle.")
REGLES = {
    "gaz_historique": dict(_REGLE, libelle="Gaz : au-dessus de l'historique du même mois", fluide_point="gaz",
                           metier="Chauffagiste"),
    "pac_historique": dict(_REGLE, libelle="PAC : électricité au-dessus de l'historique du même mois",
                           fluide_point="pac_electricite", metier="Frigoriste"),
    "chaleur_historique": dict(_REGLE, libelle="Chaleur : au-dessus de l'historique du même mois",
                               fluide_point="chaleur", metier="Chauffagiste"),
    "cad_historique": dict(_REGLE, libelle="CAD : au-dessus de l'historique du même mois", fluide_point="cad",
                           metier="Chauffagiste"),
    # 3 mois : sur 2022-2025, les écarts de 2 mois étaient groupés sur les mêmes mois d'intersaison (effet du climat)
    "elec_historique": dict(_REGLE, libelle="Électricité : au-dessus de l'historique du même mois",
                            fluide_point="electricite", metier="Concierge", persistance=3),
    "eau_historique": dict(_REGLE, libelle="Eau : au-dessus de l'historique du même mois", fluide_point="eau",
                           metier="Sanitaire", profils=["Habite", "Partiel", "Travaux"],
                           aide_seuil="Écart toléré entre l'eau consommée dans le mois et celle du même mois des 3 années "
                                      "précédentes (médiane, 2 années au moins), et au moins 480 l/jour de plus."),
    "solaire_historique": dict(_REGLE, libelle="Solaire : production sous l'historique du même mois",
                               fluide_point=SOLAIRE, metier="Solaire", profils=["Habite", "Partiel", "Vide"], seuil=15.0,
                               unite_seuil="% sous le même mois des années précédentes",
                               aide_seuil="Perte tolérée par rapport au rendement (production ÷ rayonnement) du même mois "
                                          "des 3 années précédentes, décote annuelle des modules déduite. Les mois très "
                                          "peu ensoleillés ne sont pas jugés."),
}


# ---------------------------------------------------------------- séries par mois civil et références du mois


def preparer_mensuelles(pts, raw):
    """{compteur: (horodatages, valeurs valides, mois civil couvert par chaque relevé, pas)} des compteurs comparés à
    leur historique : ce qui ne dépend pas de la date vue, préparé une seule fois par rejeu."""
    if raw.empty:
        return {}
    concernes = pts[pts["fluide"].isin([*FLUIDES, CHALEUR_PAC]) & (pts["nature"] == "intervalle")]
    ids = concernes.index
    if "immeuble_id" in concernes.columns:
        # Un fluide d'un immeuble déjà relevé au mois (plusieurs années) : sa courbe fine n'apporte rien à cette règle
        # et la réagréger à chaque analyse double la durée d'un rejeu.
        au_mois = concernes["pas_min"] >= PAS_MENSUEL
        deja = set(zip(concernes.loc[au_mois, "immeuble_id"], concernes.loc[au_mois, "fluide"]))
        garde = [au or (im, fl) not in deja for au, im, fl in zip(au_mois, concernes["immeuble_id"], concernes["fluide"])]
        ids = concernes.index[garde]
    r = raw[raw["point_id"].isin(ids) & (raw["qualite"] == "valide")]
    # horodatage de fin d'intervalle -> mois couvert
    return {pid: (g["ts"], g["valeur"], (g["ts"] - pd.Timedelta(seconds=1)).dt.to_period("M"), float(pts.loc[pid, "pas_min"]))
            for pid, g in r.groupby("point_id")}


def series_mensuelles(pts, raw, jusqua=None, prepare=None):
    """{compteur: valeur par mois civil} des compteurs comparés à leur historique (valeurs valides).

    Relevé mensuel : la valeur du mois. Courbe plus fine : somme des mois COMPLETS seulement (≥ 90 % des relevés).
    `jusqua` (rejeu) : seuls les relevés reçus à cette date sont vus. `prepare` : preparer_mensuelles(pts, raw) déjà
    calculé (rejeu)."""
    out = {}
    for pid, (ts, valeur, mois, pas) in (preparer_mensuelles(pts, raw) if prepare is None else prepare).items():
        if jusqua is not None:
            vus = ts <= jusqua
            if not vus.any():
                continue
            valeur, mois = valeur[vus], mois[vus]
        somme = valeur.groupby(mois).sum()
        if pas < PAS_MENSUEL:
            attendus = pd.Series(somme.index.days_in_month * 1440 / pas, index=somme.index)
            somme = somme[valeur.groupby(mois).count() >= MOIS_COMPLET_MIN * attendus]
        if len(somme):
            out[pid] = somme.sort_index()
    return out


def _serie_du_lot(cx, serie):
    if cx is None:
        return None
    try:
        lignes = cx.execute("SELECT periode, valeur FROM reference WHERE serie = ?", (serie,)).fetchall()
    except sqlite3.OperationalError:
        return None
    return pd.Series({pd.Period(p, "M"): float(v) for p, v in lignes}).sort_index() if lignes else None


def _mois_complets(jours):
    """Somme par mois civil d'une série journalière, mois complets seulement."""
    mois = jours.index.to_period("M")
    somme = jours.groupby(mois).sum()
    return somme[jours.groupby(mois).count() >= MOIS_COMPLET_MIN * somme.index.days_in_month]


def degres_jours(cx, text_h):
    """Degrés-jours par mois civil : série du lot importé si elle existe, sinon température horaire de la station."""
    du_lot = _serie_du_lot(cx, SERIE_DJ)
    if du_lot is not None:
        return du_lot
    t = None if text_h is None else text_h.dropna()
    if t is None or t.empty:
        return pd.Series(dtype=float)
    jours = t.resample("D").mean()[t.resample("D").count() >= JOUR_HEURES_MIN]
    return _mois_complets((BASE_DJ - jours).clip(lower=0))


def rayonnement(cx, ray_h):
    """Rayonnement global par mois civil (kWh/m²) : série du lot si elle existe, sinon station horaire (W/m²)."""
    du_lot = _serie_du_lot(cx, SERIE_RAYONNEMENT)
    if du_lot is not None:
        return du_lot
    r = None if ray_h is None else ray_h.dropna()
    if r is None or r.empty:
        return pd.Series(dtype=float)
    jours = (r.resample("D").sum() / 1000)[r.resample("D").count() >= JOUR_HEURES_MIN]
    return _mois_complets(jours)


def changements(cx):
    """{immeuble: premier mois complet après son dernier changement d'installation (mise en service ou retrait)}."""
    if cx is None:
        return {}
    try:
        lignes = cx.execute("SELECT immeuble_id, mise_en_service, retrait FROM installation").fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for immeuble, *dates in lignes:
        for d in dates:
            try:
                mois = pd.Period(str(d)[:7], "M") + 1
            except (ValueError, TypeError):
                continue  # date absente ou illisible : pas de changement connu
            out[immeuble] = max(out.get(immeuble, mois), mois)
    return out


def contexte(cx, text_h=None, ray_h=None):
    """Références mensuelles communes à tous les compteurs d'une analyse."""
    return {"dj": degres_jours(cx, text_h), "rayonnement": rayonnement(cx, ray_h), "changements": changements(cx)}


# ---------------------------------------------------------------- attendu d'un mois


def reference_prudente(valeurs, sens=1):
    """Médiane des mêmes mois ; avec 2 années seulement, la plus prudente des deux (la plus haute pour juger un
    excès, la plus basse pour juger un manque) : une année anormale (site fermé) ne fausse pas la référence."""
    v = sorted(float(x) for x in valeurs)
    if len(v) == 2:
        return v[1] if sens > 0 else v[0]
    return float(np.median(v))


def _memes_mois(index, mois, borne, depuis):
    limite = min(mois, borne) if borne is not None else mois
    return limite, [m for m in (mois - 12 * k for k in range(1, ANNEES_RECHERCHE + 1))
                    if m in index and m < limite and (depuis is None or m >= depuis)][:ANNEES_REFERENCE]


def attendu_mois(s, dj, mois, borne=None, depuis=None):
    """Consommation attendue d'un mois d'après les mêmes mois des années précédentes ; None s'il y en a moins de 2.

    `borne` : mois de début d'une dérive déjà en alerte (la référence reste antérieure à ce mois).
    `depuis` : premier mois après le dernier changement d'installation du site (la référence ne remonte pas avant)."""
    limite, memes = _memes_mois(s.index, mois, borne, depuis)
    if len(memes) < ANNEES_MIN:
        return None
    reference = reference_prudente(s[memes])
    if reference <= 0:
        return None
    attendu, corrige = reference, False
    if mois in dj.index and all(m in dj.index for m in memes):
        historique = s[(s.index < limite) & (s.index >= limite - MOIS_PENTE)]
        if depuis is not None:
            historique = historique[historique.index >= depuis]
        communs = historique.index.intersection(dj.index)
        if len(communs) >= MOIS_PENTE_MIN and float(dj[communs].std()) > 0:
            pente = max(0.0, float(np.polyfit(dj[communs].astype(float), historique[communs].astype(float), 1)[0]))
            # climat de référence : celui du mois dont vient la valeur de référence (médiane, ou année prudente)
            dj_reference = (float(dj[min(memes, key=lambda m: abs(float(s[m]) - reference))]) if len(memes) == 2
                            else float(np.median(dj[memes])))
            attendu = reference + pente * (float(dj[mois]) - dj_reference)
            corrige = True
    if attendu <= 0:
        return None  # mois bien plus doux que ses homologues : attendu non significatif, mois non jugé
    return {"attendu": attendu, "reference": reference, "annees": sorted(m.year for m in memes), "corrige": corrige}


def attendu_rapport(s, base, mois, borne=None, depuis=None, sens=1, base_min=0.0, decote=0.0):
    """Attendu d'un mois par le RAPPORT s ÷ base du même mois des années précédentes, × la base du mois jugé.

    Solaire : production ÷ rayonnement (sens −1, on cherche un manque). PAC : électricité ÷ chaleur produite
    (sens +1), c'est-à-dire l'inverse du rendement. None si le mois ou ses homologues n'ont pas de base exploitable."""
    utile = lambda m: m in base.index and float(base[m]) > 0 and float(base[m]) >= base_min  # noqa: E731
    if not utile(mois):
        return None
    _limite, memes = _memes_mois(s[[m for m in s.index if utile(m)]].index, mois, borne, depuis)
    if len(memes) < ANNEES_MIN:
        return None
    rapports = [float(s[m]) / float(base[m]) * (1 - decote) ** ((mois - m).n / 12) for m in memes]
    reference = reference_prudente(rapports, sens)
    if reference <= 0:
        return None
    return {"attendu": reference * float(base[mois]), "reference": reference, "annees": sorted(m.year for m in memes),
            "corrige": True}


def attendu_solaire(s, ray, mois, borne=None, depuis=None, decote=DECOTE_DEFAUT):
    """Production attendue d'un mois : rendement (kWh par kWh/m²) du même mois des années précédentes, décote
    déduite, × rayonnement du mois. None si le mois ou ses homologues sont trop peu ensoleillés ou inconnus."""
    return attendu_rapport(s, ray, mois, borne, depuis, -1, RAYONNEMENT_MIN_MOIS, decote)


# ---------------------------------------------------------------- détection


def _nombre(x):
    return f"{x:,.0f}".replace(",", " ")


def _annees(annees):
    if len(annees) > 1 and annees[-1] - annees[0] == len(annees) - 1:
        return f"{annees[0]} à {annees[-1]}"
    return ", ".join(str(a) for a in annees)


def _mois_en_ecart(s, fin, attendu_fn, seuil_pct, sens=1, exces_min_j=0.0):
    """Derniers mois consécutifs en écart (au-dessus si sens = 1, en dessous si sens = −1), du plus ancien au dernier."""
    s = s.sort_index()
    if s.empty or s.index[-1] < pd.Period(fin, "M") - RETARD_MAX_MOIS:
        return []
    juges, mois = [], s.index[-1]
    while mois in s.index:  # un mois manquant interrompt la série : rien n'est comblé
        a = attendu_fn(s, mois)
        if a is None:
            break
        ecart = sens * (float(s[mois]) - a["attendu"])
        if ecart <= a["attendu"] * seuil_pct / 100 or ecart < exces_min_j * mois.days_in_month:
            break
        juges.insert(0, {**a, "mois": mois, "valeur": float(s[mois]), "ecart": ecart})
        mois -= 1
    return juges


def _resultat(juges, unite):
    """Champs communs d'une alerte : durée, écart relatif, attendu et détail du dernier mois."""
    dernier, jours = juges[-1], [j["mois"].days_in_month for j in juges]
    relatif = sum(j["valeur"] for j in juges) / sum(j["attendu"] for j in juges) - 1
    u, nom = ("m³" if unite == "m3" else unite), f"{MOIS[dernier['mois'].month - 1]} {dernier['mois'].year}"
    return {"persistance": len(juges), "persistance_jours": sum(jours), "unite": "mois",
            "debut": str(juges[0]["mois"].start_time.date()), "mesure": f"{relatif * 100:+.0f} %".replace("-", "−"),
            "attendu": f"{_nombre(dernier['attendu'])} {u} pour {nom}", "force": min(1.0, abs(relatif) / 0.5),
            "reference": "mêmes mois des années précédentes", "heures_mesurees": sum(jours) * 24, "jours_rythme": jours[-1],
            "_relatif": relatif, "_jours": jours,
            "_detail": f"{_nombre(dernier['valeur'])} {u} en {nom} au lieu de {_nombre(dernier['attendu'])} {u} attendus "
                       f"(référence : {MOIS[dernier['mois'].month - 1]} {_annees(dernier['annees'])}"}


def _avec_projection(r, exces, annee_reference, hypothese):
    """Montants en kWh : constaté depuis le début, rythme du dernier mois, projection sur une année de référence."""
    relatif, jours = r.pop("_relatif"), r.pop("_jours")
    proj = abs(relatif) * annee_reference if annee_reference is not None else None
    r.update(chiffrage="mesure", kwh_mesure=max(0.0, sum(exces)), kwh_j=max(0.0, exces[-1] / jours[-1]), kwh_proj=proj,
             hypothese=hypothese if proj is not None else None,
             sans_projection=None if proj is not None else "non calculée (année de référence incomplète pour ce compteur)")
    return r


def det_historique(s, dj, fin, seuil_pct=20.0, persistance=2, ref_avant=None, kwh_par_unite=1.0, unite="kWh",
                   depuis=None, grandeur="kwh", exces_min_j=0.0, chaleur=None):
    """Consommation : derniers mois consécutifs au-dessus de l'attendu de plus de `seuil_pct` % ; None sous la
    persistance. `s` : consommation par mois civil (unité du compteur) ; `kwh_par_unite` : pouvoir calorifique d'un
    compteur de gaz en m³ ; `grandeur` « m3 » : dérive chiffrée en volume d'eau (dérive constante) ; `chaleur` : chaleur
    produite par la PAC chaque mois, quand elle est comptée (l'électricité est alors jugée à chaleur produite égale)."""
    borne = pd.Period(ref_avant, "M") if ref_avant is not None else None
    if chaleur is not None:  # PAC avec compteur de chaleur : le rendement lui-même, plus juste que le climat
        attendu_fn = lambda serie, m: attendu_rapport(serie, chaleur, m, borne, depuis, 1, CHALEUR_MIN_MOIS)  # noqa: E731
    else:
        attendu_fn = lambda serie, m: attendu_mois(serie, dj, m, borne, depuis)  # noqa: E731
    juges = _mois_en_ecart(s, fin, attendu_fn, seuil_pct, 1, exces_min_j)
    if len(juges) < persistance:
        return None
    r = _resultat(juges, unite)
    corrige = juges[-1]["corrige"]
    r["climat"] = ", à climat égal" if all(j["corrige"] for j in juges) else ""
    if chaleur is not None:
        d = juges[-1]
        rendements = f"{float(chaleur[d['mois']]) / d['valeur']:.1f} au lieu de {1 / d['reference']:.1f}".replace(".", ",")
        r["climat"] = ", à chaleur produite égale"
        r["detail"] = r.pop("_detail") + f", à chaleur produite égale ; rendement du mois : {rendements})."
    else:
        r["detail"] = r.pop("_detail") + ("" if grandeur == "m3" else ", corrigée du climat du mois" if corrige else
                                          ", sans correction du climat : degrés-jours du mois ou historique insuffisants") + ")."
    if grandeur == "m3":
        jours = r.pop("_jours")
        r.pop("_relatif")
        r.update(m3_mesure=max(0.0, sum(j["ecart"] for j in juges)), m3_j=max(0.0, juges[-1]["ecart"] / jours[-1]))
        return r
    # Projection : même écart relatif sur une année de référence du compteur (mêmes mois d'avant la dérive)
    avant = min(borne, juges[0]["mois"]) if borne is not None else juges[0]["mois"]
    annee = [attendu_mois(s, pd.Series(dtype=float), juges[-1]["mois"] - k, avant, depuis) for k in range(12)]
    reference_an = sum(a["reference"] for a in annee) * kwh_par_unite if all(annee) else None
    return _avec_projection(r, [j["ecart"] * kwh_par_unite for j in juges], reference_an,
                            "même écart sur une année de référence du compteur")


def det_solaire_historique(s, ray, fin, seuil_pct=15.0, persistance=2, ref_avant=None, depuis=None, decote=DECOTE_DEFAUT):
    """Production solaire : derniers mois consécutifs sous l'attendu de plus de `seuil_pct` %, à ensoleillement égal."""
    borne = pd.Period(ref_avant, "M") if ref_avant is not None else None
    juges = _mois_en_ecart(s, fin, lambda serie, m: attendu_solaire(serie, ray, m, borne, depuis, decote), seuil_pct, -1)
    if len(juges) < persistance:
        return None
    r = _resultat(juges, "kWh")
    dernier = juges[-1]
    r["detail"] = r.pop("_detail") + f", rayonnement du mois : {_nombre(float(ray[dernier['mois']]))} kWh/m²)."
    # Projection : même perte relative sur la production attendue des 12 derniers mois (leur ensoleillement réel)
    avant = min(borne, juges[0]["mois"]) if borne is not None else juges[0]["mois"]
    annee = [attendu_solaire(s, ray, dernier["mois"] - k, avant, depuis, decote) for k in range(12)]
    connus = [a["attendu"] for a in annee if a]
    reference_an = sum(connus) if len(connus) >= 8 else None  # les mois d'hiver non jugés produisent peu
    return _avec_projection(r, [j["ecart"] for j in juges], reference_an,
                            "même perte sur l'ensoleillement des 12 derniers mois")


def candidat(im, fluide, mensuelles, en_defaut, ctx, fin, P, regle, ref_avant=None):
    """(compteur, résultat) pour un fluide de l'immeuble : le compteur sain au plus long historique mensuel."""
    points = [p for p in im["points"] if p["fluide"] == fluide and p["id"] in mensuelles and p["id"] not in en_defaut]
    if not points:
        return None, None
    p = max(points, key=lambda x: len(mensuelles[x["id"]]))
    s, depuis = mensuelles[p["id"]], ctx["changements"].get(im["id"])
    if fluide == SOLAIRE:
        decote = float(p.get("degradation_pct_an") or DECOTE_DEFAUT * 100) / 100
        return p["id"], det_solaire_historique(s, ctx["rayonnement"], fin, regle["seuil"], regle["persistance"], ref_avant,
                                               depuis, decote)
    reglage, kwh = CONSOMMATIONS[fluide], 1.0
    if fluide == "gaz" and p.get("unite") == "m3":  # gaz en m³ : pouvoir calorifique du référentiel ; sinon pas d'alerte
        kwh = P.get("gaz_pcs_kwh_par_m3")
        if not kwh:
            return p["id"], None
    dj = ctx["dj"] if reglage["climat"] else pd.Series(dtype=float)
    chaleur = None
    if fluide == "pac_electricite":  # chaleur de la PAC comptée au mois : jugée à chaleur produite égale
        chaleurs = [mensuelles[c["id"]] for c in im["points"]
                    if c["fluide"] == CHALEUR_PAC and c["id"] in mensuelles and c["id"] not in en_defaut]
        chaleur = max(chaleurs, key=len) if chaleurs else None
    return p["id"], det_historique(s, dj, fin, regle["seuil"], regle["persistance"], ref_avant, float(kwh),
                                   p.get("unite") or "kWh", depuis, reglage.get("grandeur", "kwh"),
                                   reglage.get("exces_min_j", 0.0), chaleur)


def doublon(cause, trouvees):
    """Vrai si une règle plus fine du même fluide est déjà en alerte sur l'immeuble (une alerte par cause, règle 6)."""
    return any(c in trouvees for c in PLUS_FINES.get(cause, ()))
