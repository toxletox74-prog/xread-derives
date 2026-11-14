"""Document « Une méthode de détection par fluide et par pas de relevé » (PDF, reportlab).

    python -m evaluation.pdf_methodes_par_pas

Les seuils, les durées et la matrice fluide × pas sont LUS dans le moteur (vigie/regles.py) : le document dit ce que le
code fait. Les chiffres du chapitre « Ce que les données ont montré » sont des mesures faites sur le lot communal
(13 et 14.11.2026) ; ils sont à remesurer si les règles ou les données changent.
"""
import os
import sqlite3
from datetime import date

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer)

from vigie import moteur, parc, regles, service

from . import pdf_mise_en_page as M

SORTIE = os.path.join(service.RACINE, "docs", "Xread_Derives_methodes_par_pas_de_releve.pdf")
TITRE = "Xread Dérives · Une méthode de détection par fluide et par pas de relevé"
R = moteur.regles_effectives({})
TOTAL = [None]


def nombre(x):
    """Nombre au format français, sans décimale inutile."""
    return (f"{x:g}" if float(x) != int(x) else str(int(x))).replace(".", ",")


def reglage(cause):
    """« seuil unité, durée » d'une règle, tel que le moteur l'applique par défaut."""
    r = R[cause]
    return f"{nombre(r['seuil'])} {r['unite_seuil']}, tenu {r['persistance']} {r['unite_persistance']}"


# ---------------------------------------------------------------- gabarits de page


def page_contenu(c, doc):
    c.saveState()
    c.setStrokeColor(M.GRIS_LIGNE)
    c.setLineWidth(0.5)
    c.line(M.MARGE_G, M.HAUTEUR - 13 * M.mm, M.LARGEUR - M.MARGE_D, M.HAUTEUR - 13 * M.mm)
    c.setFont("Texte-Demi", 7.4)
    c.setFillColor(M.NUIT)
    c.drawString(M.MARGE_G, M.HAUTEUR - 11 * M.mm, "Xread Dérives")
    c.setFont("Texte", 7.4)
    c.setFillColor(M.GRIS)
    c.drawString(M.MARGE_G + 50, M.HAUTEUR - 11 * M.mm, "· Une méthode de détection par fluide et par pas de relevé")
    c.drawRightString(M.LARGEUR - M.MARGE_D, M.HAUTEUR - 11 * M.mm, f"V0.3.0 · {date.today():%d.%m.%Y}")
    c.line(M.MARGE_G, 13 * M.mm, M.LARGEUR - M.MARGE_D, 13 * M.mm)
    c.setFont("Texte", 7)
    c.drawString(M.MARGE_G, 9 * M.mm, "Seuils et durées : valeurs par défaut, réglables dans « Règles & coûts » · tarifs = valeurs d'EXEMPLE")
    c.setFont("Texte-Demi", 7.6)
    c.setFillColor(M.NUIT)
    c.drawRightString(M.LARGEUR - M.MARGE_D, 9 * M.mm, f"{doc.page} / {TOTAL[0]}" if TOTAL[0] else str(doc.page))
    c.restoreState()


class Document(BaseDocTemplate):
    def __init__(self, chemin):
        super().__init__(chemin, pagesize=(M.LARGEUR, M.HAUTEUR), leftMargin=M.MARGE_G, rightMargin=M.MARGE_D,
                         topMargin=M.MARGE_H, bottomMargin=M.MARGE_B, title=TITRE, author="Xread Dérives (Vigie)",
                         subject="Méthodes de détection des dérives selon le pas de relevé")
        cadre = Frame(M.MARGE_G, M.MARGE_B, M.UTILE, M.HAUTEUR - M.MARGE_H - M.MARGE_B, id="normal", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("titre", [cadre], onPage=M.page_titre),
                               PageTemplate("contenu", [cadre], onPage=page_contenu)])

    def afterFlowable(self, f):
        if isinstance(f, M.Titre):
            self.canv.bookmarkPage(f.cle)
            self.canv.addOutlineEntry(f.texte_brut, f.cle, level=f.niveau, closed=False)
            self.notify("TOCEntry", (f.niveau, f.texte_brut, self.page, f.cle))


