// Fiche technique d'un immeuble : contacts, données techniques, partenaires par fluide, consommation
// (jour / mois / année), compteurs, suivi horodaté des alertes et des bons, historique.
import {
  api, h, vider, fmt, chip, tenter, dialogue, confirmer, champ, liste, saisie, lireFormulaire, cliquable, PROFILS,
} from './outils.js';
import { profilTexte, ouvrirBon } from './pages_suivi.js';
import { formImmeuble, formCompteur, tableCompteurs, surveillance, supprimerImmeuble } from './pages_parc.js';
import { icone, pastilleFluide, cleFluide, titreIcone, etatVide } from './icones.js';

const ECHELLES = [['jour', 'Jour'], ['mois', 'Mois'], ['annee', 'Année']];
const UNITES = { m3: 'm³', degC: '°C' };
const CLASSE_SUIVI = { en_attente: 'g-Attente', bon_envoye: 'g-Modérée', retour_incident: 'g-Élevée',
  a_verifier: 'g-Données', cloturee: 'g-OK', sourdine: 'g-Attente' };
const CLASSE_DECLARATION = { en_cours: 'g-Modérée', en_vigueur: 'g-Données', a_venir: 'g-Attente', echue: 'g-OK' };
const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

function libellePeriode(p, echelle) {
  if (echelle === 'annee') return p;
  if (echelle === 'mois') return `${MOIS[Number(p.slice(5, 7)) - 1]} ${p.slice(0, 4)}`;
  return `${p.slice(8, 10)}.${p.slice(5, 7)}`;
}

function contact(titre, nom, email, tel, vide, completer) {
  return h('div', { class: 'kpi' }, h('div', { class: 'kpi-tete' }, h('span', { class: 'kpi-ico' }, icone('contact')),
    h('span', { class: 'lib' }, titre)),
    nom ? h('span', { class: 'gras' }, nom)
      : h('span', {}, h('span', { class: 'doux' }, vide + ' · '), h('button', { type: 'button', class: 'lien', onclick: completer }, 'Compléter')),
    email ? h('a', { href: 'mailto:' + email, class: 'petit' }, email) : null,
    tel ? h('a', { href: 'tel:' + tel.replace(/\s/g, ''), class: 'petit' }, tel) : null);
}

// ---------------------------------------------------------------- consommation (graphique)

function barres(valeurs, unite, echelle) {
  const L = 760, H = 190, bas = 28, haut = 16;
  const max = Math.max(...valeurs.map((v) => v.valeur ?? 0), 0.0001);
  const larg = (L - 8) / Math.max(1, valeurs.length);
  const pas = Math.max(1, Math.ceil(valeurs.length / 12));
  const svg = h('svg', { class: 'graphe graphe-haut', viewBox: `0 0 ${L} ${H}`, role: 'img',
    'aria-label': `Consommation par ${echelle}, ${valeurs.length} périodes, maximum ${fmt.n1(max)} ${unite}` });
  valeurs.forEach((v, i) => {
    const hb = v.valeur === null ? 0 : Math.max(1, (v.valeur / max) * (H - bas - haut));
    svg.appendChild(h('rect', { x: 4 + i * larg, y: H - bas - hb, width: Math.max(1, larg - 2), height: hb,
      class: i === valeurs.length - 1 ? 'dernier' : null },
    h('title', {}, `${libellePeriode(v.periode, echelle)} : ${v.valeur === null ? 'pas de donnée' : fmt.n1(v.valeur) + ' ' + unite}`
      + (v.estimee ? ' (valeur estimée par le distributeur)' : ''))));
    if (i % pas === 0) {
      svg.appendChild(h('text', { x: 4 + i * larg + larg / 2, y: H - 10, 'text-anchor': 'middle' }, libellePeriode(v.periode, echelle)));
    }
  });
  svg.appendChild(h('text', { x: 4, y: 11 }, `max ${fmt.n1(max)} ${unite}`));
  return svg;
}

