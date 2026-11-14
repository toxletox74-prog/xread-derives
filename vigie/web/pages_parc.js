// Écrans du parc : adresses et immeubles, fiche immeuble (compteurs et connexions), imports.
import {
  api, h, vider, fmt, chip, chipStatut, tenter, dialogue, confirmer, champ, liste, saisie, lireFormulaire,
  telecharger, graphe, toast, PROFILS, ETATS_POINT,
} from './outils.js';
import { pastillesFluides, profilTexte, listeAlertes, ouvrirBon } from './pages_suivi.js';
import { icone, pastilleFluide, titreIcone, etatVide } from './icones.js';

// Fluide du compteur surveillé par une règle : préfixe de la cause (eau_nuit, cad_signature, gaz_vide, pac_cop…)
const FLUIDE_PREFIXE = { eau: 'eau', chaleur: 'chaleur', cad: 'cad', gaz: 'gaz', elec: 'electricite', pac: 'pac_electricite',
  solaire: 'solaire' };
const METEO = ['meteo', 'rayonnement']; // grandeurs du parc, jamais rattachées à un immeuble
const PAS_MENSUEL = 43200;
const libPas = (m) => (m >= PAS_MENSUEL ? 'mensuel' : m === 1440 ? 'journalier' : m + ' min');
const fluideRegle = (id) => FLUIDE_PREFIXE[String(id).split('_')[0]];

// ---------------------------------------------------------------- parc

export async function pageParc(main, ctx) {
  const parc = await api('GET', '/api/parc');
  const filtres = { q: '', profil: '' };
  const zone = h('div', { class: 'pile' });
  const rendre = () => {
    const q = filtres.q.toLowerCase();
    const adresses = parc.adresses.map((ad) => ({ ...ad, immeubles: ad.immeubles.filter((im) =>
      (!filtres.profil || im.profil === filtres.profil)
      && (!q || `${ad.rue} ${ad.npa_localite} ${im.nom} ${im.id}`.toLowerCase().includes(q))) }))
      .filter((ad) => ad.immeubles.length);
    vider(zone, adresses.length ? adresses.map((ad) => h('section', { class: 'carte' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('adresse', 'h2', {}, ad.rue),
        h('span', { class: 'doux petit' }, `${ad.npa_localite} · ${ad.immeubles.length} immeuble(s)`))),
      h('div', { class: 'carte-corps' }, h('div', { class: 'grille-immeubles' }, ad.immeubles.map(carteImmeuble)))))
      : h('div', { class: 'carte' }, vide(parc)));
  };
  const nbImmeubles = parc.adresses.reduce((n, a) => n + a.immeubles.length, 0);
  const nbCompteurs = parc.adresses.reduce((n, ad) => n + ad.immeubles.reduce((m, im) => m + im.points.length, 0), 0);
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Parc immobilier'),
        h('p', { class: 'doux' }, `${parc.adresses.length} adresses · ${nbImmeubles} immeubles · ${nbCompteurs} compteurs et capteurs`)),
      h('div', { class: 'actions' },
        h('button', { type: 'button', onclick: () => exporterParc() }, icone('exporter'), 'Exporter vers Excel'),
        h('a', { class: 'bouton', href: '#/imports' }, icone('importer'), 'Importer depuis Excel'),
        h('button', { type: 'button', class: 'primaire', onclick: () => formImmeuble(null, parc, ctx) }, icone('ajouter'),
          'Ajouter un immeuble'))),
    h('div', { class: 'filtres' },
      champ('Rechercher', h('input', { type: 'search', name: 'q', placeholder: 'Adresse, immeuble, code…' })),
      champ('Occupation', liste('profil', [['', 'Toutes'], ...Object.entries(PROFILS)], ''))),
    zone,
    meteo(parc));
  main.querySelector('input[name=q]').addEventListener('input', (ev) => { filtres.q = ev.target.value; rendre(); });
  main.querySelector('select[name=profil]').addEventListener('change', (ev) => { filtres.profil = ev.target.value; rendre(); });
  rendre();
}

