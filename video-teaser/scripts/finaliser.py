"""Niveau musical de diffusion et durée de conteneur exacte, sans réencoder la vidéo."""
import os
import json
import subprocess
import sys
from pathlib import Path

for argument in sys.argv[1:]:
    source=Path(argument)
    destination=source.with_name(source.stem+'.finalisation.mp4')
    flux=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(source)]))['streams']
    audio=any(element['codec_type']=='audio' for element in flux)
    options_audio=['-map','0:a:0','-c:a','aac','-b:a','192k','-af','loudnorm=I=-20:TP=-1.5:LRA=9'] if audio else ['-an']
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-map','0:v:0','-c:v','copy',
                    *options_audio,'-t','60','-movflags','+faststart',str(destination)],check=True)
    os.replace(destination,source)
    print('Finalisation : '+str(source),flush=True)
