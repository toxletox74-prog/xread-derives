// Réglages > Relevés des compteurs par API : clé API, adresse et format du fournisseur, test, relevé.
// La clé ne revient jamais du serveur : seuls ses 4 derniers caractères sont affichés.
import { api, h, fmt, tenter, champ, liste, saisie, lireFormulaire, confirmer } from './outils.js';
import { icone, pastilleFluide } from './icones.js';

const STATUTS = {
  jamais: ['g-Données', 'Jamais relevé'], ok: ['g-OK', 'Relevés à jour'], partiel: ['g-Attente', 'Relevé partiel'],
  erreur: ['g-Critique', 'Échec du relevé'],
};

function statut(c) {
  if (!c.actif) return h('span', { class: 'chip g-Données' }, 'Désactivée');
  const [classe, lib] = STATUTS[c.statut] || STATUTS.jamais;
  return h('span', { class: 'chip ' + classe }, lib);
}

function texteCle(c) {
  if (!c.cle.presente) return c.cle.origine === 'illisible' ? 'Illisible : à saisir à nouveau' : 'Aucune';
  return `${c.cle.masque} (${c.cle.origine === 'env' ? `variable ${c.env_cle}` : 'protégée par Windows'})`;
}

function resume(c) {
  const tuile = (lib, valeur) => h('div', {}, h('div', { class: 'doux petit' }, lib), h('b', {}, valeur));
  return h('div', { class: 'resume-import' },
    tuile('Clé API', texteCle(c)),
    tuile('Compteurs reliés', String(c.points.length)),
    tuile('Dernier relevé', fmt.dateHeure(c.derniere_synchro)),
    tuile('Fréquence', c.actif && c.auto ? `Toutes les ${c.intervalle_h} h` : 'Manuelle'));
}

function compteursRelies(c) {
  if (!c.points.length) {
    return h('p', { class: 'doux petit' }, `Aucun compteur relié : dans Parc, choisissez pour chaque compteur la connexion « ${c.source_api} » `
      + 'et indiquez son identifiant chez le fournisseur (colonnes « connexion » et « identifiant » du parc Excel).');
  }
  const premiers = c.points.slice(0, 8).map((p) => (p.identifiant === p.id ? p.id : `${p.id} → ${p.identifiant}`)).join(', ');
  return h('p', { class: 'doux petit' }, `Compteurs reliés : ${premiers}${c.points.length > 8 ? `, … (${c.points.length} au total)` : ''}.`);
}

function formulaire(c) {
  const coche = (nom, valeur, texte) => h('label', { class: 'coche' }, h('input', { type: 'checkbox', name: nom, checked: valeur }), texte);
  const nombre = (nom, valeur, min, max) => h('input', { type: 'number', name: nom, value: valeur, min, max });
  const base = h('div', { class: 'formulaire' },
    champ('Fournisseur', saisie('fournisseur', c.fournisseur, { placeholder: 'Nom du fournisseur de télérelève' })),
    champ('Adresse de l\'API', saisie('url_base', c.url_base, { placeholder: 'https://api.fournisseur.ch/v1', inputmode: 'url' }),
      'Donnée par le fournisseur. https:// obligatoire (la clé ne circule jamais en clair).'),
    champ('Clé API', h('input', { type: 'password', name: 'cle', autocomplete: 'off', spellcheck: false,
      placeholder: c.cle.presente ? `${c.cle.masque} — laisser vide pour la garder` : 'Collez ici la clé reçue' }),
    c.protection_disponible
      ? 'Chiffrée par votre compte Windows avant d\'être enregistrée ; jamais affichée, envoyée au seul fournisseur.'
      : `Sur ce système, donnez la clé par la variable d'environnement ${c.env_cle}.`),
    h('div', { class: 'champ' }, h('span', { class: 'lib' }, 'Connexion'),
      coche('actif', c.actif, 'Activer la connexion'),
      coche('auto', c.auto, 'Relever automatiquement (tant que Vigie est ouvert)')));
  const avance = h('details', { class: 'avance' }, h('summary', {}, 'Format du fournisseur (réglages avancés)'),
    h('p', { class: 'doux petit' }, 'À reprendre de la documentation du fournisseur. Par défaut : GET {adresse}'
      + '/points/{identifiant}/mesures?debut=…&fin=… avec l\'en-tête X-API-Key ; réponse JSON {"mesures": [{"ts": '
      + '"2026-11-12T07:00:00Z", "valeur": 4.385}]}, ts en UTC, fin d\'intervalle.'),
    h('div', { class: 'formulaire' },
      champ('Envoi de la clé', liste('auth', Object.entries(c.auths), c.auth)),
      champ('Nom de la clé', saisie('auth_nom', c.auth_nom), 'En-tête (ex. X-API-Key) ou paramètre (ex. api_key).'),
      champ('Chemin', saisie('chemin', c.chemin), 'Champs remplacés : {identifiant}, {debut}, {fin} (UTC).', 'large'),
      champ('Format de réponse', liste('format', Object.entries(c.formats), c.format)),
      champ('Liste des valeurs (JSON)', saisie('json_liste', c.json_liste), 'Ex. mesures ou data.values ; vide si la réponse est la liste.'),
      champ('Champ horodatage', saisie('json_ts', c.json_ts), 'Texte ISO ou secondes depuis 1970.'),
      champ('Champ valeur', saisie('json_valeur', c.json_valeur)),
      champ('Historique au premier relevé (jours)', nombre('historique_j', c.historique_j, 1, 400)),
      champ('Recouvrement (heures)', nombre('recul_h', c.recul_h, 0, 168), 'Heures redemandées à chaque relevé (valeurs corrigées).'),
      champ('Fréquence du relevé automatique (heures)', nombre('intervalle_h', c.intervalle_h, 1, 24))));
  return h('div', { class: 'pile' }, base, avance);
}