function vide(parc) {
  if (parc.adresses.length) return etatVide('immeuble', 'Aucun immeuble ne correspond.');
  return etatVide('immeuble', 'Aucun immeuble pour l\'instant. Importez votre parc depuis Excel ou ajoutez un immeuble.',
    h('a', { class: 'bouton', href: '#/imports' }, icone('importer'), 'Importer depuis Excel'));
}

function carteImmeuble(im) {
  const aConnecter = im.points.filter((p) => p.etat === 'a_connecter').length;
  return h('a', { class: 'immeuble-lien', href: '#/immeuble/' + encodeURIComponent(im.id) },
    h('span', { class: 'ligne' }, h('span', { class: 'nom-imm' }, icone('immeuble'), im.nom), h('span', { class: 'tag' }, im.id)),
    h('span', { class: 'doux petit' }, profilTexte(im)),
    pastillesFluides(im.points),
    h('span', { class: 'doux petit' }, `${im.points.length} compteur(s)` + (aConnecter ? ` · ${aConnecter} à connecter` : '')));
}

function meteo(parc) {
  const m = parc.meteo[0];
  return h('div', { class: 'banniere info' },
    h('span', { class: 'avec-ico' }, pastilleFluide('meteo'),
      h('span', {}, m ? `Température extérieure (référence météo du parc) : ${m.source} · dernière donnée ${fmt.dateHeure(m.derniere)}`
        : 'Aucune température extérieure : les règles « chauffage trop fort pour la météo » et « rendement PAC » ne peuvent pas tourner.')));
}

async function exporterParc() {
  await tenter(async () => {
    const rep = await api('GET', '/api/export/parc', undefined, { brut: true });
    telecharger(await rep.blob(), 'parc_vigie.xlsx');
  }, 'Fichier Excel téléchargé.');
}

// ---------------------------------------------------------------- formulaires immeuble et compteur

export function formImmeuble(im, parc, ctx) {
  const nouveau = !im;
  const val = im || { profil: 'Habite' };
  const ad = parc.adresses.find((a) => a.id === val.adresse_id) || {};
  const taux = val.taux_occupation !== null && val.taux_occupation !== undefined ? Math.round(val.taux_occupation * 100) : '';
  const form = h('div', { class: 'formulaire' },
    champ('Code immeuble', saisie('id', val.id, { required: true, readonly: !nouveau, placeholder: 'ex. T8' }),
      nouveau ? 'Court et unique : il sert dans les fichiers de mesures.' : 'Le code ne peut pas être modifié.'),
    champ('Nom', saisie('nom', val.nom, { required: true, placeholder: 'Résidence Les Tilleuls' })),
    champ('Rue et numéro', saisie('rue', ad.rue, { required: true })),
    champ('NPA et localité', saisie('npa_localite', ad.npa_localite, { required: true, placeholder: '1213 Onex' })),
    champ('Occupation', liste('profil', Object.entries(PROFILS), val.profil),
      'Détermine les règles appliquées : un immeuble vide ne doit consommer ni eau ni chauffage au-delà du hors-gel.'),
    champ('Taux d\'occupation (%)', h('input', { type: 'number', name: 'taux_occupation', min: 0, max: 100, value: taux }),
      'Pour un immeuble partiellement occupé.'),
    champ('Logements', h('input', { type: 'number', name: 'logements', min: 0, value: val.logements ?? '' })),
    champ('Surface de référence énergétique (m²)', h('input', { type: 'number', name: 'sre_m2', min: 0, value: val.sre_m2 ?? '' })),
    champ('Talon hors-gel (kWh/jour)', h('input', { type: 'number', name: 'talon_horsgel_kwh_j', min: 0, value: val.talon_horsgel_kwh_j ?? '' }),
      'Chaleur maximale attendue en hors-gel. Indispensable pour surveiller le chauffage d\'un immeuble vide.'),
    champ('Propriétaire', saisie('proprietaire', val.proprietaire)),
    champ('Remarque', h('textarea', { name: 'remarque', rows: 3 }, val.remarque || ''), null, 'large'));
  dialogue(nouveau ? 'Ajouter un immeuble' : 'Modifier ' + val.nom, form, [{
    texte: 'Enregistrer', classe: 'primaire', action: async () => {
      const r = await tenter(() => api('POST', '/api/immeubles', lireFormulaire(form)), 'Immeuble enregistré.');
      if (!r) return false;
      const cible = '#/immeuble/' + encodeURIComponent(r.immeuble.id);
      if (location.hash === cible) await ctx.recharger();
      else ctx.aller(cible);
      return true;
    },
  }]);
}

