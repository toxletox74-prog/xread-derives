"""Mise en page du document PDF (reportlab) : polices, styles, gabarits de page, tableaux, figures, encadrés."""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

NUIT = colors.HexColor("#0F1B2D")
BLEU = colors.HexColor("#1D4ED8")
BLEU_PALE = colors.HexColor("#EFF6FF")
BLEU_TRAIT = colors.HexColor("#BFDBFE")
GRIS = colors.HexColor("#64748B")
GRIS_TEXTE = colors.HexColor("#334155")
GRIS_LIGNE = colors.HexColor("#E2E8F0")
GRIS_FOND = colors.HexColor("#F1F5F9")
GRIS_ZEBRE = colors.HexColor("#F8FAFC")
ORANGE = colors.HexColor("#C2410C")
ORANGE_PALE = colors.HexColor("#FFF7ED")
VERT = colors.HexColor("#15803D")

LARGEUR, HAUTEUR = A4
MARGE_G, MARGE_D, MARGE_H, MARGE_B = 20 * mm, 20 * mm, 22 * mm, 20 * mm
UTILE = LARGEUR - MARGE_G - MARGE_D

TITRE_DOC = "Vigie · Méthodes de détection et évaluation des dérives par fluide"


def polices():
    dossier = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    for nom, fichier in (("Texte", "segoeui.ttf"), ("Texte-Gras", "segoeuib.ttf"), ("Texte-Demi", "seguisb.ttf"),
                         ("Texte-Italique", "segoeuii.ttf"), ("Texte-Leger", "segoeuil.ttf"), ("Mono", "consola.ttf"),
                         ("Mono-Gras", "consolab.ttf")):
        pdfmetrics.registerFont(TTFont(nom, os.path.join(dossier, fichier)))
    pdfmetrics.registerFontFamily("Texte", normal="Texte", bold="Texte-Gras", italic="Texte-Italique",
                                  boldItalic="Texte-Gras")
    pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Gras", italic="Mono", boldItalic="Mono-Gras")


def styles():
    s = {}
    s["corps"] = ParagraphStyle("corps", fontName="Texte", fontSize=9.4, leading=14, textColor=GRIS_TEXTE,
                                spaceAfter=6, alignment=TA_LEFT)
    s["corps_serre"] = ParagraphStyle("corps_serre", parent=s["corps"], spaceAfter=2)
    s["puce"] = ParagraphStyle("puce", parent=s["corps"], leftIndent=12, bulletIndent=2, spaceAfter=3)
    s["h1"] = ParagraphStyle("h1", fontName="Texte-Demi", fontSize=17, leading=22, textColor=NUIT, spaceBefore=4,
                             spaceAfter=4, keepWithNext=1)
    s["h2"] = ParagraphStyle("h2", fontName="Texte-Demi", fontSize=12.2, leading=16, textColor=NUIT, spaceBefore=12,
                             spaceAfter=5, keepWithNext=1)
    s["h3"] = ParagraphStyle("h3", fontName="Texte-Gras", fontSize=9.8, leading=13, textColor=BLEU, spaceBefore=8,
                             spaceAfter=3, keepWithNext=1)
    s["legende"] = ParagraphStyle("legende", fontName="Texte-Italique", fontSize=7.8, leading=10.5, textColor=GRIS,
                                  spaceBefore=3, spaceAfter=10)
    s["cellule"] = ParagraphStyle("cellule", fontName="Texte", fontSize=7.8, leading=10, textColor=GRIS_TEXTE)
    s["cellule_d"] = ParagraphStyle("cellule_d", parent=s["cellule"], alignment=TA_RIGHT)
    s["cellule_c"] = ParagraphStyle("cellule_c", parent=s["cellule"], alignment=TA_CENTER)
    s["entete"] = ParagraphStyle("entete", fontName="Texte-Demi", fontSize=7.6, leading=9.6, textColor=colors.white)
    s["entete_d"] = ParagraphStyle("entete_d", parent=s["entete"], alignment=TA_RIGHT)
    s["formule"] = ParagraphStyle("formule", fontName="Mono", fontSize=8.4, leading=12, textColor=NUIT)
    s["encadre"] = ParagraphStyle("encadre", parent=s["corps"], fontSize=8.9, leading=13, spaceAfter=3)
    s["toc1"] = ParagraphStyle("toc1", fontName="Texte-Demi", fontSize=10.5, leading=17, textColor=NUIT,
                               leftIndent=0, firstLineIndent=0)
    s["toc2"] = ParagraphStyle("toc2", fontName="Texte", fontSize=9, leading=13, textColor=GRIS_TEXTE, leftIndent=16)
    s["chiffre"] = ParagraphStyle("chiffre", fontName="Texte-Demi", fontSize=19, leading=22, textColor=BLEU)
    s["chiffre_legende"] = ParagraphStyle("chiffre_legende", fontName="Texte", fontSize=7.6, leading=10,
                                          textColor=GRIS_TEXTE)
    return s


