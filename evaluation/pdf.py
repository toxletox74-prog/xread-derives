"""Document PDF : méthodes de détection et de chiffrage, données des fluides et météo, évaluation, révisions.

  python -m evaluation.pdf   ->  docs/Vigie_methodes_et_evaluation_derives.pdf

Tous les chiffres viennent des fichiers produits par la campagne (evaluation/sorties/*.json) ou du code du moteur.
Campagne principale : « horaire » (relevés horaires, 12 mois, moteur actuel) ; « horaire_avant » : copie figée V0.2.0 sur
l'expérience de chiffrage ; « avant » et « apres » : campagne précédente (pas de 15 min, 120 jours) des révisions R1-R7.
"""
import json
import os
from datetime import date

from reportlab.platypus import CondPageBreak, NextPageTemplate, PageBreak, Paragraph, Spacer

from vigie import service

from . import pdf_mise_en_page as M
from .campagne import SORTIES

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE_PDF = os.path.join(RACINE, "docs", "Vigie_methodes_et_evaluation_derives.pdf")
FIG = os.path.join(SORTIES, "figures")
NOMS = {"eau_nuit": "Eau — fuite de nuit", "eau_vide": "Eau — immeuble vide",
        "chaleur_signature": "Chaleur — signature", "chaleur_vide": "Chaleur — immeuble vide",
        "elec_nuit": "Électricité — nuit", "pac_totale": "PAC — chaleur totale", "pac_chauffage": "PAC — chauffage seul",
        "pac_ecs": "PAC — eau chaude seule", "pac_aucune": "PAC — électricité seule",
        "cad_signature": "CAD — signature", "cad_vide": "CAD — immeuble vide", "gaz_signature": "Gaz — signature",
        "gaz_vide": "Gaz — immeuble vide"}
ORDRE = list(NOMS)
CLIMAT = ("chaleur_signature", "chaleur_vide", "pac_totale", "pac_chauffage", "pac_ecs", "pac_aucune", "cad_signature",
          "cad_vide", "gaz_signature", "gaz_vide")


# ---------------------------------------------------------------- formats français


def nb(x, nd=0, signe=False):
    if x is None:
        return "—"
    if round(x, nd) == 0:
        x = 0.0  # pas de « −0,0 »
    s = f"{x:+,.{nd}f}" if signe else f"{x:,.{nd}f}"
    if signe and round(x, nd) == 0:
        s = s.replace("+", "±")
    return s.replace(",", " ").replace(".", ",").replace("-", "−")


def pct(x, nd=0, signe=False):
    return "—" if x is None else nb(100 * x, nd, signe) + " %"


def amp(det, a):
    if a is None:
        return "non atteint"
    if det in ("eau_nuit",):
        return nb(a, 0) + " l/h"
    if det == "eau_vide":
        return nb(a, 0) + " l/j"
    if det.endswith("_vide"):
        return "× " + nb(a, 2)
    return nb(100 * a, 0 if abs(100 * a - round(100 * a)) < 0.05 else 1) + " %"


def plage(q, nd=0, signe=True):
    """« médiane (min à max) » d'un résumé de quantiles (rapports exprimés en %)."""
    if not q:
        return "—"
    return f"{pct(q['mediane'], nd, signe)} ({pct(q['min'], nd, signe)} à {pct(q['max'], nd, signe)})"


def lire(nom):
    chemin = os.path.join(SORTIES, nom)
    if not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


class Contexte:
    def __init__(self):
        self.s = M.styles()
        self.fig = 0
        self.tab = 0
        self.h = lire(os.path.join("horaire", "resume.json"))            # campagne principale (horaire, 12 mois)
        self.hav = lire(os.path.join("horaire_avant", "resume.json"))    # V0.2.0, expérience de chiffrage
        self.av = lire(os.path.join("avant", "resume.json"))             # campagne précédente (15 min, 120 j)
        self.ap = lire(os.path.join("apres", "resume.json"))
        self.d = lire("donnees.json")
        self.b = lire("biais_attendu.json")
        self.b_15 = lire("biais_attendu_v020_15min.json")
        self.v = lire("validation.json")
        self.temps = lire("temps_exemple.json")
        self.camp = lire(os.path.join("horaire", "campagne.json"))
        self.camp_15 = lire(os.path.join("apres", "campagne.json"))
        self.ref = service.defauts()

    def p(self, texte, style="corps"):
        return Paragraph(texte, self.s[style])

    def puces(self, items):
        return [Paragraph(x, self.s["puce"], bulletText="•") for x in items]

    def figure(self, nom, legende, largeur=M.UTILE):
        self.fig += 1
        return M.figure(os.path.join(FIG, nom), largeur, legende, self.s, self.fig)  # liste [image, légende]

    def tableau(self, lignes, largeurs, legende, **kw):
        self.tab += 1
        return [M.legende_tableau(legende, self.s, self.tab), M.tableau(lignes, largeurs, self.s, **kw), Spacer(1, 8)]

    def h1(self, numero, texte):
        return [CondPageBreak(60 * M.mm), M.Titre(f"{numero}&nbsp;&nbsp;{texte}", self.s["h1"], 0, f"s{numero}"),
                M.FiletTitre(), Spacer(1, 6)]

    def h2(self, numero, texte):
        return [CondPageBreak(35 * M.mm), M.Titre(f"{numero}&nbsp;&nbsp;{texte}", self.s["h2"], 1, f"s{numero}")]

    def h3(self, texte):
        return Paragraph(texte, self.s["h3"])


