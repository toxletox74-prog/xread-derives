// Carte du parc : liste des adresses (à gauche) et carte swisstopo (à droite), points colorés selon la criticité.
// Leaflet (vigie/web/leaflet.js, BSD-2) est chargé par index.html ; seules les tuiles viennent de wmts.geo.admin.ch.
import { api, h, vider, fmt, tenter, dialogue, champ, saisie, PROFILS } from './outils.js';
import { icone, pastilleFluide, titreIcone } from './icones.js';

export const ETATS = {
  Critique: { couleur: '#B42318', libelle: 'Critique', classe: 'pe-critique' },
  Élevée: { couleur: '#D97706', libelle: 'Élevée', classe: 'pe-elevee' },
  Modérée: { couleur: '#2563EB', libelle: 'Modérée', classe: 'pe-moderee' },
  Données: { couleur: '#6B7280', libelle: 'Problème de données', classe: 'pe-donnees' },
  Attente: { couleur: '#7C3AED', libelle: 'Compteur à connecter', classe: 'pe-attente' }, // violet : distinct de « Élevée »
  OK: { couleur: '#16A34A', libelle: 'Sans dérive', classe: 'pe-ok' },
};
const GENEVE = [46.2044, 6.1432];
const FONDS = {
  'Plan couleur (swisstopo)': 'ch.swisstopo.pixelkarte-farbe',
  'Plan gris (swisstopo)': 'ch.swisstopo.pixelkarte-grau',
  'Photo aérienne (swisstopo)': 'ch.swisstopo.swissimage',
};
let carteActive = null; // une seule carte Leaflet à la fois (libérée à chaque nouvel affichage)
// Position d'une adresse sur la carte (coordonnées GPS de la base ; celles d'un site fictif viennent du plan du jeu)
const position = (ad) => (ad.lat === null || ad.lat === undefined ? null : [ad.lat, ad.lon]);

const point = (etat, petit = false) => h('span', { class: `point-etat ${ETATS[etat].classe}${petit ? ' petit-point' : ''}`,
  'aria-hidden': 'true' });

function infobulle(ad) {
  return h('div', { class: 'infobulle' },
    h('div', { class: 'gras' }, ad.rue), h('div', { class: 'doux petit' }, ad.npa_localite),
    ad.immeubles.map((im) => h('div', { class: 'infobulle-immeuble' },
      h('div', {}, point(im.etat, true), ' ', h('span', { class: 'gras' }, im.nom),
        h('span', { class: 'doux petit' }, ` · ${PROFILS[im.profil] || im.profil}`)),
      im.alertes.length
        ? h('ul', {}, im.alertes.map((a) => h('li', {},
          pastilleFluide(a.gravite === 'Données' ? 'donnees' : a.fluide, { taille: 'xs' }), h('span', {}, `${a.gravite} — ${a.titre}`,
            a.chf_mois ? h('span', { class: 'doux' }, ` (≈ ${fmt.n0(a.chf_mois)} CHF/mois)`) : null))))
        : h('div', { class: 'doux petit' }, im.etat === 'Attente' ? 'Compteur(s) pas encore connecté(s)' : 'Aucune dérive en cours'))),
    position(ad) ? h('div', { class: 'doux petit' }, `GPS ${ad.lat.toFixed(5)}, ${ad.lon.toFixed(5)}`) : null,
    ad.geo_source && ad.geo_source !== 'geo.admin.ch'
      ? h('div', { class: 'doux petit' }, ad.geo_source === 'manuel' ? 'Position saisie à la main' : (ad.geo_label || '')) : null);
}

function fenetre(ad) {
  return h('div', { class: 'infobulle' }, h('div', { class: 'gras' }, `${ad.rue}, ${ad.npa_localite}`),
    ad.immeubles.map((im) => h('div', {}, point(im.etat, true), ' ',
      h('a', { href: '#/immeuble/' + encodeURIComponent(im.id) }, im.nom),
      h('span', { class: 'doux petit' }, im.alertes.length ? ` · ${im.alertes.length} alerte(s)` : ''))));
}

