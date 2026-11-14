"""Lanceur de Vigie, utilisable depuis n'importe quel dossier (et par « Lancer Vigie.bat »).

  python lancer_vigie.py                    interface de gestion sur votre base (vigie.db)
  python lancer_vigie.py interface --demo   interface sur la base d'exemple
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vigie.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv if len(sys.argv) > 1 else [sys.argv[0], "interface"])
