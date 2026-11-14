"""Recoupement des alertes au niveau du parc : cause commune (météo ou calendrier).

Chaque immeuble est jugé seul par le moteur. Quand plusieurs immeubles entrent en alerte LES MÊMES JOURS pour des
règles qui dépendent de la météo ou du calendrier, la cause est plus probablement commune (épisode de météo mal rendu
par l'attendu, jours fériés, vacances) qu'une dérive propre à chaque installation.

Critère, par famille de règles : les alertes dont le début tombe dans une même fenêtre de `cause_commune_fenetre_jours`
jours forment un groupe ; il est retenu s'il réunit au moins `cause_commune_immeubles_min` immeubles distincts ET au
moins `cause_commune_part_min` des immeubles sur lesquels une règle de la famille a tourné (un parc de 48 sites n'est
pas un parc de 5).

Effet : l'alerte n'est JAMAIS supprimée (une vraie dérive simultanée doit rester visible). Elle porte le champ
`cause_commune`, son constat le dit, sa confiance est multipliée par `cause_commune_confiance` (donc son score baisse)
et aucun bon n'est créé automatiquement pour elle (bons.automatiser) ; le bon manuel reste possible. Les alertes
« Données » et celles à risque de sinistre (fuites) ne sont jamais concernées.
"""
import pandas as pd

from . import historique, solaire

# Familles : règles qui partagent la même dépendance à la météo ou au calendrier. Absentes : l'eau (sinistre), les
# immeubles vides (talon déclaré, sans météo), les coupures d'onduleur et le retour du CAD (défauts d'installation).
FAMILLES = {
    "signature de chauffage": ("chaleur_signature", "cad_signature", "gaz_signature"),
    "pompe à chaleur": ("pac_cop", "pac_signature"),
    "électricité": ("elec_nuit", "elec_jour"),
    "solaire": solaire.CAUSES,
    "même mois, à climat égal": tuple(c["cause"] for c in historique.CONSOMMATIONS.values() if c["climat"]),
    "solaire au mois": ("solaire_historique",),
}
IMMEUBLES_MIN, PART_MIN, FENETRE_JOURS, CONFIANCE = 4, 0.10, 3, 0.5  # mêmes valeurs que config/referentiel.json


def groupes(alertes, juges, P):
    """{id d'alerte: marque `cause_commune`} des alertes prises dans un groupe retenu (le plus nombreux pour chacune).

    `juges` : {(immeuble, cause)} des règles qui ont tourné, pour rapporter le groupe au parc réellement jugé."""
    n_min = P.get("cause_commune_immeubles_min", IMMEUBLES_MIN)
    part_min = P.get("cause_commune_part_min", PART_MIN)
    fenetre = pd.Timedelta(days=P.get("cause_commune_fenetre_jours", FENETRE_JOURS))
    marques = {}
    for famille, causes in FAMILLES.items():
        n_juges = len({im for im, cause in juges if cause in causes})
        debuts = [(pd.Timestamp(str(a["debut"])[:10]), a) for a in alertes
                  if a["cause"] in causes and not a["sinistre"] and a.get("debut")]
        for d0 in sorted({d for d, _a in debuts}):
            groupe = [(d, a) for d, a in debuts if d0 <= d <= d0 + fenetre]
            n = len({a["immeuble_id"] for _d, a in groupe})
            if n < n_min or n < part_min * n_juges:
                continue
            marque = {"famille": famille, "immeubles": n, "juges": n_juges, "du": str(d0.date()),
                      "au": str(max(d for d, _a in groupe).date())}
            for _d, a in groupe:
                if marques.get(a["id"], {}).get("immeubles", 0) < n:
                    marques[a["id"]] = marque
    return marques


def marquer(alertes, juges, P):
    """Marque les alertes à cause commune probable : champ `cause_commune`, constat complété, confiance abaissée."""
    marques = groupes(alertes, juges, P)
    for a in alertes:
        if a["id"] in marques:
            a["cause_commune"] = marques[a["id"]]
            a["constat"] += (f" {a['cause_commune']['immeubles']} immeubles en alerte les mêmes jours : effet probable de "
                             "météo ou de calendrier, à vérifier avant d'agir.")
            a["confiance"] = round(a["confiance"] * P.get("cause_commune_confiance", CONFIANCE), 2)