export function formCompteur(p, immeubleId, listes, ctx) {
  const nouveau = !p;
  const val = p || { immeuble_id: immeubleId, fluide: 'eau', etat: 'a_connecter' };
  const defF = (id) => listes.fluides.find((f) => f.id === id) || {};
  const fluides = listes.fluides.filter((f) => !METEO.includes(f.id)).map((f) => [f.id, f.libelle]);
  const nombre = (name, valeur, attrs) => h('input', { type: 'number', name, value: valeur ?? '', ...attrs });
  // Installation solaire : puissance crête (obligatoire), production prévue, âge et décote des modules
  const solaire = h('fieldset', { class: 'large cadre' + (val.fluide === 'solaire' ? '' : ' cache') },
    h('legend', { class: 'petit gras' }, 'Installation solaire'),
    champ('Puissance crête (kWc)', nombre('puissance_crete_kwc', val.puissance_crete_kwc, { min: 0.1, step: 0.1 }),
      'Obligatoire. Une production horaire au-delà de la puissance crête signale un défaut d\'échelle.'),
    champ('Production brute prévue (kWh/an)', nombre('production_prevue_kwh_an', val.production_prevue_kwh_an, { min: 0 }),
      'Selon l\'étude de l\'installateur. Référence tant qu\'il n\'y a pas d\'historique, et base de la projection.'),
    champ('Année de mise en service', nombre('mise_en_service', val.mise_en_service, { min: 1980, max: 2100 }),
      'Donne l\'âge des modules.'),
    champ('Décote annuelle des modules (%/an)', nombre('degradation_pct_an', val.degradation_pct_an,
      { min: 0, max: 5, step: 0.1, placeholder: '0,5' }),
    'Baisse normale de production par année d\'utilisation (garantie du fabricant ; 0,5 % si vide). Elle est déduite '
      + 'avant de juger une baisse de production.'));
  const sources = listes.sources.includes(val.source) || !val.source ? listes.sources : [...listes.sources, val.source];
  const form = h('div', { class: 'formulaire' },
    champ('Code compteur', saisie('id', val.id, { required: true, readonly: !nouveau, placeholder: immeubleId + '_EAU' }),
      'Identifiant utilisé dans la colonne point_id des fichiers de mesures.'),
    champ('Fluide', liste('fluide', fluides, val.fluide)),
    champ('Libellé', saisie('libelle', val.libelle, { placeholder: 'Eau froide générale' })),
    champ('Unité', liste('unite', listes.unites, val.unite || defF(val.fluide).unite)),
    champ('Nature de la valeur', liste('nature', [['index', 'Index cumulé (relevé de compteur)'],
      ['intervalle', 'Consommation par pas de temps'], ['instantane', 'Valeur instantanée (température, puissance)'],
      ['livraison', 'Quantité livrée (bon de livraison)']],
    val.nature || defF(val.fluide).nature)),
    champ('Pas de temps (minutes)', liste('pas_min', listes.pas.map((x) => [x, x === 1440 ? '1440 (journalier)' : x === PAS_MENSUEL ? '43200 (mensuel)' : String(x)]),
      val.pas_min || 15), 'Électricité et eau : 15 min. Chaleur : 60 min. Au pas journalier, une fuite de nuit est invisible.'),
    champ('Connexion des données', liste('source', sources, val.source || listes.sources[0])),
    champ('Identifiant de l\'appareil', saisie('identifiant', val.identifiant, { placeholder: 'N° de série, adresse M-Bus, DevEUI…' })),
    champ('Fournisseur (facture)', saisie('fournisseur', val.fournisseur, { placeholder: 'Services industriels, distributeur…' })),
    champ('État', liste('etat', Object.entries(ETATS_POINT), val.etat),
      '« À connecter » : déclaré, pas encore de données. Passe à « Actif » à la première mesure importée.'),
    solaire,
    h('input', { type: 'hidden', name: 'immeuble_id', value: immeubleId }));
  form.querySelector('select[name=fluide]').addEventListener('change', (ev) => {
    const f = defF(ev.target.value);
    form.querySelector('select[name=unite]').value = f.unite;
    form.querySelector('select[name=nature]').value = f.nature;
    form.querySelector('select[name=pas_min]').value = ['electricite', 'pac_electricite', 'eau'].includes(f.id) ? '15' : '60';
    solaire.classList.toggle('cache', f.id !== 'solaire');
  });
  const boutons = [{
    texte: 'Enregistrer', classe: 'primaire', action: async () => {
      const r = await tenter(() => api('POST', '/api/compteurs', lireFormulaire(form)), 'Compteur enregistré.');
      if (!r) return false;
      r.avertissements.forEach((a) => toast(a, true));
      await ctx.recharger();
      return true;
    },
  }];
  if (!nouveau) {
    boutons.unshift({ texte: 'Supprimer', classe: 'danger', action: async () => {
      if (!await confirmer('Supprimer ce compteur ?', `Le compteur ${val.id} et toutes ses mesures seront supprimés définitivement. `
        + 'Pour arrêter simplement de le suivre, passez-le plutôt à l\'état « Inactif ».', 'Supprimer définitivement', true)) return false;
      const ok = await tenter(() => api('DELETE', '/api/compteurs/' + encodeURIComponent(val.id)), 'Compteur supprimé.');
      if (ok) await ctx.recharger();
      return !!ok;
    } });
  }
  dialogue(nouveau ? 'Ajouter un compteur ou capteur' : 'Compteur ' + val.id, form, boutons);
}