function sectionConsommation(points) {
  const suivis = points.filter((p) => p.etat !== 'inactif');
  const etat = { pid: (suivis.find((p) => p.derniere) || suivis[0] || {}).id, echelle: 'mois' };
  const boutonsCompteurs = h('div', { class: 'segments', role: 'group', 'aria-label': 'Compteur' });
  const boutonsEchelle = h('div', { class: 'segments', role: 'group', 'aria-label': 'Échelle' });
  const zone = h('div', { class: 'carte-corps' });
  const rendre = async () => {
    vider(boutonsCompteurs, suivis.map((p) => h('button', { type: 'button', 'aria-pressed': String(p.id === etat.pid),
      class: p.id === etat.pid ? 'choisi' : null, onclick: () => { etat.pid = p.id; rendre(); } },
    pastilleFluide(p.fluide, { taille: 'xs' }), p.libelle)));
    vider(boutonsEchelle, ECHELLES.map(([e, lib]) => h('button', { type: 'button', 'aria-pressed': String(e === etat.echelle),
      class: e === etat.echelle ? 'choisi' : null, onclick: () => { etat.echelle = e; rendre(); } }, lib)));
    if (!etat.pid) return vider(zone, etatVide('compteur', 'Aucun compteur.'));
    vider(zone, h('p', { class: 'doux' }, 'Chargement…'));
    const r = await tenter(() => api('GET', `/api/consommation/${encodeURIComponent(etat.pid)}?echelle=${etat.echelle}`));
    if (!r) return null;
    const unite = UNITES[r.point.unite] || r.point.unite;
    if (!r.valeurs.length) return vider(zone, etatVide('courbe', 'Pas encore de données pour ce compteur.'));
    const choisi = suivis.find((p) => p.id === etat.pid) || {};
    const graphe = barres(r.valeurs, unite, etat.echelle);
    graphe.classList.add('f-' + cleFluide(choisi.fluide));
    const parPeriode = { jour: 'par jour', mois: 'par mois', annee: 'par an' }[etat.echelle];
    return vider(zone,
      h('div', { class: 'resume-import' },
        h('div', {}, h('div', { class: 'doux petit' }, r.instantane ? 'Moyenne' : `Total (${r.valeurs.length} périodes)`),
          h('b', {}, r.instantane ? `${fmt.n1(r.moyenne)} ${unite}` : `${fmt.n0(r.total)} ${unite}`)),
        h('div', {}, h('div', { class: 'doux petit' }, `Moyenne ${parPeriode}`), h('b', {}, `${fmt.n1(r.moyenne)} ${unite}`)),
        h('div', {}, h('div', { class: 'doux petit' }, 'Dernière période'),
          h('b', {}, `${libellePeriode(r.valeurs.at(-1).periode, etat.echelle)} : ${fmt.n1(r.valeurs.at(-1).valeur)} ${unite}`))),
      graphe,
      h('p', { class: 'doux petit' }, `${r.point.libelle} (${r.point.id}) · ${r.instantane ? 'moyenne' : 'consommation'} ${parPeriode}, `
        + 'heure de Genève. Périodes sans mesure laissées vides (jamais comblées) ; la période en cours peut être partielle.'));
  };
  const section = h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('courbe', 'h2', {}, 'Consommation par fluide'),
      h('span', { class: 'doux petit' }, 'Choisissez le compteur et l\'échelle : journalière (90 jours), mensuelle ou annuelle.')),
    boutonsEchelle),
    h('div', { class: 'carte-corps' }, boutonsCompteurs), zone);
  section.choisir = (pid) => { etat.pid = pid; rendre(); section.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  rendre();
  return section;
}

// ---------------------------------------------------------------- fiche : contacts et technique