class Redaction:
    """Petits outils de rédaction : titres numérotés, paragraphes, puces, fiches de méthode."""

    def __init__(self):
        self.s, self.n1, self.n2, self.tab = M.styles(), 0, 0, 0

    def h1(self, texte):
        self.n1, self.n2 = self.n1 + 1, 0
        return [CondPageBreak(60 * M.mm), M.Titre(f"{self.n1}. {texte}", self.s["h1"], 0, f"c{self.n1}"), M.FiletTitre(),
                Spacer(1, 4)]

    def h2(self, texte):
        self.n2 += 1
        return [CondPageBreak(38 * M.mm), M.Titre(f"{self.n1}.{self.n2} {texte}", self.s["h2"], 1, f"c{self.n1}-{self.n2}")]

    def p(self, texte):
        return Paragraph(texte, self.s["corps"])

    def puces(self, lignes):
        return [Paragraph(x, self.s["puce"], bulletText="•") for x in lignes]

    def tableau(self, legende, lignes, largeurs, **kw):
        self.tab += 1
        return [M.legende_tableau(legende, self.s, self.tab), M.tableau(lignes, largeurs, self.s, **kw), Spacer(1, 8)]

    def fiche(self, pas, methode, calcul, reglages, justification, limites):
        """Une méthode pour un pas de relevé : ce qu'on calcule, quand on alerte, pourquoi c'est une dérive."""
        s, etiquette = self.s, ParagraphStyle("et", parent=self.s["cellule"], fontName="Texte-Demi", textColor=M.NUIT)
        corps = ParagraphStyle("fc", parent=s["cellule"], fontSize=8.3, leading=11.4)
        formules = ParagraphStyle("ff", parent=s["formule"], fontSize=7.9, leading=11.4)
        lignes = [[Paragraph("Méthode", etiquette), Paragraph(methode, corps)],
                  [Paragraph("Calcul", etiquette),
                   Paragraph("<br/>".join(x.replace("  ", "&nbsp;&nbsp;") for x in calcul), formules)],
                  [Paragraph("Seuil et durée", etiquette), Paragraph(reglages, corps)],
                  [Paragraph("Ce qui justifie la dérive", etiquette), Paragraph(justification, corps)],
                  [Paragraph("Limites", etiquette), Paragraph(limites, corps)]]
        titre = Paragraph(f"Relevé {pas}", ParagraphStyle("fp", parent=s["h3"], spaceBefore=6))
        return [CondPageBreak(52 * M.mm), titre, M.tableau(lignes, [33 * M.mm, M.UTILE - 33 * M.mm], s, entete=0), Spacer(1, 4)]


# ---------------------------------------------------------------- contenu


def page_titre(d):
    blanc = ParagraphStyle("t", fontName="Texte-Leger", fontSize=11, leading=15, textColor=M.colors.white)
    titre = ParagraphStyle("tt", fontName="Texte-Demi", fontSize=25, leading=31, textColor=M.colors.white)
    sur = ParagraphStyle("st", fontName="Texte-Demi", fontSize=9, leading=12, textColor=M.BLEU_TRAIT)
    meta = [["Objet", "Dire, pour chaque fluide et pour chaque finesse de relevé (quart d'heure, heure, jour, mois), quelle "
                      "méthode calcule la dérive, avec quel calcul, et ce qui justifie de parler de dérive"],
            ["Version", f"Xread Dérives V0.3.0 · {len(regles.REGLES)} règles de dérive, réglables dans « Règles &amp; coûts »"],
            ["Source", "Seuils, durées et matrice lus dans le moteur (vigie/regles.py) au moment de la génération"],
            ["Mesures citées", "Lot communal fictif : 172 compteurs mensuels 2021-2025, 38 courbes 2025"],
            ["Date", date.today().strftime("%d.%m.%Y")]]
    return [Spacer(1, 18 * M.mm), Paragraph("XREAD DÉRIVES · DOCUMENT DE MÉTHODE", sur), Spacer(1, 7 * M.mm),
            Paragraph("Une méthode de détection", titre), Paragraph("par fluide et par pas de relevé", titre),
            Spacer(1, 6 * M.mm),
            Paragraph("Un relevé au quart d'heure, à l'heure, au jour ou au mois ne montre pas la même chose. Xread Dérives "
                      "choisit donc la méthode de détection selon la finesse des données de chaque compteur. Ce document "
                      "décrit chaque méthode, son calcul et sa justification.", blanc),
            Spacer(1, 44 * M.mm),
            M.tableau([[f"<b>{a}</b>", b] for a, b in meta], [34 * M.mm, M.UTILE - 34 * M.mm], d.s, entete=0),
            Spacer(1, 10 * M.mm),
            M.chiffres_cles([(str(len(regles.FLUIDES_MATRICE)), "fluides surveillés"),
                             (str(len(regles.PAS_MATRICE)), "pas de relevé : quart d'heure, heure, jour, mois"),
                             (str(len(regles.REGLES)), "règles de dérive, une méthode par fluide et par pas")], d.s),
            Spacer(1, 8 * M.mm),
            M.encadre("<b>À retenir.</b> Le moteur applique à chaque compteur la méthode la plus fine que son relevé "
                      "permet, et le dit quand une règle ne peut pas tourner. Une dérive n'est déclarée que par "
                      "comparaison à une référence d'avant la dérive, à conditions égales, et tenue dans la durée.",
                      d.s, fond=M.GRIS_FOND, trait=M.NUIT),
            NextPageTemplate("contenu"), PageBreak(), Paragraph("Sommaire", d.s["h1"]), M.FiletTitre(), Spacer(1, 8),
            M.sommaire(d.s), PageBreak()]


