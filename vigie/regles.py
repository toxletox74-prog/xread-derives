"""Textes et réglages par défaut des règles de dérive : constat, consigne, gravité, seuil, persistance, métier.

Extraits de moteur.py (qui les réexporte) pour garder le moteur sous 800 lignes. Les règles solaires,
complémentaires et de comparaison à l'historique apportent leurs propres textes (solaire.py, complements.py,
historique.py).
"""
from . import complements, historique, solaire

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
        constat="Depuis {persistance} {unite}, la chaufferie produit {mesure} de chaleur par rapport à l'attendu, à température extérieure comparable.",
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
# Chauffage à distance (CAD) et gaz : mêmes règles que la chaleur (signature énergétique, immeuble vide). La chaleur
# livrée par le CAD et l'énergie du gaz d'une chaudière suivent la météo comme la chaleur produite (gaz ≈ chaleur ÷
# rendement de la chaudière) ; persistance et gravité identiques, vérifiées par la campagne d'évaluation. Le CAD est
# confié au chauffagiste (régulation et circuit de l'immeuble, côté secondaire de la sous-station) : la consigne lui
# demande de signaler au fournisseur (SIG) un défaut côté réseau.
TEXTES.update({
    "cad_signature": dict(TEXTES["chaleur_signature"], fluide="Chauffage à distance (CAD)",
        titre="CAD : chaleur livrée trop forte pour la météo",
        constat="Depuis {persistance} {unite}, la sous-station reçoit {mesure} de chaleur par rapport à l'attendu, à température extérieure comparable.",
        consigne="Vérifier la courbe de chauffe et la régulation de la sous-station (sonde extérieure, consigne de départ, vanne de régulation). Si le défaut est côté réseau, le signaler au fournisseur de chaleur.",
        prestataire="Chauffagiste, puis fournisseur CAD si besoin"),
    "cad_vide": dict(TEXTES["chaleur_vide"], fluide="Chauffage à distance (CAD)",
        titre="CAD : chauffage normal dans un immeuble déclaré vide",
        constat="L'immeuble est déclaré vide mais la sous-station reçoit {mesure} depuis {persistance} {unite}, au lieu de {attendu}.",
        consigne="Repasser la régulation de la sous-station en mode hors-gel et vérifier pourquoi le mode a changé.",
        prestataire="Chauffagiste"),
    "gaz_signature": dict(TEXTES["chaleur_signature"], fluide="Gaz (chaudière)",
        titre="Gaz : consommation trop forte pour la météo",
        constat="Depuis {persistance} {unite}, la chaudière consomme {mesure} de gaz par rapport à l'attendu, à température extérieure comparable.",
        consigne="Vérifier la courbe de chauffe, la consigne de départ, la sonde extérieure et le réglage du brûleur (combustion, cycles courts).",
        prestataire="Chauffagiste"),
    "gaz_vide": dict(TEXTES["chaleur_vide"], fluide="Gaz (chaudière)",
        titre="Gaz : chaudière en marche normale dans un immeuble déclaré vide",
        constat="L'immeuble est déclaré vide mais la chaudière consomme {mesure} de gaz depuis {persistance} {unite}, au lieu de {attendu}.",
        consigne="Repasser la chaudière en mode hors-gel et vérifier pourquoi le mode a changé (intervention, coupure, régulateur).",
        prestataire="Chauffagiste"),
})
TEXTES_DONNEES = {
    "donnees_silence": "Compteur muet",
    "donnees_completude": "Données incomplètes",
    "donnees_index": "Index qui recule",
    "donnees_negatif": "Valeurs négatives rejetées",
    "donnees_crete": "Production au-delà de la puissance crête",
    "donnees_injection": complements.TEXTE_INJECTION,
}
TEXTES.update(solaire.TEXTES)  # production solaire : arrêt, panne, dégradation (vigie/solaire.py)
TEXTES.update(complements.TEXTES)  # eau au jour, retour du chauffage à distance (vigie/complements.py)
TEXTES.update(historique.TEXTES)  # gaz et PAC : même mois des années précédentes (vigie/historique.py)


# ---------------------------------------------------------------- règles réglables par le gestionnaire
# Valeurs par défaut des détecteurs. Le gestionnaire peut les modifier dans l'interface (table `regle`) :
# activation, profils concernés, seuil, persistance, gravité, délai, métier du prestataire, consigne.
PROFILS = ["Habite", "Partiel", "Vide", "Travaux"]
GRAVITES = ["Critique", "Élevée", "Modérée"]
METIERS = ["Concierge", "Sanitaire", "Chauffagiste", "Frigoriste", "Électricien", "Solaire", "Télérelève", "Ventilation",
           "Régie"]
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

for _fl, _lib in (("cad", "CAD"), ("gaz", "Gaz")):
    REGLES[f"{_fl}_signature"] = dict(REGLES["chaleur_signature"], fluide_point=_fl,
                                      libelle=f"{_lib} : chauffage trop fort pour la météo")
    REGLES[f"{_fl}_vide"] = dict(REGLES["chaleur_vide"], fluide_point=_fl,
                                 libelle=f"{_lib} : chauffage normal dans un immeuble vide")
