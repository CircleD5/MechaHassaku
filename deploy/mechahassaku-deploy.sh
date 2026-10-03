#!/bin/bash
# Auto deploy for MechaHassaku, run every few minutes by mechahassaku-deploy.timer (as root).
#   1. fetch origin/main; do nothing if unchanged
#   2. fast-forward the checkout, install requirements if they changed, run the unit tests
#   3. restart the bot and check it stays up; roll back to the previous commit if it does not
# A commit that failed is remembered and skipped until a newer commit arrives.
# Installed copy: /usr/local/bin/mechahassaku-deploy (the repo copy is the source of truth).
set -uo pipefail

# Overridable from the environment for testing on a scratch checkout
REPO=${REPO:-/home/000no/MechaHassaku}
RUN_AS=${RUN_AS:-000no}
BRANCH=${BRANCH:-main}
SERVICE=${SERVICE:-mechahassaku.service}
HEALTH_WAIT=${HEALTH_WAIT:-30}
STATE_DIR=${STATE_DIR:-/var/lib/mechahassaku-deploy}
FAILED_FILE=$STATE_DIR/failed_commit

as_user() { runuser -u "$RUN_AS" -- "$@"; }
log() { echo "[deploy] $*"; }

mkdir -p "$STATE_DIR"
exec 9>/run/lock/mechahassaku-deploy.lock
flock -n 9 || exit 0
cd "$REPO" || { log "repo not found: $REPO"; exit 1; }

as_user git fetch -q origin "$BRANCH" || { log "git fetch failed"; exit 1; }
OLD=$(as_user git rev-parse HEAD)
NEW=$(as_user git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && exit 0
if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$NEW" ]; then
    exit 0
fi

log "updating ${OLD:0:7} -> ${NEW:0:7}"

fail() {
    log "$1; staying on ${OLD:0:7}"
    as_user git reset -q --hard "$OLD"
    echo "$NEW" > "$FAILED_FILE"
    exit 1
}

as_user git merge -q --ff-only "$NEW" || fail "not a fast-forward (local changes on the server?)"

if as_user git diff --name-only "$OLD" "$NEW" | grep -qx requirements.txt; then
    log "requirements.txt changed, installing"
    as_user "$REPO/env/bin/pip" install -q -r requirements.txt || fail "pip install failed"
fi

if [ -d tests ]; then
    as_user "$REPO/env/bin/python" -m unittest discover -s tests -t . -q 2>&1 | tail -n 20
    [ "${PIPESTATUS[0]}" -eq 0 ] || fail "tests failed on ${NEW:0:7}"
fi

# The running bot keeps the old code in memory until this restart
systemctl restart "$SERVICE"
RESTARTS_BEFORE=$(systemctl show -p NRestarts --value "$SERVICE")
sleep "$HEALTH_WAIT"
RESTARTS_AFTER=$(systemctl show -p NRestarts --value "$SERVICE")

if systemctl is-active -q "$SERVICE" && [ "$RESTARTS_BEFORE" = "$RESTARTS_AFTER" ]; then
    rm -f "$FAILED_FILE"
    log "deployed ${NEW:0:7}"
    exit 0
fi

log "bot did not stay up on ${NEW:0:7}, rolling back"
as_user git reset -q --hard "$OLD"
systemctl reset-failed "$SERVICE"
systemctl restart "$SERVICE"
echo "$NEW" > "$FAILED_FILE"
exit 1
