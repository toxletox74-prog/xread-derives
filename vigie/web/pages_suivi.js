// Écrans de suivi : tableau de bord, alertes, bons de travaux.
import {
  api, h, vider, fmt, enjeu, chip, chipStatut, toast, tenter, dialogue, confirmer, champ, liste, saisie, telecharger,
  PROFILS, RETOURS, STATUTS_BON,
} from './outils.js';
import { carteParc } from './carte.js';
import { MOT_DE_PASSE_MANQUANT } from './pages_reglages.js';
import { icone, pastilleFluide, tagFluide, cleFluide, libelleFluide, titreIcone, etatVide } from './icones.js';

const GRAVITES = ['Critique', 'Élevée', 'Modérée', 'Données'];
const boutonAnalyse = (ctx) => h('button', { type: 'button', class: 'primaire', onclick: () => tenter(() => ctx.analyser()) },
  icone('analyser'), 'Lancer l\'analyse');

// ---------------------------------------------------------------- tableau de bord

export async function pageTableau(main, ctx) {
  const e = ctx.etat;
  if (e.parc_vide) return accueil(main, ctx);
  const [{ alertes }, carte] = await Promise.all([api('GET', '/api/alertes'), carteParc(ctx)]);
  const k = e.kpis;
  const sousTitre = `${e.adresses} adresses · ${e.immeubles} immeubles · ${e.compteurs.actifs} compteurs suivis`
    + (e.fin_donnees ? ` · données au ${fmt.dateHeure(e.fin_donnees)}` : ' · aucune donnée importée')
    + (e.derniere_analyse ? ` · analyse du ${fmt.dateHeure(e.derniere_analyse.le)}` : '');
  const bannieres = [];
  if (e.tarifs_exemple) {
    bannieres.push(h('div', { class: 'banniere attention' },
      h('span', {}, 'Les montants en CHF utilisent des tarifs d\'exemple. Saisissez vos tarifs de contrat pour des enjeux réels.'),
      h('a', { class: 'bouton', href: '#/regles' }, 'Saisir mes tarifs')));
  }
  if (e.fin_donnees && !e.meteo.ok && !e.climat_mensuel) {
    bannieres.push(h('div', { class: 'banniere attention' },
      h('span', {}, e.meteo.derniere
        ? `Température extérieure muette depuis le ${fmt.dateHeure(e.meteo.derniere)} : `
          + 'les règles « chauffage trop fort pour la météo » et « rendement PAC » ne sont pas fiables.'
        : 'Aucune température extérieure : les règles « chauffage trop fort pour la météo » et « rendement PAC » ne tournent pas.'),
      h('a', { class: 'bouton', href: '#/reglages' }, 'Voir la source météo')));
  }
  if (e.smtp_mot_de_passe_manquant) {
    bannieres.push(h('div', { class: 'banniere attention' }, h('span', {}, MOT_DE_PASSE_MANQUANT),
      h('a', { class: 'bouton', href: '#/reglages' }, 'Saisir le mot de passe')));
  }
  const c = e.couverture || {};
  if (c.sans_effet || c.compteurs_sans_regle) {
    bannieres.push(h('div', { class: 'banniere attention' },
      h('span', {}, [c.sans_effet ? `${c.sans_effet} règle(s) active(s) ne tournent sur aucun compteur : le relevé de vos `
        + 'compteurs est trop grossier pour elles.' : null,
      c.compteurs_sans_regle ? ` ${c.compteurs_sans_regle} compteur(s) n'ont aucune règle de dérive.` : null]),
      h('a', { class: 'bouton', href: '#/regles' }, 'Voir la couverture des règles')));
  }
  if (k.bons_brouillon) {
    bannieres.push(h('div', { class: 'banniere info' },
      h('span', {}, `${k.bons_brouillon} bon(s) de travaux prêt(s) : relisez et envoyez au prestataire.`),
      h('a', { class: 'bouton primaire', href: '#/bons' }, 'Voir les bons')));
  }
  if (e.compteurs.a_connecter) {
    bannieres.push(h('div', { class: 'banniere info' },
      h('span', {}, `${e.compteurs.a_connecter} compteur(s) déclaré(s) mais pas encore connecté(s) : aucune donnée reçue.`),
      h('a', { class: 'bouton', href: '#/imports' }, 'Importer des mesures')));
  }
  const pert = k.pertinence;
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Tableau de bord du parc'), h('p', { class: 'doux' }, sousTitre)),
      h('div', { class: 'actions' }, boutonAnalyse(ctx))),
    bannieres,
    h('section', { class: 'grille-kpi', 'aria-label': 'Indicateurs clés' },
      kpi('alerte', 'Alertes ouvertes', fmt.n0(k.alertes), `dont ${k.critiques} critique(s) · ${k.donnees} problème(s) de données`,
        k.critiques ? 'ton-crit' : 'ton-ok', repartitionGravite(alertes)),
      kpi('argent', 'Rythme des dérives ouvertes', fmt.chf(k.chf_mois, 'CHF/mois'),
        (k.chf_mesure ? `dérives constatées ${fmt.chf(k.chf_mesure)} · ` : 'tous fluides · ')
        + (e.tarifs_exemple ? 'tarifs d\'exemple, à remplacer' : 'aux conditions actuelles')),
      kpi('courbe', "Projection si rien n'est fait", fmt.chf(k.chf_proj, 'CHF sur 12 mois'),
        'hypothèses : climat normal de Genève, dérive constante — information, pas un déclencheur'),
      kpi('energie', 'Énergie et eau en dérive', '≈ ' + fmt.n1((k.kwh_mois || 0) / 1000) + ' MWh/mois',
        k.m3_mois ? `et ≈ ${fmt.n0(k.m3_mois)} m³ d'eau par mois` : 'chaleur, PAC et électricité'),
      kpi('co2', 'Émissions évitables', '≈ ' + fmt.n1(k.co2_t_mois) + ' t CO₂/mois', 'facteurs d\'émission par vecteur', 'ton-ok'),
      kpi('bon', 'Bons de travaux en cours', fmt.n0(k.bons_ouverts),
        k.bons_brouillon ? `dont ${k.bons_brouillon} à valider` : 'aucun en attente de validation', k.bons_brouillon ? 'ton-elev' : ''),
      kpi('pertinence', 'Pertinence des alertes', pert.taux === null ? '—' : fmt.pct(pert.taux),
        pert.retours ? `${pert.pertinentes} pertinente(s) sur ${pert.retours} retour(s)` : 'donnez votre avis sur chaque alerte')),
    carte,
    h('section', { class: 'carte', 'aria-labelledby': 't-alertes' },
      h('div', { class: 'carte-tete' }, h('div', { class: 'titres' },
        titreIcone('alerte', 'h2', { id: 't-alertes' }, 'À traiter, par priorité'),
        h('span', { class: 'doux petit' }, 'Classement : rythme mensuel en CHF × confiance × urgence (× 1,5 si risque de sinistre)'
          + ' · 1 alerte par cause et par immeuble')),
      repartitionFluides(alertes)),
      listeAlertes(alertes, ctx, 'Aucune dérive en cours. Les compteurs analysés se comportent comme attendu.')));
  carte.monter();
}

