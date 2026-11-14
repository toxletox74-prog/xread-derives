// Pictogrammes de Xread Dérives : dessinés pour l'outil (grille 24 × 24, trait 1,75, extrémités et angles arrondis).
// Construits dans le DOM (espace de noms SVG via h()) : ni innerHTML, ni style en ligne, ni fichier externe.
// La couleur suit `currentColor` ; la teinte de chaque fluide vient des jetons CSS --c-<fluide> (app.css).
import { h } from './outils.js';

// Chaque pictogramme = liste de formes [balise, attributs]. Formes « pleines » : attribut plein: true.
const P = (d) => ['path', { d }];
const C = (cx, cy, r, plein) => ['circle', { cx, cy, r, plein }];
const R = (x, y, width, height, rx) => ['rect', { x, y, width, height, rx }];

const DESSINS = {
  // ---------------------------------------------------------------- fluides
  eau: [P('M12 3.25c-3.2 3.85-6.25 7.3-6.25 10.9a6.25 6.25 0 0 0 12.5 0c0-3.6-3.05-7.05-6.25-10.9Z'),
    P('M9.1 14.6a2.95 2.95 0 0 0 2.9 2.65')],
  eau_chaude: [P('M9.75 6.5c-2.55 3.05-4.75 5.75-4.75 8.6a4.75 4.75 0 0 0 9.5 0c0-2.85-2.2-5.55-4.75-8.6Z'),
    P('M16.75 3.25c-.9.9-.9 1.85 0 2.75s.9 1.85 0 2.75'), P('M20 3.25c-.9.9-.9 1.85 0 2.75s.9 1.85 0 2.75'),
    P('M7.6 15.4a2.15 2.15 0 0 0 2.15 1.95')],
  electricite: [P('M13.25 2.75 4.75 13.5h6.5l-.75 7.75 8.75-10.75h-6.5l.5-7.75Z')],
  pac: [R(2.75, 5, 18.5, 12.5, 2.5), C(9.25, 11.25, 3.75), C(9.25, 11.25, 0.8, true),
    P('M9.25 11.25c-.35-1.35.25-2.4 1.4-2.85M9.25 11.25c1.35.35 1.85 1.45 1.4 2.6M9.25 11.25c-1.1.9-2.3.85-3.05-.1'),
    P('M15.5 8.75h3M15.5 11.25h3M15.5 13.75h3'), P('M6 17.5v2M18 17.5v2')],
  chaleur: [R(3.5, 5, 3.6, 13, 1.8), R(8.05, 5, 3.6, 13, 1.8), R(12.6, 5, 3.6, 13, 1.8), R(17.15, 5, 3.35, 13, 1.68),
    P('M2 15.5h1.5M20.5 15.5H22'), P('M6.5 18v2M17.5 18v2')],
  cad: [P('M14.25 20.75v-7.6l3.6-3.15 3.6 3.15v7.6Z'), P('M2.75 14.25h11.5M2.75 18h11.5'),
    P('M5.5 3c-1 1-1 2 0 3s1 2 0 3'), P('M9.5 3c-1 1-1 2 0 3s1 2 0 3'), P('M17.85 17.25v3.5')],
  gaz: [P('M12 21.25a6.25 6.25 0 0 0 6.25-6.25c0-3.6-2.6-5.7-3.75-9-1.85 1.55-2.6 3.4-2.6 5.15-1.05-.7-1.85-2.05-2.05-3.6-2 1.95-4.1 4.35-4.1 7.45A6.25 6.25 0 0 0 12 21.25Z'),
    P('M12 21.25a2.6 2.6 0 0 1-2.6-2.6c0-1.65 1.35-2.5 2.6-3.95 1.25 1.45 2.6 2.3 2.6 3.95a2.6 2.6 0 0 1-2.6 2.6Z')],
  mazout: [P('M7.1 3.25h9.8c.85 2.9 1.35 5.8 1.35 8.75s-.5 5.85-1.35 8.75H7.1c-.85-2.9-1.35-5.8-1.35-8.75s.5-5.85 1.35-8.75Z'),
    P('M6.3 7.5h11.4M6.3 16.5h11.4'), P('M12 9.9c-1 1.2-1.75 2.05-1.75 2.95a1.75 1.75 0 0 0 3.5 0c0-.9-.75-1.75-1.75-2.95Z')],
  meteo: [P('M13.75 14.25V5a2.25 2.25 0 0 0-4.5 0v9.25a4.25 4.25 0 1 0 4.5 0Z'), P('M11.5 17.25V9.5'),
    P('M17 5.5h2.5M17 9h2.5M17 12.5h1.75')],
  // panneau photovoltaïque incliné sous le soleil
  solaire: [C(7, 6.75, 2.5), P('M7 1.75v1.25M7 10.5v1.25M2 6.75h1.25M10.75 6.75H12M3.45 3.2l.9.9M9.65 9.4l.9.9M3.45 10.3l.9-.9M9.65 4.1l.9-.9'),
    P('M8.25 13.25h13l-2.25 7.5H6Z'), P('M7.1 17h13M12.6 13.25l-1.85 7.5M17 13.25l-1.85 7.5')],
  // bois (granulés) : deux bûches
  bois: [R(3.25, 13.25, 17.5, 6, 3), R(5.75, 5.75, 12.5, 6, 3), C(6.25, 16.25, 1.1), C(8.75, 8.75, 1.1)],
  // rayonnement solaire (météo)
  soleil: [C(12, 12, 4), P('M12 2.75v2.5M12 18.75v2.5M2.75 12h2.5M18.75 12h2.5M5.45 5.45l1.75 1.75M16.8 16.8l1.75 1.75M5.45 18.55l1.75-1.75M16.8 7.2l1.75-1.75')],
  donnees: [P('M4.5 9.25a10.6 10.6 0 0 1 15 0'), P('M7.4 12.4a6.5 6.5 0 0 1 9.2 0'), P('M10.25 15.5a2.5 2.5 0 0 1 3.5 0'),
    C(12, 19, 1.1, true)],
  compteur: [R(4, 3.25, 16, 17.5, 2.5), R(7, 6.5, 10, 4.25, 1), C(12, 15.75, 2.25), P('M12 15.75l1.2-1.2')],
  // ---------------------------------------------------------------- interface
  tableau: [R(3.25, 3.25, 7.5, 9.5, 1.75), R(13.25, 3.25, 7.5, 5.5, 1.75), R(13.25, 11.25, 7.5, 9.5, 1.75),
    R(3.25, 15.25, 7.5, 5.5, 1.75)],
  immeuble: [P('M5 20.75V4.75a1.5 1.5 0 0 1 1.5-1.5h7a1.5 1.5 0 0 1 1.5 1.5v16'), P('M15 9.25h3a1.5 1.5 0 0 1 1.5 1.5v10'),
    P('M2.75 20.75h18.5'), P('M8.5 7.25h3M8.5 10.75h3M8.5 14.25h3'), P('M9 20.75v-3h2v3')],
  adresse: [P('M12 21.25s-6.75-5.75-6.75-11.25a6.75 6.75 0 0 1 13.5 0c0 5.5-6.75 11.25-6.75 11.25Z'), C(12, 10, 2.5)],
  alerte: [P('M10.3 4.15 2.85 17.4a1.95 1.95 0 0 0 1.7 2.9h14.9a1.95 1.95 0 0 0 1.7-2.9L13.7 4.15a1.95 1.95 0 0 0-3.4 0Z'),
    P('M12 9.25v4.25'), C(12, 16.9, 1.05, true)],
  bon: [R(5, 4.5, 14, 16.75, 2.25), R(9, 2.75, 6, 3.5, 1.25), P('M8.5 11h7M8.5 14.5h7M8.5 18h4')],
  prestataire: [P('M4.75 17.25V15a7.25 7.25 0 0 1 14.5 0v2.25'), P('M10 8.1V12.5M14 8.1v4.4'),
    P('M2.75 17.25h18.5a.75.75 0 0 1 .75.75v.5a1.5 1.5 0 0 1-1.5 1.5H3.5A1.5 1.5 0 0 1 2 18.5V18a.75.75 0 0 1 .75-.75Z')],
  regles: [P('M3.75 6.5h9M17.25 6.5h3M3.75 12h3.5M11.25 12h9M3.75 17.5h11.5M19.25 17.5h1'),
    C(15.25, 6.5, 2), C(9.25, 12, 2), C(17.25, 17.5, 2)],
  reglages: [C(12, 12, 3), C(12, 12, 6.5),
    P('M12 2.75v2.75M12 18.5v2.75M2.75 12H5.5M18.5 12h2.75M5.45 5.45l1.95 1.95M16.6 16.6l1.95 1.95M5.45 18.55l1.95-1.95M16.6 7.4l1.95-1.95')],
  importer: [P('M12 3.5v11'), P('M7.5 10.25 12 14.75l4.5-4.5'), P('M4 15.5v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3')],
  exporter: [P('M12 14.75v-11'), P('M7.5 8 12 3.5 16.5 8'), P('M4 15.5v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3')],
  carte: [P('M9 4.25 3.25 6.5v13.25L9 17.5l6 2.25 5.75-2.25V4.25L15 6.5Z'), P('M9 4.25V17.5M15 6.5v13.25')],
  analyser: [P('M19.75 10.5A8 8 0 0 0 5.6 7.1L4 8.75'), P('M4 4.25v4.5h4.5'), P('M4.25 13.5a8 8 0 0 0 14.15 3.4L20 15.25'),
    P('M20 19.75v-4.5h-4.5')],
  ajouter: [P('M12 5v14M5 12h14')],
  argent: [R(2.5, 6, 19, 12, 2.25), C(12, 12, 2.6), P('M6 9.25v.01M18 14.75v.01')],
  co2: [P('M5 19.25c0-8.25 5.1-13.6 14.75-14.75-.4 9.6-5.9 14.75-14.75 14.75Z'), P('M5 19.25 12.25 12')],
  energie: [P('M4.25 17.5a8.25 8.25 0 1 1 15.5 0'), P('M12 14.25 15.5 10'), C(12, 14.25, 1.25, true), P('M4.25 17.5h15.5')],
  pertinence: [C(12, 12, 8.75), P('M8.25 12.25l2.6 2.6 4.9-5.1')],
  courbe: [P('M4 4.25v15.5h16'), P('M7.5 15.25l3.5-4.25 3 2.5 4.75-6.25')],
  modifier: [P('M4 20h4.1L19.2 8.9a2.8 2.8 0 0 0-4-4.1L4 16v4Z'), P('M13.5 6.5l4 4')],
  supprimer: [P('M4.5 7h15'), P('M9.5 7V4.75a.75.75 0 0 1 .75-.75h3.5a.75.75 0 0 1 .75.75V7'), P('M6.5 7l.95 12.6a1.5 1.5 0 0 0 1.5 1.4h6.1a1.5 1.5 0 0 0 1.5-1.4L17.5 7'),
    P('M10 11v5.75M14 11v5.75')],
  courriel: [R(3, 5, 18, 14, 2.25), P('M3.6 6.6 12 12.9l8.4-6.3')],
  fermer: [P('M6.5 6.5l11 11M17.5 6.5l-11 11')],
  retour: [P('M19 12H5.5'), P('M11 6l-6 6 6 6')],
  ok: [C(12, 12, 8.75), P('M8.25 12.25l2.6 2.6 4.9-5.1')],
  info: [C(12, 12, 8.75), P('M12 11v5.25'), C(12, 7.9, 1.05, true)],
  contact: [C(12, 8.25, 3.75), P('M4.75 20.25a7.25 7.25 0 0 1 14.5 0')],
};

