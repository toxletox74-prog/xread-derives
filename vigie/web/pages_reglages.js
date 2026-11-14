// Écrans de réglage : prestataires, règles et coûts de la dérive, automatisation et messagerie.
import {
  api, h, vider, fmt, chip, tenter, dialogue, confirmer, champ, liste, saisie, lireFormulaire, PROFILS,
} from './outils.js';
import { icone, pastilleFluide, tagFluide, titreIcone, etatVide } from './icones.js';
import { carteConnecteur } from './connecteur.js';

// ---------------------------------------------------------------- prestataires

export async function pagePrestataires(main, ctx) {
  const [{ prestataires, metiers, besoins }, parc] = await Promise.all([api('GET', '/api/prestataires'), api('GET', '/api/parc')]);
  const immeubles = parc.adresses.flatMap((a) => a.immeubles);
  const nomImm = Object.fromEntries(immeubles.map((i) => [i.id, i.nom]));
  const couverts = new Set(prestataires.filter((p) => p.actif).map((p) => p.metier));
  const manquants = besoins.filter((m) => !couverts.has(m));
  const ouvrir = (p) => formPrestataire(p, metiers, immeubles, ctx);
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Prestataires'),
        h('p', { class: 'doux' }, 'Quand une dérive est détectée, le bon de travaux est adressé au prestataire du métier prévu par la règle. '
          + 'Un prestataire dédié à l\'immeuble passe avant celui de tout le parc.')),
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primaire', onclick: () => ouvrir(null) },
        icone('ajouter'), 'Ajouter un prestataire'))),
    manquants.length ? h('div', { class: 'banniere attention' },
      h('span', {}, 'Aucun prestataire pour : ' + manquants.join(', ') + '. Les bons de ces dérives devront être attribués à la main.'))
      : h('div', { class: 'banniere ok' }, h('span', {}, 'Chaque métier demandé par les règles actives a au moins un prestataire.')),
    h('section', { class: 'carte' }, h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Entreprise', 'Métier', 'Contact', 'E-mail', 'Téléphone', 'Immeubles couverts', 'État']
        .map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, prestataires.length ? prestataires.map((p) => h('tr', { class: 'cliquable', tabindex: '0',
        onclick: () => ouvrir(p), onkeydown: (ev) => { if (ev.key === 'Enter') ouvrir(p); } },
      h('td', {}, h('span', { class: 'cellule-fluide' }, h('span', { class: 'kpi-ico' }, icone('prestataire')), p.nom)),
      h('td', {}, h('span', { class: 'tag' }, p.metier)), h('td', {}, p.contact || '—'),
      h('td', {}, p.email), h('td', {}, p.telephone || '—'),
      h('td', {}, p.perimetre === '*' ? 'Tout le parc' : !p.perimetre ? 'Aucun immeuble (à rattacher)'
        : p.perimetre.split(',').length > 6 ? `${p.perimetre.split(',').length} immeubles : ${p.perimetre.split(',').join(', ')}`
          : p.perimetre.split(',').map((i) => nomImm[i] || i).join(', ')),
      h('td', {}, p.actif ? h('span', { class: 'chip g-OK' }, 'Actif') : h('span', { class: 'chip g-Données' }, 'Inactif'))))
        : h('tr', {}, h('td', { colspan: '7' }, etatVide('prestataire',
          'Aucun prestataire. Ajoutez-les ici ou dans la feuille « Prestataires » de l\'import Excel.'))))))));
}