function kpi(ico, lib, val, sous, ton = '', extra = null) {
  return h('div', { class: 'kpi' },
    h('div', { class: 'kpi-tete' }, h('span', { class: 'kpi-ico ' + ton }, icone(ico)), h('span', { class: 'lib' }, lib)),
    h('span', { class: 'val' }, val), extra, h('span', { class: 'sous' }, sous));
}

// Nombre d'alertes ouvertes par gravité (comptage des alertes reçues du moteur)
function repartitionGravite(alertes) {
  const n = (g) => alertes.filter((a) => a.gravite === g).length;
  const presentes = GRAVITES.filter((g) => n(g));
  if (!presentes.length) return null;
  return h('div', { class: 'repartition', 'aria-label': 'Alertes par gravité' },
    presentes.map((g) => h('span', { class: 'chip g-' + g }, `${g} ${n(g)}`)));
}

// Répartition des alertes par fluide : pastille + libellé + nombre
function repartitionFluides(alertes) {
  const parCle = new Map();
  alertes.filter((a) => a.gravite !== 'Données').forEach((a) => {
    const c = cleFluide(a.fluide);
    parCle.set(c, (parCle.get(c) || 0) + 1);
  });
  if (!parCle.size) return null;
  return h('div', { class: 'repartition', 'aria-label': 'Alertes par fluide' },
    [...parCle].map(([c, n]) => h('span', { class: 'tag-fluide f-' + c }, pastilleFluide(c, { taille: 'xs' }),
      h('span', {}, `${libelleFluide(c)} · ${n}`))));
}

