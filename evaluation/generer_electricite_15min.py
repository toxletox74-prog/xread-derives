"""Courbes de charge d'électricité au quart d'heure, année 2025, pour les 48 sites du lot communal (FICTIVES).

    python -m evaluation.generer_electricite_15min

Le lot ne fournit l'électricité soutirée qu'au mois. Ce script en tire une courbe au quart d'heure par compteur :

- le TOTAL de chaque mois est exactement le relevé mensuel du compteur (la courbe retombe sur le relevé) ;
- la FORME vient de la typologie du site (bureaux, école, crèche, piscine, logements, éclairage public…), du
  calendrier du lot (jours ouvrés, fériés, vacances scolaires) et, pour l'éclairage public, du lever et du coucher
  du soleil à Genève ;
- un site équipé de solaire soutire moins en plein jour ; quand la courbe d'injection du lot montre que le site
  injecte au réseau, il ne soutire rien ;
- un aléa reproductible (graine fixe) évite des journées identiques.

Ces courbes sont SYNTHÉTIQUES : elles servent à essayer les méthodes au quart d'heure, pas à décrire des bâtiments
réels. Aucune dérive n'y est ajoutée : seules celles déjà présentes dans les relevés mensuels s'y retrouvent.
Format : celui des courbes du lot (horodatage local de DÉBUT d'intervalle avec décalage ; séparateur point-virgule).
"""
import os
import sqlite3

import numpy as np
import pandas as pd

from vigie import service

BASE = os.path.join(service.RACINE, "vigie.db")
SORTIE = os.path.join(service.RACINE, "donnees", "RC-Electricite-15min-2025-FICTIF.csv")
FUSEAU = "Europe/Zurich"
GRAINE = 2025
ALEA_JOUR, ALEA_QUART = 0.04, 0.05      # écart-type relatif d'un jour à l'autre, d'un quart d'heure à l'autre
LATITUDE, MIDI_SOLAIRE_UTC = 46.2, 11.6  # Genève : midi solaire vers 11 h 35 UTC
CREPUSCULE_H = 0.4                       # l'éclairage public s'allume un peu avant la nuit noire


def plage(heure, debut, fin, rampe=0.75):
    """1 entre `debut` et `fin` (heures locales), avec une montée et une descente de `rampe` heure."""
    return np.clip(np.minimum(heure - debut, fin - heure) / rampe + 1, 0, 1)


def formes(heure, jour_semaine, ouvre, vacances):
    """{typologie: (part permanente, occupation de 0 à 1 par quart d'heure)}."""
    sam, dim = jour_semaine == 5, jour_semaine == 6
    classe = ouvre & ~vacances
    mercredi = jour_semaine == 2
    ecole = classe * np.where(mercredi, plage(heure, 7.25, 12.25), plage(heure, 7.25, 16.5)) \
        + 0.15 * (ouvre & vacances) * plage(heure, 8, 16)
    mardi_a_samedi = ((jour_semaine >= 1) & (jour_semaine <= 4) & ouvre) | sam
    soirs = (jour_semaine >= 3) & (jour_semaine <= 5)
    return {
        "Administration": (0.25, ouvre * plage(heure, 7, 18)),
        "École primaire": (0.18, ecole),
        "École avec piscine": (0.45, ecole),
        "Crèche (EVE)": (0.20, ouvre * plage(heure, 6.5, 18.5)),
        "Maison de quartier": (0.20, ouvre * (0.4 * plage(heure, 9, 12) + plage(heure, 14, 22)) + sam * 0.7 * plage(heure, 10, 18)),
        "Salle communale": (0.15, soirs * plage(heure, 18, 23.75) + dim * 0.6 * plage(heure, 10, 17)
                            + ouvre * 0.2 * plage(heure, 9, 12)),
        "Bibliothèque": (0.25, mardi_a_samedi * plage(heure, 10, 18)),
        "Salle de spectacle": (0.20, ouvre * 0.35 * plage(heure, 10, 17)
                               + ((jour_semaine >= 2) & (jour_semaine <= 5)) * plage(heure, 17.5, 23.25)),
        "Installation sportive": (0.20, ouvre * (0.5 * plage(heure, 8, 17) + plage(heure, 17, 22))
                                  + (sam | dim) * 0.8 * plage(heure, 9, 19)),
        "Piscine couverte": (0.55, plage(heure, 7, 21) * np.where(sam | dim, 0.85, 1.0)),
        "Patinoire": (0.60, plage(heure, 9, 22)),
        "Voirie et ateliers": (0.20, ouvre * plage(heure, 6.5, 17)),
        "Caserne de pompiers": (0.50, plage(heure, 7, 19) * np.where(ouvre, 1.0, 0.7)),
        "Logements communaux": (0.35, 0.6 * plage(heure, 6, 8.5) + plage(heure, 17, 23) + (sam | dim) * 0.4 * plage(heure, 9, 17)),
        "Abri PC": (0.90, ouvre * plage(heure, 8, 17)),
        "Cimetière": (0.30, ouvre * plage(heure, 8, 17) + sam * 0.5 * plage(heure, 8, 12)),
        "Parking souterrain": (0.55, plage(heure, 6, 22) * np.where(ouvre, 1.0, 0.6)),
    }


