# COPIE FIGÉE du moteur V0.2.0 AVANT révision (référence « avant » de la campagne d évaluation). Ne pas modifier.
"""Moteur de détection Vigie : qualité -> attendu -> détecteurs -> impact -> priorisation -> consignes.

Principe : les chiffres (kWh, m3, CHF, CO2) sont TOUJOURS calculés ici, jamais générés par un LLM.
L'attendu utilisé dans ce prototype est statistique et explicable (profil de nuit, signature
énergétique, régression du rendement PAC). Un modèle de prévision (Chronos-2) peut être branché
dans `attendu_chronos()` sans changer le reste du moteur.
"""
import numpy as np
import pandas as pd

URGENCE = {"Critique": 3.0, "Élevée": 2.0, "Modérée": 1.0, "Données": 0.0}

# ---------------------------------------------------------------- chargement


def charger_series(cx):
    pts = pd.read_sql("SELECT * FROM point_mesure", cx).set_index("id")
    raw = pd.read_sql("SELECT ts, point_id, valeur, qualite FROM mesure", cx)
    if raw.empty:
        return pts, {}, {}, None
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True).dt.tz_localize(None)
    fin = raw["ts"].max()
    series, qualite = {}, {}
    for pid, g in raw.groupby("point_id"):
        g = g.sort_values("ts").set_index("ts")
        nature = pts.loc[pid, "nature"]
        v = g["valeur"].where(g["qualite"] != "suspecte")
        recul = 0
        if nature == "index":
            d = v.diff()
            recul = int((d < 0).sum())
            v = d.where(d >= 0)
        if nature == "instantane":
            h = v.resample("h", label="right", closed="right").mean()
        else:
            h = v.resample("h", label="right", closed="right").sum(min_count=1)
        series[pid] = h
        debut30 = fin - pd.Timedelta(days=30)
        attendu = 30 * 24 * 60 / pts.loc[pid, "pas_min"]
        qualite[pid] = {
            "derniere": g.index.max(),
            "completude": min(1.0, (g.index > debut30).sum() / attendu),
            "index_recule": recul,
            "suspectes": int((g["qualite"] == "suspecte").sum()),
        }
    return pts, series, qualite, fin


def jour(s):
    return s.resample("D").sum(min_count=1)


def serie_consecutive_fin(cond):
    """Nombre de True consécutifs en fin de série (persistance)."""
    n = 0
    for v in reversed(list(cond)):
        if v:
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------- détecteurs


def det_qualite(pid, q, fin, P):
    out = []
    silence_h = (fin - q["derniere"]).total_seconds() / 3600
    if silence_h > P["silence_max_heures"]:
        out.append(("donnees_silence", f"Aucune donnée reçue depuis {silence_h / 24:.0f} jours.", silence_h / 24))
    if q["completude"] < P["completude_min"]:
        out.append(("donnees_completude", f"Seulement {q['completude']:.0%} des mesures attendues reçues sur 30 jours.", None))
    if q["index_recule"]:
        out.append(("donnees_index", f"L'index a reculé {q['index_recule']} fois sans changement de compteur déclaré.", None))
    if q["suspectes"]:
        out.append(("donnees_negatif", f"{q['suspectes']} valeurs négatives rejetées (défaut de décodage ou d'échelle).", None))
    return out


def det_eau_nuit(s_m3h, P, seuil_l_h=20.0, persistance=3):
    h1, h2 = P["heures_nuit"]
    l_h = s_m3h * 1000
    nuit = l_h[(l_h.index.hour > h1) & (l_h.index.hour <= h2)]
    mins = nuit.groupby(nuit.index.date).min().dropna()
    n = serie_consecutive_fin(mins > seuil_l_h)
    if n < persistance:
        return None
    ref = mins.iloc[-(n + 30):-n].median() if len(mins) > n + 5 else 0.0
    exces_l_h = max(0.0, mins.iloc[-n:].median() - ref)
    return {"persistance": n, "unite": "nuits", "debut": str(mins.index[-n]),
            "mesure": f"{mins.iloc[-n:].median():.0f} l/h", "attendu": f"{ref:.0f} l/h",
            "m3_j": exces_l_h * 24 / 1000, "jours_an": 365, "force": min(1.0, exces_l_h / 100)}