function accueil(main, ctx) {
  const etape = (n, titre, texte, ...actions) => h('div', { class: 'carte' }, h('div', { class: 'carte-corps' },
    h('span', { class: 'tag etape' }, 'Étape ' + n), h('h2', {}, titre),
    h('p', { class: 'doux' }, texte), h('div', { class: 'actions' }, actions)));
  vider(main,
    h('div', { class: 'entete-page' }, h('div', { class: 'titres' }, h('h1', {}, 'Bienvenue dans Xread Dérives'),
      h('p', { class: 'doux' }, 'Votre parc est vide. Trois étapes pour surveiller les dérives de vos immeubles.'))),
    h('div', { class: 'grille-kpi' },
      etape(1, 'Importer votre parc', 'Adresses, immeubles, compteurs et prestataires depuis un fichier Excel. '
        + 'Téléchargez le modèle, complétez-le, importez-le.',
      h('a', { class: 'bouton primaire', href: '#/imports' }, icone('importer'), 'Importer mon parc (Excel)')),
      etape(2, 'Connecter les compteurs', 'Importez les relevés (CSV de votre passerelle M-Bus, LoRaWAN ou de l\'export du distributeur).',
        h('a', { class: 'bouton', href: '#/imports' }, icone('compteur'), 'Importer des mesures')),
      etape(3, 'Régler et automatiser', 'Seuils selon l\'occupation, tarifs de vos contrats, prestataires par métier et envoi des bons de travaux.',
        h('a', { class: 'bouton', href: '#/regles' }, 'Règles & coûts'), h('a', { class: 'bouton', href: '#/prestataires' }, 'Prestataires'))),
    h('div', { class: 'banniere info' },
      h('span', {}, 'Pour découvrir l\'outil, chargez un parc fictif de 5 immeubles : 120 jours de consommations simulées sur la météo réelle de Genève, avec 6 dérives.'),
      h('button', { type: 'button', onclick: () => tenter(async () => {
        await api('POST', '/api/exemple');
        await ctx.recharger();
      }, 'Exemple chargé et analysé.') }, 'Charger l\'exemple')));
}

function etatFluide(p) {
  if (p.etat === 'a_connecter') return 'Attente';
  if (p.alertes.length) return ['Critique', 'Élevée', 'Modérée', 'Données'].find((g) => p.alertes.includes(g));
  return 'OK';
}

export function pastillesFluides(points) {
  return h('span', { class: 'fluides' }, points.filter((p) => p.etat !== 'inactif').map((p) => {
    const etat = etatFluide(p);
    const lib = etat === 'Attente' ? 'à connecter' : etat;
    return h('span', { class: 'puce-fluide', title: `${p.libelle} · ${lib}` }, pastilleFluide(p.fluide, { taille: 'xs' }),
      h('span', { class: 'lib-puce' }, p.libelle.split(' (')[0]), h('span', { class: 'etat-mini g-' + (etat === 'Attente' ? 'Connecter' : etat) }, lib));
  }));
}