def essentiel(d):
    petit = ParagraphStyle("mc", parent=d.s["cellule"], fontSize=7.1, leading=9.2)
    lignes = [["Fluide"] + [libelle for _pas, libelle in regles.PAS_MATRICE]]
    for ligne in regles.matrice():
        cases = [Paragraph("<br/>".join("• " + x["methode"] for x in c["regles"]) or "—", petit) for c in ligne["cases"]]
        lignes.append([Paragraph(f"<b>{ligne['fluide']}</b>", petit)] + cases)
    largeur = (M.UTILE - 26 * M.mm) / 4
    out = d.h1("L'essentiel")
    out += [d.p("La finesse d'un relevé décide de ce qu'on peut observer, donc de la méthode qui détecte une dérive. "
                "<b>Le moteur applique à chaque compteur la méthode la plus fine que son relevé permet</b> : il n'applique "
                "jamais une méthode horaire à un relevé journalier, ni une méthode journalière à un relevé mensuel."),
            *d.puces(["<b>Quart d'heure et heure</b> : on voit la nuit, la journée et les coupures. Les méthodes regardent "
                      "le fonctionnement heure par heure.",
                      "<b>Jour</b> : on ne voit plus la nuit, mais le niveau de base, le type de jour et la météo du jour.",
                      "<b>Mois</b> : il ne reste que la saison. La seule méthode fiable est la comparaison au même mois des "
                      "années précédentes, ramenée à conditions égales (climat, ensoleillement, chaleur produite)."]),
            Spacer(1, 4)]
    out += d.tableau("La méthode appliquée selon le fluide et le pas du relevé (source : vigie/regles.py)", lignes,
                     [26 * M.mm] + [largeur] * 4, zebre=True)
    out += [M.encadre("<b>Lecture.</b> Un compteur relevé au jour reçoit aussi la règle du mois (elle travaille sur le "
                      "cumul mensuel), mais elle se tait si la méthode journalière est déjà en alerte : une seule alerte "
                      "par cause et par immeuble. L'interface dit où une règle ne peut pas tourner : bannière du tableau de "
                      "bord, section « Couverture des règles », mention « sans effet ici » sur la fiche de l'immeuble.", d.s)]
    return out


def pourquoi(d):
    out = d.h1("Pourquoi la méthode dépend du pas")
    lignes = [["Pas du relevé", "Ce qu'on observe", "Ce qu'on ne peut plus voir", "Délai de détection typique"],
              ["Quart d'heure", "Coupures brèves, forme de la journée, nuit", "—", "1 à 7 jours"],
              ["Heure", "Nuit et jour, abaissement nocturne, rendement heure par heure", "Coupures plus courtes que l'heure",
               "3 à 7 jours"],
              ["Jour", "Niveau de base, type de jour (ouvré ou non), météo du jour", "La nuit, le rendement instantané",
               "3 à 7 jours"],
              ["Mois", "La saison et l'année", "Tout ce qui dure moins de quelques semaines", "2 à 3 mois"]]
    out += d.tableau("Ce qu'un relevé permet d'observer", lignes, [26 * M.mm, 58 * M.mm, 50 * M.mm, M.UTILE - 134 * M.mm])
    out += [d.p("Appliquer une méthode à un relevé trop grossier donne soit rien, soit une fausse alerte. Exemple : la "
                "fuite d'eau de nuit se lit dans le débit minimum entre 1 h et 5 h. Sur un relevé journalier, ce débit "
                "n'existe pas : la règle ne tourne pas, et c'est le niveau de base (le minimum sur 7 jours) qui prend le "
                "relais. Sur un relevé mensuel, ni l'un ni l'autre n'est visible : on compare le mois au même mois des "
                "années précédentes.")]
    return out