# ---------------------------------------------------------------- page de titre et sommaire


def page_titre(c):
    s = c.s
    from reportlab.lib.styles import ParagraphStyle
    blanc = ParagraphStyle("t", fontName="Texte-Leger", fontSize=11, leading=15, textColor=M.colors.white)
    titre = ParagraphStyle("tt", fontName="Texte-Demi", fontSize=27, leading=33, textColor=M.colors.white)
    sur = ParagraphStyle("st", fontName="Texte-Demi", fontSize=9, leading=12, textColor=M.BLEU_TRAIT)
    out = [Spacer(1, 18 * M.mm), Paragraph("VIGIE · XREAD DÉRIVES · DOCUMENT TECHNIQUE", sur), Spacer(1, 7 * M.mm),
           Paragraph("Détection des dérives par fluide", titre),
           Paragraph("Méthodes, données et évaluation", titre), Spacer(1, 6 * M.mm),
           Paragraph("Eau, chaleur, électricité, pompes à chaleur et qualité des données, sur relevés horaires et un an "
                     "d'historique : règles de détection, chiffrage mesuré, données utilisées, campagne d'évaluation "
                     "et révisions du moteur V0.2.", blanc),
           Spacer(1, 46 * M.mm)]
    camp = c.camp or {}
    meta = [["Objet", "Calcul des dérives par fluide au pas horaire, chiffrage sans annualisation du chauffage et des "
                      "PAC, priorisation, évaluation des règles"],
            ["Version évaluée", "Moteur Vigie V0.2 révisé (R1 à R12) ; copie figée V0.2.0 pour les comparaisons"],
            ["Données", "Consommations SIMULÉES (fictives), relevés horaires, 12 mois d'historique ; température réelle "
                        "MétéoSuisse, station Genève-Cointrin (GVE), et température fictive"],
            ["Campagne", f"{nb(camp.get('scenarios'))} scénarios, bases SQLite temporaires, série météo figée le "
                         f"{(camp.get('meteo_reelle') or '')[:10]}"],
            ["Valeurs monétaires", "Tarifs et facteurs CO₂ = valeurs d'EXEMPLE du référentiel, jamais des valeurs réelles"],
            ["Date", date.today().strftime("%d.%m.%Y")]]
    out.append(M.tableau([[f"<b>{a}</b>", b] for a, b in meta], [38 * M.mm, M.UTILE - 38 * M.mm], s, entete=0,
                         zebre=True))
    out += [Spacer(1, 10 * M.mm),
            M.encadre("Ce document traite uniquement du calcul des dérives : méthodes de détection et de chiffrage, "
                      "données des fluides, données météo, protocole et résultats d'évaluation, révisions du moteur, "
                      "limites. Il ne décrit ni l'interface, ni les bons de travaux, ni la carte du parc.", s,
                      fond=M.GRIS_FOND, trait=M.NUIT)]
    return out


def sommaire(c):
    return [NextPageTemplate("contenu"), PageBreak(), Paragraph("Sommaire", c.s["h1"]), M.FiletTitre(), Spacer(1, 8),
            M.sommaire(c.s), PageBreak()]


# ---------------------------------------------------------------- outils sur les résultats


def courbe(res, det, met):
    return (res or {}).get("balayage", {}).get(f"{det}|{met}")


def seuil50(res, det, met):
    b = courbe(res, det, met)
    return b["seuil50"] if b else None


def erreur_med(res, det, met):
    b = courbe(res, det, met)
    return (b or {}).get("erreur_chiffrage") or {}


def delai(res, det, met):
    return (res or {}).get("delai", {}).get(f"{det}|{met}")


def chiffrage(res, det, met="reelle"):
    return ((res or {}).get("chiffrage") or {}).get(f"{det}|{met}") or {}


def ecart_principal(r):
    """Écart au réel du montant principal : dérive constatée (moteur actuel) ou montant annuel (V0.2.0)."""
    return r.get("ecart_mesure") or r.get("ecart_annuel")