export function profilTexte(im) {
  let t = PROFILS[im.profil] || im.profil;
  if (im.profil === 'Partiel' && im.taux_occupation !== null) t += ' · ' + fmt.pct(im.taux_occupation);
  if (im.logements) t += ` · ${im.logements} logements`;
  return t;
}

// ---------------------------------------------------------------- alertes

export function listeAlertes(alertes, ctx, messageVide) {
  if (!alertes.length) return etatVide('ok', messageVide);
  return h('ol', { class: 'liste' }, alertes.map((a, i) => carteAlerte(a, i + 1, ctx)));
}

function carteAlerte(a, rang, ctx) {
  const donnees = a.gravite === 'Données';
  const resolue = a.statut === 'resolue';
  const { principal, precisions: details } = enjeu(a);
  const retours = h('div', { class: 'retours', role: 'group', 'aria-label': 'Votre avis sur cette alerte' },
    h('span', { class: 'doux petit' }, 'Votre avis :'),
    Object.entries(RETOURS).map(([cle, lib]) => h('button', {
      type: 'button', class: a.retour === cle ? 'choisi' : null, 'aria-pressed': a.retour === cle ? 'true' : 'false',
      onclick: () => tenter(async () => {
        await api('POST', `/api/alertes/${encodeURIComponent(a.id)}/retour`, { retour: cle });
        await ctx.recharger();
      }, 'Merci : votre avis sert à mesurer la pertinence des alertes.'),
    }, lib)));
  let actionBon = null;
  if (a.bon) {
    actionBon = h('button', { type: 'button', onclick: () => ouvrirBon(a.bon.id, ctx) },
      icone('bon'), `Bon ${a.bon.numero} · ${STATUTS_BON[a.bon.statut]}`);
  } else if (!resolue && a.suivi !== 'sourdine') {
    actionBon = h('button', { type: 'button', class: 'primaire', onclick: () => tenter(async () => {
      const r = await api('POST', `/api/alertes/${encodeURIComponent(a.id)}/bon`, {});
      await ctx.rafraichirEtat();
      await ouvrirBon(r.bon.id, ctx);
    }) }, icone('bon'), 'Créer le bon de travaux');
  }
  return h('li', { class: 'alerte gr-' + a.gravite },
    h('div', { class: 'alerte-media' }, pastilleFluide(donnees ? 'donnees' : a.fluide, { taille: 'lg' }),
      h('span', { class: 'rang', 'aria-hidden': 'true' }, resolue ? '✓' : rang)),
    h('div', { class: 'corps' },
      h('div', { class: 'tags' }, chip(a.gravite), tagFluide(a.fluide),
        a.persistance ? h('span', { class: 'doux petit' }, 'depuis ' + a.persistance) : null,
        a.cause_commune ? h('span', { class: 'chip g-Attente', title: 'Effet probable de météo ou de calendrier : à vérifier avant d\'agir. Aucun bon automatique.' },
          `Cause commune probable · ${a.cause_commune.immeubles} immeubles les mêmes jours`) : null,
        resolue ? h('span', { class: 'chip g-OK' }, 'Résolue le ' + fmt.date(a.cloturee_le)) : null,
        a.suivi === 'sourdine' ? h('span', { class: 'chip g-Attente' },
          `En sourdine jusqu'au ${fmt.date(a.sourdine.jusquau)} : ${a.sourdine.motif}`) : null),
      h('span', { class: 'titre' }, a.titre),
      h('a', { class: 'doux petit lien-immeuble', href: '#/immeuble/' + encodeURIComponent(a.immeuble_id) },
        icone('immeuble'), `${a.immeuble} · ${a.adresse}`),
      h('p', {}, a.constat),
      h('p', { class: 'consigne' }, h('strong', {}, `Consigne — ${a.metier || a.prestataire}, sous ${a.delai} : `), a.consigne),
      retours),
    h('div', { class: 'impact' },
      h('span', { class: 'chf' }, principal),
      details.length ? h('span', { class: 'doux petit' }, details.join(' · ')) : null,
      h('span', { class: 'doux petit' }, donnees ? 'Pas d\'alerte énergie tant que les données manquent'
        : 'Confiance ' + fmt.pct(a.confiance)),
      a.sinistre ? h('span', { class: 'chip g-Critique' }, 'Risque de sinistre') : null,
      a.payeur && a.payeur !== '—' ? h('span', { class: 'doux petit' }, 'Imputation : ' + a.payeur) : null,
      actionBon));
}