// Fluide : clé du moteur (vigie/db.py FLUIDES) ou libellé affiché → pictogramme et teinte.
const LIBELLES_FLUIDES = {
  eau: 'Eau froide', eau_chaude: 'Eau chaude sanitaire', electricite: 'Électricité', pac: 'Pompe à chaleur',
  chaleur: 'Chaleur', cad: 'Chauffage à distance', gaz: 'Gaz', mazout: 'Mazout', meteo: 'Température extérieure',
  solaire: 'Production solaire', soleil: 'Rayonnement solaire', bois: 'Bois (granulés)', donnees: 'Données des compteurs',
};

const sansAccents = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

export function cleFluide(fluide) {
  const s = sansAccents(fluide);
  if (s.startsWith('pac') || s.includes('pompe a chaleur')) return 'pac';
  if (s === 'cad' || s.includes('distance') || /\bcad\b/.test(s)) return 'cad';
  if (s.startsWith('cad')) return 'cad';
  if (s.includes('granul') || s.startsWith('bois')) return 'bois';
  if (s.includes('gaz')) return 'gaz';
  if (s.includes('mazout')) return 'mazout';
  if (s.startsWith('solaire') || s.includes('photovolta') || s.includes('production solaire')) return 'solaire';
  if (s.includes('rayonnement') || s.includes('ensoleill')) return 'soleil';
  if (s === 'eau_chaude' || s.includes('eau chaude') || /\becs\b/.test(s)) return 'eau_chaude';
  if (s.startsWith('eau')) return 'eau';
  if (s.includes('electri')) return 'electricite';
  if (s === 'meteo' || s.includes('temperature')) return 'meteo';
  if (s.includes('chaleur') || s.includes('chauff')) return 'chaleur';
  if (s.includes('donnee')) return 'donnees';
  return 'compteur';
}