function formFiche(f, ctx) {
  const im = f.immeuble;
  const t = im.technique || {};
  const champsTech = f.listes.technique.map((c) => (c.type === 'choix'
    ? champ(c.libelle, liste('t_' + c.cle, [['', '—'], ...c.choix], t[c.cle] ?? ''))
    : champ(c.libelle, c.cle === 'notes' ? h('textarea', { name: 't_' + c.cle, rows: 3 }, t[c.cle] ?? '')
      : saisie('t_' + c.cle, t[c.cle] ?? ''), null, c.cle === 'notes' ? 'large' : '')));
  const form = h('div', { class: 'formulaire' },
    h('h3', { class: 'large' }, 'Gestionnaire'),
    champ('Nom', saisie('gestionnaire', im.gestionnaire)), champ('E-mail', saisie('gestionnaire_email', im.gestionnaire_email)),
    champ('Téléphone', saisie('gestionnaire_tel', im.gestionnaire_tel)),
    h('h3', { class: 'large' }, 'Concierge'),
    champ('Nom', saisie('concierge', im.concierge)),
    champ('E-mail', saisie('concierge_email', im.concierge_email), 'Destinataire des bons adressés au concierge.'),
    champ('Téléphone', saisie('concierge_tel', im.concierge_tel)),
    h('h3', { class: 'large' }, 'Données techniques'), champsTech);
  dialogue(`Fiche technique — ${im.nom}`, form, [{ texte: 'Enregistrer', classe: 'primaire', action: async () => {
    const corps = { technique: {} };
    form.querySelectorAll('[name]').forEach((el) => {
      if (el.name.startsWith('t_')) corps.technique[el.name.slice(2)] = el.value;
      else corps[el.name] = el.value;
    });
    const ok = await tenter(() => api('PUT', `/api/immeubles/${encodeURIComponent(im.id)}/fiche`, corps), 'Fiche enregistrée.');
    if (ok) await ctx.recharger();
    return !!ok;
  } }], { large: true });
}

function blocTechnique(f, completer) {
  const t = f.immeuble.technique || {};
  const lignes = f.listes.technique.filter((c) => t[c.cle] !== undefined && t[c.cle] !== '');
  return h('div', { class: 'kpi technique' }, h('div', { class: 'kpi-tete' }, h('span', { class: 'kpi-ico' }, icone('reglages')),
    h('span', { class: 'lib' }, 'Données techniques')),
    lignes.length ? h('dl', {}, lignes.map((c) => [h('dt', {}, c.libelle), h('dd', {}, String(t[c.cle]))]))
      : h('span', {}, h('span', { class: 'doux' }, 'Non renseignées · '),
        h('button', { type: 'button', class: 'lien', onclick: completer }, 'Compléter')));
}

// Bâtiments du site (avec leur identifiant) et installations techniques, issus du classeur patrimoine
function sectionSite(f) {
  const bats = f.batiments || [];
  const insts = f.installations || [];
  if (!bats.length && !insts.length) return null;
  const v = (x) => (x === null || x === undefined || x === '' ? '—' : String(x));
  const table = (entetes, lignes) => h('div', { class: 'defile' }, h('table', {},
    h('thead', {}, h('tr', {}, entetes.map((x) => h('th', { scope: 'col' }, x)))), h('tbody', {}, lignes)));
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('immeuble', 'h2', {}, 'Bâtiments et installations du site'),
      h('span', { class: 'doux petit' }, `${bats.length} bâtiment(s) · ${insts.length} installation(s) technique(s). `
        + 'Les compteurs sont rattachés au site.'))),
    bats.length ? table(['Identifiant', 'Bâtiment', 'Construction', 'Rénovation', 'SRE (m²)', 'Niveaux', 'Logements', 'Label', 'Ouverture', 'Remarque'],
      bats.map((b) => h('tr', {}, h('td', {}, h('span', { class: 'tag' }, b.id)), h('td', {}, b.nom), h('td', {}, v(b.annee_construction)),
        h('td', {}, v(b.annee_renovation)), h('td', { class: 'nombre' }, b.sre_m2 ? fmt.n0(b.sre_m2) : 'sans objet'),
        h('td', {}, v(b.niveaux)), h('td', {}, v(b.logements)), h('td', {}, v(b.label)), h('td', {}, v(b.ouverture)),
        h('td', { class: 'doux petit' }, v(b.remarque))))) : null,
    insts.length ? table(['Identifiant', 'Installation', 'Énergie', 'Puissance', 'Mise en service', 'Retrait', 'Remarque'],
      insts.map((i) => h('tr', {}, h('td', {}, h('span', { class: 'tag' }, i.id)), h('td', {}, i.libelle), h('td', {}, v(i.vecteur)),
        h('td', { class: 'nombre' }, i.puissance_kw ? `${fmt.n0(i.puissance_kw)} ${i.type === 'pv' ? 'kWc' : 'kW'}` : '—'),
        h('td', {}, v(i.mise_en_service)), h('td', {}, i.retrait ? h('span', { class: 'chip g-Données' }, i.retrait) : 'en service'),
        h('td', { class: 'doux petit' }, v(i.remarque))))) : null);
}