function saisirCoordonnees(ad, ctx) {
  const lat = saisie('lat', ad.lat ?? '', { placeholder: '46.2038' });
  const lon = saisie('lon', ad.lon ?? '', { placeholder: '6.1495' });
  dialogue(`Position de ${ad.rue}`, h('div', { class: 'formulaire' },
    h('p', { class: 'large doux' }, 'Adresse introuvable par le géocodeur fédéral (adresse nouvelle, mal orthographiée ou '
      + 'fictive). Saisissez la position GPS, par exemple relevée sur map.geo.admin.ch (clic droit sur le bâtiment).'),
    champ('Latitude', lat), champ('Longitude', lon)), [{
    texte: 'Enregistrer', classe: 'primaire', action: async () => !!(await tenter(async () => {
      await api('PUT', `/api/adresses/${encodeURIComponent(ad.id)}/coordonnees`, { lat: lat.value, lon: lon.value });
      await ctx.recharger();
    }, 'Position enregistrée.')),
  }]);
}

export async function carteParc(ctx) {
  const donnees = await api('GET', '/api/carte');
  const marqueurs = {};
  const zoneCarte = h('div', { class: 'carte-geo', role: 'region', 'aria-label': 'Carte des immeubles du canton de Genève' });
  const elementListe = (ad) => {
    const localise = position(ad) !== null;
    const rang = Object.keys(ETATS);
    const pire = ad.immeubles.flatMap((im) => im.alertes)
      .sort((a, b) => rang.indexOf(a.gravite) - rang.indexOf(b.gravite) || b.chf_mois - a.chf_mois)[0];
    return h('li', {},
      h('button', { type: 'button', class: 'adresse-ligne', 'aria-label': `${ad.rue}, ${ETATS[ad.etat].libelle}`,
        onclick: () => {
          if (!localise) return saisirCoordonnees(ad, ctx);
          carteActive.flyTo(position(ad), 16, { duration: 0.6 });
          marqueurs[ad.id].openTooltip();
          return null;
        } },
      point(ad.etat),
      h('span', { class: 'adresse-texte' },
        h('span', { class: 'gras' }, ad.rue),
        h('span', { class: 'doux petit' }, `${ad.npa_localite} · ${ad.immeubles.map((i) => i.nom).join(', ')}`),
        pire ? h('span', { class: 'petit alerte-mini' }, pastilleFluide(pire.gravite === 'Données' ? 'donnees' : pire.fluide,
          { taille: 'xs' }), `${pire.gravite} — ${pire.titre}`)
          : h('span', { class: 'petit doux' }, ETATS[ad.etat].libelle),
        localise ? null : h('span', { class: 'chip g-Attente' }, 'non localisée — cliquer pour placer'))));
  };
  const actions = donnees.non_localisees ? h('div', { class: 'banniere attention' },
    h('span', {}, `${donnees.non_localisees} adresse(s) non localisée(s).`),
    h('button', { type: 'button', onclick: () => tenter(async () => {
      const r = await api('POST', '/api/geocoder');
      await ctx.recharger();
      return r;
    }, (r) => `${r.localisees.length} adresse(s) localisée(s)`
      + (r.introuvables.length ? `, ${r.introuvables.length} introuvable(s) : placez-les à la main.` : '.')) },
    icone('adresse'), 'Localiser les adresses')) : null;
  const section = h('section', { class: 'carte', 'aria-labelledby': 't-carte' },
    h('div', { class: 'carte-tete' }, h('div', { class: 'titres' }, titreIcone('carte', 'h2', { id: 't-carte' }, 'Carte du parc'),
      h('span', { class: 'doux petit' }, 'Couleur = problème le plus grave de l\'adresse. Survolez un point pour voir les '
        + 'problèmes ; cliquez pour ouvrir l\'immeuble. Fonds et calques en haut à droite de la carte.')),
    h('a', { href: '#/parc', class: 'petit' }, 'Gérer le parc')),
    actions ? h('div', { class: 'carte-corps' }, actions) : null,
    h('div', { class: 'carte-split' },
      h('div', { class: 'carte-liste' }, h('ol', { class: 'liste-adresses' }, donnees.adresses.map(elementListe))),
      h('div', { class: 'carte-droite' }, zoneCarte,
        h('div', { class: 'legende' }, Object.entries(ETATS).map(([etat, e]) => h('span', {}, point(etat, true), ' ',
          e.libelle, h('span', { class: 'doux' }, ` (${donnees.adresses.filter((a) => a.etat === etat).length})`)))))),
    h('p', { class: 'doux petit carte-source' }, 'Fond de carte © swisstopo · '
      + (donnees.plan_reporte ? `${donnees.plan_reporte} site(s) d'un jeu de données fictif : coordonnées GPS calculées `
        + 'depuis le plan du jeu (milieu du plan posé sur Carouge – Plainpalais) et enregistrées. Positions fictives, '
        + 'aucune adresse transmise.'
        : 'coordonnées : géocodeur fédéral (geo.admin.ch), auquel seules les adresses sont transmises.')));
  section.monter = () => monterCarte(zoneCarte, donnees, marqueurs);
  return section;
}