function formPrestataire(p, metiers, immeubles, ctx) {
  const nouveau = !p;
  const val = p || { metier: metiers[0], perimetre: '*', actif: 1 };
  const tout = val.perimetre === '*';
  const choisis = new Set(tout ? [] : val.perimetre.split(','));
  const listeImm = h('div', { class: 'profils' + (tout ? ' cache' : '') }, immeubles.map((i) => h('label', { class: 'coche' },
    h('input', { type: 'checkbox', value: i.id, 'data-groupe': 'immeubles', checked: choisis.has(i.id) }), i.nom)));
  const radioTout = h('input', { type: 'radio', name: 'portee', value: 'tout', checked: tout });
  const radioCertains = h('input', { type: 'radio', name: 'portee', value: 'certains', checked: !tout });
  [radioTout, radioCertains].forEach((r) => r.addEventListener('change', () => listeImm.classList.toggle('cache', radioTout.checked)));
  const metierListe = metiers.includes(val.metier) ? metiers : [...metiers, val.metier];
  const form = h('div', { class: 'formulaire' },
    champ('Entreprise', saisie('nom', val.nom, { required: true })),
    champ('Métier', liste('metier', metierListe, val.metier), 'Doit correspondre au métier indiqué dans les règles.'),
    champ('Personne de contact', saisie('contact', val.contact)),
    champ('E-mail (réception des bons)', h('input', { type: 'email', name: 'email', value: val.email || '', required: true })),
    champ('Téléphone', saisie('telephone', val.telephone)),
    h('div', { class: 'champ' }, h('span', { class: 'lib' }, 'État'),
      h('label', { class: 'coche' }, h('input', { type: 'checkbox', name: 'actif', checked: !!val.actif }), 'Prestataire actif')),
    h('fieldset', { class: 'large cadre' },
      h('legend', { class: 'petit gras' }, 'Immeubles couverts'),
      h('label', { class: 'coche' }, radioTout, 'Tout le parc'),
      h('label', { class: 'coche' }, radioCertains, 'Certains immeubles seulement'), listeImm));
  const lire = () => {
    const d = lireFormulaire(form);
    d.perimetre = radioTout.checked ? '*' : (d.immeubles || []).join(',');
    d.actif = d.actif ? 1 : 0;
    delete d.immeubles;
    delete d.portee;
    return d;
  };
  const boutons = [{ texte: 'Enregistrer', classe: 'primaire', action: async () => {
    const ok = await tenter(() => api(nouveau ? 'POST' : 'PUT', '/api/prestataires' + (nouveau ? '' : '/' + p.id), lire()),
      'Prestataire enregistré.');
    if (ok) await ctx.recharger();
    return !!ok;
  } }];
  if (!nouveau) {
    boutons.unshift({ texte: 'Supprimer', classe: 'danger', action: async () => {
      if (!await confirmer('Supprimer ce prestataire ?', `${p.nom} sera supprimé. S'il a déjà reçu des bons, `
        + 'il est seulement désactivé pour garder l\'historique.', 'Supprimer', true)) return false;
      const r = await tenter(() => api('DELETE', '/api/prestataires/' + p.id),
        (x) => (x.resultat === 'desactive' ? 'Prestataire désactivé (historique conservé).' : 'Prestataire supprimé.'));
      if (r) await ctx.recharger();
      return !!r;
    } });
  }
  dialogue(nouveau ? 'Ajouter un prestataire' : p.nom, form, boutons);
}

// ---------------------------------------------------------------- règles et coûts

export async function pageRegles(main, ctx) {
  const [r, couts] = await Promise.all([api('GET', '/api/regles'), api('GET', '/api/couts')]);
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Règles & coûts'),
        h('p', { class: 'doux' }, 'Ce que Vigie surveille selon l\'occupation de chaque immeuble, à partir de quand il alerte, '
          + 'qui intervient, et combien coûte une dérive.')),
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primaire',
        onclick: () => tenter(() => ctx.analyser()) }, icone('analyser'), 'Relancer l\'analyse avec ces réglages'))),
    methodes(r.matrice),
    couverture(r.couverture),
    matrice(r),
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('regles', 'h2', {}, 'Règles de détection'),
        h('span', { class: 'doux petit' }, 'Une alerte n\'est levée que si le dépassement dure au moins la persistance indiquée : '
          + 'un pic isolé n\'est pas une alerte.'))),
      r.regles.map((x) => blocRegle(x, r, ctx))),
    blocCouts(couts, ctx));
}

