#!/bin/zsh
# Relevé des sondages présidentielle 2027 (Wikipédia), gratuit : garde l'historique (data/polls/, cache local
# et table Supabase `sondages`). Wikipédia est mis à jour par ses contributeurs à chaque publication d'un
# institut, en général dans la journée. À lancer toutes les 6 h par cron.
cd "$(dirname "$0")/../pipeline" || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> ../data/logs/sondages.log
../.venv/bin/python -m htf.cli polls --export >> ../data/logs/sondages.log 2>&1
../.venv/bin/python -m htf.cli visuels >> ../data/logs/sondages.log 2>&1
