#!/bin/sh
# Copie le code partage vers le depot de l'add-on Home Assistant.
# Source unique : ce depot. La CI de l'add-on verifie que les copies
# sont identiques a la branche main de Minitel-HA.
#
#   tools/sync_addon.sh [dossier minitel-ha de l'add-on]
set -e
SRC=$(cd "$(dirname "$0")/.." && pwd)
DST=${1:-$SRC/../Minitel-HA-addon/minitel-ha}
FILES="alerts.py devices.py discover.py ha_client.py ha_live.py hub.py i18n.py
journal.py pagehtml.py pagevideo.py server.py session.py settings.py utils.py
ws_browser.py ws_minitel.py requirements.txt static/index.html"

mkdir -p "$DST/static"
for f in $FILES; do
  cp "$SRC/$f" "$DST/$f"
done
printf '%s\n' $FILES > "$DST/SHARED_FILES"
echo "OK : $(printf '%s\n' $FILES | wc -l) fichiers copies vers $DST"