def eclairage_public(utc, heure):
    """Allumé du coucher au lever du soleil (un peu avant et après), abaissé à 60 % entre minuit et 5 h."""
    declinaison = -23.44 * np.cos(2 * np.pi * (utc.dayofyear.to_numpy() + 10) / 365)
    demi_jour = np.degrees(np.arccos(-np.tan(np.radians(LATITUDE)) * np.tan(np.radians(declinaison)))) / 15
    heure_utc = utc.hour.to_numpy() + utc.minute.to_numpy() / 60 + 0.125  # milieu du quart d'heure
    nuit = np.abs(heure_utc - MIDI_SOLAIRE_UTC) > demi_jour - CREPUSCULE_H
    return nuit * np.where(heure < 5, 0.6, 1.0)


def puissances(occupation, solaire_, cle_mois, du_mois, plancher):
    """Poids de chaque quart d'heure = (socle du mois + amplitude d'occupation × occupation) × effet du solaire.

    L'amplitude due à l'occupation (éclairage, bureautique, cuisine) est la MÊME toute l'année pour un site ; c'est
    le socle permanent qui change d'un mois à l'autre pour retomber sur le relevé : il porte le chauffage électrique
    ou la PAC en hiver, et presque toute la consommation d'une école en août. `plancher` : part permanente du mois
    le plus « occupé ». Donner à chaque mois la même forme concentrait un mois de vacances sur quelques jours de
    classe, avec des pointes irréalistes."""
    solaire_mois = pd.Series(solaire_).groupby(cle_mois).sum()
    occupe_mois = pd.Series(occupation * solaire_).groupby(cle_mois).sum()
    utiles = occupe_mois[occupe_mois > 0]
    amplitude = float(((1 - plancher) * du_mois[utiles.index] / utiles).min())
    return (du_mois - amplitude * occupe_mois) / solaire_mois, amplitude  # socle de chaque mois, amplitude du site


def continu(par_mois, mois_du_jour):
    """Valeur par JOUR, continue d'un mois à l'autre, dont la moyenne de chaque mois reste la valeur du mois.

    Un socle constant par mois fait une marche le 1er de chaque mois : la règle « électricité de nuit » y voyait une
    hausse brutale (11 fausses alertes en décembre). On relie donc des valeurs de milieu de mois par des segments, en
    choisissant ces valeurs pour que la moyenne de chaque mois soit exacte (système linéaire 12 × 12)."""
    n = len(mois_du_jour)
    jours = np.arange(n)
    milieux = np.array([jours[mois_du_jour == m].mean() for m in range(12)])
    base = np.zeros((n, 12))  # poids de chaque valeur de milieu de mois dans chaque jour (interpolation linéaire)
    for k in range(12):
        gauche = milieux[k - 1] if k else -np.inf
        droite = milieux[k + 1] if k < 11 else np.inf
        monte = np.where(np.isinf(gauche), 1.0, (jours - gauche) / (milieux[k] - gauche if k else 1))
        descend = np.where(np.isinf(droite), 1.0, (droite - jours) / (droite - milieux[k] if k < 11 else 1))
        base[:, k] = np.clip(np.minimum(monte, descend), 0, 1)
    moyennes = np.array([base[mois_du_jour == m].mean(axis=0) for m in range(12)])
    return base @ np.linalg.solve(moyennes, np.asarray(par_mois, dtype=float))