export async function pageAlertes(main, ctx) {
  const statut = sessionStorage.getItem('vigie-alertes-statut') || 'ouverte';
  const { alertes } = await api('GET', '/api/alertes?statut=' + statut);
  const filtres = { gravite: '', fluide: '', q: '' };
  const zone = h('div', {});
  const rendre = () => {
    const q = filtres.q.toLowerCase();
    const vis = alertes.filter((a) => (!filtres.gravite || a.gravite === filtres.gravite)
      && (!filtres.fluide || a.fluide === filtres.fluide)
      && (!q || `${a.immeuble} ${a.adresse} ${a.titre}`.toLowerCase().includes(q)));
    vider(zone, listeAlertes(vis, ctx, 'Aucune alerte ne correspond.'));
  };
  const fluides = [...new Set(alertes.map((a) => a.fluide))].sort();
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Alertes'),
        h('p', { class: 'doux' }, 'Chaque dérive confirmée par sa persistance devient une alerte, avec son coût, '
          + 'sa consigne et le prestataire à mandater.')),
      h('div', { class: 'actions' }, boutonAnalyse(ctx))),
    h('div', { class: 'filtres' },
      champ('Afficher', liste('statut', [['ouverte', 'Alertes ouvertes'], ['sourdine', 'En sourdine'], ['resolue', 'Alertes résolues'], ['toutes', 'Toutes']], statut)),
      champ('Gravité', liste('gravite', [['', 'Toutes'], 'Critique', 'Élevée', 'Modérée', 'Données'], '')),
      champ('Fluide', liste('fluide', [['', 'Tous les fluides'], ...fluides], '')),
      champ('Rechercher', h('input', { type: 'search', name: 'q', placeholder: 'Immeuble, adresse…' }))),
    h('section', { class: 'carte' }, zone));
  main.querySelector('select[name=statut]').addEventListener('change', (ev) => {
    sessionStorage.setItem('vigie-alertes-statut', ev.target.value);
    pageAlertes(main, ctx);
  });
  for (const nom of ['gravite', 'fluide']) {
    main.querySelector(`select[name=${nom}]`).addEventListener('change', (ev) => { filtres[nom] = ev.target.value; rendre(); });
  }
  main.querySelector('input[name=q]').addEventListener('input', (ev) => { filtres.q = ev.target.value; rendre(); });
  rendre();
}

// ---------------------------------------------------------------- bons de travaux