def det_eau_vide(s_m3h, P, seuil_l_j=50.0, persistance=2):
    d = jour(s_m3h).dropna() * 1000
    n = serie_consecutive_fin(d > seuil_l_j)
    if n < persistance:
        return None
    return {"persistance": n, "unite": "jours", "debut": str(d.index[-n].date()),
            "mesure": f"{d.iloc[-n:].mean():.0f} l/jour", "attendu": "≈ 0 l/jour",
            "m3_j": d.iloc[-n:].mean() / 1000, "jours_an": 365, "force": 0.8}


def degres_jours(text_h, base=16.0):
    return (base - text_h).clip(lower=0).resample("D").mean()


def det_chaleur_signature(s_kwh, text_h, fin, P, seuil=1.10, persistance=7):
    d = jour(s_kwh)
    dj = degres_jours(text_h).reindex(d.index)
    df = pd.DataFrame({"q": d, "dj": dj}).dropna()
    ref = df[df.index < fin - pd.Timedelta(days=P["fenetre_analyse_jours"])]
    if len(ref) < 30:
        return None
    b, a = np.polyfit(ref["dj"], ref["q"], 1)  # q = a + b * DJ (signature énergétique)
    df["att"] = a + b * df["dj"]
    df = df[df.index.normalize() < fin.normalize()]  # jour en cours incomplet exclu
    ratio = df["q"] / df["att"].clip(lower=1)
    n = serie_consecutive_fin(ratio > seuil)
    if n < persistance:
        return None
    der = df.iloc[-n:]
    exces = (der["q"] - der["att"]).mean()
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
            "mesure": f"{(ratio.iloc[-n:].mean() - 1) * 100:+.0f} % de chaleur par rapport à l'attendu",
            "attendu": f"{der['att'].mean():.0f} kWh/jour à météo égale",
            "kwh_j": exces, "jours_an": P["jours_saison_chauffe"], "force": min(1.0, (ratio.iloc[-n:].mean() - 1) * 4)}


def det_chaleur_vide(s_kwh, talon, fin, P=None, facteur=1.5, persistance=2):
    d = jour(s_kwh)
    d = d[d.index.normalize() < fin.normalize()].dropna()
    n = serie_consecutive_fin(d > talon * facteur)
    if n < persistance:
        return None
    der = d.iloc[-n:]
    return {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
            "mesure": f"{der.mean():.0f} kWh/jour", "attendu": f"{talon:.0f} kWh/jour au maximum en hors-gel",
            "kwh_j": der.mean() - talon, "jours_an": (P or {}).get("jours_saison_chauffe", 210), "force": 1.0}


def det_elec_nuit(s_kwh, fin, P, seuil=1.20, persistance=3):
    h1, h2 = P["heures_nuit"]
    kw = s_kwh  # kWh par heure = kW moyen
    detect = kw[(kw.index.hour > h1) & (kw.index.hour <= h2)]
    nuits = detect.groupby(detect.index.date).mean().dropna()
    large = kw[(kw.index.hour > 22) | (kw.index.hour <= 6)]
    cle = [(t - pd.Timedelta(hours=7)).date() for t in large.index]  # nuit 22h-6h rattachée à sa veille
    nuits_large = large.groupby(cle).mean()
    dates = pd.to_datetime(pd.Series(nuits.index))
    ref_mask = ((dates < fin - pd.Timedelta(days=20)) & (dates >= fin - pd.Timedelta(days=50))).values
    ref = nuits[ref_mask].median()
    if not ref or np.isnan(ref):
        return None
    n = serie_consecutive_fin(nuits / ref > seuil)
    if n < persistance:
        return None
    nl = pd.Series(nuits_large.values, index=pd.to_datetime(nuits_large.index))
    ref_l = nl[(nl.index < fin - pd.Timedelta(days=20)) & (nl.index >= fin - pd.Timedelta(days=50))].median()
    exces_kw = max(0.0, nl.iloc[-n:].mean() - ref_l)
    return {"persistance": n, "unite": "nuits", "debut": str(nuits.index[-n]),
            "mesure": f"{nuits.iloc[-n:].mean():.1f} kW".replace(".", ","), "attendu": f"{ref:.1f} kW".replace(".", ","),
            "kwh_j": exces_kw * 8, "jours_an": 365, "delta_kw": exces_kw, "force": min(1.0, exces_kw / 2)}


