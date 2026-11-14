"""Protection d'un secret (clé API) sur ce poste, sans dépendance.

Sous Windows : DPAPI (CryptProtectData), liée au compte Windows de l'utilisateur. Le texte stocké en base est
illisible sur un autre poste ou par un autre compte ; une copie de vigie.db ne livre donc pas la clé.
Ailleurs : pas de stockage ; la clé se donne par variable d'environnement.
"""
import base64
import ctypes
import sys

DISPONIBLE = sys.platform == "win32"
ENTROPIE = b"Vigie - connecteur API des compteurs"
SANS_FENETRE = 0x01  # CRYPTPROTECT_UI_FORBIDDEN


class ErreurSecret(ValueError):
    pass


if DISPONIBLE:
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(octets):
    tampon = ctypes.create_string_buffer(octets, len(octets))
    return _Blob(len(octets), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char))), tampon


def _dpapi(fonction, octets):
    entree, _t1 = _blob(octets)
    entropie, _t2 = _blob(ENTROPIE)
    sortie = _Blob()
    if not fonction(ctypes.byref(entree), None, ctypes.byref(entropie), None, None, SANS_FENETRE, ctypes.byref(sortie)):
        raise ErreurSecret("Windows n'a pas pu protéger ou relire la clé (compte Windows différent ?). Saisissez-la à nouveau.")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(sortie.pbData, ctypes.c_void_p))


def proteger(texte):
    """Texte -> chaîne base64 protégée par le compte Windows courant."""
    if not DISPONIBLE:
        raise ErreurSecret("Enregistrement de la clé possible sous Windows seulement : utilisez la variable "
                           "d'environnement VIGIE_API_CLE.")
    return base64.b64encode(_dpapi(_crypt32.CryptProtectData, texte.encode("utf-8"))).decode("ascii")


def relire(protege):
    if not DISPONIBLE:
        raise ErreurSecret("Clé enregistrée sous Windows : illisible sur ce système.")
    try:
        brut = base64.b64decode(protege, validate=True)
    except ValueError as e:
        raise ErreurSecret("Clé enregistrée endommagée : saisissez-la à nouveau.") from e
    return _dpapi(_crypt32.CryptUnprotectData, brut).decode("utf-8")


def masque(cle):
    """Ce que l'interface peut montrer : les 4 derniers caractères seulement."""
    return "••••" + cle[-4:] if len(cle) >= 8 else "••••"