export async function pageBons(main, ctx) {
  const { bons } = await api('GET', '/api/bons');
  let filtre = 'ouverts';
  const corps = h('tbody', {});
  const ligne = (b) => h('tr', { class: 'cliquable', tabindex: '0',
    onclick: () => ouvrirBon(b.id, ctx), onkeydown: (ev) => { if (ev.key === 'Enter') ouvrirBon(b.id, ctx); } },
  h('td', { class: 'gras sans-retour' }, b.numero),
  h('td', {}, b.immeuble || b.immeuble_id),
  h('td', {}, h('div', { class: 'cellule-fluide' }, b.alerte.fluide ? pastilleFluide(b.alerte.fluide, { libelle: b.alerte.fluide }) : null,
    h('div', {}, h('div', {}, b.alerte.titre || ''), b.alerte.gravite ? chip(b.alerte.gravite) : null))),
  h('td', {}, b.prestataire || h('span', { class: 'chip g-Attente' }, 'à choisir')),
  h('td', {}, chipStatut(b.statut), b.mode === 'auto' ? h('span', { class: 'doux petit' }, ' · auto') : null),
  h('td', { class: 'nombre' }, fmt.date(b.cree_le)),
  h('td', { class: 'nombre' }, fmt.date(b.envoye_le)),
  h('td', {}, b.alerte_statut === 'resolue' ? h('span', { class: 'chip g-OK' }, 'Disparue') : b.alerte_statut === 'ouverte' ? 'Toujours mesurée' : '—'));
  const rendre = () => {
    const vis = bons.filter((b) => filtre === 'tous' || (filtre === 'ouverts'
      ? ['brouillon', 'envoye', 'en_cours', 'retour'].includes(b.statut) : b.statut === filtre));
    vider(corps, vis.length ? vis.map(ligne)
      : h('tr', {}, h('td', { colspan: '8' }, etatVide('bon', 'Aucun bon de travaux dans cette catégorie.'))));
  };
  vider(main,
    h('div', { class: 'entete-page' },
      h('div', { class: 'titres' }, h('h1', {}, 'Bons de travaux'),
        h('p', { class: 'doux' }, 'Préparés à partir des alertes et adressés au prestataire du métier concerné. '
          + 'Relisez, envoyez, suivez jusqu\'à la clôture.')),
      h('div', { class: 'actions' }, h('a', { class: 'bouton', href: '#/reglages' }, icone('reglages'), 'Automatisation et messagerie'))),
    h('div', { class: 'filtres' }, champ('Afficher', liste('filtre', [['ouverts', 'En cours (brouillon, envoyé, en cours, retour reçu)'],
      ...Object.entries(STATUTS_BON), ['tous', 'Tous']], filtre))),
    h('section', { class: 'carte' }, h('div', { class: 'defile' }, h('table', {},
      h('thead', {}, h('tr', {}, ['N°', 'Immeuble', 'Problème', 'Prestataire', 'Statut', 'Créé le', 'Envoyé le', 'Dérive']
        .map((t, i) => h('th', { class: i === 5 || i === 6 ? 'nombre' : null, scope: 'col' }, t)))), corps))));
  main.querySelector('select[name=filtre]').addEventListener('change', (ev) => { filtre = ev.target.value; rendre(); });
  rendre();
}

function selectPrestataire(b, modifiable) {
  const memeMetier = b.prestataires.filter((p) => p.metier === b.alerte.metier);
  const autres = b.prestataires.filter((p) => p.metier !== b.alerte.metier);
  return h('select', { name: 'prestataire_id', disabled: !modifiable },
    h('option', { value: '' }, b.prestataire_id ? '' : '— choisir —'),
    memeMetier.length ? h('optgroup', { label: 'Métier : ' + (b.alerte.metier || '') },
      memeMetier.map((p) => h('option', { value: p.id, selected: p.id === b.prestataire_id }, `${p.nom} (${p.email})`))) : null,
    autres.length ? h('optgroup', { label: 'Autres prestataires' },
      autres.map((p) => h('option', { value: p.id, selected: p.id === b.prestataire_id }, `${p.nom} · ${p.metier}`))) : null);
}