// Une méthode par fluide ET par pas de relevé : ce que le moteur applique selon la finesse des données
function methodes(m) {
  if (!m || !m.length) return null;
  const pas = m[0].cases.map((c) => c.libelle);
  const cellule = (c) => h('td', { class: c.compteurs ? '' : 'doux' },
    c.regles.length ? h('ul', { class: 'liste-methodes' }, c.regles.map((x) => h('li', {}, x.methode))) : 'aucune règle',
    h('div', { class: 'petit ' + (c.compteurs ? 'gras' : 'doux') }, c.compteurs ? `${c.compteurs} compteur(s) dans votre parc` : 'aucun compteur à ce pas'));
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('regles', 'h2', {}, 'Une méthode par fluide et par pas de relevé'),
      h('span', { class: 'doux petit' }, 'La méthode de détection dépend de la finesse du relevé : la nuit ne se voit que sur un relevé horaire, '
        + 'le niveau de base au jour ; au mois, il reste la comparaison au même mois des années précédentes. '
        + 'Détail et justification : docs/Xread_Derives_methodes_par_pas_de_releve.pdf.'))),
    h('div', { class: 'defile' }, h('table', { class: 'matrice-methodes' },
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Fluide'), pas.map((p) => h('th', { scope: 'col' }, p)))),
      h('tbody', {}, m.map((l) => h('tr', {}, h('th', { scope: 'row' }, l.fluide), l.cases.map(cellule)))))));
}

// Alerte de couverture : une règle qui ne correspond pas à la granularité de tous les compteurs de son fluide
function couverture(c) {
  if (!c || !(c.alertes.length || c.sans_regle.length)) return null;
  const ligne = (a) => h('li', {}, h('span', { class: 'chip ' + (a.niveau === 'sans_effet' ? 'g-Critique' : 'g-Attente') },
    a.niveau === 'sans_effet' ? 'sans effet' : 'partielle'), ' ', a.texte);
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('alerte', 'h2', {}, 'Couverture des règles'),
      h('span', { class: 'doux petit' }, 'Une règle ne juge un compteur que s\'il est relevé assez finement pour elle. '
        + `${c.sans_effet} règle(s) sans effet, ${c.partielles} partielle(s), ${c.compteurs_sans_regle} compteur(s) sans règle.`))),
    h('div', { class: 'carte-corps' },
      c.alertes.length ? h('ul', { class: 'liste-regles' }, c.alertes.map(ligne)) : null,
      c.sans_regle.length ? h('p', {}, h('span', { class: 'gras' }, 'Compteurs sans aucune règle de dérive : '),
        c.sans_regle.map((s) => `${s.fluide} (${s.compteurs} ${s.pas})`).join(' · '),
        '. Seule la qualité de leurs données est contrôlée.') : null));
}

function matrice(r) {
  const coche = (oui) => (oui ? h('span', { class: 'coche-oui', 'aria-label': 'oui' }, '✓') : h('span', { class: 'doux', 'aria-label': 'non' }, '—'));
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('immeuble', 'h2', {}, 'Surveillance selon l\'occupation'),
      h('span', { class: 'doux petit' }, 'Coché = la règle s\'applique aux immeubles de cette occupation. Modifiable dans chaque règle '
        + 'ci-dessous. « Compteurs concernés » = compteurs de votre parc relevés assez finement pour que la règle tourne.'))),
    h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Règle'),
        r.profils.map((p) => h('th', { scope: 'col', class: 'centre' }, PROFILS[p])),
        h('th', { scope: 'col' }, 'Relevé nécessaire'), h('th', { scope: 'col', class: 'centre' }, 'Compteurs concernés'),
        h('th', { scope: 'col' }, 'Prestataire'))),
      h('tbody', {},
        r.regles.map((x) => h('tr', {},
          h('td', {}, h('span', { class: 'cellule-fluide' }, pastilleFluide(x.fluide, { taille: 'xs', libelle: x.fluide }),
            h('span', { class: x.active ? 'gras' : 'doux' }, x.libelle, x.active ? null : ' (désactivée)'))),
          r.profils.map((p) => h('td', { class: 'centre' }, coche(x.active && x.profils.includes(p)))),
          h('td', { class: 'petit' }, x.releve),
          h('td', { class: 'centre' }, x.compteurs ? h('span', { class: 'gras' }, x.compteurs) : h('span', { class: 'doux' }, 'aucun')),
          h('td', {}, x.metier))),
        h('tr', {}, h('td', {}, h('span', { class: 'cellule-fluide' }, pastilleFluide('donnees', { taille: 'xs' }),
          h('span', { class: 'gras' }, 'Qualité des données (compteur muet, lacunes, index qui recule)'))),
          r.profils.map(() => h('td', { class: 'centre' }, coche(true))), h('td', { class: 'petit' }, 'tout relevé'),
          h('td', { class: 'centre doux' }, 'tous'), h('td', {}, r.qualite.metier))))));
}