class Titre(Paragraph):
    """Titre numéroté inscrit au sommaire (niveau 0 ou 1) avec un signet PDF."""

    def __init__(self, texte, style, niveau, cle):
        super().__init__(texte, style)
        self.niveau, self.cle, self.texte_brut = niveau, cle, texte


class FiletTitre(Flowable):
    def __init__(self, largeur=UTILE, couleur=BLEU, epaisseur=1.6, longueur=42 * mm):
        super().__init__()
        self.largeur, self.couleur, self.epaisseur, self.longueur = largeur, couleur, epaisseur, longueur

    def wrap(self, *a):
        return self.largeur, 8

    def draw(self):
        self.canv.setStrokeColor(GRIS_LIGNE)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 4, self.largeur, 4)
        self.canv.setStrokeColor(self.couleur)
        self.canv.setLineWidth(self.epaisseur)
        self.canv.line(0, 4, self.longueur, 4)


class Document(BaseDocTemplate):
    def __init__(self, chemin, **kw):
        super().__init__(chemin, pagesize=A4, leftMargin=MARGE_G, rightMargin=MARGE_D, topMargin=MARGE_H,
                         bottomMargin=MARGE_B, title="Vigie — méthodes de détection et évaluation des dérives",
                         author="Vigie (Xread Dérives) — évaluation technique", subject="Détection des dérives par fluide",
                         **kw)
        cadre = Frame(MARGE_G, MARGE_B, UTILE, HAUTEUR - MARGE_H - MARGE_B, id="normal", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("titre", [cadre], onPage=page_titre),
                               PageTemplate("contenu", [cadre], onPage=page_contenu)])

    def afterFlowable(self, f):
        if isinstance(f, Titre):
            self.canv.bookmarkPage(f.cle)
            self.canv.addOutlineEntry(f.texte_brut.replace("&amp;", "&").replace("&nbsp;", " "), f.cle,
                                      level=f.niveau, closed=False)
            self.notify("TOCEntry", (f.niveau, f.texte_brut, self.page, f.cle))


def page_titre(c, doc):
    c.saveState()
    c.setFillColor(NUIT)
    c.rect(0, HAUTEUR - 128 * mm, LARGEUR, 128 * mm, stroke=0, fill=1)
    c.setFillColor(BLEU)
    c.rect(0, HAUTEUR - 131 * mm, LARGEUR, 3 * mm, stroke=0, fill=1)
    c.restoreState()


def page_contenu(c, doc):
    c.saveState()
    c.setStrokeColor(GRIS_LIGNE)
    c.setLineWidth(0.5)
    c.line(MARGE_G, HAUTEUR - 13 * mm, LARGEUR - MARGE_D, HAUTEUR - 13 * mm)
    c.setFont("Texte-Demi", 7.4)
    c.setFillColor(NUIT)
    c.drawString(MARGE_G, HAUTEUR - 11 * mm, "Vigie")
    c.setFont("Texte", 7.4)
    c.setFillColor(GRIS)
    c.drawString(MARGE_G + 22, HAUTEUR - 11 * mm, "· Méthodes de détection et évaluation des dérives par fluide")
    c.drawRightString(LARGEUR - MARGE_D, HAUTEUR - 11 * mm, "Révision du moteur V0.2 · novembre 2026")
    c.line(MARGE_G, 13 * mm, LARGEUR - MARGE_D, 13 * mm)
    c.setFont("Texte", 7)
    c.drawString(MARGE_G, 9 * mm, "Consommations simulées (fictives) · météo réelle MétéoSuisse · tarifs et facteurs CO₂ = valeurs d'EXEMPLE")
    c.setFont("Texte-Demi", 7.6)
    c.setFillColor(NUIT)
    numero = f"{doc.page} / {TOTAL_PAGES[0]}" if TOTAL_PAGES[0] else str(doc.page)
    c.drawRightString(LARGEUR - MARGE_D, 9 * mm, numero)
    c.restoreState()