def principes(d):
    out = d.h1("Les principes communs à toutes les méthodes")
    out += [d.p("Quelle que soit la méthode, une dérive n'est déclarée que si cinq conditions sont réunies. Ce sont elles "
                "qui justifient le mot « dérive » plutôt que « variation »."),
            *d.puces([
                "<b>Une référence d'avant la dérive.</b> L'attendu est appris sur une période antérieure à la fenêtre "
                "d'analyse (30 jours), puis gelé tant que l'alerte est ouverte : la dérive ne devient jamais la norme.",
                "<b>À conditions égales.</b> On ne compare jamais deux valeurs brutes : même météo pour le chauffage, même "
                "ensoleillement pour le solaire, même type de jour pour les bâtiments occupés en semaine, même chaleur "
                "produite pour une pompe à chaleur.",
                "<b>Jamais d'extrapolation.</b> Un jour n'est jugé que si la référence contient des jours comparables plus "
                "froids ET plus doux que lui. Sinon il n'est pas jugé, et la règle ne conclut pas.",
                "<b>Une durée minimale.</b> Un pic isolé n'est pas une dérive : l'écart doit tenir plusieurs nuits, "
                "plusieurs jours ou plusieurs mois de suite (seule exception voulue : une coupure d'onduleur).",
                "<b>La qualité d'abord.</b> Un compteur muet, incomplet, à valeurs négatives ou à index qui recule produit "
                "une alerte « Données » et aucune alerte de dérive. Un trou n'est jamais comblé pour décider."]),
            d.p("Le chiffrage suit la même logique pour toutes les méthodes : <b>dérive constatée</b> = somme des écarts "
                "mesurés depuis le début ; <b>rythme mensuel</b> = écart des 30 derniers jours ; <b>projection sur 12 mois</b> "
                "= hypothèse, jamais un déclencheur. Une dérive sous 8,22 CHF par mois est masquée, sauf risque de sinistre.")]
    return out


def eau(d):
    out = d.h1("Eau")
    out += d.fiche("au quart d'heure ou à l'heure", "Fuite de nuit : le débit minimum entre 1 h et 5 h.",
                   ["débit_min(nuit) = plus petit débit horaire entre 1 h et 5 h",
                    "dérive si débit_min &gt; seuil, plusieurs nuits de suite",
                    "volume perdu = (débit_min − débit de référence) × heures mesurées"],
                   reglage("eau_nuit") + ". Gravité critique, risque de sinistre.",
                   "La nuit, un immeuble sain passe par zéro : personne ne tire d'eau à 3 h. Un débit qui ne retombe jamais "
                   "sous 20 l/h, trois nuits de suite, coule en continu : c'est une fuite ou une chasse d'eau bloquée.",
                   "Une nuit n'est jugée que si 3 heures sur 4 sont mesurées. Invisible au pas journalier.")
    out += d.fiche("au jour", "Niveau de base : le minimum de consommation sur 7 jours glissants.",
                   ["base(j) = plus petite consommation des 7 derniers jours",
                    "dérive si base(j) &gt; max(2 × base de référence, base de référence + 480 l/jour)"],
                   reglage("eau_talon") + " (et au moins +480 l/jour, soit 20 l/h en continu).",
                   "Une fuite coule tous les jours, y compris le week-end le plus creux : elle relève le minimum. Un pic "
                   "d'usage (remplissage d'un bassin, manifestation) ne le change pas. Sept jours contiennent toujours un "
                   "week-end.",
                   "Peu sensible sur un très gros consommateur : 20 l/h ne doublent pas une base de 30 000 l/jour.")
    out += d.fiche("au mois", "Le même mois des années précédentes, sans correction du climat.",
                   ["attendu(mois) = médiane du même mois des 3 années précédentes (2 au moins)",
                    "dérive si mesuré &gt; attendu × (1 + seuil) et mesuré − attendu &gt; 480 l/jour"],
                   reglage("eau_historique") + ".",
                   "L'eau d'un bâtiment suit son usage, qui se répète d'une année à l'autre au même mois. Un mois 20 % "
                   "au-dessus de ses trois homologues, deux fois de suite, n'est plus une variation d'usage.",
                   "Deux mois de délai. Un changement d'usage non déclaré ressort comme une dérive.")
    out += [d.p(f"<b>Immeuble vide</b> (à l'heure ou au jour) : toute consommation au-delà de {reglage('eau_vide')} est "
                "signalée, car un immeuble déclaré vide ne doit rien consommer.")]
    return out