def pas_detection(res, det, p, amplitudes=None):
    """(détectées, scénarios) au pas `p` pour les ampleurs données (défaut : robustesse et nominale), toutes météos."""
    from .campagne import NOMINALE, ROBUSTE
    k = n = 0
    for a in amplitudes or (ROBUSTE[det], NOMINALE[det]):
        for met in ("fictive", "reelle"):
            r = ((res or {}).get("pas") or {}).get(f"{det}|{met}|{p}|{a}")
            if r:
                k, n = k + r["detectees"], n + r["n"]
    return k, n


def pas_fausses(res, det, p):
    """(alertes énergie sur immeubles sains, scénarios) au pas `p`, toutes météos."""
    k = n = 0
    for met in ("fictive", "reelle"):
        r = ((res or {}).get("pas") or {}).get(f"{det}|{met}|{p}|0")
        if r:
            k += r["detectees"] + sum(r["autres_alertes"].values())
            n += r["n"]
    return k, n


TYPE_SAIN = {"eau_nuit": "eau_nuit", "chaleur_signature": "eau_nuit", "elec_nuit": "eau_nuit", "eau_vide": "chaleur_vide",
             "chaleur_vide": "chaleur_vide", "pac_totale": "pac_totale", "pac_chauffage": "pac_chauffage",
             "pac_ecs": "pac_ecs", "pac_aucune": "pac_aucune", "cad_signature": "cad_signature", "cad_vide": "cad_vide",
             "gaz_signature": "gaz_signature", "gaz_vide": "gaz_vide"}
TYPE_DELAI = {"eau_nuit": "chaufferie", "chaleur_vide": "vide", "pac_totale": "pac_totale", "pac_chauffage": "pac_chauffage",
              "pac_ecs": "pac_ecs", "pac_aucune": "pac_aucune", "cad_signature": "chaufferie_cad", "cad_vide": "vide_cad",
              "gaz_signature": "chaufferie_gaz", "gaz_vide": "vide_gaz"}


def fausses(res, det, met):
    """(fausses alertes de la cause du détecteur, analyses d'immeubles sains) : 30 graines + suivi quotidien 61 j."""
    from .campagne import CAUSE
    cause = CAUSE[det]
    t = TYPE_SAIN[det]
    sain = res["sain"].get(f"{t}|{met}") or {}
    ds = res["delai_sain"].get(f"{TYPE_DELAI[t]}|{met}") or {}
    k = sain.get("par_cause", {}).get(cause, 0) + ds.get("par_cause", {}).get(cause, 0)
    n = sain.get("n", 0) + ds.get("immeubles_jours", 0)
    return k, n


def fausses_toutes(res, met):
    k = sum(sum(v["par_cause"].values()) for kk, v in res["sain"].items() if kk.endswith("|" + met))
    k += sum(sum(v["par_cause"].values()) for kk, v in res["delai_sain"].items() if kk.endswith("|" + met))
    n = sum(v["n"] for kk, v in res["sain"].items() if kk.endswith("|" + met))
    n += sum(v["immeubles_jours"] for kk, v in res["delai_sain"].items() if kk.endswith("|" + met))
    return k, n


def robuste(res, variante, det, sain=False):
    return (res or {}).get("robustesse", {}).get(f"{variante}|{det}|{'sain' if sain else 'derive'}")


def projection(res, det, met="reelle"):
    """(écart à l'année normale, étendue sur les années réelles 2016-2025) de la projection 12 mois."""
    r = chiffrage(res, det, met)
    return r.get("ecart_proj"), r.get("ecart_proj_annees")


def biais(b, modele, met, version):
    r = (b or {}).get("resume", {}).get(f"{modele}|{met}|{version}") or {}
    return r


# ---------------------------------------------------------------- 1. synthèse