TOTAL_PAGES = [None]  # nombre de pages connu après une première construction (numérotation « n / N »)


def sommaire(s):
    toc = TableOfContents()
    toc.levelStyles = [s["toc1"], s["toc2"]]
    toc.dotsMinLevel = 0
    return toc


def tableau(lignes, largeurs, s, entete=1, alignements=None, zebre=True, police=None, total=False):
    """lignes : listes de textes (ou Flowables). alignements : 'g', 'd' ou 'c' par colonne."""
    alignements = alignements or ["g"] * len(largeurs)
    data = []
    for i, ligne in enumerate(lignes):
        rang = []
        for j, cel in enumerate(ligne):
            if isinstance(cel, Flowable):
                rang.append(cel)
                continue
            if i < entete:
                st = s["entete_d"] if alignements[j] == "d" else s["entete"]
            else:
                st = {"d": s["cellule_d"], "c": s["cellule_c"]}.get(alignements[j], s["cellule"])
            if police:
                st = ParagraphStyle("p", parent=st, fontSize=police, leading=police * 1.28)
            texte = "" if cel is None else str(cel)
            texte = {"reelle": "réelle"}.get(texte, texte)  # libellé d'affichage de la météo réelle
            rang.append(Paragraph(texte, st))
        data.append(rang)
    t = Table(data, colWidths=largeurs, repeatRows=entete, hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2), ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4.5), ("LINEBELOW", (0, entete), (-1, -1), 0.4, GRIS_LIGNE)]
    if entete:
        cmds += [("BACKGROUND", (0, 0), (-1, entete - 1), NUIT)]
    if zebre:
        for i in range(entete, len(data)):
            if (i - entete) % 2 == 1:
                cmds.append(("BACKGROUND", (0, i), (-1, i), GRIS_ZEBRE))
    if total:
        cmds += [("LINEABOVE", (0, -1), (-1, -1), 0.9, NUIT), ("BACKGROUND", (0, -1), (-1, -1), BLEU_PALE)]
    t.setStyle(TableStyle(cmds))
    return t


def figure(chemin, largeur, legende, s, numero):
    from reportlab.lib.utils import ImageReader
    lx, ly = ImageReader(chemin).getSize()
    img = Image(chemin, width=largeur, height=largeur * ly / lx)
    img.hAlign = "LEFT"
    img.keepWithNext = 1  # l'image reste avec sa légende (et un titre qui la précède reste avec l'image)
    return [img, Paragraph(f"<b>Figure {numero}</b> — {legende}", s["legende"])]


def legende_tableau(texte, s, numero):
    return Paragraph(f"<b>Tableau {numero}</b> — {texte}", ParagraphStyle("lt", parent=s["legende"], spaceBefore=0,
                                                                          spaceAfter=4, keepWithNext=1))


def encadre(contenu, s, fond=BLEU_PALE, trait=BLEU, largeur=UTILE):
    """Encadré à filet gauche ; `contenu` = liste de Flowables ou texte."""
    if isinstance(contenu, str):
        contenu = [Paragraph(contenu, s["encadre"])]
    t = Table([[contenu]], colWidths=[largeur], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fond), ("LINEBEFORE", (0, 0), (0, -1), 2.2, trait),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def formule(lignes, s):
    import re
    paras = [Paragraph(re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group()), x), s["formule"]) for x in lignes]
    return encadre(paras, s, fond=GRIS_FOND, trait=NUIT)


def chiffres_cles(items, s, largeur=UTILE):
    """Rangée de chiffres clés : [(valeur, légende)]."""
    n = len(items)
    cel = [[Paragraph(v, s["chiffre"]), Spacer(1, 2), Paragraph(l, s["chiffre_legende"])] for v, l in items]
    t = Table([cel], colWidths=[largeur / n] * n, hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, -1), GRIS_ZEBRE),
                           ("LINEBEFORE", (1, 0), (-1, -1), 0.6, colors.white),
                           ("LINEABOVE", (0, 0), (-1, 0), 1.6, BLEU)]))
    return t
