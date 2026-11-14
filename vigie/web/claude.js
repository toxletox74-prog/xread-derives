// Claude (MCP) : clé du serveur MCP de la base principale et commandes de branchement (serveur : espaces.py, POST /mcp).
// Réservé à une personne connectée ; la clé n'est montrée qu'une fois, à sa création.
import { api, h, vider, tenter, dialogue, confirmer, toast } from './outils.js';

let compteur = 0;

// Texte à copier : zone en lecture seule (sélection au clic) et bouton « Copier »
function copiable(libelle, texte, aide) {
  const id = 'claude-' + (++compteur);
  const zone = texte.includes('\n')
    ? h('textarea', { id, readonly: true, spellcheck: 'false', rows: texte.split('\n').length }, texte)
    : h('input', { id, type: 'text', readonly: true, spellcheck: 'false', value: texte });
  zone.addEventListener('focus', () => zone.select());
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(texte);
      toast('Copié dans le presse-papiers.');
    } catch {
      zone.focus();
      toast('Copie impossible ici : le texte est sélectionné, faites Ctrl+C.', true);
    }
  };
  return h('div', { class: 'champ' }, h('label', { for: id }, libelle), zone,
    h('div', { class: 'actions' }, h('button', { type: 'button', onclick: copier }, 'Copier'),
      aide ? h('span', { class: 'aide' }, aide) : null));
}

function branchements(url, cle) {
  const desktop = JSON.stringify({ mcpServers: { 'xread-derives': {
    command: 'npx', args: ['mcp-remote', url, '--header', 'Authorization:${AUTH}'], env: { AUTH: 'Bearer ' + cle },
  } } }, null, 2);
  return h('div', { class: 'pile' },
    h('div', { class: 'banniere ok' }, h('span', {}, 'Clé créée. Copiez-la maintenant : elle ne sera plus affichée. '
      + 'Une nouvelle clé remplace celle-ci.')),
    copiable('Clé API', cle),
    copiable('Claude Code (terminal)',
      `claude mcp add --transport http xread-derives ${url} --header "Authorization: Bearer ${cle}"`),
    copiable('Claude Desktop (claude_desktop_config.json)', desktop,
      'Passe par mcp-remote (Node.js requis). Redémarrez Claude Desktop après l\'enregistrement.'));
}

export async function dialogueClaude() {
  const etat = await tenter(() => api('GET', '/api/mcp'));
  if (!etat) return;
  const url = location.origin + etat.chemin;
  const zone = h('div', { class: 'pile' });
  const corps = h('div', { class: 'pile' },
    h('p', {}, 'Branchez Claude sur ce parc : il interroge le moteur de dérives en lecture seule (alertes, parc, '
      + 'immeubles, règles, bons) et cite les chiffres calculés par Vigie. Il ne peut rien modifier.'),
    h('div', { class: 'banniere attention' }, h('span', {},
      'Ce que Claude lit (alertes, adresses, montants) part vers le service d\'Anthropic. À n\'activer que si le '
      + 'détenteur des données l\'accepte.')),
    copiable('Adresse du serveur MCP', url),
    zone);
  const afficherEtat = (creee) => vider(zone, h('p', { class: 'doux petit' }, creee
    ? `Une clé est active depuis le ${new Date(creee).toLocaleString('fr-CH')}. Elle n'est plus lisible : générez-en une `
      + 'nouvelle pour la recopier (l\'ancienne cessera de fonctionner).'
    : 'Aucune clé active.'));
  afficherEtat(etat.cle_creee);

  let active = !!etat.cle_creee;
  const { el } = dialogue('Claude (MCP)', corps, [
    { texte: 'Révoquer la clé', classe: 'danger', action: async () => {
      if (!active) { toast('Aucune clé active.'); return false; }
      if (!await confirmer('Révoquer la clé', 'Claude ne pourra plus interroger ce parc avec cette clé.', 'Révoquer', true)) {
        return false;
      }
      if (await tenter(() => api('DELETE', '/api/mcp/cle'), 'Clé révoquée.')) { active = false; afficherEtat(null); }
      return false;
    } },
    { texte: 'Générer une clé', classe: 'primaire', action: async () => {
      if (active && !await confirmer('Nouvelle clé', 'La clé actuelle cessera aussitôt de fonctionner.', 'Remplacer')) {
        return false;
      }
      const r = await tenter(() => api('POST', '/api/mcp/cle'));
      if (r) { active = true; vider(zone, branchements(url, r.cle)); }
      return false;
    } },
  ], { large: true, texteFermer: 'Fermer' });
  return el;
}