// ---------------------------------------------------------------- fiche immeuble

export function surveillance(im, regles, sesBons, ctx) {
  const presents = new Set(im.points.filter((p) => p.etat === 'actif').map((p) => p.fluide));
  const actives = regles.regles.filter((r) => r.active && r.profils.includes(im.profil));
  const manque = (r) => !presents.has(r.fluide_point);
  // trop grossier : aucun compteur actif du fluide n'est assez fin (un compteur plus fin relève d'une autre règle)
  const tropGrossier = (r) => !im.points.some((p) => p.etat === 'actif' && p.fluide === r.fluide_point && p.pas_min <= r.pas_releve[1]);
  // la règle ne tourne que si un compteur actif du fluide est relevé au pas qu'elle exige
  const auBonPas = (r) => im.points.some((p) => p.etat === 'actif' && p.fluide === r.fluide_point
    && p.pas_min >= r.pas_releve[0] && p.pas_min <= r.pas_releve[1]);
  return h('div', { class: 'carte-corps' },
    actives.length ? h('ul', { class: 'liste-regles' },
      actives.map((r) => h('li', {}, pastilleFluide(r.fluide, { taille: 'xs' }), h('span', {}, h('span', { class: 'gras' }, r.libelle),
        ` — seuil ${fmt.n1(r.seuil)} ${r.unite_seuil}, sur ${r.persistance} ${r.unite_persistance}`,
        manque(r) ? h('span', { class: 'doux petit' }, ' (pas de compteur actif pour ce fluide)')
          : auBonPas(r) || !tropGrossier(r) ? null : [' ', h('span', { class: 'chip g-Attente' }, `sans effet ici : demande un relevé ${r.releve}`)],
        r.id.endsWith('_vide') && fluideRegle(r.id) !== 'eau' && !im.talon_horsgel_kwh_j
          ? [' ', h('span', { class: 'chip g-Attente' }, 'inactive : talon hors-gel à renseigner')] : null))))
      : h('p', { class: 'doux' }, 'Aucune règle de dérive pour cette occupation.'),
    h('p', { class: 'doux petit' }, 'Toujours appliqué : contrôle de la qualité des données de chaque compteur.'),
    h('h3', {}, 'Bons de travaux'),
    sesBons.length ? h('ul', { class: 'journal' }, sesBons.map((b) => h('li', {},
      h('button', { type: 'button', class: 'lien', onclick: () => ouvrirBon(b.id, ctx) }, b.numero),
      chipStatut(b.statut), h('span', { class: 'doux petit' }, b.alerte.titre || ''))))
      : h('p', { class: 'doux' }, 'Aucun bon de travaux.'));
}

