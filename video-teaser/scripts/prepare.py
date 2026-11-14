"""Assets hors réseau, logo extrait du produit, partition synthétisée originale."""
import math
import re
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_logo = ROOT.parent / 'vigie/web/index.html'
if source_logo.exists():
    html = source_logo.read_text(encoding='utf-8')
    logo = re.search(r'<svg class="logo".*?</svg>', html, re.S).group(0)
    logo = logo.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ')
    (ROOT / 'public/assets/logo.svg').write_text(logo, encoding='utf-8')
elif not (ROOT / 'public/assets/logo.svg').exists():
    raise FileNotFoundError('Ajouter le logo dans public/assets/logo.svg.')

rate = 24000
notes = [146.8324, 174.6141, 130.8128, 164.8138]
out = bytearray()
for i in range(60 * rate):
    t = i / rate
    root = notes[int(t / 8) % 4]
    pad = sum(math.sin(2 * math.pi * root * r * t) for r in [1, 1.5, 2]) * .032
    beat = t % .625
    pulse = math.sin(2 * math.pi * root * 2 * t) * math.exp(-beat * 11) * .065
    kick = math.sin(2 * math.pi * (48 * beat + 3 * (1-math.exp(-beat*22)))) * math.exp(-beat * 20) * .08
    air = math.sin(2*math.pi*3181*t)*math.sin(2*math.pi*4783*t)*math.exp(-beat*65)*.014
    cue = 0
    for start in [8,16,26,38,51]:
        dt=t-start
        if 0 <= dt < 1.4:
            cue += math.sin(2*math.pi*880*dt)*math.exp(-dt*5)*.045
    fade = min(1,t/2,(60-t)/3)
    val = (pad+pulse+kick+air+cue)*fade
    out.extend(struct.pack('<hh', int(val*32767), int(val*32767)))
with wave.open(str(ROOT/'public/audio/score.wav'),'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(out)
print('Logo et musique originale : prêts.')
