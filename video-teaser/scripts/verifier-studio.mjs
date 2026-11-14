import {chromium} from 'playwright';
import fs from 'node:fs/promises';
const navigateur=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await navigateur.newPage({viewport:{width:1600,height:1000}});
 const erreurs=[];
 page.on('pageerror',erreur=>erreurs.push(erreur.message));
 await page.goto('http://localhost:3010',{waitUntil:'networkidle'});
 await page.getByText('EnergyTeaser1080',{exact:true}).first().click();
 await page.screenshot({path:'out/qa/remotion-studio.png'});
 const texte=await page.locator('body').innerText();
 for(const nom of ['EnergyTeaser1080','EnergyTeaser4K','EnergyTeaserVertical']) {
  if(!texte.includes(nom))throw new Error(`Composition absente : ${nom}`);
 }
 if(erreurs.length)throw new Error(erreurs.join('\n'));
 await fs.writeFile('out/qa/studio-validation.json',JSON.stringify({compositions:3,erreurs,statut:'OK'},null,2));
 console.log('Studio : 3 compositions disponibles, aucune erreur JavaScript.');
} finally {await navigateur.close()}
