"""Lecture et écriture de classeurs Excel (.xlsx) sans dépendance externe.

Un .xlsx est une archive zip de fichiers XML. On ne lit que ce dont l'import du parc a besoin :
noms des feuilles, cellules texte (partagées ou en ligne), nombres et booléens. Pas de formules
recalculées (la valeur mise en cache par Excel est lue), pas de mise en forme.
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
TAILLE_MAX = 20 * 1024 * 1024  # 20 Mo décompressés par fichier interne : protège contre les archives piégées


class ErreurExcel(ValueError):
    pass


def _xml(z, nom):
    info = z.getinfo(nom)
    if info.file_size > TAILLE_MAX:
        raise ErreurExcel(f"Fichier interne trop volumineux : {nom}")
    brut = z.read(nom)
    if b"<!DOCTYPE" in brut or b"<!ENTITY" in brut:  # jamais présent dans un vrai classeur : refus (entités piégées)
        raise ErreurExcel("Classeur refusé : contenu XML non standard.")
    try:
        return ET.fromstring(brut)
    except ET.ParseError as e:
        raise ErreurExcel("Classeur endommagé : impossible de le lire.") from e


def _colonne(ref):
    m = re.match(r"[A-Z]{1,3}", ref)
    if not m:
        raise ErreurExcel("Classeur endommagé : référence de cellule illisible.")
    lettres = m.group(0)
    n = 0
    for c in lettres:
        n = n * 26 + ord(c) - 64
    return n - 1


def _nombre(texte):
    v = float(texte)
    if v.is_integer():
        return int(v)  # n° de série ou téléphone saisis en nombre : pas de notation 1.2e+16
    return v


def lire_xlsx(contenu, seulement=None):
    """Retourne {nom_de_feuille: [[valeurs de la ligne], …]} ; cellules vides = None.
    `seulement` = fonction(nom de feuille) -> bool : ne lit que les feuilles retenues (classeur très volumineux)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(contenu))
    except zipfile.BadZipFile as e:
        raise ErreurExcel("Ce fichier n'est pas un classeur Excel .xlsx valide.") from e
    noms = set(z.namelist())
    if "xl/workbook.xml" not in noms:
        raise ErreurExcel("Ce fichier n'est pas un classeur Excel .xlsx valide.")
    partages = []
    if "xl/sharedStrings.xml" in noms:
        for si in _xml(z, "xl/sharedStrings.xml").findall("m:si", NS):
            partages.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    liens = {r.get("Id"): r.get("Target") for r in _xml(z, "xl/_rels/workbook.xml.rels").findall("pr:Relationship", NS)}
    feuilles = {}
    for f in _xml(z, "xl/workbook.xml").find("m:sheets", NS):
        cible = liens.get(f.get(f"{{{NS['r']}}}id"), "")
        chemin = cible.lstrip("/") if cible.startswith("/") else "xl/" + cible
        if chemin not in noms or (seulement is not None and not seulement(f.get("name"))):
            continue
        feuilles[f.get("name")] = _lire_feuille(_xml(z, chemin), partages)
    return feuilles


COLONNES_MAX = 200


def _lire_feuille(racine, partages):
    """Lignes de la feuille ; l'indice dans la liste = n° de ligne Excel - 1 (les lignes vides sont conservées)."""
    lignes = []
    for row in racine.iter(f"{{{NS['m']}}}row"):
        numero = int(row.get("r") or len(lignes) + 1)
        if numero > len(lignes) + 1:
            lignes.extend([] for _ in range(numero - 1 - len(lignes)))
        valeurs = {}
        courante = 0
        for c in row.findall("m:c", NS):
            courante = _colonne(c.get("r")) if c.get("r") else courante
            if courante >= COLONNES_MAX:
                raise ErreurExcel(f"Trop de colonnes (plus de {COLONNES_MAX}) : feuille refusée.")
            col, courante = courante, courante + 1
            t, v = c.get("t"), c.find("m:v", NS)
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                try:
                    val = partages[int(v.text)]
                except (ValueError, IndexError) as e:
                    raise ErreurExcel("Classeur endommagé : texte introuvable.") from e
            elif t == "b":
                val = v.text == "1"
            elif t in ("str", "e"):
                val = v.text
            else:
                try:
                    val = _nombre(v.text)
                except ValueError:
                    val = v.text
            valeurs[col] = val
        if valeurs:
            ligne = [None] * (max(valeurs) + 1)
            for i, val in valeurs.items():
                ligne[i] = val
            lignes.append(ligne)
        else:
            lignes.append([])
    return lignes


def _ref(col, lig):
    lettres = ""
    col += 1
    while col:
        col, r = divmod(col - 1, 26)
        lettres = chr(65 + r) + lettres
    return f"{lettres}{lig}"


def ecrire_xlsx(feuilles):
    """`feuilles` = {nom: [[valeurs], …]} (la 1re ligne = en-têtes, en gras). Retourne le contenu .xlsx."""
    tampon = io.BytesIO()
    noms = list(feuilles)
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(noms) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n[:31])}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(noms, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(noms) + 1))
                   + f'<Relationship Id="rId{len(noms) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
                   '<cellXfs count="2"><xf fontId="0"/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>')
        for i, n in enumerate(noms, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _feuille_xml(feuilles[n]))
    return tampon.getvalue()


def _feuille_xml(lignes):
    largeurs = {}
    rows = []
    for li, ligne in enumerate(lignes, 1):
        cells = []
        for ci, v in enumerate(ligne):
            if v is None or v == "":
                continue
            largeurs[ci] = max(largeurs.get(ci, 8), min(60, len(str(v)) + 2))
            style = ' s="1"' if li == 1 else ""
            if isinstance(v, bool):
                cells.append(f'<c r="{_ref(ci, li)}" t="b"{style}><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)):
                cells.append(f'<c r="{_ref(ci, li)}"{style}><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{_ref(ci, li)}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        rows.append(f'<row r="{li}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>' for c, w in sorted(largeurs.items()))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            + (f"<cols>{cols}</cols>" if cols else "") + f'<sheetData>{"".join(rows)}</sheetData></worksheet>')
