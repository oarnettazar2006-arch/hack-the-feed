#!/bin/zsh
# Collecte presse, YouTube et site Brut (gratuite, sans appel à Claude). Lancée par cron à 8h et 20h
# jusqu'au hackathon, pour accumuler l'historique que les flux RSS ne gardent qu'un ou deux jours.
cd "$(dirname "$0")/../pipeline" || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> ../data/logs/collect_media.log
../.venv/bin/python -m htf.cli media >> ../data/logs/collect_media.log 2>&1