def synthese(c):
    h = c.h
    out = c.h1(1, "Synthèse")
    gen = h["generateur"]
    n_gen = sum(v["graines"] for v in gen.values())
    fa_gen = sum(v["fausses_total"] for v in gen.values())
    fn_gen = sum(v["manquees_total"] for v in gen.values())
    kf, nf = fausses_toutes(h, "fictive")
    kr, nr = fausses_toutes(h, "reelle")
    out.append(c.p(
        "Vigie repère, dans les courbes de comptage d'un parc immobilier, les dérives qui coûtent (fuite, chauffage "
        "déréglé, électricité de nuit, pompe à chaleur dégradée) et les défauts de mesure, puis les chiffre en kWh, m³, "
        "CHF et CO₂. Cette révision part de deux constats sur les données réelles : <b>elles arrivent au mieux à "
        "l'heure</b> (jamais au quart d'heure, parfois une fois par jour), et l'on dispose d'<b>un an d'historique</b>. "
        "Le moteur, le générateur d'exemple et la campagne d'évaluation travaillent donc au pas horaire sur 12 mois. "
        "Chaque alerte sépare deux notions : la <b>dérive constatée</b> (mesurée depuis son début, seule base de "
        "l'alerte, du bon et de la priorité) et une <b>projection</b> sur 12 mois si rien n'est fait, étiquetée avec son "
        "hypothèse (climat normal de Genève ou dérive constante), qui ne déclenche jamais rien. Deux fluides de "
        "chauffage sont ajoutés : le <b>chauffage à distance (CAD)</b> et le <b>gaz</b>."))
    signature = chiffrage(h, "chaleur_signature")
    signature_av = chiffrage(c.hav, "chaleur_signature")
    out.append(M.chiffres_cles([
        (f"{nb(n_gen)}", "exemples officiels régénérés au pas horaire (4 configurations × 20 graines) : "
                         f"{nb(fa_gen)} fausse alerte, {nb(fn_gen)} dérive manquée"),
        (f"{nb(kf + kr)} / {nb(nf + nr)}", "fausses alertes sur analyses d'immeubles sains simulés (météo fictive et réelle)"),
        (pct((ecart_principal(signature) or {}).get("mediane"), 0, True),
         "écart médian au réel de la dérive constatée (signature, oct. à avr.) ; "
         f"{pct((signature_av.get('ecart_annuel') or {}).get('mediane'), 0, True)} avec l'ancienne annualisation"),
        ("100 %", "précision et rappel des 4 évaluations officielles ; "
                  f"{nb((c.v or {}).get('tests', {}).get('tests'))} tests verts")], c.s))
    out.append(Spacer(1, 10))
    from .pdf_resultats import tableau_synthese
    out += tableau_synthese(c)
    out.append(c.h3("Ce qui change dans cette version (détail et mesures au chapitre 9)"))
    out += c.puces([
        "<b>Pas horaire partout</b> : compteurs déclarés à 60 min par défaut, générateur et simulateur relevés à l'heure ; "
        "un relevé journalier n'est attribué à aucune heure et ne sert qu'aux règles journalières (R8, R12).",
        "<b>Dérive constatée</b> : excès cumulé heure par heure depuis le début de la dérive (chauffage, CAD, gaz, "
        "PAC) ou excès constaté × heures mesurées (eau, électricité) ; rythme mensuel au climat des derniers jours (R9).",
        "<b>Projection séparée</b> : coût sur 12 mois si rien n'est fait, au climat normal de Genève (degrés-jours "
        "GVE 2016-2025) pour le chauffage et les PAC, dérive constante pour l'eau et l'électricité ; affichée comme "
        "hypothèse, hors du score et de la gravité, absente du bon envoyé au prestataire (R13).",
        "<b>CAD et gaz</b> : signature énergétique et immeuble vide, tarifs et facteurs CO₂ d'exemple, gaz en m³ "
        "converti par le pouvoir calorifique ; exemple officiel sur 12 mois avec deux immeubles CAD et deux au gaz "
        "(R14, R15).",
        "<b>Référence d'un an</b> : l'attendu du chauffage et de la PAC est appris sur la même saison de l'année "
        "précédente et les 60 jours récents ; repli sur toute la période antérieure si cette saison manque (R10).",
        "<b>Priorisation sur la mesure</b> : score = rythme mensuel constaté en CHF × confiance × urgence, comparable "
        "entre fluides ; la projection n'y entre pas ; enjeu minimal en CHF par mois (R11).",
        "Révisions R1 à R7 de la campagne précédente (trous d'index, heures et nuits incomplètes, jour en cours, "
        "jours lacunaires, abaissement nocturne, référence gelée) conservées et revérifiées au pas horaire."])
    out.append(c.h3("Limites qui restent (chapitre 10)"))
    k1, n1 = pas_detection(h, "eau_nuit", 1440)
    out += c.puces([
        f"Au pas journalier, la fuite de nuit, l'électricité de nuit et les PAC ne sont plus surveillées (fuite de nuit "
        f"détectée {nb(k1)} fois sur {nb(n1)} au pas journalier) : le pas horaire est nécessaire pour ces règles.",
        "Le chiffrage mesuré commence au début détecté de la dérive : la part antérieure (dérive progressive, jours "
        "sous le seuil) n'est pas comptée ; « immeuble vide » est chiffré au-dessus du talon déclaré, donc sous-estimé.",
        "Un changement d'occupation non déclaré ressemble à une dérive (ou la masque) ; les périodes déclarées manquent.",
        "Toutes les consommations sont simulées (lois linéaires) : ces résultats valident la logique et la robustesse "
        "du calcul, pas son taux de pertinence sur un parc réel."])
    return out


if __name__ == "__main__":
    from evaluation.pdf_revisions import construire
    construire()