REGLES.update(solaire.REGLES)
REGLES.update(complements.REGLES)
REGLES.update(historique.REGLES)

# ---------------------------------------------------------------- relevé exigé par chaque règle
# Pas de temps (minutes) des compteurs sur lesquels une règle PEUT tourner : (le plus fin, le plus grossier). Une règle
# horaire affichée pour un compteur relevé au jour laisserait croire à une surveillance qui n'existe pas.
HEURE, JOUR, MOIS = 60, 1440, 43200
PAS_REGLES = {"eau_nuit": (0, HEURE), "eau_vide": (0, JOUR), "eau_talon": (JOUR, JOUR), "elec_nuit": (0, HEURE),
              "elec_jour": (JOUR, JOUR), "pac_cop": (0, HEURE), "pac_signature": (JOUR, JOUR), "cad_retour": (0, HEURE),
              **{f"{fl}_{regle}": (0, JOUR) for fl in ("chaleur", "cad", "gaz") for regle in ("signature", "vide")},
              **{cause: (0, JOUR) for cause in solaire.CAUSES}, solaire.CAUSE_ONDULEUR: (0, HEURE),
              **{cause: (0, MOIS) for cause in historique.REGLES}}
RELEVES = {(0, HEURE): "à l'heure ou plus fin", (0, JOUR): "au jour ou plus fin", (JOUR, JOUR): "au jour (pas à l'heure)",
           (0, MOIS): "au mois ou plus fin"}
for _cause, _regle in REGLES.items():
    _regle["pas_releve"] = PAS_REGLES[_cause]

# ---------------------------------------------------------------- une méthode par fluide ET par pas de relevé
# Le pas du relevé décide de ce qu'on peut observer, donc de la méthode : la nuit ne se voit qu'à l'heure, le niveau de
# base se voit au jour, et au mois il ne reste que la comparaison au même mois des années précédentes. Cette matrice
# est la source unique de l'interface (page Règles) et du document des méthodes (docs/).
PAS_MATRICE = ((15, "Quart d'heure"), (HEURE, "Heure"), (JOUR, "Jour"), (MOIS, "Mois"))
FLUIDES_MATRICE = (("Eau", ("eau",)), ("Électricité", ("electricite",)), ("Gaz", ("gaz",)),
                   ("Chaleur (chaufferie)", ("chaleur",)), ("Chauffage à distance", ("cad", "cad_temperature_retour")),
                   ("Pompe à chaleur", ("pac_electricite",)), ("Solaire", ("solaire",)))
METHODES = {
    "eau_nuit": "Fuite de nuit : débit minimum entre 1 h et 5 h",
    "eau_talon": "Niveau de base : minimum sur 7 jours",
    "eau_vide": "Immeuble vide : volume du jour",
    "eau_historique": "Même mois des années précédentes",
    "elec_nuit": "Puissance de nuit comparée aux nuits de référence, à température égale si le site suit le froid",
    "elec_jour": "Jour comparé aux jours de même type",
    "elec_historique": "Même mois des années précédentes, à climat égal",
    "pac_cop": "Rendement heure par heure, à météo et chaleur égales",
    "pac_signature": "Électricité du jour à météo égale",
    "pac_historique": "Même mois, à chaleur produite égale (sinon à climat égal)",
    "cad_retour": "Température de retour à température extérieure égale",
    "solaire_onduleur": "Coupures : zéro entre deux relevés producteurs",
    "solaire_arret": "Arrêt : journées comparables d'ensoleillement",
    "solaire_panne": "Panne : journées comparables, chute brutale",
    "solaire_degradation": "Dégradation : journées comparables, baisse progressive",
    "solaire_historique": "Rendement du même mois, à ensoleillement égal",
    **{f"{fl}_signature": "Consommation du jour à météo égale" for fl in ("chaleur", "cad", "gaz")},
    **{f"{fl}_vide": "Immeuble vide : au-delà du hors-gel" for fl in ("chaleur", "cad", "gaz")},
    **{f"{fl}_historique": "Même mois des années précédentes, à climat égal" for fl in ("chaleur", "cad", "gaz")},
}


def matrice(actives=None, compteurs=None):
    """[{fluide, cases: [{pas, libelle, regles: [{id, methode}]}]}] : les règles qui tournent pour chaque fluide et
    chaque pas de relevé. `actives` : causes actives (toutes par défaut). Une règle qui accepte un relevé plus
    grossier que le pas (la règle du mois sur un relevé au jour) y figure aussi : elle travaille sur le cumul.
    `compteurs` : [(fluide, pas en minutes, nombre)] du parc, pour dire combien de compteurs sont dans chaque case."""
    actives = set(REGLES) if actives is None else set(actives)
    bornes = [0] + [pas for pas, _libelle in PAS_MATRICE]  # un compteur va dans la première colonne assez grossière
    lignes = []
    for nom, fluides in FLUIDES_MATRICE:
        cases = []
        for pas, libelle in PAS_MATRICE:
            du_pas = [c for c, r in REGLES.items() if r["fluide_point"] in fluides and c in actives
                      and PAS_REGLES[c][0] <= pas <= PAS_REGLES[c][1]]
            du_pas.sort(key=lambda c: (PAS_REGLES[c][1], c))  # la méthode la plus fine d'abord
            bas = bornes[bornes.index(pas) - 1]
            cases.append({"pas": pas, "libelle": libelle, "regles": [{"id": c, "methode": METHODES[c]} for c in du_pas],
                          # compteurs du fluide principal (la température de retour n'est pas un second compteur)
                          "compteurs": sum(n for fl, p, n in compteurs or () if fl == fluides[0] and bas < p <= pas)})
        lignes.append({"fluide": nom, "cases": cases})
    return lignes