export const libelleFluide = (fluide) => LIBELLES_FLUIDES[cleFluide(fluide)] || String(fluide || '');

// Pictogramme seul. `libelle` : rend l'icône annoncée (role img) quand aucun texte ne l'accompagne.
export function icone(nom, { classe = '', libelle = null } = {}) {
  const formes = DESSINS[nom] || DESSINS.compteur;
  const attrs = { class: ('ico ' + classe).trim(), viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.75', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', focusable: 'false' };
  if (libelle) Object.assign(attrs, { role: 'img', 'aria-label': libelle });
  else attrs['aria-hidden'] = 'true';
  return h('svg', attrs, libelle ? h('title', {}, libelle) : null, formes.map(([balise, a]) => {
    const { plein, ...reste } = a;
    return h(balise, plein ? { ...reste, fill: 'currentColor', stroke: 'none' } : reste);
  }));
}

// Pastille ronde teintée de la couleur du fluide. taille : 'xs' | 'sm' | 'md' | 'lg'.
export function pastilleFluide(fluide, { taille = 'sm', libelle = null } = {}) {
  const cle = cleFluide(fluide);
  return h('span', { class: `pastille-fluide t-${taille} f-${cle}`, title: libelle || null },
    icone(cle === 'compteur' ? 'compteur' : cle, { libelle }));
}