def socle_journalier(socle_mois, mois_du_jour, dj_jour, chauffe_electrique):
    """Socle de chaque jour : continu d'un mois à l'autre et, pour un site chauffé à l'électricité (PAC, chauffage
    direct), plus haut les jours froids que les jours doux du même mois (pente apprise sur les douze mois)."""
    valeurs = socle_mois.to_numpy()
    socle = continu(valeurs, mois_du_jour)
    if chauffe_electrique:
        dj_mois = np.array([dj_jour[mois_du_jour == m].mean() for m in range(12)])
        pente = max(0.0, float(np.polyfit(dj_mois, valeurs, 1)[0]))
        socle = socle + pente * (dj_jour - continu(dj_mois, mois_du_jour))
    return np.maximum(socle, 0.25 * valeurs[mois_du_jour])  # jamais sous le quart du socle du mois


def lire(cx):
    """Relevés mensuels 2025 par compteur, typologie par site, calendrier, solaire et injection du lot."""
    mois = pd.read_sql(
        "SELECT m.point_id, m.ts, m.valeur, p.immeuble_id FROM mesure m JOIN point_mesure p ON p.id = m.point_id "
        "WHERE p.fluide = 'electricite' AND p.pas_min >= 43200 AND m.qualite = 'valide' "
        "AND m.ts > '2025-01-01T00:00:00Z' AND m.ts <= '2026-01-01T00:00:00Z'", cx)
    # le relevé de janvier est horodaté à la fin du mois (2025-02-01T00:00:00Z)
    mois["mois"] = (pd.to_datetime(mois["ts"], utc=True) - pd.Timedelta(days=1)).dt.strftime("%Y-%m")
    typologie = dict(cx.execute("SELECT id, typologie FROM immeuble").fetchall())
    calendrier = pd.read_sql("SELECT serie, periode, valeur FROM reference WHERE serie IN "
                             "('jour_ouvre', 'jour_vacances_scolaires')", cx).pivot(index="periode", columns="serie", values="valeur")
    solaires = {r[0] for r in cx.execute("SELECT DISTINCT immeuble_id FROM point_mesure WHERE fluide = 'solaire'")}
    injection = pd.read_sql("SELECT m.ts, p.immeuble_id, m.valeur FROM mesure m JOIN point_mesure p ON p.id = m.point_id "
                            "WHERE p.fluide = 'electricite_injection' AND p.pas_min = 15", cx)
    rayonnement = pd.read_sql("SELECT m.ts, m.valeur FROM mesure m JOIN point_mesure p ON p.id = m.point_id "
                              "WHERE p.fluide = 'rayonnement'", cx)
    meteo = pd.read_sql("SELECT m.ts, m.valeur FROM mesure m JOIN point_mesure p ON p.id = m.point_id "
                        "WHERE p.fluide = 'meteo'", cx)
    chauffes = {r[0] for r in cx.execute("SELECT DISTINCT immeuble_id FROM installation WHERE retrait IS NULL "
                                         "AND (type LIKE 'pac%' OR type = 'electrique_direct')")}
    return mois, typologie, calendrier, solaires, injection, rayonnement, meteo, chauffes