PAC_HEURES_REF_MIN = 20 * 24   # au moins 20 jours d'heures de fonctionnement dans la référence


PAC_HEURES_CHAUFFE_MIN = 240   # heures froides (T < 14 °C) nécessaires pour apprendre une part chauffage non comptée
PAC_JOUR_MIN_KWH = 1.0         # jour sans fonctionnement significatif de la PAC : non jugé


def _x_pac(h, flux):
    """Variables explicatives de l'électricité horaire de la PAC, selon les compteurs de chaleur disponibles.

    L'électricité d'une PAC ≈ chaleur / rendement, et 1/rendement varie à peu près linéairement avec la
    température extérieure : chaque flux de chaleur MESURÉ q apporte les termes q et q·T. Une part non mesurée est
    représentée par ce qui la gouverne : un niveau de base pour l'eau chaude, les degrés-heures pour le chauffage.
    """
    t = h["t"]
    dh = (16.0 - t).clip(lower=0)  # degrés-heures, base 16 °C comme la signature énergétique
    x = {}
    for nom in flux:
        x[nom], x[nom + "·T"] = h[nom], h[nom] * t
    if "totale" not in flux and "ecs" not in flux:
        x["base eau chaude"] = pd.Series(1.0, index=h.index)
    if "totale" not in flux and "chauffage" not in flux:
        x["chauffage"], x["chauffage·T"] = dh, dh * t
    return pd.DataFrame(x)


def det_pac(s_elec, flux, text_h, fin, P, seuil=0.85, persistance=7):
    """Consommation électrique de la PAC comparée à l'attendu, heure par heure, à météo (et production) égales.

    `flux` = chaleurs mesurées disponibles parmi {"totale", "chauffage", "ecs"} (séries horaires, kWh). Selon le
    comptage de l'immeuble : chaleur totale, seulement le chauffage, seulement l'eau chaude, ou aucun compteur de
    chaleur (signature électrique selon la météo). Le modèle est appris sur la période ANTÉRIEURE à la fenêtre
    d'analyse, au pas horaire : la température de l'heure où la chaleur est produite compte (une moyenne
    journalière mélangerait l'eau chaude d'été et le chauffage par temps froid et masquerait la dérive).
    Par jour : électricité attendue / électricité mesurée ; sous `seuil` pendant `persistance` jours = dérive.
    """
    h = pd.DataFrame({"e": s_elec, "t": text_h, **flux}).dropna()
    h = h[h["e"] >= 0]
    ref = h[h.index < fin - pd.Timedelta(days=P["fenetre_analyse_jours"])]
    if len(ref) < PAC_HEURES_REF_MIN:
        return None
    chauffage_estime = "totale" not in flux and "chauffage" not in flux
    if chauffage_estime and (ref["t"] < 14).sum() < PAC_HEURES_CHAUFFE_MIN:
        return None  # pas assez d'heures froides pour apprendre le chauffage non compté : on ne conclut pas
    x_ref = _x_pac(ref, flux)
    coef, *_ = np.linalg.lstsq(x_ref.to_numpy(), ref["e"].to_numpy(), rcond=None)
    h["e_att"] = (_x_pac(h, flux).to_numpy() @ coef).clip(min=0)
    cols = {"e": "sum", "e_att": "sum", **{k: "sum" for k in flux}}
    d = h.resample("D").agg(cols)
    d = d[(d["e_att"] > PAC_JOUR_MIN_KWH) & (d.index.normalize() < fin.normalize())]  # jour en cours exclu
    ratio = d["e_att"] / d["e"]
    n = serie_consecutive_fin(ratio < seuil)
    if n < persistance:
        return None
    der = d.iloc[-n:]
    r = {"persistance": n, "unite": "jours", "debut": str(der.index[0].date()),
         "kwh_j": (der["e"] - der["e_att"]).mean(), "jours_an": P["jours_saison_chauffe"],
         "force": min(1.0, (1 - ratio.iloc[-n:].mean()) * 3)}
    if "totale" in flux:  # chaleur totale comptée : le rendement réel se calcule
        q = der["totale"].sum()
        r.update(mesure=f"un rendement de {q / der['e'].sum():.1f}".replace(".", ","),
                 attendu=f"{q / der['e_att'].sum():.1f} à météo égale".replace(".", ","))
    else:
        base = "à météo et chaleur mesurée égales" if flux else "à météo égale"
        r.update(titre="PAC : consommation électrique en hausse",
                 mesure=f"{der['e'].mean():.0f} kWh d'électricité par jour",
                 attendu=f"{der['e_att'].mean():.0f} kWh par jour {base}")
    return r