// Ouvre la fiche d'un prestataire sur la page Prestataires
function ouvrirPrestataire(id, ctx) {
  sessionStorage.setItem('vigie-ouvrir-prestataire', String(id));
  ctx.aller('#/prestataires');
}

function tablePartenaires(partenaires, ctx) {
  return h('div', { class: 'defile' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Fluide', 'Métier', 'Partenaire technique', 'Contact', 'E-mail', 'Téléphone']
      .map((x) => h('th', { scope: 'col' }, x)))),
    h('tbody', {}, partenaires.map((p) => h('tr', {},
      h('td', {}, h('span', { class: 'cellule-fluide' }, pastilleFluide(p.fluide), p.libelle)),
      h('td', {}, h('span', { class: 'tag' }, p.metier)),
      p.prestataire ? [h('td', {}, h('button', { type: 'button', class: 'lien', title: 'Ouvrir la fiche du prestataire',
        onclick: () => ouvrirPrestataire(p.prestataire.id, ctx) }, p.prestataire.nom)), h('td', {}, p.prestataire.contact || '—'),
        h('td', {}, h('a', { href: 'mailto:' + p.prestataire.email }, p.prestataire.email)),
        h('td', {}, p.prestataire.telephone || '—')]
        : h('td', { colspan: '4' }, h('a', { href: '#/prestataires', title: 'Ajouter un prestataire' },
          h('span', { class: 'chip g-Attente' }, 'Aucun partenaire : à ajouter dans Prestataires'))))))));
}

// Fait défiler jusqu'à la ligne de l'alerte dans « Suivi des alertes et des bons » et la met en évidence
function montrerAlerte(id) {
  const tr = document.querySelector(`tr[data-alerte="${CSS.escape(id)}"]`);
  if (!tr) return;
  tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
  tr.classList.remove('eclair');
  void tr.offsetWidth; // relance l'animation
  tr.classList.add('eclair');
}

// ---------------------------------------------------------------- suivi des alertes et historique

