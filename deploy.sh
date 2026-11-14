#!/usr/bin/env bash
# Redéploie Xread Dérives sur https://xread-derive.brochardbenjamin.com
#
# Usage (Git Bash, depuis la racine du projet) :  ./deploy.sh
#
# Le VPS récupère la branche main depuis GitHub : poussez d'abord vos commits (git push).
# La base vigie.db, les données et les sorties du serveur ne sont jamais touchées (hors dépôt).
set -euo pipefail

SERVEUR="root@195.35.24.97"
URL="https://xread-derive.brochardbenjamin.com"

# Avertit si des commits locaux ne sont pas encore sur GitHub (ils ne seraient pas déployés)
git fetch -q origin main
if [ -n "$(git log origin/main..HEAD --oneline)" ]; then
  echo "Attention : commits locaux non poussés (non déployés). Faites 'git push' puis relancez."
  exit 1
fi

echo "→ Mise à jour du code et des dépendances sur le VPS…"
ssh "$SERVEUR" 'set -e
cd /var/www/xread-derive
sudo -u xread git pull --ff-only origin main
sudo -u xread .venv/bin/pip install -q -r requirements.txt
systemctl restart xread-derive
sleep 3
systemctl is-active xread-derive
git log --oneline -1'

echo "→ Vérification…"
code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/api/etat")
if [ "$code" = "200" ]; then
  echo "OK : $URL répond ($code)."
else
  echo "ERREUR : $URL répond $code. Journaux : ssh $SERVEUR journalctl -u xread-derive -n 50"
  exit 1
fi