def attendu_chronos(serie_horaire, horizon_h, covariables=None):
    """Point d'extension : prévision Chronos-2 (amazon/chronos-2, Apache 2.0).

    pip install chronos-forecasting  (puis téléchargement du modèle, hors ligne ensuite)
    Retourner un DataFrame indexé comme l'horizon avec les colonnes p05, p50, p95.
    Non utilisé par défaut : le prototype reste exécutable sans GPU ni téléchargement.
    """
    raise NotImplementedError


# ---------------------------------------------------------------- textes métier

TEXTES = {
    "eau_nuit": dict(fluide="Eau froide", gravite="Critique", sinistre=True,
        titre="Fuite d'eau probable : l'eau coule en continu la nuit",
        constat="Depuis {persistance} {unite}, entre 1 h et 5 h, l'immeuble consomme environ {mesure} alors qu'il devrait être proche de {attendu}.",
        consigne="Contrôler les chasses d'eau (avis aux locataires), les robinets de purge, l'adoucisseur et la colonne en cave. Si rien n'est trouvé : recherche de fuite par l'entreprise sanitaire.",
        prestataire="Concierge, puis entreprise sanitaire", delai="48 h", payeur="Charges locataires (frais accessoires)"),
    "eau_vide": dict(fluide="Eau froide", gravite="Élevée", sinistre=True,
        titre="Consommation d'eau dans un immeuble déclaré vide",
        constat="L'immeuble est déclaré vide mais consomme {mesure} depuis {persistance} {unite}.",
        consigne="Fermer la vanne générale si l'immeuble reste inoccupé, rechercher l'écoulement.",
        prestataire="Concierge", delai="48 h", payeur="Propriétaire (immeuble vide)"),
    "chaleur_signature": dict(fluide="Chaleur", gravite="Élevée", sinistre=False,
        titre="Chauffage trop fort pour la météo (courbe de chauffe)",
        constat="Depuis {persistance} {unite}, la chaufferie produit {mesure}, à température extérieure comparable.",
        consigne="Vérifier la pente et le décalage de la courbe de chauffe, la consigne de départ et la sonde extérieure.",
        prestataire="Chauffagiste", delai="1 semaine", payeur="Charges locataires (décompte de chauffage)"),
    "chaleur_vide": dict(fluide="Chaleur", gravite="Critique", sinistre=False,
        titre="Chauffage normal dans un immeuble déclaré vide",
        constat="L'immeuble est déclaré vide mais la chaufferie produit {mesure} depuis {persistance} {unite}, au lieu de {attendu}.",
        consigne="Repasser la chaufferie en mode hors-gel et vérifier pourquoi le mode a changé (intervention, coupure, régulateur).",
        prestataire="Chauffagiste", delai="48 h", payeur="Propriétaire (immeuble vide)"),
    "elec_nuit": dict(fluide="Électricité", gravite="Modérée", sinistre=False,
        titre="Consommation électrique de nuit en hausse",
        constat="Depuis {persistance} {unite}, la consommation de nuit est de {mesure} au lieu de {attendu} habituellement.",
        consigne="Vérifier les minuteries d'éclairage des communs et du garage, la ventilation, les équipements laissés en marche.",
        prestataire="Concierge", delai="2 semaines", payeur="Charges (électricité des communs)"),
    "pac_cop": dict(fluide="Pompe à chaleur", gravite="Élevée", sinistre=False,
        titre="PAC : rendement en baisse",
        constat="Depuis {persistance} {unite}, la PAC consomme trop d'électricité : {mesure}, alors que l'attendu est {attendu}.",
        consigne="Contrôler la charge de fluide frigorigène, le dégivrage, l'encrassement de l'évaporateur et l'usage de l'appoint électrique.",
        prestataire="Frigoriste", delai="1 semaine", payeur="Charges locataires (décompte de chauffage)"),
}
TEXTES_DONNEES = {
    "donnees_silence": "Compteur muet",
    "donnees_completude": "Données incomplètes",
    "donnees_index": "Index qui recule",
    "donnees_negatif": "Valeurs négatives rejetées",
}