function tableSuivi(f, ctx) {
  if (!f.alertes.length) return etatVide('ok', 'Aucune alerte pour cet immeuble.');
  const ligne = (a) => {
    const b = a.bon;
    const dest = b && b.destinataire_type
      ? `${b.destinataire_type === 'concierge' ? 'Concierge' : 'Partenaire technique'} : ${b.destinataire_nom || b.destinataire || ''}`
      : (b ? 'Destinataire à choisir' : '—');
    const creer = () => tenter(async () => {
      const r = await api('POST', `/api/alertes/${encodeURIComponent(a.id)}/bon`, {});
      await ouvrirBon(r.bon.id, ctx);
    });
    return h('tr', { ...(b ? cliquable(() => ouvrirBon(b.id, ctx), 'Ouvrir le bon ' + b.numero) : {}), 'data-alerte': a.id },
      h('td', { class: 'nombre' }, fmt.dateHeure(a.ouverte_le)),
      h('td', {}, h('div', { class: 'cellule-fluide' }, pastilleFluide(a.gravite === 'Données' ? 'donnees' : a.fluide, { libelle: a.fluide }),
        h('div', {}, h('div', {}, a.titre), h('div', { class: 'ligne-tags' }, chip(a.gravite),
          h('span', { class: 'doux petit' }, a.fluide))))),
      h('td', {}, h('span', { class: 'chip ' + CLASSE_SUIVI[a.suivi] }, f.suivis[a.suivi]),
        a.suivi === 'sourdine' ? h('div', { class: 'doux petit' }, `jusqu'au ${fmt.date(a.sourdine.jusquau)} : ${a.sourdine.motif}`) : null),
      h('td', {}, b ? h('button', { type: 'button', class: 'lien', onclick: () => ouvrirBon(b.id, ctx) }, b.numero)
        : (a.statut === 'ouverte' && a.suivi !== 'sourdine'
          ? h('button', { type: 'button', class: 'lien', onclick: creer }, 'Créer le bon') : '—'),
      b && b.envoye_le ? h('div', { class: 'doux petit' }, 'envoyé le ' + fmt.dateHeure(b.envoye_le)) : null),
      h('td', {}, dest),
      h('td', {}, b && b.retour_le ? [h('span', { class: 'gras' }, f.resultats_retour[b.retour_resultat] || ''),
        h('div', { class: 'doux petit' }, fmt.dateHeure(b.retour_le)), h('div', { class: 'petit' }, b.retour_texte)] : '—'),
      h('td', { class: 'nombre' }, a.statut === 'resolue' ? fmt.dateHeure(a.cloturee_le) : h('span', { class: 'doux' }, 'en cours')));
  };
  return h('div', { class: 'defile' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Ouverte le', 'Alerte', 'Suivi', 'Bon', 'Destinataire', 'Retour d\'incident', 'Dérive disparue le']
      .map((x, i) => h('th', { scope: 'col', class: i === 0 || i === 6 ? 'nombre' : null }, x)))),
    h('tbody', {}, f.alertes.map(ligne))));
}

function historique(evenements, ctx) {
  if (!evenements.length) return etatVide('info', 'Aucun événement enregistré.');
  const classe = { alerte_ouverte: 'pe-critique', alerte_rouverte: 'pe-critique', alerte_resolue: 'pe-ok', bon: 'pe-moderee',
    avis: 'pe-donnees' };
  // un événement de bon ouvre le bon ; un événement d'alerte montre l'alerte dans le suivi
  const action = (e) => (e.bon_id ? cliquable(() => ouvrirBon(e.bon_id, ctx), 'Ouvrir le bon ' + (e.numero || ''))
    : e.alerte_id ? cliquable(() => montrerAlerte(e.alerte_id), 'Voir l\'alerte dans le suivi') : {});
  return h('ol', { class: 'historique' }, evenements.map((e) => h('li', action(e),
    h('time', { datetime: e.le }, fmt.dateHeure(e.le)), h('span', { class: 'point-etat petit-point ' + (classe[e.type] || 'pe-donnees') }),
    h('span', {}, e.texte))));
}

// ---------------------------------------------------------------- déclarations : sourdine, travaux, vacance, changement