// Étiquette « pastille + libellé » (remplace l'ancienne étiquette texte du fluide).
export function tagFluide(fluide, texte) {
  return h('span', { class: 'tag-fluide f-' + cleFluide(fluide) }, pastilleFluide(fluide, { taille: 'xs' }),
    h('span', {}, texte ?? fluide));
}

// Bouton ou lien avec pictogramme : [icone, texte]
export const avecIcone = (nom, texte) => [icone(nom), h('span', {}, texte)];

// Titre de carte précédé d'un pictogramme
export function titreIcone(nom, balise, attrs, texte) {
  return h(balise, { ...attrs, class: ((attrs && attrs.class) || '') + ' titre-ico' }, h('span', { class: 'ico-titre' }, icone(nom)), texte);
}

// Bulle « comment ce chiffre est construit » : pictogramme i, détail au survol ou au focus clavier.
// La bulle se place dans le premier ancêtre positionné (tuile, colonne d'impact) pour ne jamais sortir de l'écran.
// Un clic sur la bulle ne déclenche pas l'action de l'élément cliquable qui la contient.
export function aideCalcul(...lignes) {
  const textes = lignes.flat().filter(Boolean);
  return h('span', { class: 'aide-calcul', tabindex: '0', title: '', // title vide : masque l'infobulle native du parent
    'aria-label': 'Calcul : ' + textes.join(' '), onclick: (ev) => ev.stopPropagation() },
  icone('info'), h('span', { class: 'bulle-calcul', 'aria-hidden': 'true' }, textes.map((l) => h('span', {}, l))));
}

// État vide : pictogramme dans un cercle, message, actions éventuelles
export function etatVide(nom, message, ...actions) {
  return h('div', { class: 'vide' }, h('span', { class: 'vide-ico' + (nom === 'ok' ? '' : ' ton-neutre') }, icone(nom)),
    typeof message === 'string' ? h('p', {}, message) : message, actions.length ? h('div', { class: 'actions' }, actions) : null);
}
