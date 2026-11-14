import {chromium} from 'playwright';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 for (const vertical of [false,true]) {
  const page=await browser.newPage({viewport:{width:vertical?950:1600,height:vertical?650:900},deviceScaleFactor:2,colorScheme:'dark',bypassCSP:true});
  // Les tuiles externes ne sont pas incluses dans la publicité : pas de redistribution cartographique.
  await page.route('https://**/*',route=>route.abort());
  await page.goto('http://127.0.0.1:8876/');
  await page.locator('h1').filter({hasText:'Tableau de bord du parc'}).waitFor();
  await page.addStyleTag({content:'.carte:has(#t-carte){display:none!important}.bandeau{display:none!important}.banniere{display:none!important}main{padding:26px!important}.grille-kpi{grid-template-columns:repeat(3,1fr)!important}.grille-kpi .kpi:nth-child(n+4){display:none!important}.liste .alerte:nth-child(n+3){display:none!important}*{animation:none!important;transition:none!important}'});
  if(vertical) await page.addStyleTag({content:'.grille-kpi{grid-template-columns:repeat(2,1fr)!important}.grille-kpi .kpi:nth-child(n+3){display:none!important}.liste .alerte:nth-child(n+2){display:none!important}'});
  const errors=await page.locator('main').innerText();
  if(errors.includes('Impossible d’afficher')||errors.includes("Impossible d'afficher"))throw new Error(errors);
  await page.screenshot({path:`public/assets/dashboard${vertical?'-vertical':''}.png`});
  await fs.writeFile(`public/assets/dashboard${vertical?'-vertical':''}.txt`,errors);
  await page.close();
 }
}finally{await browser.close()}

