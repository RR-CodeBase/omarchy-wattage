#!/bin/bash
# Install Battery Watt Usage into Omarchy: register the plugin, place the bar widget, and
# start the background sampler.
#
# Safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="io.github.rr-codebase.wattage"
PLUGINS_DIR="$HOME/.config/omarchy/plugins"
SECTION="right"
WITH_SERVICE=1
BIN_LINK="$HOME/.local/bin/wattage"
COMPLETION="$HOME/.local/share/bash-completion/completions/wattage"

# ---- ownership of the files we place outside the plugin ---------------------
# These two paths are the only ones written into directories the plugin does
# not own, so they are the only ones it can collide with. Someone may already
# have their own `wattage` on PATH, or their own completion for something else of
# that name. Overwriting it here - or deleting it on --uninstall - would be
# taking a file that is not ours. Each is therefore checked before it is
# touched, and a collision is reported and left standing rather than settled in
# our favour.
CLI_NAME="wattage"
MANAGED_MARK="managed by $PLUGIN_ID"

tilde() { printf '%s' "${1/#$HOME/\~}"; }

# Ours if it is a symlink naming this plugin's CLI. The literal target is
# compared rather than the resolved one, so an --uninstall that runs after the
# plugin folder is already gone still recognises, and clears, its own link.
link_is_ours() {
  local target
  [[ -L $1 ]] || return 1
  target=$(readlink -- "$1" 2>/dev/null) || return 1
  [[ $target == "$CLI" || $target == */$PLUGIN_ID/bin/$CLI_NAME ]]
}

# Ours if it is a regular file - never a symlink pointing off somewhere else -
# carrying the marker line the shipped completion contains.
file_is_ours() {
  [[ -f $1 && ! -L $1 ]] && grep -qF -- "$MANAGED_MARK" "$1" 2>/dev/null
}

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

  --no-service       Do not install the sampler systemd user service
  --section <where>  Bar section for the widget (left|center|right) [right]
  --uninstall        Remove the service and the plugin
  -h, --help         This message
USAGE
}

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

uninstall() {
  echo
  echo "Removing Battery Watt Usage"
  CLI="$PLUGINS_DIR/$PLUGIN_ID/bin/wattage"
  [[ -x $CLI ]] || CLI="$SCRIPT_DIR/bin/wattage"
  "$CLI" quiet off >/dev/null 2>&1 || true
  "$CLI" service remove >/dev/null 2>&1 && ok "sampler removed"
  if link_is_ours "$BIN_LINK"; then
    rm -f "$BIN_LINK"; ok "removed $(tilde "$BIN_LINK")"
  elif [[ -e $BIN_LINK || -L $BIN_LINK ]]; then
    warn "left $(tilde "$BIN_LINK") alone - not ours to remove"
  fi
  if file_is_ours "$COMPLETION"; then
    rm -f "$COMPLETION"; ok "removed shell completion"
  elif [[ -e $COMPLETION || -L $COMPLETION ]]; then
    warn "left $(tilde "$COMPLETION") alone - not ours to remove"
  fi
  if [[ -d "$PLUGINS_DIR/$PLUGIN_ID" ]]; then
    omarchy plugin remove "$PLUGIN_ID" --yes >/dev/null 2>&1 || true
    ok "plugin removed"
  fi
  echo
  echo "  Your history is still at ~/.local/state/omarchy/wattage.db"
  echo
  exit 0
}

while (($#)); do
  case "$1" in
    --no-service) WITH_SERVICE=0; shift ;;
    --section) SECTION="${2:-right}"; shift 2 ;;
    --uninstall) uninstall ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

echo
echo "Installing Battery Watt Usage"
echo

command -v omarchy >/dev/null || die "Omarchy not found. This plugin needs Omarchy Quattro."
command -v python3 >/dev/null || die "python3 not found"

if compgen -G "/sys/class/power_supply/BAT*" >/dev/null; then
  ok "battery found"
else
  warn "no battery in /sys/class/power_supply - Battery Watt Usage has nothing to measure"
fi

if [[ -d "$PLUGINS_DIR/$PLUGIN_ID" ]]; then
  ok "plugin already registered"
else
  omarchy plugin validate "$SCRIPT_DIR" >/dev/null || die "manifest failed validation"
  git -C "$SCRIPT_DIR" rev-parse HEAD >/dev/null 2>&1 \
    || die "commit this repo first (omarchy plugin add clones it)"
  omarchy plugin add "$SCRIPT_DIR" --enable --yes >/dev/null || die "omarchy plugin add failed"
  ok "plugin added and enabled"
fi

omarchy bar put "$PLUGIN_ID" "$SECTION" >/dev/null 2>&1 \
  && ok "widget placed in the $SECTION section" \
  || echo "  widget already placed"

CLI="$PLUGINS_DIR/$PLUGIN_ID/bin/wattage"
[[ -x $CLI ]] || CLI="$SCRIPT_DIR/bin/wattage"

# The README documents `wattage ...` as a bare command, so put it on PATH. The
# script itself stays in the plugin; this is only a link to it.
if [[ -e $BIN_LINK || -L $BIN_LINK ]] && ! link_is_ours "$BIN_LINK"; then
  warn "$(tilde "$BIN_LINK") already exists and is not ours - left alone"
  warn "run it as $CLI, or move that file aside and re-run"
else
  mkdir -p "$(dirname "$BIN_LINK")"
  ln -sfn "$CLI" "$BIN_LINK"
  ok "wattage linked into $(tilde "$BIN_LINK")"
fi

# Only advertise the short form if it will actually resolve to us.
PRETTY_CLI="$CLI"
if link_is_ours "$BIN_LINK"; then
  case ":$PATH:" in
    *":${BIN_LINK%/*}:"*) PRETTY_CLI="$CLI_NAME" ;;
    *) warn "${BIN_LINK%/*} is not on your PATH - add it to use \`wattage\` directly" ;;
  esac
fi

if [[ -f $SCRIPT_DIR/completions/wattage ]]; then
  if [[ -e $COMPLETION || -L $COMPLETION ]] && ! file_is_ours "$COMPLETION"; then
    warn "$(tilde "$COMPLETION") already exists and is not ours - left alone"
  else
    mkdir -p "$(dirname "$COMPLETION")"
    # Staged and renamed rather than written in place: writing through whatever
    # happens to be sitting at the destination is the thing being avoided.
    install -m 0644 "$SCRIPT_DIR/completions/wattage" "$COMPLETION.new"
    mv -f "$COMPLETION.new" "$COMPLETION"
    ok "shell completion installed"
  fi
fi

if ((WITH_SERVICE)); then
  "$CLI" service install >/dev/null && ok "sampler started (every 20s, Nice 19)"
fi

echo
"$CLI" doctor || true
echo
echo "  Unplug for a few minutes, then:  $PRETTY_CLI top"
echo