def electricite(d):
    out = d.h1("Électricité")
    out += d.fiche("au quart d'heure ou à l'heure", "Puissance de nuit comparée aux nuits de référence.",
                   ["P_nuit(j) = puissance moyenne entre 1 h et 5 h",
                    "site insensible au froid : référence = médiane des nuits J−50 à J−20",
                    "site qui suit le froid (PAC, chauffage électrique) : référence = nuits de même froid",
                    "  (± 2 degrés, nuits plus froides ET plus douces exigées, ramenées au froid de la nuit jugée)",
                    "dérive si P_nuit &gt; référence × (1 + seuil)"],
                   reglage("elec_nuit") + ".",
                   "La nuit, seuls tournent les équipements permanents (ventilation, éclairage de sécurité, veilles). "
                   "Une hausse durable de ce socle signale un équipement resté en marche ou une minuterie déréglée. "
                   "Dans un bâtiment chauffé à l'électricité, la nuit monte avec le froid : la comparaison se fait donc "
                   "à température extérieure égale, sinon la règle sonnait à chaque entrée dans l'hiver.",
                   "Ne voit pas une dérive qui n'existe qu'en journée. Un site est dit sensible au froid si sa puissance "
                   "de nuit suit la température dans sa propre référence (corrélation d'au moins 0,5).")
    out += d.fiche("au jour", "Chaque jour comparé aux jours de même type.",
                   ["type de jour = ouvré, ouvré en vacances scolaires, ou non ouvré (calendrier du lot)",
                    "attendu(j) = médiane des jours de même type des 8 semaines de référence",
                    "dérive si consommation(j) &gt; attendu(j) × (1 + seuil)"],
                   reglage("elec_jour") + ".",
                   "Sans la nuit, la seule comparaison juste est celle d'un mardi avec d'autres jours ouvrés, d'un dimanche "
                   "avec d'autres dimanches : dans un bâtiment de bureaux, un week-end consomme deux fois moins.",
                   "Un type de jour absent de la référence (moins de 4 jours) n'est pas jugé.")
    out += d.fiche("au mois", "Le même mois des années précédentes, à climat égal.",
                   ["attendu(mois) = référence du même mois + pente × (degrés-jours du mois − degrés-jours de la référence)",
                    "pente apprise sur l'historique du compteur (nulle s'il ne suit pas le climat)"],
                   reglage("elec_historique") + ".",
                   "Trois mois de suite au-dessus du même mois des années précédentes : la hausse n'est ni saisonnière ni "
                   "passagère. La durée est de 3 mois, et non 2, car les écarts de 2 mois mesurés sur 2022-2025 étaient "
                   "groupés sur les mêmes mois d'intersaison (effet du climat).",
                   "Un nouvel équipement ou un changement d'horaires ressort comme une dérive.")
    return out


def chauffage(d):
    out = d.h1("Gaz, chaleur de chaufferie et chauffage à distance")
    out += [d.p("Ces trois fluides suivent la météo de la même façon : la méthode est identique, seul le compteur change "
                "(gaz consommé, chaleur produite, chaleur livrée à la sous-station).")]
    out += d.fiche("au quart d'heure, à l'heure ou au jour", "Signature énergétique : la consommation du jour à météo égale.",
                   ["DJ(j) = degrés-jours base 16 °C du jour (température horaire de la station météo)",
                    "avec la même saison de l'an passé : attendu(j) = a + b × DJ(j) (+ c × DJ de nuit, à l'heure)",
                    "en première année : attendu(j) = médiane des jours comparables (± 2 DJ, même type de jour),",
                    "                     chacun ramené au DJ du jour par la pente locale",
                    "dérive si mesuré(j) &gt; attendu(j) × (1 + seuil)"],
                   reglage("gaz_signature") + " (mêmes valeurs pour la chaleur et le chauffage à distance).",
                   "À température extérieure égale, un bâtiment bien réglé consomme la même chose. Sept jours de suite à "
                   "plus de 10 % au-dessus de sa propre signature signalent un réglage qui a bougé : courbe de chauffe, "
                   "consigne de départ, sonde extérieure.",
                   "En première saison de chauffe, rien n'est conclu tant que la référence ne contient pas de jour aussi "
                   "froid. Sans jour jugeable depuis 10 jours, la règle ne conclut plus.")
    out += d.fiche("à l'heure (chauffage à distance)", "Température de retour à température extérieure égale.",
                   ["T_retour attendue(j) = a + b × T_extérieure(j), apprise sur la référence",
                    "dérive si T_retour(j) &gt; attendue + seuil"],
                   reglage("cad_retour") + ". Non chiffrée en kWh, jamais masquée.",
                   "Un retour trop chaud signifie que l'eau traverse la sous-station sans céder sa chaleur : vanne de "
                   "régulation bloquée ouverte, by-pass, débit excessif. L'énergie livrée peut rester normale.",
                   "Demande les températures de départ et de retour à l'heure.")
    out += d.fiche("au mois", "Le même mois des années précédentes, à climat égal.",
                   ["attendu(mois) = référence du même mois + pente × (degrés-jours du mois − degrés-jours de la référence)",
                    "référence = médiane des 3 années précédentes ; avec 2 années seulement, la plus prudente des deux",
                    "la référence ne remonte jamais avant le dernier changement d'installation du site"],
                   reglage("gaz_historique") + ".",
                   "Une comparaison brute ne tient pas : un mois plus froid fait monter tous les compteurs sans dérive. "
                   "Ramené au climat du mois, un écart de 20 % tenu deux mois ne s'explique plus par la météo.",
                   "Deux années de référence nécessaires. En été, l'écart pèse quelques francs : l'alerte passe sous "
                   "l'enjeu minimal et revient à l'automne.")
    out += [d.p(f"<b>Immeuble vide</b> (à l'heure ou au jour) : chauffage au-delà de {reglage('gaz_vide')}, le talon étant "
                "la consommation de maintien hors gel déclarée pour l'immeuble.")]
    return out