export async function ouvrirBon(id, ctx) {
  const b = await tenter(() => api('GET', '/api/bons/' + id));
  if (!b) return;
  const modifiable = b.statut === 'brouillon';
  const ro = modifiable ? {} : { readonly: true };
  const choixPrest = selectPrestataire(b, modifiable);
  const destinataire = h('input', { type: 'email', name: 'destinataire', value: b.destinataire || '', ...ro });
  const objet = saisie('objet', b.objet, ro);
  const corps = h('textarea', { name: 'corps', rows: '16', ...ro }, b.corps);
  choixPrest.addEventListener('change', () => {
    const p = b.prestataires.find((x) => String(x.id) === choixPrest.value);
    if (p) destinataire.value = p.email;
  });
  const a = b.alerte;
  const contenu = h('div', { class: 'pile' },
    h('div', { class: 'ligne-tags' },
      chipStatut(b.statut), a.gravite ? chip(a.gravite) : null, a.fluide ? tagFluide(a.fluide) : null,
      h('span', { class: 'doux lien-immeuble' }, icone('immeuble'), `${b.immeuble || ''} · ${a.adresse || ''}`)),
    h('div', { class: 'resume-import' },
      h('div', {}, h('div', { class: 'doux petit' }, 'Enjeu chiffré'), h('b', {}, enjeu(a).principal),
        h('div', { class: 'doux petit' }, enjeu(a).precisions.slice(0, 2).join(' · '))),
      h('div', {}, h('div', { class: 'doux petit' }, 'Imputation'), h('b', {}, a.payeur || '—')),
      h('div', {}, h('div', { class: 'doux petit' }, 'Délai demandé'), h('b', {}, a.delai || '—')),
      h('div', {}, h('div', { class: 'doux petit' }, 'Dérive'),
        h('b', {}, b.alerte_statut === 'resolue' ? 'Disparue des mesures' : 'Toujours mesurée'))),
    choixDestinataire(b, id, ctx),
    retourIncident(b, id, ctx),
    h('div', { class: 'formulaire' },
      champ('Prestataire', choixPrest, b.prestataire
        ? `${b.prestataire} · ${b.prestataire_metier}${b.prestataire_tel ? ' · ' + b.prestataire_tel : ''}`
        : `Aucun prestataire « ${a.metier || ''} » pour cet immeuble : choisissez-en un.`),
      champ('Destinataire (e-mail)', destinataire)),
    champ('Objet', objet),
    champ('Message au prestataire', corps, 'Les chiffres proviennent du moteur de détection. L\'enjeu en CHF et l\'imputation restent internes.'),
    h('div', {}, h('h3', {}, 'Historique'), h('ul', { class: 'journal' },
      b.journal.map((j) => h('li', {}, h('time', {}, fmt.dateHeure(j.le)), h('span', {}, j.texte))))));

  const enregistrer = async () => {
    if (choixPrest.value && Number(choixPrest.value) !== b.prestataire_id) {
      await api('PUT', '/api/bons/' + id, { prestataire_id: Number(choixPrest.value) });
    }
    const d = { objet: objet.value, corps: corps.value };
    if (destinataire.value) d.destinataire = destinataire.value;
    return api('PUT', '/api/bons/' + id, d);
  };
  const changer = (statut, texte, avantTout) => ({ texte, action: async () => {
    const ok = await tenter(async () => {
      if (avantTout) await avantTout();
      return api('PUT', '/api/bons/' + id, { statut });
    }, 'Bon mis à jour.');
    if (ok) await ctx.recharger();
    return !!ok;
  } });
  const boutons = [];
  if (['brouillon', 'envoye', 'en_cours', 'retour'].includes(b.statut)) {
    boutons.push({ texte: 'Annuler le bon', classe: 'danger', action: async () => {
      if (!await confirmer('Annuler ce bon ?', `Le bon ${b.numero} sera classé comme annulé (il reste dans l'historique).`,
        'Annuler le bon', true)) return false;
      const ok = await tenter(() => api('PUT', '/api/bons/' + id, { statut: 'annule' }), 'Bon annulé.');
      if (ok) await ctx.recharger();
      return !!ok;
    } });
  }
  if (modifiable) {
    boutons.push({ texte: 'Enregistrer', action: async () => !!(await tenter(enregistrer, 'Bon enregistré.')) });
    boutons.push({ texte: 'Télécharger pour Outlook (.eml)', action: async () => {
      await tenter(async () => {
        await enregistrer();
        const rep = await api('GET', `/api/bons/${id}/eml`, undefined, { brut: true });
        telecharger(await rep.blob(), b.numero + '.eml');
      }, 'Courriel téléchargé : ouvrez-le, vérifiez, envoyez-le, puis marquez le bon comme envoyé.');
      return false;
    } });
    boutons.push(changer('envoye', 'Marquer comme envoyé', enregistrer));
    boutons.push({ texte: 'Envoyer par e-mail', classe: 'primaire', action: async () => {
      if (!ctx.etat.smtp_configure) {
        toast('Messagerie non configurée : téléchargez le courriel pour Outlook, ou configurez l\'envoi dans Réglages.', true);
        return false;
      }
      const enregistre = await tenter(enregistrer);
      if (!enregistre) return false;
      if (!await confirmer('Envoyer le bon ?', `Le bon ${b.numero} va être envoyé à ${enregistre.destinataire}.`, 'Envoyer')) return false;
      const ok = await tenter(() => api('POST', `/api/bons/${id}/envoyer`), `Bon ${b.numero} envoyé.`);
      if (ok) await ctx.recharger();
      return !!ok;
    } });
  } else if (b.statut === 'envoye') {
    boutons.push(changer('en_cours', 'Intervention en cours'), changer('termine', 'Intervention terminée'));
  } else if (b.statut === 'retour') {
    boutons.push(changer('en_cours', 'Nouvelle intervention'), changer('termine', 'Clôturer le bon'));
  } else if (b.statut === 'en_cours') {
    boutons.push(changer('termine', 'Intervention terminée'));
  }
  dialogue(`Bon de travaux ${b.numero}`, contenu, boutons, { large: true, texteFermer: 'Fermer' });
}