def applicabilite(cause, compteurs):
    """Sur combien de compteurs actifs du parc la règle peut tourner. `compteurs` : [(fluide, pas en minutes, nombre)].

    Retourne le relevé exigé (texte), le nombre de compteurs au bon pas, et le nombre de compteurs du fluide."""
    fluide, (fin, grossier) = REGLES[cause]["fluide_point"], PAS_REGLES[cause]
    du_fluide = [(pas, n) for fl, pas, n in compteurs if fl == fluide]
    return {"releve": RELEVES[(fin, grossier)], "compteurs": sum(n for pas, n in du_fluide if fin <= pas <= grossier),
            "compteurs_fluide": sum(n for _pas, n in du_fluide),
            # relevés trop grossiers pour la règle ; un compteur plus fin relève d'une autre règle (eau à l'heure)
            "trop_grossiers": sum(n for pas, n in du_fluide if pas > grossier)}


NOMS_PAS = {15: "au quart d'heure", HEURE: "à l'heure", JOUR: "au jour", MOIS: "au mois"}
# Mesures d'appui d'une règle, sans règle propre : météo, débit et départ du CAD, chaleur produite par la PAC
AUXILIAIRES = {"meteo", "rayonnement", "cad_debit", "cad_temperature_aller", "pac_chaleur", "pac_chaleur_chauffage",
               "pac_chaleur_ecs"}


def nom_pas(pas):
    return NOMS_PAS.get(int(pas), f"toutes les {int(pas)} min")


def couverture(compteurs, regles, libelles=None):
    """Alerte de couverture du parc : une règle active qui ne correspond pas à la granularité de tous les compteurs
    de son fluide, et les compteurs qu'aucune règle active ne surveille.

    `compteurs` : [(fluide, pas en minutes, nombre de compteurs actifs)] ; `regles` : règles effectives (id, active,
    libelle, fluide_point) ; `libelles` : {fluide: nom affiché}. Niveaux : « sans_effet » (la règle ne tourne sur
    aucun compteur du fluide), « partielle » (une partie seulement), puis la liste des compteurs sans règle."""
    alertes, couverts = [], set()
    for r in regles:
        if not r["active"]:
            continue
        fin, grossier = PAS_REGLES[r["id"]]
        du_fluide = sorted((pas, n) for fl, pas, n in compteurs if fl == r["fluide_point"])
        au_pas = [(pas, n) for pas, n in du_fluide if fin <= pas <= grossier]
        # seuls les relevés TROP GROSSIERS manquent à la règle : un compteur plus fin relève d'une autre règle
        hors = [(pas, n) for pas, n in du_fluide if pas > grossier]
        couverts.update((r["fluide_point"], pas) for pas, _n in au_pas)
        if not hors or (fin > 0 and any(pas < fin for pas, _n in du_fluide)):
            continue  # règle du relevé au jour alors que le fluide a des courbes plus fines : la règle fine s'en charge
        total, detail = sum(n for _pas, n in du_fluide), ", ".join(f"{n} {nom_pas(pas)}" for pas, n in hors)
        if not au_pas:
            texte = (f"« {r['libelle']} » ne tourne sur aucun de vos {total} compteur(s) de ce fluide ({detail}) : "
                     f"elle exige un relevé {RELEVES[(fin, grossier)]}.")
        else:
            texte = (f"« {r['libelle']} » tourne sur {sum(n for _pas, n in au_pas)} compteur(s) sur {total} : les "
                     f"autres ({detail}) ne sont pas relevés {RELEVES[(fin, grossier)]}.")
        alertes.append({"niveau": "partielle" if au_pas else "sans_effet", "regle": r["id"], "texte": texte})
    sans = [{"fluide": (libelles or {}).get(fl, fl), "pas": nom_pas(pas), "compteurs": n}
            for fl, pas, n in sorted(compteurs) if fl not in AUXILIAIRES and (fl, pas) not in couverts]
    return {"alertes": sorted(alertes, key=lambda a: a["niveau"] != "sans_effet"), "sans_regle": sans,
            "sans_effet": sum(a["niveau"] == "sans_effet" for a in alertes),
            "partielles": sum(a["niveau"] == "partielle" for a in alertes),
            "compteurs_sans_regle": sum(s["compteurs"] for s in sans)}
