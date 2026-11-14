import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia,renderStill} from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs/promises';
const serveUrl=await bundle({entryPoint:path.resolve('src/index.ts')});
const target=process.argv[2]||'EnergyTeaser1080';
await fs.mkdir('out/qa',{recursive:true});
if(target==='qa'){
 for(const id of ['EnergyTeaser1080','EnergyTeaserVertical']){
  const composition=await selectComposition({serveUrl,id});
  if(composition.durationInFrames!==1800||composition.fps!==30)throw new Error('Timeline incorrecte');
  for(const frame of [70,190,280,450,640,780,1010,1100,1250,1450,1540,1720]){
   await renderStill({serveUrl,composition,frame,output:path.resolve(`out/qa/${id}-${frame}.jpg`),imageFormat:'jpeg',scale:.6});
  }
 }
}else{
 const composition=await selectComposition({serveUrl,id:target});
 let last=-1;
 await renderMedia({serveUrl,composition,codec:'h264',crf:18,pixelFormat:'yuv420p',outputLocation:path.resolve(process.argv[3]||'out/energy-software-teaser.mp4'),concurrency:4,onProgress:({progress})=>{const p=Math.floor(progress*10);if(p!==last){last=p;console.log(`Rendu ${p*10}%`)}}});
}