function monterCarte(zone, donnees, marqueurs) {
  const L = window.L;
  if (!L) {
    vider(zone, h('div', { class: 'vide' }, 'Bibliothèque de carte non chargée.'));
    return;
  }
  if (carteActive) carteActive.remove();
  const fonds = Object.fromEntries(Object.entries(FONDS).map(([nom, couche]) => [nom,
    L.tileLayer(`${donnees.tuiles}/1.0.0/${couche}/default/current/3857/{z}/{x}/{y}.jpeg`, {
      maxZoom: 19, maxNativeZoom: 18, attribution: '© swisstopo' })]));
  const calques = Object.fromEntries(Object.keys(ETATS).map((etat) => [etat, L.layerGroup()]));
  carteActive = L.map(zone, { center: GENEVE, zoom: 11, layers: [fonds['Plan couleur (swisstopo)']] });
  carteActive.attributionControl.setPrefix(false);
  const points = [];
  for (const ad of donnees.adresses) {
    const p = position(ad);
    if (p === null) continue;
    const m = L.circleMarker(p, { radius: 9, weight: 2, color: '#FFFFFF',
      fillColor: ETATS[ad.etat].couleur, fillOpacity: 0.95 })
      .bindTooltip(infobulle(ad), { direction: 'auto', offset: [10, 0], opacity: 1 })
      .bindPopup(fenetre(ad));
    m.addTo(calques[ad.etat]);
    marqueurs[ad.id] = m;
    points.push(p);
  }
  Object.values(calques).forEach((c) => c.addTo(carteActive));
  // Libellés des calques : texte fixe du programme (aucune donnée importée), pastille par classe CSS
  const titres = Object.fromEntries(Object.entries(calques).map(([etat, c]) => {
    const n = donnees.adresses.filter((a) => a.etat === etat && position(a) !== null).length;
    return [`<span class="point-etat petit-point ${ETATS[etat].classe}"></span> ${ETATS[etat].libelle} (${n})`, c];
  }));
  // Écran étroit : sélecteur replié derrière un bouton « Calques » pour ne pas masquer la carte
  L.control.layers(fonds, titres, { collapsed: zone.clientWidth < 640, position: 'topright' }).addTo(carteActive);
  L.control.scale({ imperial: false }).addTo(carteActive);
  if (points.length > 1) carteActive.fitBounds(points, { padding: [40, 40], maxZoom: 15 });
  else if (points.length === 1) carteActive.setView(points[0], 15);
}