export function tableCompteurs(im, parc, ctx, zoneGraphe) {
  if (!im.points.length) {
    return etatVide('compteur', 'Aucun compteur déclaré pour cet immeuble.',
      h('button', { type: 'button', class: 'primaire', onclick: () => formCompteur(null, im.id, parc.listes, ctx) },
        icone('ajouter'), 'Ajouter un compteur'));
  }
  const libFluide = (id) => (parc.listes.fluides.find((f) => f.id === id) || {}).libelle || id;
  const classeEtat = { actif: 'g-OK', a_connecter: 'g-Connecter', inactif: 'g-Données' };
  return h('div', { class: 'defile' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Fluide', 'Compteur', 'Connexion', 'Pas', 'État', 'Dernière donnée', 'Complétude', 'Alerte', '']
      .map((t, i) => h('th', { scope: 'col', class: [3, 6].includes(i) ? 'nombre' : null }, t)))),
    h('tbody', {}, im.points.map((p) => {
      const g = p.alertes.length ? ['Critique', 'Élevée', 'Modérée', 'Données'].find((x) => p.alertes.includes(x)) : null;
      return h('tr', {},
        h('td', {}, h('span', { class: 'cellule-fluide' }, pastilleFluide(p.fluide), libFluide(p.fluide))),
        h('td', {}, p.libelle, h('div', { class: 'doux petit' }, p.id + (p.fournisseur ? ' · ' + p.fournisseur : '')
          + (p.puissance_crete_kwc ? ` · ${fmt.n1(p.puissance_crete_kwc)} kWc` : '')
          + (p.production_prevue_kwh_an ? ` · ${fmt.n0(p.production_prevue_kwh_an)} kWh/an prévus` : '')
          + (p.niveau ? ` · ${p.niveau}` : '') + (p.parent_id ? ` · relié à ${p.parent_id}` : '')
          + (p.service_debut || p.service_fin ? ` · en service ${p.service_debut || '…'} → ${p.service_fin || 'aujourd\'hui'}` : ''))),
        h('td', {}, p.source, p.identifiant ? h('div', { class: 'doux petit' }, p.identifiant) : null),
        h('td', { class: 'nombre' }, libPas(p.pas_min), p.avertissements.some((a) => a.includes('grossier'))
          ? h('div', {}, h('span', { class: 'chip g-Attente' }, 'trop grossier')) : null),
        h('td', {}, h('span', { class: 'chip ' + classeEtat[p.etat] }, ETATS_POINT[p.etat])),
        h('td', {}, p.derniere ? fmt.dateHeure(p.derniere) : h('span', { class: 'doux' }, 'aucune')),
        h('td', { class: 'nombre' }, p.completude === null ? '—' : fmt.pct(p.completude),
          p.completude !== null && p.pas_min >= PAS_MENSUEL ? h('div', { class: 'doux petit' }, 'sur 12 mois') : null),
        h('td', {}, g ? chip(g) : (p.etat === 'actif' ? h('span', { class: 'chip g-OK' }, 'OK') : '—')),
        h('td', { class: 'sans-retour' },
          h('button', { type: 'button', class: 'lien', disabled: !p.derniere, onclick: () => zoneGraphe.choisir(p.id) }, 'Courbe'),
          h('button', { type: 'button', class: 'lien', onclick: () => formCompteur(p, im.id, parc.listes, ctx) }, 'Modifier')));
    }))));
}

export async function supprimerImmeuble(im, ctx) {
  if (!await confirmer('Supprimer cet immeuble ?', `« ${im.nom} », ses ${im.points.length} compteur(s), toutes leurs mesures et ses alertes `
    + 'seront supprimés définitivement. Les bons de travaux restent dans l\'historique.', 'Supprimer définitivement', true)) return;
  const ok = await tenter(() => api('DELETE', '/api/immeubles/' + encodeURIComponent(im.id)), 'Immeuble supprimé.');
  if (ok) ctx.aller('#/parc');
}