// Sur combien de compteurs du parc la règle tourne réellement (une règle horaire ne juge pas un relevé journalier)
function portee(x) {
  if (x.compteurs) return h('span', { class: 'gras' }, `Tourne sur ${x.compteurs} compteur(s) de votre parc.`);
  if (x.compteurs_fluide && !x.trop_grossiers) return h('span', { class: 'doux' }, 'Non concernée : vos compteurs de ce fluide sont relevés plus finement, une autre règle les surveille.');
  return h('span', { class: 'chip g-Attente' }, x.compteurs_fluide
    ? `sans effet : aucun de vos ${x.compteurs_fluide} compteur(s) de ce fluide n'est relevé ${x.releve}`
    : 'sans effet : aucun compteur de ce fluide dans votre parc');
}

function blocRegle(x, r, ctx) {
  const actif = h('input', { type: 'checkbox', checked: x.active });
  const profils = h('div', { class: 'profils' }, r.profils.map((p) => h('label', { class: 'coche' },
    h('input', { type: 'checkbox', value: p, 'data-groupe': 'profils', checked: x.profils.includes(p) }), PROFILS[p])));
  const metiers = r.metiers.includes(x.metier) ? r.metiers : [...r.metiers, x.metier];
  const champs = h('div', { class: 'regle-champs' },
    h('div', { class: 'champ large' }, h('span', { class: 'lib' }, 'S\'applique aux immeubles'), profils),
    champ(`Seuil (${x.unite_seuil})`, h('input', { type: 'number', name: 'seuil', step: 'any', min: x.seuil_min, max: x.seuil_max,
      value: x.seuil }), `${x.aide_seuil} Par défaut : ${fmt.n1(x.defaut.seuil)}.`),
    champ(`Persistance (${x.unite_persistance})`, h('input', { type: 'number', name: 'persistance', min: 1, max: 60,
      value: x.persistance }), `Par défaut : ${x.defaut.persistance}.`),
    champ('Gravité', liste('gravite', r.gravites, x.gravite)),
    champ('Prestataire (métier)', liste('metier', metiers, x.metier)),
    champ('Délai d\'intervention', saisie('delai', x.delai)),
    champ('Consigne transmise au prestataire', h('textarea', { name: 'consigne', rows: 3 }, x.consigne), null, 'large'));
  const enregistrer = () => tenter(async () => {
    const d = lireFormulaire(champs);
    d.active = actif.checked;
    d.profils = d.profils || [];
    await api('PUT', '/api/regles/' + x.id, d);
    await ctx.recharger();
  }, 'Règle enregistrée. Elle s\'appliquera à la prochaine analyse.');
  const retablir = () => tenter(async () => {
    await api('DELETE', '/api/regles/' + x.id);
    await ctx.recharger();
  }, 'Valeurs par défaut rétablies.');
  champs.appendChild(h('div', { class: 'actions large' },
    h('button', { type: 'button', class: 'primaire', onclick: enregistrer }, 'Enregistrer la règle'),
    x.modifiee ? h('button', { type: 'button', onclick: retablir }, 'Rétablir les valeurs par défaut') : null));
  return h('div', { class: 'regle' + (x.active ? '' : ' inactive') },
    h('div', { class: 'regle-tete' },
      h('div', { class: 'regle-titre' }, pastilleFluide(x.fluide, { taille: 'md' }), h('h3', {}, x.libelle),
        x.modifiee ? h('span', { class: 'modifie' }, 'modifiée') : null),
      h('div', { class: 'ligne-tags' }, chip(x.gravite), tagFluide(x.fluide),
        x.sinistre ? h('span', { class: 'chip g-Critique' }, 'risque de sinistre') : null),
      h('p', { class: 'doux' }, 'Alerte affichée : « ' + x.titre + ' »'),
      h('p', { class: 'doux petit' }, 'Imputation : ' + x.payeur),
      h('p', { class: 'petit' }, `Relevé nécessaire : ${x.releve}. `, portee(x)),
      h('label', { class: 'coche' }, actif, 'Règle active')),
    champs);
}

