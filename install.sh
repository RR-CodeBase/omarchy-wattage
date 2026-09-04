#!/bin/bash
# Install Wattage into Omarchy: register the plugin, place the bar widget, and
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
  echo "Removing Wattage"
  CLI="$PLUGINS_DIR/$PLUGIN_ID/bin/wattage"
  [[ -x $CLI ]] || CLI="$SCRIPT_DIR/bin/wattage"
  "$CLI" quiet off >/dev/null 2>&1 || true
  "$CLI" service remove >/dev/null 2>&1 && ok "sampler removed"
  [[ -L $BIN_LINK || -f $BIN_LINK ]] && { rm -f "$BIN_LINK"; ok "removed ${BIN_LINK/#$HOME/\~}"; }
  [[ -f $COMPLETION ]] && { rm -f "$COMPLETION"; ok "removed shell completion"; }
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
echo "Installing Wattage"
echo

command -v omarchy >/dev/null || die "Omarchy not found. This plugin needs Omarchy Quattro."
command -v python3 >/dev/null || die "python3 not found"

if compgen -G "/sys/class/power_supply/BAT*" >/dev/null; then
  ok "battery found"
else
  warn "no battery in /sys/class/power_supply - Wattage has nothing to measure"
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
mkdir -p "$(dirname "$BIN_LINK")"
ln -sfn "$CLI" "$BIN_LINK"
ok "wattage linked into ${BIN_LINK/#$HOME/\~}"
# Only advertise the short form if it will actually resolve.
PRETTY_CLI="$CLI"
case ":$PATH:" in
  *":${BIN_LINK%/*}:"*) PRETTY_CLI="wattage" ;;
  *) warn "${BIN_LINK%/*} is not on your PATH - add it to use \`wattage\` directly" ;;
esac

if [[ -f $SCRIPT_DIR/completions/wattage ]]; then
  mkdir -p "$(dirname "$COMPLETION")"
  install -m 0644 "$SCRIPT_DIR/completions/wattage" "$COMPLETION"
  ok "shell completion installed"
fi

if ((WITH_SERVICE)); then
  "$CLI" service install >/dev/null && ok "sampler started (every 20s, Nice 19)"
fi

echo
"$CLI" doctor || true
echo
echo "  Unplug for a few minutes, then:  $PRETTY_CLI top"
echo