def pac(d):
    out = d.h1("Pompe à chaleur")
    out += d.fiche("au quart d'heure ou à l'heure", "Rendement heure par heure, à météo et chaleur égales.",
                   ["électricité attendue(h) = modèle appris sur la référence : chaleur produite et température extérieure",
                    "rendement relatif = électricité attendue ÷ électricité mesurée",
                    "dérive si rendement relatif &lt; 1 − seuil"],
                   reglage("pac_cop") + ".",
                   "Pour la même chaleur à fournir par la même température, la machine doit consommer la même "
                   "électricité. Une baisse durable de ce rendement désigne la machine elle-même : fluide frigorigène, "
                   "dégivrage, évaporateur encrassé, appoint électrique.",
                   "Fonctionne aussi sans compteur de chaleur, avec une précision moindre.")
    out += d.fiche("au jour", "Électricité de la PAC à météo égale (signature journalière).",
                   ["attendu(j) = signature de l'électricité en fonction des degrés-jours, comme pour le chauffage",
                    "dérive si mesuré(j) &gt; attendu(j) × (1 + seuil)"],
                   reglage("pac_signature") + ".",
                   "Au jour, le rendement instantané n'est plus visible, mais l'électricité d'une PAC suit toujours la "
                   "météo : au-dessus de sa signature une semaine durant, elle consomme trop pour le froid qu'il fait.",
                   "Ne distingue pas une machine moins efficace d'un bâtiment qui demande plus de chaleur.")
    out += d.fiche("au mois", "Le même mois, à chaleur produite égale ; à climat égal sans compteur de chaleur.",
                   ["avec compteur de chaleur :",
                    "  attendu(mois) = chaleur du mois × médiane[électricité ÷ chaleur du même mois]",
                    "  (revient à comparer le rendement du mois à celui des années précédentes)",
                    "sans compteur de chaleur :",
                    "  attendu(mois) = référence du même mois + pente × écart de degrés-jours"],
                   reglage("pac_historique") + ".",
                   "À chaleur produite égale, la demande du bâtiment et la météo sont neutralisées : il ne reste que le "
                   "rendement de la machine. C'est la justification la plus directe (exemple mesuré : rendement de 3,0 au "
                   "lieu de 4,2).",
                   "Un mois où la PAC n'a presque pas tourné (moins de 50 kWh de chaleur) n'est pas jugé.")
    return out