def generer(chemin=SORTIE, base=BASE):
    cx = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    try:
        mois, typologie, calendrier, solaires, injection, rayonnement, meteo, chauffes = lire(cx)
    finally:
        cx.close()
    # L'année civile locale 2025 : 35 040 quarts d'heure, du 1er janvier 00:00 au 31 décembre 23:45 (heure de Genève)
    utc = pd.date_range("2024-12-31 23:00", periods=365 * 96, freq="15min", tz="UTC")
    local = utc.tz_convert(FUSEAU)
    heure = local.hour.to_numpy() + local.minute.to_numpy() / 60
    jours = local.strftime("%Y-%m-%d")
    cle_mois = local.strftime("%Y-%m").to_numpy()
    semaine = local.dayofweek.to_numpy()
    ouvre = calendrier["jour_ouvre"].reindex(jours).fillna(pd.Series(semaine < 5, index=jours)).to_numpy().astype(bool) \
        if "jour_ouvre" in calendrier else semaine < 5
    vacances = calendrier["jour_vacances_scolaires"].reindex(jours).fillna(0).to_numpy().astype(bool) \
        if "jour_vacances_scolaires" in calendrier else np.zeros(len(utc), bool)
    profils = formes(heure, semaine, ouvre, vacances)
    # Rayonnement de la station (W/m², heure finissante) rapporté à chaque quart d'heure, de 0 à 1
    soleil = pd.Series(rayonnement["valeur"].to_numpy(), index=pd.to_datetime(rayonnement["ts"], utc=True))
    soleil = np.clip(soleil.reindex((utc + pd.Timedelta(minutes=15)).ceil("h")).fillna(0).to_numpy() / 800.0, 0, 1)
    fin_utc = (utc + pd.Timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    horodatage = local.strftime("%Y-%m-%dT%H:%M:%S%z").str.replace(r"(\d{2})(\d{2})$", r"\1:\2", regex=True).to_numpy()
    numero_jour = pd.factorize(jours)[0]
    premier = np.unique(numero_jour, return_index=True)[1]            # premier quart d'heure de chaque jour
    mois_du_jour = local.month.to_numpy()[premier] - 1
    # Degrés-jours base 16 °C de chaque jour local (température horaire de la station) : chauffage électrique
    temperature = pd.Series(meteo["valeur"].to_numpy(), index=pd.to_datetime(meteo["ts"], utc=True).dt.tz_convert(FUSEAU))
    par_jour = temperature.groupby(temperature.index.strftime("%Y-%m-%d")).mean()
    dj_jour = (16.0 - par_jour.reindex(pd.unique(jours)).interpolate().bfill().ffill().to_numpy()).clip(min=0)
    blocs, bilan = [], []
    for pid, releves in sorted(mois.groupby("point_id")):
        site = releves["immeuble_id"].iloc[0]
        du_mois = releves.set_index("mois")["valeur"]
        alea = np.random.default_rng([GRAINE, int(site[1:])])
        if typologie.get(site) == "Éclairage public":
            poids = eclairage_public(utc, heure) * alea.normal(1, 0.01, len(utc))
        else:
            plancher, occupation = profils[typologie[site]]
            occupation, solaire_ = np.clip(occupation, 0, 1), np.ones(len(utc))
            if site in solaires:  # le solaire couvre une partie des besoins en plein jour
                solaire_ = 1 - 0.55 * soleil
                inj = injection[injection["immeuble_id"] == site]
                if len(inj):      # le site injecte au réseau : il ne soutire rien pendant ce quart d'heure
                    injecte = pd.Series(inj["valeur"].to_numpy(), index=inj["ts"]).reindex(fin_utc).fillna(0).to_numpy() > 0
                    solaire_ = np.where(injecte, 0.0, solaire_)
            socle_mois, amplitude = puissances(occupation, solaire_, cle_mois, du_mois, plancher)
            socle = socle_journalier(socle_mois.sort_index(), mois_du_jour, dj_jour, site in chauffes)[numero_jour]
            poids = (socle + amplitude * occupation) * solaire_ \
                * alea.lognormal(0, ALEA_JOUR, numero_jour.max() + 1)[numero_jour] * alea.lognormal(0, ALEA_QUART, len(utc))
        somme = pd.Series(poids).groupby(cle_mois).sum()
        valeurs = np.round(poids * (du_mois / somme).reindex(cle_mois).to_numpy(), 3)
        blocs.append(pd.DataFrame({"horodatage": horodatage, "id_compteur": pid, "id_site": site, "energie_kwh": valeurs}))
        bilan.append((pid, typologie.get(site), float(valeurs.sum()), float(du_mois.sum()), float(valeurs.max() * 4)))
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    pd.concat(blocs, ignore_index=True).to_csv(chemin, sep=";", index=False, encoding="utf-8-sig", float_format="%.3f",
                                               lineterminator="\n")
    return chemin, bilan


if __name__ == "__main__":
    fichier, lignes = generer()
    print(f"{fichier} — {len(lignes)} compteurs, {len(lignes) * 365 * 96} valeurs")
    for pid, typo, total, releve, pointe in lignes:
        print(f"  {pid:8} {typo or '':24} {total:>10.0f} kWh (relevés : {releve:>10.0f}) · pointe {pointe:>6.1f} kW")