// ---------------------------------------------------------------- imports

export async function pageImports(main, ctx) {
  const zoneParc = h('div', { class: 'pile' });
  const zoneMesures = h('div', { class: 'pile' });
  const zonePatrimoine = h('div', { class: 'pile' });
  const carte = (ico, titre, sous, action, ...corps) => h('section', { class: 'carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone(ico, 'h2', {}, titre),
      h('span', { class: 'doux petit' }, sous)), action),
    h('div', { class: 'carte-corps' }, corps));
  vider(main,
    h('div', { class: 'entete-page' }, h('div', { class: 'titres' }, h('h1', {}, 'Imports'),
      h('p', { class: 'doux' }, 'Votre parc depuis Excel, les relevés des compteurs depuis un fichier CSV ou Excel. Tout reste sur ce poste.'))),
    carte('immeuble', '1. Parc immobilier (Excel)',
      'Feuilles « Immeubles », « Compteurs » et « Prestataires ». Ajout ou mise à jour par code ; rien n\'est supprimé.',
      h('button', { type: 'button', onclick: () => exporterParc() }, icone('exporter'),
        ctx.etat.parc_vide ? 'Télécharger le modèle Excel' : 'Télécharger mon parc (modèle)'),
      depot('.xlsx', 'Déposez votre fichier Excel (.xlsx) ici', (f) => apercuParc(f, zoneParc, ctx)), zoneParc),
    carte('compteur', '2. Relevés des compteurs (CSV ou Excel)',
      'Colonnes ts, point_id, valeur. ts = date et heure du relevé, en UTC, fin d\'intervalle (ex. 2026-11-11T06:00:00Z '
        + '= consommation de 06:00 à 07:00, heure de Genève en hiver). CSV : séparateur , ou ;. Excel : feuille « mesures ». '
        + 'Exemples dans le dossier « exemple de données fluides ».', null,
      depot('.csv,.txt,.xlsx', 'Déposez le fichier CSV ou Excel (.xlsx) de votre passerelle ou de votre distributeur', (f) => importerMesures(f, zoneMesures, ctx)),
      zoneMesures,
      h('p', { class: 'doux petit' }, 'Contrôles : compteur inconnu ou valeur illisible → ligne rejetée ; doublon → la dernière valeur l\'emporte ; '
        + 'valeur négative → marquée suspecte et exclue des calculs. Un compteur « à connecter » devient « actif » à sa première mesure.')),
    carte('immeuble', 'Classeur patrimoine et courbes (jeu de données complet)',
      'Classeur .xlsx : feuilles Batiments, Installations, Compteurs, Mesures (relevés mensuels) et références. Puis les '
        + 'courbes .csv ou .xlsx au jour, à l\'heure ou au quart d\'heure des mêmes compteurs. Aperçu avant import ; rien n\'est supprimé.',
      null,
      depot('.xlsx,.csv', 'Déposez le classeur patrimoine (.xlsx) ou un fichier de courbes (.csv ou .xlsx)',
        (f) => apercuPatrimoine(f, zonePatrimoine, ctx)), zonePatrimoine),
    carte('donnees', '3. Connexions automatiques','M-Bus, wM-Bus / OMS, LoRaWAN, export DLMS du distributeur, Modbus TCP, BACnet', null,
      h('p', {}, 'Déjà automatique : la température extérieure officielle MétéoSuisse (station réglable dans Réglages). '
        + 'Pour les compteurs, les connecteurs directs sont prévus dans une prochaine version. En attendant, exportez les relevés de votre passerelle '
        + 'ou du portail de votre distributeur en CSV et importez-les ci-dessus. Le type de connexion de chaque compteur se déclare '
        + 'dans sa fiche (Parc › immeuble › compteur).')),
    ctx.etat.parc_vide ? h('div', { class: 'banniere info' },
      h('span', {}, 'Envie d\'essayer d\'abord ? Chargez un parc fictif : consommations simulées sur la météo réelle de Genève.'),
      h('button', { type: 'button', onclick: () => tenter(async () => {
        await api('POST', '/api/exemple');
        ctx.aller('#/');
      }, 'Exemple chargé et analysé.') }, 'Charger l\'exemple')) : null);
}