export function carteConnecteur(c, ctx) {
  const form = formulaire(c);
  const enregistrer = () => tenter(async () => {
    const d = lireFormulaire(form);
    if (!d.cle) delete d.cle;
    await api('PUT', '/api/connecteur', d);
    await ctx.recharger();
  }, 'Connexion API enregistrée.');
  const tester = () => tenter(() => api('POST', '/api/connecteur/tester'),
    (r) => `Connexion réussie : ${fmt.n0(r.valeurs)} valeur(s) reçue(s) sur 24 h pour ${r.compteur}`
      + (r.identifiant !== r.compteur ? ` (${r.identifiant})` : '') + '.');
  const relever = () => tenter(async () => {
    const r = await api('POST', '/api/connecteur/synchroniser');
    await ctx.recharger();
    return r;
  }, (r) => r.message + (r.importees ? ' Lancez l\'analyse pour mettre à jour les alertes.' : ''));
  const oublier = async () => {
    if (!await confirmer('Supprimer la clé API', 'La clé enregistrée sur ce poste sera effacée ; les relevés automatiques '
      + 's\'arrêteront jusqu\'à la saisie d\'une nouvelle clé.', 'Supprimer la clé', true)) return;
    await tenter(async () => { await api('DELETE', '/api/connecteur/cle'); await ctx.recharger(); }, 'Clé supprimée.');
  };
  const demo = async () => {
    if (!await confirmer('Fournisseur de démonstration', 'Vigie joue lui-même le rôle du fournisseur (clé de démonstration '
      + 'DEMO-VIGIE-2026) et tous les compteurs de l\'exemple passent en connexion « API du fournisseur ». Les relevés '
      + 'reçus prolongent l\'exemple jusqu\'à l\'heure actuelle. Réservé à la base d\'exemple.', 'Brancher la démonstration')) return;
    await tenter(async () => {
      const r = await api('POST', '/api/connecteur/demo');
      await ctx.recharger();
      return r;
    }, (r) => `Démonstration branchée : ${r.relies} compteur(s) reliés. Cliquez sur « Tester la connexion » puis « Relever maintenant ».`);
  };
  return h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' },
      h('h2', { class: 'titre-ico' }, pastilleFluide('donnees'), 'Relevés des compteurs par API'),
      h('span', { class: 'doux petit' }, 'Clé API remise par votre fournisseur de télérelève : Vigie va chercher lui-même les relevés.')),
    statut(c)),
    h('div', { class: 'carte-corps' },
      h('p', {}, 'Seuls la clé, l\'identifiant de chaque compteur et la période demandée partent vers le fournisseur. '
        + 'Aucune consommation ne quitte ce poste ; les valeurs reçues passent les mêmes contrôles que l\'import CSV.'),
      c.base_exemple ? h('div', { class: 'banniere info' },
        h('span', {}, 'Pas encore de clé ? Essayez le principe sur la base d\'exemple avec un fournisseur de démonstration.'),
        h('button', { type: 'button', onclick: demo }, 'Brancher la démonstration')) : null,
      resume(c),
      c.message ? h('p', { class: c.statut === 'erreur' ? 'gras' : 'doux petit' }, c.message) : null,
      compteursRelies(c),
      form,
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'primaire', onclick: enregistrer }, 'Enregistrer'),
        h('button', { type: 'button', onclick: tester, disabled: !c.cle.presente || !c.url_base }, icone('ok'), 'Tester la connexion'),
        h('button', { type: 'button', onclick: relever, disabled: !c.cle.presente || !c.url_base || !c.points.length },
          icone('importer'), 'Relever maintenant'),
        c.cle.presente && c.cle.origine === 'poste'
          ? h('button', { type: 'button', class: 'danger', onclick: oublier }, icone('supprimer'), 'Supprimer la clé') : null)));
}
