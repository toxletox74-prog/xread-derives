// Vigie — navigation entre les écrans et état général (bandeau, compteurs).
import { api, h, vider, toast, tenter, dialogue, saisie, champ } from './outils.js';
import { icone, etatVide } from './icones.js';
import { pageTableau, pageAlertes, pageBons } from './pages_suivi.js';
import { pageRejeu } from './rejeu.js';
import { dialogueClaude } from './claude.js';
import { pageParc, pageImports } from './pages_parc.js';
import { pageImmeuble } from './fiche.js';
import { pagePrestataires, pageRegles, pageReglages } from './pages_reglages.js';

const NAV = [
  ['#/', 'Tableau de bord', 'tableau', 'alertes'],
  ['#/parc', 'Parc', 'immeuble'],
  ['#/alertes', 'Alertes', 'alerte'],
  ['#/rejeu', 'Rejeu', 'analyser'],
  ['#/bons', 'Bons de travaux', 'bon', 'brouillons'],
  ['#/prestataires', 'Prestataires', 'prestataire'],
  ['#/regles', 'Règles & coûts', 'regles'],
  ['#/imports', 'Imports', 'importer'],
  ['#/reglages', 'Réglages', 'reglages'],
];
const ROUTES = [
  [/^#\/?$/, pageTableau], [/^#\/parc$/, pageParc], [/^#\/immeuble\/([^/]+)$/, pageImmeuble],
  [/^#\/alertes$/, pageAlertes], [/^#\/rejeu$/, pageRejeu], [/^#\/bons$/, pageBons], [/^#\/prestataires$/, pagePrestataires],
  [/^#\/regles$/, pageRegles], [/^#\/imports$/, pageImports], [/^#\/reglages$/, pageReglages],
];

const ctx = {
  etat: null,
  aller(hash) { if (location.hash === hash) afficher(); else location.hash = hash; },
  async recharger() { await rafraichirEtat(); await afficher(); },
  rafraichirEtat,
  async analyser() {
    const r = await api('POST', '/api/analyser');
    const b = r.bons;
    let msg = r.donnees_au ? `Analyse terminée : ${r.alertes} alertes ouvertes, ${r.nouvelles.length} nouvelles.`
      : 'Aucune mesure à analyser : importez d\'abord les données des compteurs.';
    if (b && b.crees.length) msg += ` ${b.crees.length} bon(s) de travaux préparé(s).`;
    if (b && b.envoyes.length) msg += ` ${b.envoyes.length} envoyé(s).`;
    toast(msg);
    if (b && b.erreurs.length) toast('Envois impossibles : ' + b.erreurs.join(' · '), true);
    await ctx.recharger();
  },
};

async function rafraichirEtat() {
  try {
    ctx.etat = await api('GET', '/api/etat');
  } catch (e) {
    toast(e.message, true);
    return;
  }
  const e = ctx.etat;
  const nav = document.getElementById('nav');
  const actuel = (location.hash || '#/').replace(/^#\/immeuble.*/, '#/parc');
  vider(nav, NAV.map(([href, lib, ico, badge]) => {
    const n = badge === 'alertes' ? e.kpis.critiques : badge === 'brouillons' ? e.kpis.bons_brouillon : 0;
    const actif = actuel === href || (href === '#/' && actuel === '#');
    return h('a', { href, class: actif ? 'actif' : null, 'aria-current': actif ? 'page' : null }, icone(ico), lib,
      n ? h('span', { class: 'pastille-nav', title: badge === 'alertes' ? 'alertes critiques' : 'bons à valider' }, n) : null);
  }));
  vider(document.getElementById('base-info'),
    e.base === 'vigie_demo.db' ? 'Base d\'exemple (données fictives)' : 'Données locales · ' + e.base, boutonAcces(e.acces));
}

// Lecture seule sans identification (serveur : acces.py) : le bandeau le dit et propose la connexion
function boutonAcces(acces) {
  if (!acces) return null;
  const lien = (texte, action) => h('button', { type: 'button', class: 'lien', style: 'color:inherit', onclick: action }, texte);
  const claude = lien('Claude (MCP)', dialogueClaude); // brancher Claude sur ce parc : réservé à qui peut modifier
  if (acces.session) {
    return [' · ', claude, ' · ',
      lien('Se déconnecter', async () => { await tenter(() => api('DELETE', '/api/session')); await ctx.recharger(); })];
  }
  if (acces.ecriture) return [' · ', claude];
  if (!acces.connexion) return ' · Lecture seule';
  return [' · Lecture seule', lien('Se connecter', () => {
    const mdp = saisie('mot_de_passe', '', { type: 'password', autocomplete: 'current-password', autofocus: true,
      onkeydown: (ev) => { if (ev.key === 'Enter') el.querySelector('button.primaire').click(); } });
    const { el } = dialogue('Se connecter', champ('Mot de passe', mdp, 'Nécessaire pour modifier ; la consultation reste libre.'), [{
      texte: 'Se connecter', classe: 'primaire', action: async () => {
        const r = await tenter(() => api('POST', '/api/session', { mot_de_passe: mdp.value }));
        if (!r) return false;
        await ctx.recharger();
        return true;
      },
    }]);
  })];
}

async function afficher() {
  const main = document.getElementById('page');
  const hash = location.hash || '#/';
  for (const [motif, page] of ROUTES) {
    const m = hash.match(motif);
    if (!m) continue;
    try {
      await page(main, ctx, ...m.slice(1).map(decodeURIComponent));
    } catch (err) {
      const vide = etatVide('alerte', h('div', { class: 'pile' }, h('h2', {}, 'Impossible d\'afficher cette page'),
        h('p', {}, err.message)), h('button', { type: 'button', onclick: () => ctx.recharger() }, icone('analyser'), 'Réessayer'));
      vide.querySelector('.vide-ico').classList.replace('ton-neutre', 'ton-crit');
      vider(main, h('div', { class: 'carte' }, vide));
    }
    return;
  }
  ctx.aller('#/');
}

// Un lien interne suivi depuis un dialogue le ferme, même s'il mène à la page déjà affichée
document.addEventListener('click', (ev) => {
  const lien = ev.target.closest('dialog a[href^="#"]');
  if (lien) lien.closest('dialog').remove();
});
window.addEventListener('hashchange', async () => {
  document.querySelectorAll('dialog').forEach((d) => d.remove());
  window.scrollTo(0, 0);
  await rafraichirEtat();
  await afficher();
});
await rafraichirEtat();
await afficher();