function formDeclaration(im, regles, types, ctx) {
  const type = liste('type', Object.entries(types), 'sourdine');
  const fluides = new Set(im.points.map((p) => p.fluide));
  const cRegle = champ('Règle mise en sourdine', liste('cause', regles.regles.filter((r) => fluides.has(r.fluide_point))
    .map((r) => [r.id, r.libelle])), 'La dérive reste calculée et visible « en sourdine », sans bon de travaux.');
  const cCompteur = champ('Compteur concerné', liste('point_id', [['', 'Tous les compteurs de l\'immeuble'],
    ...im.points.map((p) => [p.id, `${p.libelle} (${p.id})`])]),
  'Compteur remplacé, ou compteur de l\'installation dont la consigne ou la courbe de chauffe a changé.');
  const debut = saisie('debut', '', { type: 'date' });
  const cDebut = champ('Début', debut);
  const cFin = champ('Fin', saisie('fin', '', { type: 'date' }), 'Obligatoire : la déclaration cesse seule à cette date.');
  const ajuster = () => {
    const t = type.value;
    cRegle.style.display = t === 'sourdine' ? '' : 'none';
    cCompteur.style.display = t === 'changement' ? '' : 'none';
    cFin.style.display = t === 'changement' ? 'none' : '';
    cDebut.querySelector('label').textContent = { sourdine: 'Début (vide : dès maintenant)',
      changement: 'Date du changement' }[t] || 'Début';
  };
  type.addEventListener('change', ajuster);
  const form = h('div', { class: 'formulaire' }, champ('Type', type), cRegle, cCompteur, cDebut, cFin,
    champ('Motif', h('textarea', { name: 'motif', rows: 2 }), 'Obligatoire : il reste affiché avec la déclaration.', 'large'),
    champ('Auteur', saisie('auteur', '')));
  ajuster();
  dialogue(`Déclarer — ${im.nom}`, form, [{ texte: 'Déclarer', classe: 'primaire', action: async () => {
    const ok = await tenter(() => api('POST', `/api/immeubles/${encodeURIComponent(im.id)}/declarations`, lireFormulaire(form)),
      'Déclaration enregistrée. Travaux, vacance et changement : pris en compte à la prochaine analyse.');
    if (ok) await ctx.recharger();
    return !!ok;
  } }]);
}

function tableDeclarations(d, ctx) {
  if (!d.declarations.length) return etatVide('info', 'Aucune déclaration pour cet immeuble.');
  const supprimer = async (x) => {
    if (!await confirmer('Supprimer la déclaration', `${x.libelle} : la suppression est tracée dans l'historique.`, 'Supprimer', true)) return;
    if (await tenter(() => api('DELETE', '/api/declarations/' + x.id), 'Déclaration supprimée.')) await ctx.recharger();
  };
  return h('div', { class: 'defile' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Déclaration', 'État', 'Motif', 'Déclarée le', ''].map((x) => h('th', { scope: 'col' }, x)))),
    h('tbody', {}, d.declarations.map((x) => h('tr', {},
      h('td', {}, x.libelle),
      h('td', {}, h('span', { class: 'chip ' + CLASSE_DECLARATION[x.etat] }, d.etats[x.etat])),
      h('td', {}, x.motif, x.auteur ? h('div', { class: 'doux petit' }, x.auteur) : null),
      h('td', { class: 'nombre' }, fmt.dateHeure(x.cree_le)),
      h('td', {}, h('button', { type: 'button', class: 'lien', onclick: () => supprimer(x) }, 'Supprimer')))))));
}

// ---------------------------------------------------------------- page

