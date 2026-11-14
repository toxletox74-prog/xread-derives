// Rejeu : la détection rejouée jour après jour sur une période passée (python -m vigie rejouer).
// Chaque ligne est un épisode : même site et même cause, du premier jour d'alerte au dernier.
import { api, h, vider, fmt, chip, liste, champ } from './outils.js';
import { pastilleFluide, etatVide } from './icones.js';

const jour = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : '—');

function montant(e) {
  const parts = [];
  if (e.chf_mesure) parts.push(`≈ ${fmt.n0(e.chf_mesure)} CHF`);
  if (e.kwh_mesure) parts.push(`${fmt.n0(e.kwh_mesure)} kWh`);
  if (e.m3_mesure) parts.push(`${fmt.n1(e.m3_mesure)} m³`);
  return parts.length ? parts.join(' · ') : '—';
}

export async function pageRejeu(main) {
  const { rejeu } = await api('GET', '/api/rejeu');
  const entete = h('div', { class: 'entete-page' }, h('div', { class: 'titres' }, h('h1', {}, 'Rejeu de la détection'),
    h('p', { class: 'doux' }, 'Le moteur est relancé comme s\'il avait tourné chaque jour de la période : à chaque date, il ne '
      + 'voit que les relevés déjà reçus. Chaque ligne est un épisode de dérive ou de défaut de données.')));
  if (!rejeu) {
    return vider(main, entete, h('section', { class: 'carte' }, etatVide('analyser',
      'Aucun rejeu enregistré. Lancez par exemple : python -m vigie rejouer 2025-02-15 2025-12-31')));
  }
  const filtres = { gravite: '', q: '' };
  const zone = h('div', {});
  const rendre = () => {
    const q = filtres.q.toLowerCase();
    const vis = rejeu.episodes.filter((e) => (!filtres.gravite || e.gravite === filtres.gravite)
      && (!q || `${e.immeuble} ${e.immeuble_id} ${e.point_id} ${e.titre}`.toLowerCase().includes(q)));
    vider(zone, vis.length ? h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Détecté le', 'Site', 'Épisode', 'Début', 'Fin', 'Jours en alerte', 'Dérive constatée']
        .map((x, i) => h('th', { scope: 'col', class: i === 5 ? 'nombre' : null }, x)))),
      h('tbody', {}, vis.map((e) => h('tr', {},
        h('td', { class: 'nombre' }, jour(e.detecte_le)),
        h('td', {}, h('a', { href: '#/immeuble/' + encodeURIComponent(e.immeuble_id) }, e.immeuble),
          h('div', { class: 'doux petit' }, e.point_id || e.immeuble_id)),
        h('td', {}, h('div', { class: 'cellule-fluide' }, pastilleFluide(e.gravite === 'Données' ? 'donnees' : e.fluide),
          h('div', {}, h('div', { class: 'gras' }, e.titre), h('div', { class: 'ligne-tags' }, chip(e.gravite)),
            h('div', { class: 'petit' }, e.constat)))),
        h('td', { class: 'nombre' }, jour(e.debut)),
        h('td', { class: 'nombre' }, e.disparu_le ? jour(e.disparu_le) : h('span', { class: 'chip g-Attente' }, 'en cours à la fin')),
        h('td', { class: 'nombre' }, String(e.jours_en_alerte)),
        h('td', {}, montant(e)))))))
      : etatVide('ok', 'Aucun épisode ne correspond.'));
  };
  const parGravite = (g) => rejeu.episodes.filter((e) => e.gravite === g).length;
  vider(main, entete,
    h('div', { class: 'resume-import' },
      h('div', {}, h('div', { class: 'doux petit' }, 'Période rejouée'), h('b', {}, `${jour(rejeu.debut)} – ${jour(rejeu.fin)}`),
        h('div', { class: 'petit' }, `${rejeu.analyses} analyses, une tous les ${rejeu.pas_jours} jour(s)`)),
      h('div', {}, h('div', { class: 'doux petit' }, 'Épisodes'), h('b', {}, String(rejeu.episodes.length)),
        h('div', { class: 'petit' }, ['Critique', 'Élevée', 'Modérée', 'Données'].filter(parGravite)
          .map((g) => `${parGravite(g)} ${g.toLowerCase()}`).join(' · '))),
      h('div', {}, h('div', { class: 'doux petit' }, 'Montants'), h('b', {}, 'tarifs d\'exemple'),
        h('div', { class: 'petit' }, 'plus grand montant constaté pendant l\'épisode'))),
    h('div', { class: 'filtres' },
      champ('Gravité', liste('gravite', [['', 'Toutes'], 'Critique', 'Élevée', 'Modérée', 'Données'], '')),
      champ('Rechercher', h('input', { type: 'search', name: 'q', placeholder: 'Site, compteur, dérive…' }))),
    h('section', { class: 'carte' }, zone));
  main.querySelector('select[name=gravite]').addEventListener('change', (ev) => { filtres.gravite = ev.target.value; rendre(); });
  main.querySelector('input[name=q]').addEventListener('input', (ev) => { filtres.q = ev.target.value; rendre(); });
  return rendre();
}
