"""Base exclusivement fictive dans .cache ; aucune lecture de la base utilisateur."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from vigie import db, service, serveur
cache=ROOT/'.cache'
cache.mkdir(exist_ok=True)
service.SORTIE=str(cache/'sorties')
path=cache/'vigie_demo.db'
if not path.exists():
    cx=db.connecter(str(path))
    service.charger_exemple(cx,meteo_reelle=False,taille='standard')
    service.analyser(cx,automatiser=False)
    cx.close()
server, app=serveur.creer_serveur(str(path),8876)
print('DEMO READY http://127.0.0.1:8876',flush=True)
server.serve_forever()