# ---------------------------------------------------------------- règles réglables par le gestionnaire
# Valeurs par défaut des détecteurs. Le gestionnaire peut les modifier dans l'interface (table `regle`) :
# activation, profils concernés, seuil, persistance, gravité, délai, métier du prestataire, consigne.
PROFILS = ["Habite", "Partiel", "Vide", "Travaux"]
GRAVITES = ["Critique", "Élevée", "Modérée"]
METIERS = ["Concierge", "Sanitaire", "Chauffagiste", "Frigoriste", "Électricien", "Télérelève", "Ventilation", "Régie"]
METIER_DONNEES = "Télérelève"

REGLES = {
    "eau_nuit": dict(libelle="Fuite d'eau la nuit", fluide_point="eau", active=True,
        profils=["Habite", "Partiel", "Travaux"], seuil=20.0, unite_seuil="l/h", seuil_min=1, seuil_max=500,
        aide_seuil="Débit minimum entre 1 h et 5 h au-delà duquel l'eau coule en continu.",
        persistance=3, unite_persistance="nuits", metier="Sanitaire"),
    "eau_vide": dict(libelle="Eau consommée dans un immeuble vide", fluide_point="eau", active=True,
        profils=["Vide"], seuil=50.0, unite_seuil="l/jour", seuil_min=1, seuil_max=5000,
        aide_seuil="Consommation journalière tolérée quand personne n'habite l'immeuble.",
        persistance=2, unite_persistance="jours", metier="Concierge"),
    "chaleur_signature": dict(libelle="Chauffage trop fort pour la météo", fluide_point="chaleur", active=True,
        profils=["Habite", "Partiel"], seuil=10.0, unite_seuil="% au-dessus de l'attendu", seuil_min=2, seuil_max=100,
        aide_seuil="Écart toléré entre la chaleur produite et l'attendu, à température extérieure égale.",
        persistance=7, unite_persistance="jours", metier="Chauffagiste"),
    "chaleur_vide": dict(libelle="Chauffage normal dans un immeuble vide", fluide_point="chaleur", active=True,
        profils=["Vide"], seuil=1.5, unite_seuil="× le talon hors-gel", seuil_min=1, seuil_max=10,
        aide_seuil="Multiple du talon hors-gel au-delà duquel le chauffage n'est plus en hors-gel.",
        persistance=2, unite_persistance="jours", metier="Chauffagiste"),
    "elec_nuit": dict(libelle="Électricité de nuit en hausse", fluide_point="electricite", active=True,
        profils=["Habite", "Partiel"], seuil=20.0, unite_seuil="% au-dessus des nuits de référence",
        seuil_min=5, seuil_max=300,
        aide_seuil="Hausse tolérée de la puissance de nuit par rapport aux nuits J-50 à J-20.",
        persistance=3, unite_persistance="nuits", metier="Concierge"),
    "pac_cop": dict(libelle="Pompe à chaleur : rendement en baisse / électricité en hausse",
        fluide_point="pac_electricite", active=True,
        profils=["Habite", "Partiel", "Vide"], seuil=15.0, unite_seuil="% de rendement en moins", seuil_min=3, seuil_max=60,
        aide_seuil="Baisse tolérée du rendement (électricité attendue / mesurée), à météo et chaleur mesurée égales. "
                   "Fonctionne avec la chaleur totale, seulement le chauffage, seulement l'eau chaude, ou sans compteur "
                   "de chaleur (électricité seule).",
        persistance=7, unite_persistance="jours", metier="Frigoriste"),
}