export async function pageImmeuble(main, ctx, id) {
  const [parc, regles, f, { bons }] = await Promise.all([api('GET', '/api/parc'), api('GET', '/api/regles'),
    api('GET', `/api/immeubles/${encodeURIComponent(id)}/fiche`), api('GET', '/api/bons')]);
  const ad = parc.adresses.find((a) => a.immeubles.some((i) => i.id === id));
  if (!ad) throw new Error('Immeuble introuvable : ' + id);
  const im = ad.immeubles.find((i) => i.id === id);
  const fi = f.immeuble;
  const conso = sectionConsommation(im.points);
  const ouverts = f.alertes.filter((a) => a.statut === 'ouverte').length;
  const completer = () => formFiche(f, ctx);
  const suivi = h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('bon', 'h2', {}, 'Suivi des alertes et des bons'),
      h('span', { class: 'doux petit' }, 'En attente → Bon envoyé (concierge ou partenaire technique) → Retour d\'incident → Clôturée. '
        + 'Cliquez sur une ligne pour ouvrir son bon de travaux.'))),
    tableSuivi(f, ctx));
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' },
        h('a', { href: '#/parc', class: 'petit retour-lien' }, icone('retour'), 'Parc'),
        h('h1', {}, im.nom),
        h('div', { class: 'fluides' }, [...new Map(im.points.filter((p) => p.etat !== 'inactif')
          .map((p) => [cleFluide(p.fluide), p])).values()].map((p) => h('button', { type: 'button', class: 'nu',
          title: `Consommation : ${p.libelle}`, onclick: () => conso.choisir(p.id) }, pastilleFluide(p.fluide, { taille: 'sm', libelle: p.libelle })))),
        h('p', { class: 'doux' }, `${ad.rue}, ${ad.npa_localite} · code ${im.id}${im.typologie ? ' · ' + im.typologie : ''} · ${profilTexte(im)}`
          + (im.proprietaire ? ` · propriétaire : ${im.proprietaire}` : '') + ' · ',
        h('a', { href: '#suivi', onclick: (ev) => { ev.preventDefault(); suivi.scrollIntoView({ behavior: 'smooth', block: 'start' }); } },
          `${ouverts} alerte(s) ouverte(s)`))),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'danger', onclick: () => supprimerImmeuble(im, ctx) }, icone('supprimer'), 'Supprimer'),
        h('button', { type: 'button', onclick: () => formImmeuble(im, parc, ctx) }, icone('immeuble'), 'Modifier l\'immeuble'),
        h('button', { type: 'button', class: 'primaire', onclick: () => formFiche(f, ctx) }, icone('modifier'), 'Modifier la fiche'))),
    im.remarque ? h('div', { class: 'banniere info' }, h('span', {}, im.remarque)) : null,
    h('section', { class: 'grille-fiche', 'aria-label': 'Contacts et données techniques' },
      contact('Gestionnaire', fi.gestionnaire, fi.gestionnaire_email, fi.gestionnaire_tel, 'Non renseigné', completer),
      contact('Concierge', fi.concierge, fi.concierge_email, fi.concierge_tel, 'Non renseigné', completer),
      blocTechnique(f, completer)),
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('prestataire', 'h2', {}, 'Partenaires techniques par fluide'),
        h('span', { class: 'doux petit' }, 'Qui intervient sur chaque installation de l\'immeuble (gérés dans Prestataires).')),
      h('a', { href: '#/prestataires', class: 'petit' }, 'Prestataires')),
      tablePartenaires(f.partenaires, ctx)),
    sectionSite(f),
    conso,
    suivi,
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('regles', 'h2', {}, 'Périodes déclarées et sourdines'),
        h('span', { class: 'doux petit' }, 'Sourdine justifiée d\'une règle, travaux ou vacance datés (règles d\'énergie suspendues, '
          + 'fuites et défauts de données maintenus), changement de compteur, de consigne ou de courbe de chauffe '
          + '(la référence repart de cette date).')),
      h('button', { type: 'button', onclick: () => formDeclaration(im, regles, f.declarations.types, ctx) }, icone('ajouter'), 'Déclarer')),
      tableDeclarations(f.declarations, ctx)),
    h('div', { class: 'colonnes' },
      h('section', { class: 'carte principale' },
        h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('info', 'h2', {}, 'Historique horodaté'),
          h('span', { class: 'doux petit' }, 'Toutes les étapes, de la plus récente à la plus ancienne (heure de Genève).'))),
        h('div', { class: 'carte-corps' }, historique(f.historique, ctx))),
      h('section', { class: 'carte laterale' },
        h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('regles', 'h2', {}, 'Surveillance appliquée'),
          h('span', { class: 'doux petit' }, `Occupation « ${PROFILS[im.profil]} »`)), h('a', { href: '#/regles', class: 'petit' }, 'Régler')),
        surveillance(im, regles, bons.filter((b) => b.immeuble_id === id), ctx))),
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('compteur', 'h2', {}, 'Compteurs, capteurs et connexions'),
        h('span', { class: 'doux petit' }, 'D\'où viennent les données de chaque fluide et si elles arrivent.')),
      h('button', { type: 'button', onclick: () => formCompteur(null, im.id, parc.listes, ctx) }, icone('ajouter'), 'Ajouter un compteur')),
      tableCompteurs(im, parc, ctx, conso)));
}