function blocCouts(c, ctx) {
  const lignes = c.tarifs.map((t) => h('tr', {},
    h('td', {}, h('span', { class: 'cellule-fluide' }, pastilleFluide(t.vecteur), t.libelle)),
    h('td', {}, h('span', { class: 'saisie-unite' }, h('input', { type: 'number', step: 'any', min: 0, name: 'chf_' + t.vecteur,
      value: t.chf_par_unite, 'aria-label': `Tarif ${t.libelle} en CHF par ${t.unite}`, class: 'etroit' }),
    ` CHF/${t.unite === 'm3' ? 'm³' : t.unite}`)),
    h('td', {}, liste('statut_' + t.vecteur, [['EXEMPLE', 'Valeur d\'exemple'], ['CONTRAT', 'Tarif de mon contrat']], t.statut)),
    h('td', {}, t.vecteur === 'eau' ? '—' : h('span', { class: 'saisie-unite' }, h('input', { type: 'number', step: 'any', min: 0,
      name: 'co2_' + t.vecteur, value: t.co2_kg_par_kwh ?? '', 'aria-label': `Facteur CO₂ ${t.libelle}`, class: 'etroit' }), ' kg/kWh'))));
  const form = h('div', { class: 'pile' },
    h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Vecteur', 'Tarif', 'Source du tarif', 'Facteur CO₂'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, lignes))),
    h('div', { class: 'formulaire' },
      champ('Enjeu minimal affiché (CHF par mois)', h('input', { type: 'number', step: 'any', name: 'enjeu_min_chf_mois', min: 0,
        value: c.enjeu_min_chf_mois }), 'Une dérive dont le rythme (CHF par 30 jours, aux conditions actuelles) est plus faible '
        + 'est masquée, sauf risque de sinistre ou problème de données.'),
      champ('Compteur muet après (heures)', h('input', { type: 'number', name: 'silence_max_heures', min: 1, max: 720,
        value: c.silence_max_heures }), 'Au-delà : alerte « Données » au prestataire de télérelève, aucune alerte énergie sur ce compteur.'),
      champ('Complétude minimale sur 30 jours (%)', h('input', { type: 'number', name: 'completude_min', min: 10, max: 100,
        value: Math.round(c.completude_min * 100) }), 'En dessous, les données sont jugées insuffisantes pour décider.')));
  const enregistrer = () => tenter(async () => {
    const d = lireFormulaire(form);
    await api('PUT', '/api/couts', {
      tarifs: c.tarifs.map((t) => ({ vecteur: t.vecteur, chf_par_unite: d['chf_' + t.vecteur], statut: d['statut_' + t.vecteur],
        co2_kg_par_kwh: t.vecteur === 'eau' ? null : d['co2_' + t.vecteur] })),
      enjeu_min_chf_mois: d.enjeu_min_chf_mois,
      silence_max_heures: d.silence_max_heures, completude_min: d.completude_min === '' ? null : Number(d.completude_min) / 100,
    });
    await ctx.recharger();
  }, 'Coûts enregistrés. Les montants seront recalculés à la prochaine analyse.');
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('argent', 'h2', {}, 'Coûts de la dérive'),
      h('span', { class: 'doux petit' }, 'Eau et électricité : excès par jour × 365 (CHF/an). Chauffage et PAC : excès mesuré depuis le début '
        + 'de la dérive, sans année extrapolée. Tous : rythme par 30 jours (CHF/mois), base de la priorité. '
        + 'CO₂ = kWh × facteur du vecteur.'))),
    h('div', { class: 'carte-corps' },
      c.tarifs.some((t) => t.statut !== 'CONTRAT') ? h('div', { class: 'banniere attention' },
        h('span', {}, 'Certains tarifs sont des valeurs d\'exemple : les montants affichés ne sont pas ceux de vos contrats.')) : null,
      form,
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primaire', onclick: enregistrer }, 'Enregistrer les coûts'))));
}

// ---------------------------------------------------------------- automatisation et messagerie

const MODES = [
  ['manuel', 'Manuel', 'Je crée moi-même les bons depuis les alertes.'],
  ['brouillon', 'Préparation automatique (recommandé)', 'Après chaque analyse, Vigie prépare le bon de chaque nouvelle alerte '
    + 'et l\'adresse au bon prestataire. Je relis et j\'envoie.'],
  ['envoi', 'Envoi automatique', 'Vigie envoie directement le bon au prestataire par e-mail (messagerie configurée requise). '
    + 'Je suis en copie si je l\'indique.'],
];