# ---------------------------------------------------------------- moteur


def regles_effectives(ref):
    """Règles par défaut (REGLES + TEXTES) complétées par les réglages du gestionnaire (ref['regles'])."""
    reglages = ref.get("regles") or {}
    out = {}
    for cause, defaut in REGLES.items():
        r = {**TEXTES[cause], **defaut}
        r.update({k: v for k, v in (reglages.get(cause) or {}).items() if v is not None})
        r["profils"] = list(r["profils"])
        out[cause] = r
    return out


def analyser(cx, ref):
    P = ref["parametres"]
    tarifs, co2 = ref["tarifs"], ref["facteurs_co2_kg_par_kwh"]
    R = regles_effectives(ref)
    pts, series, qualite, fin = charger_series(cx)
    if fin is None:
        return [], None
    meteo_id = (ref.get("meteo") or {}).get("id")
    text_h = series.get(meteo_id)
    alertes, points_en_defaut = [], set()

    # 1. Qualité des données d'abord : un point défaillant ne produit pas d'alerte énergie
    for im in ref["immeubles"]:
        for p in im["points"]:
            q = qualite.get(p["id"])
            if q is None:
                alertes.append(_alerte_donnees(im, p, "donnees_silence", "Aucune donnée reçue.", fin))
                points_en_defaut.add(p["id"])
                continue
            defauts = det_qualite(p["id"], q, fin, P)
            if defauts:  # une seule alerte par point, tous les constats regroupés
                constat = " ".join(c for _, c, _ in defauts)
                alertes.append(_alerte_donnees(im, p, defauts[0][0], constat, fin))
                points_en_defaut.add(p["id"])

    # 2. Détecteurs métier, selon le profil du lieu et les règles réglées par le gestionnaire
    for im in ref["immeubles"]:
        ids = {p["fluide"]: p["id"] for p in im["points"]}
        ok = lambda f: f in ids and ids[f] not in points_en_defaut and ids[f] in series
        actif = lambda c: R[c]["active"] and im["profil"] in R[c]["profils"]
        cand = []
        if ok("eau") and actif("eau_nuit"):
            r = R["eau_nuit"]
            cand.append(("eau_nuit", ids["eau"], det_eau_nuit(series[ids["eau"]], P, r["seuil"], r["persistance"])))
        if ok("eau") and actif("eau_vide"):
            r = R["eau_vide"]
            cand.append(("eau_vide", ids["eau"], det_eau_vide(series[ids["eau"]], P, r["seuil"], r["persistance"])))
        # Sans talon hors-gel déclaré, pas de seuil inventé : la règle ne tourne pas (signalé dans la fiche immeuble)
        if ok("chaleur") and actif("chaleur_vide") and im.get("talon_horsgel_kwh_j"):
            r = R["chaleur_vide"]
            cand.append(("chaleur_vide", ids["chaleur"], det_chaleur_vide(
                series[ids["chaleur"]], im["talon_horsgel_kwh_j"], fin, P, r["seuil"], r["persistance"])))
        if ok("chaleur") and actif("chaleur_signature") and text_h is not None:
            r = R["chaleur_signature"]
            cand.append(("chaleur_signature", ids["chaleur"], det_chaleur_signature(
                series[ids["chaleur"]], text_h, fin, P, 1 + r["seuil"] / 100, r["persistance"])))
        if ok("electricite") and actif("elec_nuit"):
            r = R["elec_nuit"]
            cand.append(("elec_nuit", ids["electricite"], det_elec_nuit(
                series[ids["electricite"]], fin, P, 1 + r["seuil"] / 100, r["persistance"])))
        if ok("pac_electricite") and actif("pac_cop") and text_h is not None:
            # Chaleurs PAC disponibles et fiables : totale, ou seulement chauffage et/ou eau chaude, ou aucune
            flux = {nom: series[ids[f]] for nom, f in (("totale", "pac_chaleur"), ("chauffage", "pac_chaleur_chauffage"),
                                                       ("ecs", "pac_chaleur_ecs")) if ok(f)}
            if "totale" in flux:
                flux = {"totale": flux["totale"]}  # la totale contient déjà chauffage et eau chaude
            r = R["pac_cop"]
            cand.append(("pac_cop", ids["pac_electricite"], det_pac(
                series[ids["pac_electricite"]], flux, text_h, fin, P, 1 - r["seuil"] / 100, r["persistance"])))
        for cause, pid, res in cand:
            if res:
                alertes.append(_alerte_metier(im, pid, cause, res, qualite[pid], R[cause], tarifs, co2, P))

    # 3. Filtre d'enjeu minimal (sauf sinistre et données), puis priorisation
    alertes = [a for a in alertes if a["gravite"] == "Données" or a["sinistre"] or a["chf_an"] >= P["enjeu_min_chf_an"]]
    for a in alertes:
        a["score"] = round(a["chf_an"] * a["confiance"] * URGENCE[a["gravite"]] * (1.5 if a["sinistre"] else 1.0), 1)
    alertes.sort(key=lambda a: (a["gravite"] == "Données", -a["score"]))
    for i, a in enumerate(alertes, 1):
        a["rang"] = i
    return alertes, fin