function depot(accept, texte, surFichier) {
  const input = h('input', { type: 'file', accept, class: 'cache' });
  const zone = h('div', { class: 'depot' }, h('span', { class: 'vide-ico' }, icone('importer')), h('p', { class: 'gras' }, texte),
    h('button', { type: 'button', onclick: () => input.click() }, 'Choisir un fichier'), input);
  input.addEventListener('change', () => { if (input.files[0]) surFichier(input.files[0]); input.value = ''; });
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('survol'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('survol'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('survol');
    if (e.dataTransfer.files[0]) surFichier(e.dataTransfer.files[0]);
  });
  return zone;
}

async function apercuParc(fichier, zone, ctx) {
  vider(zone, h('p', { class: 'doux' }, 'Lecture de ' + fichier.name + '…'));
  const r = await tenter(() => api('POST', '/api/import/parc?appliquer=0', fichier));
  if (!r) return vider(zone);
  const bloc = (titre, c) => h('div', {}, h('div', { class: 'doux petit' }, titre),
    h('b', {}, `${c.nouveaux} nouveau(x)`), h('div', { class: 'petit' }, `${c.modifies} modifié(s) · ${c.inchanges} inchangé(s)`));
  const total = ['immeubles', 'compteurs', 'prestataires'].reduce((n, k) => n + r[k].nouveaux + r[k].modifies, 0);
  vider(zone,
    h('h3', {}, 'Aperçu de ' + fichier.name),
    h('div', { class: 'resume-import' }, bloc('Immeubles', r.immeubles), bloc('Compteurs', r.compteurs), bloc('Prestataires', r.prestataires)),
    r.erreurs.length ? h('div', {}, h('p', { class: 'gras' }, `${r.erreurs.length} ligne(s) refusée(s) — elles ne seront pas importées :`),
      h('div', { class: 'defile' }, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Feuille'), h('th', {}, 'Ligne'), h('th', {}, 'Problème'))),
        h('tbody', {}, r.erreurs.map((e) => h('tr', {}, h('td', {}, e.feuille), h('td', {}, e.ligne), h('td', {}, e.message))))))) : null,
    r.avertissements.length ? h('div', { class: 'banniere attention' },
      h('div', {}, r.avertissements.map((a) => h('div', {}, a)))) : null,
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'primaire', disabled: !total, onclick: () => tenter(async () => {
        await api('POST', '/api/import/parc?appliquer=1', fichier);
        vider(zone, h('div', { class: 'banniere ok' }, h('span', {}, 'Parc importé.'),
          h('a', { class: 'bouton', href: '#/parc' }, 'Voir le parc')));
        await ctx.rafraichirEtat();
      }, 'Parc importé.') }, total ? `Importer ${total} ligne(s)` : 'Rien de nouveau à importer'),
      h('button', { type: 'button', onclick: () => vider(zone) }, 'Abandonner')));
}