def solaire(d):
    out = d.h1("Production solaire")
    out += [d.p("Ici la dérive est un <b>manque</b> de production. La condition égale est l'ensoleillement, mesuré par le "
                "rayonnement global de la station météo, et la décote annuelle prévue des modules est toujours déduite.")]
    out += d.fiche("au quart d'heure ou à l'heure", "Coupures de l'onduleur : production à zéro entre deux relevés producteurs.",
                   ["jour = heures où le rayonnement de la station météo est positif",
                    "coupure = relevés à zéro encadrés par deux relevés producteurs, en plein jour",
                    "production perdue = moyenne des deux relevés qui encadrent × durée de la coupure"],
                   reglage("solaire_onduleur") + ". Exception voulue à la durée minimale.",
                   "Le soleil ne s'éteint pas : si l'installation produit à 11 h et à 12 h mais rien entre les deux, "
                   "l'onduleur a décroché. C'est un événement franc, pas une variation.",
                   "Un relevé à l'heure ne voit pas une coupure plus courte que l'heure. La nuit, l'aube et une journée "
                   "entière à l'arrêt ne sont pas des coupures.")
    out += d.fiche("au quart d'heure, à l'heure ou au jour", "Journées comparables d'ensoleillement.",
                   ["rendement(j) = production(j) ÷ ensoleillement(j)",
                    "attendu(j) = médiane du rendement des journées comparables (± 30 jours de la même date,",
                    "             ensoleillement à ± 15 %, au moins 5 jours) × (1 − décote) ^ années d'écart",
                    "arrêt : production &lt; 10 % de l'attendu ; panne : chute brutale ; dégradation : baisse progressive"],
                   f"Arrêt : {reglage('solaire_arret')}. Panne : {reglage('solaire_panne')}. "
                   f"Dégradation : {reglage('solaire_degradation')}.",
                   "À ensoleillement égal et à la même saison, une installation saine produit la même chose. Une chute "
                   "brutale désigne un composant (chaîne, diode, cellule) ; une baisse progressive, l'encrassement ou "
                   "l'ombrage.",
                   "Jours couverts (moins de 0,6 kWh/m²) et jours de gel non jugés. Au jour, la répartition de la perte "
                   "dans la journée (matin, midi, après-midi) n'est pas disponible pour le diagnostic.")
    out += d.fiche("au mois", "Rendement du même mois, à ensoleillement égal.",
                   ["rendement(mois) = production du mois ÷ rayonnement du mois",
                    "attendu(mois) = rayonnement du mois × rendement du même mois des années précédentes × décote",
                    "dérive si production &lt; attendu × (1 − seuil)"],
                   reglage("solaire_historique") + ".",
                   "C'est la référence de plusieurs années qui manque aux courbes fines en première année de suivi : "
                   "une baisse lente, apprise peu à peu par la méthode journalière, reste visible d'une année sur l'autre.",
                   "Les mois très peu ensoleillés (moins de 40 kWh/m² : décembre, janvier) ne sont pas jugés.")
    return out


def mesures(d):
    out = d.h1("Ce que les données ont montré")
    out += [d.p("Chaque choix de méthode ci-dessus a été vérifié sur le lot communal. Les mesures qui ont décidé :")]
    lignes = [["Question", "Mesure", "Décision"],
              ["Peut-on comparer un mois au même mois d'avant, sans le climat ?",
               "Gaz et PAC, 2022-2025 : 44 épisodes sur 25 compteurs en comparaison brute ; 3 à climat égal",
               "Correction du climat par les degrés-jours du mois"],
              ["Une seule année de référence suffit-elle ?",
               "Sites fermés début 2021 : 2022 paraissait à +60 % ; eau, 28 épisodes ramenés à 1",
               "2 années au moins, et la plus prudente des deux"],
              ["Un changement d'installation fausse-t-il l'historique ?",
               "Chaudière remplacée par une PAC (S04) : électricité à +120 % sans aucune dérive",
               "Référence jamais antérieure au dernier changement"],
              ["Le type de jour compte-t-il pour le chauffage ?",
               "École, crèche, bibliothèque, administration : jour ouvré +9 à +17 %, jour non ouvré −18 à −25 % ; "
               "logements et piscine ± 4 %",
               "Comparaison entre jours de même type, pour les immeubles où l'effet se voit"],
              ["La médiane des jours comparables est-elle juste ?",
               "Dérive réelle de +20 % lue +14 % ou +28 % ; +19 à +20 % une fois les jours ramenés au même degré-jour",
               "Correction par la pente locale, et jamais d'extrapolation"],
              ["Faut-il juger la PAC au climat ou à la chaleur produite ?",
               "S09 : rendement mensuel de 3,0 au lieu de 4,2, soit +39 % d'électricité à chaleur égale",
               "À chaleur produite égale dès que la chaleur est comptée"],
              ["La nuit d'un bâtiment chauffé à l'électricité se compare-t-elle aux nuits d'avant ?",
               "48 courbes au quart d'heure (synthétiques) : 14 alertes de nuit en décembre sans la température, 3 avec",
               "Nuit comparée aux nuits de même froid pour les sites sensibles"],
              ["Combien de mois pour l'électricité ?",
               "À 2 mois, 13 épisodes dont plusieurs groupés sur les mêmes mois d'intersaison",
               "3 mois de suite"]]
    out += d.tableau("Les mesures qui ont fixé les méthodes (lot communal, 13 et 14.11.2026)", lignes,
                     [50 * M.mm, 68 * M.mm, M.UTILE - 118 * M.mm])
    out += [M.encadre("<b>Validation.</b> Sur les exemples où les dérives sont connues d'avance (7 puis 16 dérives "
                      "injectées, météo fictive et météo réelle), le moteur garde 100 % de précision et 100 % de rappel "
                      "après ces changements. Ces exemples sont relevés à l'heure sur 12 mois : ils ne valident donc pas les "
                      "méthodes du jour et du mois, qui le sont par leurs tests et par les mesures ci-dessus.", d.s)]
    return out