// Le mot de passe SMTP n'est gardé qu'en mémoire : après un redémarrage, l'envoi automatique échoue tant qu'il manque
export const MOT_DE_PASSE_MANQUANT = 'Envoi automatique des bons impossible : le mot de passe de la messagerie n\'est pas '
  + 'en mémoire (il est perdu à chaque redémarrage de Vigie). Saisissez-le dans Réglages › Messagerie, ou définissez la variable d\'environnement '
  + 'VIGIE_SMTP_MOT_DE_PASSE. En attendant, les bons restent en brouillon.';

// Dernière analyse automatique : date, déclencheur, résultat ou erreur
function etatAnalyseAuto(a, e) {
  const [classe, lib] = !e ? ['g-Données', 'Jamais lancée']
    : { ok: ['g-OK', 'Réussie'], attention: ['g-Attente', 'À vérifier'], erreur: ['g-Critique', 'Échec'] }[e.statut] || ['g-Données', e.statut];
  const tuile = (titre, valeur) => h('div', {}, h('div', { class: 'doux petit' }, titre), h('b', {}, valeur));
  return h('div', { class: 'pile' },
    h('div', { class: 'resume-import' },
      tuile('Dernière analyse automatique', e ? `${fmt.dateHeure(e.le)} (${e.declencheur})` : '—'),
      tuile('Résultat', h('span', { class: 'chip ' + classe }, lib)),
      tuile('Fréquence', a.analyse_auto ? `Toutes les ${a.analyse_intervalle_h} h et après un relevé API` : 'Manuelle')),
    e && e.message ? h('p', { class: e.statut === 'ok' ? 'doux petit' : 'gras' }, e.message) : null);
}

function carteMeteo(m, ctx) {
  const exemple = m.source === 'exemple';
  const fictif = !!m.exemple_fictif; // exemple sur températures fictives : aucune mise à jour possible
  const lien = (texte, href) => h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, texte);
  const station = saisie('station', m.station, { maxlength: 3, class: 'etroit majuscules', disabled: exemple });
  const auto = h('input', { type: 'checkbox', name: 'auto', checked: m.auto, disabled: fictif });
  const classeStatut = { ok: 'g-OK', erreur: 'g-Critique', jamais: 'g-Attente', exemple: 'g-Données',
    exemple_reel: 'g-Modérée' }[m.statut] || 'g-Données';
  const libStatut = { ok: 'À jour', erreur: 'Échec', jamais: 'Jamais mise à jour', exemple: 'Données fictives',
    exemple_reel: 'Réelle (exemple)' }[m.statut] || m.statut;
  const enregistrer = () => tenter(async () => {
    await api('PUT', '/api/meteo', { station: station.value, auto: auto.checked });
    await ctx.recharger();
  }, 'Réglage météo enregistré.');
  const maj = (ev) => tenter(async () => {
    ev.currentTarget.disabled = true;
    const r = await api('POST', '/api/meteo/maj');
    await ctx.recharger();
    return r;
  }, (r) => `Météo à jour : ${fmt.n0(r.heures)} heures`
    + (r.heures_rayonnement ? ` (dont ${fmt.n0(r.heures_rayonnement)} de rayonnement solaire)` : '')
    + `, dernière mesure ${fmt.dateHeure(r.derniere_mesure)}.`);
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' },
      h('h2', { class: 'titre-ico' }, pastilleFluide('meteo'), 'Température extérieure et ensoleillement (météo)'),
      h('span', { class: 'doux petit' }, 'Indispensables aux règles « chauffage trop fort pour la météo », « rendement PAC » '
        + 'et « production solaire à ensoleillement égal ».')),
    h('span', { class: 'chip ' + classeStatut }, libStatut)),
    h('div', { class: 'carte-corps' },
      h('p', {}, h('strong', {}, 'Source : '), 'MétéoSuisse, données ouvertes du réseau SwissMetNet — station ',
        h('strong', {}, `${m.nom_station} (${m.station})`), `, température de l'air à 2 m (${m.colonne}) et rayonnement `
        + `solaire global (${m.colonne_rayonnement}), moyennes horaires. `
        + 'Mesures officielles de la Confédération, horodatées en UTC, téléchargées gratuitement ; aucune donnée '
        + 'de consommation ne quitte ce poste.'),
      h('ul', { class: 'liste-puces' },
        Object.entries(m.liens).map(([t, href]) => h('li', {}, lien(t, href))),
        h('li', {}, lien('Fichier horaire de la station (année en cours)', m.fichiers.recent))),
      exemple ? h('div', { class: 'banniere info' }, h('span', {}, !fictif
        ? 'Base d\'exemple : températures RÉELLES de Genève-Cointrin ; les consommations de chauffage et de PAC ont été '
          + 'simulées à partir d\'elles jusqu\'à la création de l\'exemple. La mise à jour AJOUTE les heures nouvelles sans '
          + 'jamais réécrire celles qui ont servi à la simulation ; les compteurs simulés, eux, s\'arrêtent à cette date.'
        : 'Base d\'exemple : les températures fictives vont avec les consommations simulées et ne sont pas remplacées. '
          + 'La mise à jour MétéoSuisse s\'active sur votre parc réel.')) : null,
      h('div', { class: 'resume-import' },
        h('div', {}, h('div', { class: 'doux petit' }, 'Dernière mise à jour'), h('b', {}, fmt.dateHeure(m.derniere_maj))),
        h('div', {}, h('div', { class: 'doux petit' }, 'Dernière mesure reçue'), h('b', {}, fmt.dateHeure(m.derniere_mesure))),
        h('div', {}, h('div', { class: 'doux petit' }, 'Fréquence'),
          h('b', {}, m.auto && !exemple ? `Au démarrage puis toutes les ${m.intervalle_auto_h} h` : 'Manuelle'))),
      m.message ? h('p', { class: m.statut === 'erreur' ? 'gras' : 'doux petit' }, m.message) : null,
      h('div', { class: 'formulaire' },
        champ('Station MétéoSuisse (code)', station, 'GVE = Genève-Cointrin. Changer de station démarre une nouvelle série.'),
        h('div', { class: 'champ' }, h('span', { class: 'lib' }, 'Mise à jour automatique'),
          h('label', { class: 'coche' }, auto, `Au démarrage de Vigie puis toutes les ${m.intervalle_auto_h} heures`))),
      h('div', { class: 'actions' },
        h('button', { type: 'button', onclick: enregistrer, disabled: fictif }, 'Enregistrer'),
        h('button', { type: 'button', class: 'primaire', onclick: maj, disabled: fictif }, icone('analyser'), 'Mettre à jour maintenant'))));
}