// Classeur patrimoine (.xlsx) ou courbes (.csv ; le classeur des courbes ne donne que son calendrier) : aperçu puis import
async function apercuPatrimoine(fichier, zone, ctx) {
  vider(zone, h('p', { class: 'doux' }, 'Lecture de ' + fichier.name + '…'));
  const courbes = `/api/import/courbes?nom=${encodeURIComponent(fichier.name)}`;
  let url = /\.csv$/i.test(fichier.name) ? courbes : '/api/import/patrimoine';
  let r = null;
  try {
    r = await api('POST', `${url}${url.includes('?') ? '&' : '?'}appliquer=0`, fichier);
  } catch (e) {
    if (url === courbes) { toast(e.message, true); return vider(zone); }
    url = courbes; // classeur sans feuille Batiments : classeur des courbes, lu pour son calendrier
    r = await tenter(() => api('POST', `${url}&appliquer=0`, fichier));
    if (!r) return vider(zone);
  }
  const rendre = (rep, fait) => {
    const m = rep.mesures;
    const blocs = rep.sites ? [
      ['Sites et bâtiments', `${rep.sites.total} sites`, `${rep.sites.nouveaux} nouveaux · ${rep.batiments} bâtiments · ${rep.installations} installations`],
      ['Compteurs', `${rep.compteurs.total}`, `${rep.compteurs.actifs} en service · ${rep.compteurs.hors_service} hors service`],
      ['Relevés mensuels', fmt.n0(m.a_importer), `${rep.periode[0]} à ${rep.periode[1]} · ${m.manquantes} manquants · ${m.doublons} doublons`],
      ['Références', fmt.n0(rep.references), 'climat, conversions, CO₂']]
      : [['Séries', `${rep.series.length}`, `${rep.compteurs} compteurs de courbe`],
        ['Mesures', fmt.n0(m), rep.series.length ? `${rep.series[0].periode[0]} à ${rep.series[0].periode[1]}` : '—'],
        ['Références', fmt.n0(rep.references), 'calendrier du lot']];
    vider(zone,
      h('h3', {}, (fait ? 'Importé : ' : 'Aperçu de ') + fichier.name + (rep.commune ? ` — ${rep.commune}` : '')),
      h('div', { class: 'resume-import' }, blocs.map(([t, n, d]) => h('div', {}, h('div', { class: 'doux petit' }, t),
        h('b', {}, n), h('div', { class: 'petit' }, d)))),
      (rep.erreurs || []).length ? h('div', { class: 'banniere attention' }, h('div', {},
        h('div', { class: 'gras' }, `${rep.erreurs.length} ligne(s) de structure refusée(s) :`),
        rep.erreurs.slice(0, 20).map((e) => h('div', {}, `${e.feuille} ligne ${e.ligne} : ${e.message}`)))) : null,
      rep.anomalies_total ? h('div', {},
        h('p', { class: 'gras' }, `${rep.anomalies_total} anomalie(s) relevée(s) et tracée(s) — rien n'est corrigé ni comblé :`),
        h('div', { class: 'defile' }, h('table', {},
          h('thead', {}, h('tr', {}, ['Anomalie', 'Compteur', 'Période', 'Détail', 'Traitement'].map((x) => h('th', { scope: 'col' }, x)))),
          h('tbody', {}, rep.anomalies.map((a) => h('tr', {}, h('td', {}, a.type), h('td', {}, a.objet || '—'),
            h('td', {}, a.periode || '—'), h('td', {}, a.detail), h('td', { class: 'doux' }, a.traitement))))))) : null,
      fait ? h('div', { class: 'banniere ok' }, h('span', {}, 'Import terminé. La trace des anomalies est aussi dans sorties/anomalies_import.csv.'),
        h('button', { type: 'button', class: 'primaire', onclick: () => tenter(() => ctx.analyser()) }, 'Lancer l\'analyse'),
        h('a', { class: 'bouton', href: '#/parc' }, 'Voir le parc'))
        : h('div', { class: 'actions' },
          h('button', { type: 'button', class: 'primaire', onclick: () => tenter(async () => {
            const applique = await api('POST', `${url}${url.includes('?') ? '&' : '?'}appliquer=1`, fichier);
            rendre(applique, true);
            await ctx.rafraichirEtat();
          }, 'Import terminé.') }, 'Importer'),
          h('button', { type: 'button', onclick: () => vider(zone) }, 'Annuler')));
  };
  return rendre(r, false);
}

async function importerMesures(fichier, zone, ctx) {
  vider(zone, h('p', { class: 'doux' }, 'Import de ' + fichier.name + '…'));
  const r = await tenter(() => api('POST', '/api/import/mesures', fichier));
  if (!r) return vider(zone);
  vider(zone,
    h('div', { class: r.rejets ? 'banniere attention' : 'banniere ok' },
      h('span', {}, `${fmt.n0(r.importees)} mesures importées, ${fmt.n0(r.rejets)} ligne(s) rejetée(s).`),
      h('button', { type: 'button', class: 'primaire', onclick: () => tenter(() => ctx.analyser()) }, 'Lancer l\'analyse')),
    r.detail_rejets.length ? h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Ligne'), h('th', {}, 'Motif'))),
      h('tbody', {}, r.detail_rejets.map((x) => h('tr', {}, h('td', {}, x.ligne), h('td', {}, x.motif)))))) : null);
  await ctx.rafraichirEtat();
}
