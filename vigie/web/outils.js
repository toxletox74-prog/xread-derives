// Outils communs de l'interface Vigie : appels au serveur local, construction du DOM, formats, dialogues.
// Tout le texte est inséré avec textContent (jamais innerHTML) : aucune donnée importée ne peut injecter de code.

export async function api(methode, chemin, corps, options = {}) {
  const init = { method: methode, headers: { 'X-Vigie': '1' } };
  if (corps instanceof Blob || corps instanceof ArrayBuffer) {
    init.body = corps;
    init.headers['Content-Type'] = 'application/octet-stream';
  } else if (corps !== undefined) {
    init.body = JSON.stringify(corps);
    init.headers['Content-Type'] = 'application/json';
  }
  let rep;
  try {
    rep = await fetch(chemin, init);
  } catch (e) {
    throw new Error('Vigie ne répond pas. Vérifiez que la fenêtre de commande de Vigie est toujours ouverte.');
  }
  if (options.brut) {
    if (!rep.ok) throw new Error((await rep.json().catch(() => ({}))).erreur || 'Erreur ' + rep.status);
    return rep;
  }
  const donnees = await rep.json().catch(() => ({}));
  if (!rep.ok) throw new Error(donnees.erreur || 'Erreur ' + rep.status);
  return donnees;
}

// Balises créées dans l'espace de noms SVG (graphiques et pictogrammes de icones.js)
const BALISES_SVG = ['svg', 'rect', 'text', 'line', 'g', 'path', 'title', 'circle', 'ellipse', 'polyline', 'polygon'];

// h('div', {class: 'x', onclick: f}, 'texte', autreNoeud, [liste]) — attributs sûrs, enfants en texte
export function h(tag, attrs, ...enfants) {
  const svg = BALISES_SVG.includes(tag);
  const el = svg ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'style') el.style.cssText = v; // CSSOM : autorisé par la politique de sécurité (pas de style en ligne)
    else if (k === 'value' && !svg) el.value = v;
    else if (k === 'checked' || k === 'selected' || k === 'disabled') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  ajouter(el, enfants);
  return el;
}

function ajouter(el, enfants) {
  for (const e of enfants) {
    if (e === null || e === undefined || e === false) continue;
    if (Array.isArray(e)) ajouter(el, e);
    else if (e instanceof Node) el.appendChild(e);
    else el.appendChild(document.createTextNode(String(e)));
  }
}

export function vider(el, ...enfants) {
  el.replaceChildren();
  ajouter(el, enfants);
  return el;
}

// ---------------------------------------------------------------- formats (français, Europe/Zurich)

const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
const absent = (x) => x === null || x === undefined || Number.isNaN(x);

function versDate(iso) {
  const s = String(iso);
  if (s.length <= 10) return new Date(s + 'T12:00:00Z');
  return new Date(s.replace(' ', 'T') + (/[Z+]/.test(s.slice(10)) ? '' : 'Z'));
}