// ---------------------------------------------------------------- destinataire et retour d'incident

function choixDestinataire(b, id, ctx) {
  const possibles = b.destinataires || {};
  const ligne = (type, lib) => {
    const d = possibles[type];
    return h('label', { class: 'coche haut' },
      h('input', { type: 'radio', name: 'destinataire_type', value: type, checked: b.destinataire_type === type,
        disabled: !d || b.statut !== 'brouillon', onchange: () => tenter(async () => {
          await api('PUT', `/api/bons/${id}/destinataire`, { destinataire_type: type });
          document.querySelector('dialog')?.remove();
          await ouvrirBon(id, ctx);
        }, 'Destinataire modifié : message recomposé.') }),
      h('span', {}, h('span', { class: 'gras' }, lib), h('br', {}),
        h('span', { class: 'doux petit' }, d ? `${d.nom}${d.metier ? ' · ' + d.metier : ''} — ${d.email}` : 'aucun pour cet immeuble')));
  };
  return h('fieldset', { class: 'cadre' }, h('legend', { class: 'petit gras' }, 'Destinataire du bon'),
    h('div', { class: 'profils' }, ligne('concierge', 'Concierge de l\'immeuble'), ligne('partenaire', 'Partenaire technique')),
    b.statut !== 'brouillon' ? h('p', { class: 'doux petit' }, 'Bon déjà envoyé : destinataire figé.') : null);
}

function retourIncident(b, id, ctx) {
  if (!['envoye', 'en_cours', 'retour'].includes(b.statut)) return null;
  const resultat = liste('resultat', Object.entries(b.resultats_retour || {}), b.retour_resultat || 'resolu');
  const texte = h('textarea', { name: 'retour_texte', rows: 3, placeholder: 'Compte rendu du concierge ou du partenaire : '
    + 'ce qui a été constaté et fait sur place.' }, b.retour_texte || '');
  const enregistrer = () => tenter(async () => {
    await api('POST', `/api/bons/${id}/retour`, { resultat: resultat.value, texte: texte.value });
    document.querySelector('dialog')?.remove();
    await ctx.recharger();
  }, 'Retour d\'incident enregistré.');
  return h('fieldset', { class: 'cadre' }, h('legend', { class: 'petit gras' }, 'Retour d\'incident'),
    b.retour_le ? h('p', { class: 'petit' }, `Dernier retour le ${fmt.dateHeure(b.retour_le)} : `,
      h('span', { class: 'gras' }, (b.resultats_retour || {})[b.retour_resultat] || ''), ` — ${b.retour_texte}`) : null,
    h('div', { class: 'formulaire' }, champ('Résultat', resultat), champ('Compte rendu', texte, null, 'large')),
    h('div', { class: 'actions' }, h('button', { type: 'button', onclick: enregistrer }, 'Enregistrer le retour')));
}