def _base(im):
    return {"immeuble_id": im["id"], "immeuble": im["nom"], "adresse": f"{im['adresse']}, {im['npa']}", "profil": im["profil"]}


def _alerte_donnees(im, p, cause, constat, fin):
    a = _base(im)
    # Identifiant stable par compteur : un compteur muet qui devient incomplet reste UNE alerte (règle 6)
    a.update(id=f"{im['id']}-donnees-{p['id']}", point_id=p["id"], cause=cause, fluide=p["libelle"], gravite="Données",
             titre=TEXTES_DONNEES[cause] + " — " + p["libelle"], constat=constat,
             consigne=f"Contrôler la chaîne de mesure ({p['source']}). Aucune alerte énergie n'est calculée sur ce point tant que les données manquent.",
             prestataire="Prestataire de télérelève", metier=METIER_DONNEES, delai="1 semaine", payeur="—", sinistre=False,
             persistance=None, debut=None, kwh_an=0, m3_an=0, chf_an=0, co2_t_an=0, confiance=1.0)
    return a


def _alerte_metier(im, pid, cause, r, q, t, tarifs, co2, P):
    a = _base(im)
    kwh_an = r.get("kwh_j", 0) * r["jours_an"]
    m3_an = r.get("m3_j", 0) * r["jours_an"]
    vecteur = "chaleur" if cause.startswith("chaleur") else "electricite"
    chf = kwh_an * tarifs[vecteur]["chf_par_unite"] + m3_an * tarifs["eau"]["chf_par_unite"]
    co2_t = kwh_an * co2[vecteur] / 1000
    conf = 0.6 + min(0.2, 0.04 * (r["persistance"] - P["persistance_min_jours"])) + 0.15 * r["force"]
    conf = min(0.97, conf) * min(1.0, q["completude"] / 0.97)
    a.update(id=f"{im['id']}-{cause}", point_id=pid, cause=cause, fluide=t["fluide"], gravite=t["gravite"],
             titre=r.get("titre", t["titre"]), constat=t["constat"].format(**r), consigne=t["consigne"],
             prestataire=t["prestataire"], metier=t["metier"], delai=t["delai"], payeur=t["payeur"],
             sinistre=t["sinistre"],
             persistance=f"{r['persistance']} {r['unite']}", debut=r["debut"],
             kwh_an=round(kwh_an), m3_an=round(m3_an, 1), chf_an=round(chf), co2_t_an=round(co2_t, 2),
             confiance=round(conf, 2), mesure=r["mesure"], attendu=r["attendu"])
    return a