export const fmt = {
  n0: (x) => (absent(x) ? '—' : nf0.format(x)),
  n1: (x) => (absent(x) ? '—' : nf1.format(x)),
  n2: (x) => (absent(x) ? '—' : nf2.format(x)),
  chf: (x, unite = 'CHF') => (x ? '≈ ' + nf0.format(x) + ' ' + unite : '—'),
  pct: (x) => (absent(x) ? '—' : nf0.format(x * 100) + ' %'),
  date(iso) {
    if (!iso) return '—';
    const d = versDate(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString('fr-CH', { timeZone: 'Europe/Zurich', day: '2-digit', month: '2-digit', year: 'numeric' });
  },
  dateHeure(iso) {
    if (!iso) return '—';
    const d = versDate(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('fr-CH', { timeZone: 'Europe/Zurich', day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit' });
  },
  depuis(iso, reference) {
    if (!iso) return 'jamais';
    const fin = reference ? versDate(reference).getTime() : Date.now();
    const heures = (fin - versDate(iso).getTime()) / 3600000;
    if (heures < 1) return 'à jour';
    if (heures < 48) return Math.round(heures) + ' h avant';
    return Math.round(heures / 24) + ' jours avant';
  },
};

export const PROFILS = { Habite: 'Habité', Partiel: 'Partiellement occupé', Vide: 'Vide', Travaux: 'Travaux' };
export const STATUTS_BON = { brouillon: 'Brouillon', envoye: 'Envoyé', en_cours: 'En cours', retour: 'Retour reçu',
  termine: 'Terminé', annule: 'Annulé' };
export const ETATS_POINT = { actif: 'Actif', a_connecter: 'À connecter', inactif: 'Inactif' };
export const RETOURS = { pertinente: 'Pertinente', deja_connue: 'Déjà connue', fausse_alerte: 'Fausse alerte' };

// Chiffrage d'une alerte (calculé par le moteur, jamais ici). D'abord la dérive CONSTATÉE (mesurée depuis le début :
// base des actions), puis le rythme mensuel (base de la priorité), puis la PROJECTION si rien n'est fait (hypothèse
// affichée : climat normal ou dérive constante ; jamais un déclencheur).
export function enjeu(a) {
  if (!a || a.gravite === 'Données') return { principal: '—', precisions: [] };
  if (a.chf_mesure === undefined || a.chf_mesure === null) {
    return { principal: a.chf_an ? fmt.chf(a.chf_an, 'CHF/an') : '—', precisions: [] }; // version antérieure
  }
  const q = [a.kwh_mesure ? fmt.n0(a.kwh_mesure) + ' kWh' : null, a.m3_mesure ? fmt.n1(a.m3_mesure) + ' m³' : null]
    .filter(Boolean).join(' · ');
  const p = [(q ? q + ' ' : '') + (a.periode || ''),
    'rythme ' + fmt.chf(a.chf_mois, 'CHF/mois') + (a.jours_rythme ? ` (sur ${a.jours_rythme} jours)` : '')];
  if (a.chf_proj !== null && a.chf_proj !== undefined) {
    p.push("Projection si rien n'est fait : " + fmt.chf(a.chf_proj) + ' ' + (a.projection || ''));
  } else if (a.projection) p.push('Projection ' + a.projection);
  return { principal: 'Dérive constatée : ' + fmt.chf(a.chf_mesure), precisions: p };
}

// Élément entier cliquable (ligne de tableau, tuile, entrée de liste), activable au clavier (Entrée, Espace).
// Les liens, boutons et champs qu'il contient gardent leur propre action.
export function cliquable(action, titre, classe = '') {
  return { class: ('cliquable ' + classe).trim(), tabindex: '0', title: titre || null,
    onclick: (ev) => { if (!ev.target.closest('a, button, input, select, textarea, label')) action(); },
    onkeydown: (ev) => {
      if ((ev.key === 'Enter' || ev.key === ' ') && ev.target === ev.currentTarget) { ev.preventDefault(); action(); }
    } };
}

// Ouvre la page Alertes déjà filtrée (gravité, clé de fluide), depuis le tableau de bord
export function allerAlertes(ctx, filtres) {
  sessionStorage.setItem('vigie-alertes-filtres', JSON.stringify(filtres));
  ctx.aller('#/alertes');
}

export const chip = (gravite) => h('span', { class: 'chip g-' + gravite }, gravite);
export const chipStatut = (s) => h('span', { class: 'chip s-' + s }, STATUTS_BON[s] || s);

// ---------------------------------------------------------------- retours visuels

export function toast(message, erreur = false) {
  let zone = document.querySelector('.toasts');
  if (!zone) {
    zone = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(zone);
  }
  const t = h('div', { class: 'toast' + (erreur ? ' erreur' : '') }, message);
  zone.appendChild(t);
  setTimeout(() => t.remove(), erreur ? 9000 : 4500);
}

export async function tenter(action, messageOk) {
  try {
    const r = await action();
    if (messageOk) toast(typeof messageOk === 'function' ? messageOk(r) : messageOk);
    return r;
  } catch (e) {
    toast(e.message, true);
    return undefined;
  }
}

// Boîte de dialogue modale. `contenu` = nœud ; `boutons` = [{texte, classe, action: async () => false pour rester ouvert}]
export function dialogue(titre, contenu, boutons = [], options = {}) {
  const d = h('dialog', { 'aria-label': titre, style: options.large ? 'width:min(980px, calc(100vw - 24px))' : null });
  const fermer = () => { if (d.open) d.close(); d.remove(); };
  const pied = h('div', { class: 'dialogue-pied' },
    h('button', { type: 'button', onclick: fermer }, options.texteFermer || 'Annuler'),
    boutons.map((b) => h('button', {
      type: 'button', class: b.classe || '', onclick: async (ev) => {
        const bouton = ev.currentTarget;
        bouton.disabled = true;
        try {
          const fini = await b.action();
          if (fini !== false) fermer();
        } finally {
          bouton.disabled = false;
        }
      },
    }, b.texte)));
  vider(d, h('div', { class: 'dialogue-tete' }, h('h2', {}, titre),
    h('button', { type: 'button', class: 'lien', onclick: fermer }, 'Fermer ✕')),
  h('div', { class: 'dialogue-corps' }, contenu), pied);
  d.addEventListener('cancel', (e) => { e.preventDefault(); fermer(); });
  document.body.appendChild(d);
  d.showModal();
  return { fermer, el: d };
}

export function confirmer(titre, message, texteOk = 'Confirmer', danger = false) {
  return new Promise((resoudre) => {
    let repondu = false;
    const { el } = dialogue(titre, h('p', {}, message), [{
      texte: texteOk, classe: danger ? 'danger' : 'primaire', action: () => { repondu = true; resoudre(true); },
    }]);
    el.addEventListener('close', () => { if (!repondu) resoudre(false); });
  });
}

// ---------------------------------------------------------------- champs de formulaire

let compteurChamp = 0;
export function champ(libelle, controle, aide, classe) {
  const id = controle.id || 'c' + (++compteurChamp);
  controle.id = id;
  return h('div', { class: 'champ ' + (classe || '') }, h('label', { for: id }, libelle), controle,
    aide ? h('span', { class: 'aide' }, aide) : null);
}

export function liste(nom, options, valeur) {
  return h('select', { name: nom }, options.map((o) => {
    const [v, lib] = Array.isArray(o) ? o : [o, o];
    return h('option', { value: v, selected: String(v) === String(valeur ?? '') }, lib);
  }));
}

export function saisie(nom, valeur, attrs = {}) {
  return h('input', { type: 'text', name: nom, value: valeur ?? '', ...attrs });
}

export function lireFormulaire(racine) {
  const d = {};
  // les cases d'un groupe (data-groupe) n'ont pas de nom : sans elles, la liste cochée était toujours perdue
  racine.querySelectorAll('input[name], input[data-groupe], select[name], textarea[name]').forEach((el) => {
    if (el.type === 'checkbox' && el.dataset.groupe) {
      d[el.dataset.groupe] ||= [];
      if (el.checked) d[el.dataset.groupe].push(el.value);
    } else if (el.type === 'checkbox') d[el.name] = el.checked;
    else d[el.name] = el.value;
  });
  return d;
}

export function telecharger(blob, nom) {
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: nom });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// Graphique en barres (SVG) des valeurs journalières
export function graphe(jours, unite) {
  const L = 720, H = 150, marge = 24;
  const valeurs = jours.map((j) => j.valeur ?? 0);
  const max = Math.max(...valeurs, 0.0001);
  const larg = (L - 8) / Math.max(1, jours.length);
  const svg = h('svg', { class: 'graphe', viewBox: `0 0 ${L} ${H}`, role: 'img',
    'aria-label': `Valeurs journalières sur ${jours.length} jours, maximum ${fmt.n1(max)} ${unite}` });
  jours.forEach((j, i) => {
    const hb = j.valeur === null ? 0 : Math.max(1, (j.valeur / max) * (H - marge - 18));
    const info = `${fmt.date(j.jour)} : ${j.valeur === null ? 'pas de donnée' : fmt.n1(j.valeur) + ' ' + unite}`;
    svg.appendChild(h('rect', { x: 4 + i * larg, y: H - marge - hb, width: Math.max(1, larg - 1.5), height: hb,
      class: i === jours.length - 1 ? 'dernier' : null }, h('title', {}, info)));
  });
  if (jours.length) {
    svg.appendChild(h('text', { x: 4, y: H - 6 }, fmt.date(jours[0].jour)));
    svg.appendChild(h('text', { x: L - 4, y: H - 6, 'text-anchor': 'end' }, fmt.date(jours[jours.length - 1].jour)));
    svg.appendChild(h('text', { x: 4, y: 12 }, `max ${fmt.n1(max)} ${unite}`));
  }
  return svg;
}