export async function pageReglages(main, ctx) {
  const [r, etatMeteo, etatApi] = await Promise.all([api('GET', '/api/reglages'), api('GET', '/api/meteo'),
    api('GET', '/api/connecteur')]);
  const a = r.automatisation;
  const m = r.messagerie;
  const auto = h('div', { class: 'pile' },
    h('fieldset', { class: 'groupe-choix' },
      h('legend', { class: 'petit gras' }, 'Création des bons de travaux'),
      MODES.map(([v, lib, aide]) => h('label', { class: 'coche haut choix' },
        h('input', { type: 'radio', name: 'mode', value: v, checked: a.mode === v }),
        h('span', {}, h('span', { class: 'gras' }, lib), h('br', {}), h('span', { class: 'doux petit' }, aide))))),
    h('div', { class: 'formulaire' },
      champ('À partir de la gravité', liste('gravite_min', r.gravites, a.gravite_min), 'Les alertes moins graves restent à traiter à la main.'),
      h('div', { class: 'champ' }, h('span', { class: 'lib' }, 'Problèmes de données'),
        h('label', { class: 'coche' }, h('input', { type: 'checkbox', name: 'inclure_donnees', checked: a.inclure_donnees }),
          'Préparer aussi un bon au prestataire de télérelève')),
      h('div', { class: 'champ' }, h('span', { class: 'lib' }, 'Analyse automatique'),
        h('label', { class: 'coche' }, h('input', { type: 'checkbox', name: 'analyse_auto', checked: a.analyse_auto }),
          'Lancer l\'analyse sans intervention (tant que Vigie tourne)')),
      champ('Fréquence de l\'analyse automatique (heures)', h('input', { type: 'number', name: 'analyse_intervalle_h',
        value: a.analyse_intervalle_h, min: 1, max: 168 }),
      'Aussi lancée après chaque relevé API automatique qui apporte de nouvelles mesures.')),
    etatAnalyseAuto(a, r.analyse_auto));
  const mess = h('div', { class: 'formulaire' },
    champ('Nom de l\'expéditeur', saisie('expediteur_nom', m.expediteur_nom, { placeholder: 'Régie — Gestion technique' })),
    champ('E-mail de l\'expéditeur', h('input', { type: 'email', name: 'expediteur_email', value: m.expediteur_email })),
    champ('Copie à (facultatif)', h('input', { type: 'email', name: 'copie_a', value: m.copie_a }),
      'Par exemple votre propre adresse, pour garder une trace.'),
    champ('Signature', h('textarea', { name: 'signature', rows: 4 }, m.signature), 'Ajoutée à la fin de chaque bon.', 'large'),
    champ('Serveur d\'envoi (SMTP)', saisie('smtp_hote', m.smtp_hote, { placeholder: 'smtp.office365.com' }),
      'Laissez vide pour télécharger les bons et les envoyer depuis Outlook.'),
    champ('Port', h('input', { type: 'number', name: 'smtp_port', value: m.smtp_port, min: 1, max: 65535 })),
    champ('Sécurité', liste('smtp_securite', [['starttls', 'STARTTLS (port 587)'], ['ssl', 'SSL (port 465)'], ['aucune', 'Aucune']],
      m.smtp_securite)),
    champ('Utilisateur', saisie('smtp_utilisateur', m.smtp_utilisateur)),
    champ('Mot de passe', h('input', { type: 'password', name: 'mot_de_passe', autocomplete: 'off',
      placeholder: r.mot_de_passe_present ? '•••••• (déjà saisi)' : '' }),
    'Gardé en mémoire jusqu\'à la fermeture de Vigie, jamais enregistré sur le disque. '
      + 'Pour le conserver : variable d\'environnement VIGIE_SMTP_MOT_DE_PASSE.'));
  const enregistrerAuto = () => tenter(async () => {
    const d = { mode: auto.querySelector('input[name=mode]:checked').value,
      gravite_min: auto.querySelector('select[name=gravite_min]').value,
      inclure_donnees: auto.querySelector('input[name=inclure_donnees]').checked,
      analyse_auto: auto.querySelector('input[name=analyse_auto]').checked,
      analyse_intervalle_h: auto.querySelector('input[name=analyse_intervalle_h]').value };
    if (d.mode === 'envoi' && !ctx.etat.smtp_configure) {
      throw new Error('L\'envoi automatique demande une messagerie configurée (serveur d\'envoi et e-mail de l\'expéditeur).');
    }
    await api('PUT', '/api/reglages', { automatisation: d });
    await ctx.recharger(); // réaffiche l'avertissement « mot de passe manquant » et la fréquence enregistrée
  }, 'Automatisation enregistrée.');
  const enregistrerMessagerie = () => tenter(async () => {
    const d = lireFormulaire(mess);
    const corps = { messagerie: d };
    if (d.mot_de_passe) corps.mot_de_passe = d.mot_de_passe;
    delete d.mot_de_passe;
    await api('PUT', '/api/reglages', corps);
    await ctx.recharger();
  }, 'Messagerie enregistrée.');
  vider(main,
    h('div', { class: 'entete-page' }, h('div', { class: 'titres' }, h('h1', {}, 'Réglages'),
      h('p', { class: 'doux' }, 'Relevés des compteurs par API, température extérieure, automatisation des bons de travaux '
        + 'et envoi par e-mail.'))),
    carteConnecteur(etatApi, ctx),
    carteMeteo(etatMeteo, ctx),
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('bon', 'h2', {}, 'Automatisation des bons de travaux'),
        h('span', { class: 'doux petit' }, 'Un seul bon ouvert par alerte : une dérive qui dure ne crée pas un nouveau bon à chaque analyse.'))),
      h('div', { class: 'carte-corps' },
        r.mot_de_passe_manquant ? h('div', { class: 'banniere attention' }, h('span', {}, MOT_DE_PASSE_MANQUANT)) : null,
        auto,
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primaire', onclick: enregistrerAuto }, 'Enregistrer')))),
    h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('courriel', 'h2', {}, 'Messagerie'),
        h('span', { class: 'doux petit' }, m.smtp_hote ? 'Envoi direct configuré.'
          : 'Sans serveur d\'envoi, chaque bon se télécharge en .eml et s\'ouvre dans Outlook, prêt à envoyer.'))),
      h('div', { class: 'carte-corps' }, mess,
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primaire', onclick: enregistrerMessagerie }, 'Enregistrer')))));
}