def couverture_parc(d):
    """Ce que la matrice donne sur le parc de la base courante, si elle existe."""
    base = os.path.join(service.RACINE, "vigie.db")
    out = d.h1("Couverture du parc et limites")
    if os.path.exists(base):
        cx = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        try:
            r = parc.liste_regles(cx, service.defauts())
        finally:
            cx.close()
        c = r["couverture"]
        lignes = [["Fluide"] + [libelle for _pas, libelle in regles.PAS_MATRICE]]
        for ligne in r["matrice"]:
            lignes.append([f"<b>{ligne['fluide']}</b>"] + [str(x["compteurs"]) if x["compteurs"] else "—" for x in ligne["cases"]])
        out += [d.p("Nombre de compteurs actifs de la base courante dans chaque case de la matrice :")]
        out += d.tableau("Compteurs du parc par fluide et par pas de relevé", lignes,
                         [44 * M.mm] + [(M.UTILE - 44 * M.mm) / 4] * 4, alignements=["g", "c", "c", "c", "c"])
        sans = [a["texte"] for a in c["alertes"] if a["niveau"] == "sans_effet"]
        out += [d.p(f"<b>{c['sans_effet']} règle(s) active(s) ne tournent sur aucun compteur</b>, faute d'un relevé assez "
                    f"fin ; {c['partielles']} ne couvrent qu'une partie des compteurs de leur fluide ; "
                    f"{c['compteurs_sans_regle']} compteur(s) n'ont aucune règle de dérive."),
                *d.puces(sans)]
        if c["sans_regle"]:
            out += [d.p("Compteurs sans règle de dérive (seule la qualité de leurs données est contrôlée) : "
                        + " · ".join(f"{x['fluide']} ({x['compteurs']} {x['pas']})" for x in c["sans_regle"]) + ".")]
    out += d.h2("Limites à connaître")
    out += d.puces([
        "<b>Les seuils ne sont pas calibrés sur des dérives réelles vérifiées.</b> Ils viennent des exemples simulés et "
        "des mesures du chapitre précédent. Aucun réglage n'est propre à un immeuble.",
        "<b>Plus le relevé est grossier, plus la détection est tardive</b> : quelques jours à l'heure ou au jour, deux à "
        "trois mois au mois. Un relevé plus fin reste le meilleur moyen d'améliorer la surveillance.",
        "<b>Un changement d'usage non déclaré ressort comme une dérive</b> (horaires, surface chauffée, saison d'une "
        "patinoire). Le gestionnaire le reconnaît ; le moteur ne le devine pas.",
        "<b>Les méthodes du jour pour l'électricité et la PAC</b> sont validées par leurs tests sur des séries "
        "construites : le lot ne contient aucun compteur de ce type relevé au jour.",
        "<b>L'ensoleillement vient de la station météo</b>, pas d'un capteur sur le toit ; les tarifs et facteurs "
        "d'émission sont des valeurs d'exemple."])
    return out


def histoire():
    d = Redaction()
    out = page_titre(d)
    for chapitre in (essentiel, pourquoi, principes, eau, electricite, chauffage, pac, solaire, mesures, couverture_parc):
        out += chapitre(d)
    return out


def generer(chemin=SORTIE):
    M.polices()
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    premier = Document(chemin)
    premier.multiBuild(histoire())  # première construction : sommaire et nombre de pages
    TOTAL[0] = premier.page
    Document(chemin).multiBuild(histoire())
    return chemin, TOTAL[0]


if __name__ == "__main__":
    fichier, pages = generer()
    print(f"{fichier} — {pages} pages")
