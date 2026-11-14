"""Contrôler les exports et décoder toutes les images et la bande-son."""
import json
import subprocess
import sys
from pathlib import Path

rapports=[]
for argument in sys.argv[1:]:
    fichier=Path(argument)
    resultat=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(fichier)],check=True,capture_output=True,text=True)
    info=json.loads(resultat.stdout)
    video=next(flux for flux in info['streams'] if flux['codec_type']=='video')
    audio=next(flux for flux in info['streams'] if flux['codec_type']=='audio')
    assert video['codec_name']=='h264', 'Codec vidéo incorrect'
    assert video['r_frame_rate']=='30/1', 'Cadence incorrecte'
    assert video['nb_frames']=='1800', 'Nombre d’images incorrect'
    assert abs(float(video['duration'])-60)<.001, 'Durée vidéo incorrecte'
    assert abs(float(info['format']['duration'])-60)<.001, 'Durée fichier incorrecte'
    assert video['pix_fmt']=='yuv420p', 'Format de pixels incorrect'
    assert audio['codec_name']=='aac', 'Codec audio incorrect'
    dimensions=(video['width'],video['height'])
    assert dimensions in [(1920,1080),(3840,2160),(1080,1920)], 'Résolution incorrecte'
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(fichier),'-f','null','-'],check=True)
    rapport={'fichier':str(fichier),'resolution':dimensions,'images':1800,'fps':30,'duree':60,'codec':'h264','audio':'aac','octets':fichier.stat().st_size,'decodage_integral':'OK'}
    rapports.append(rapport)
    print(json.dumps(rapport,ensure_ascii=False),flush=True)
if rapports:
    Path('out/validation.json').write_text(json.dumps(rapports,ensure_ascii=False,indent=2),encoding='utf-8')
