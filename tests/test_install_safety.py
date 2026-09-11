#!/usr/bin/env python3
"""Tests for the two files Battery Watt Usage places outside its own folder.

Run: python3 tests/test_install_safety.py

`~/.local/bin/wattage` and the bash completion are the only paths install.sh
writes into directories it does not own, so they are the only ones where it can
collide with something of the user's. The rule is that neither is replaced or
deleted unless Battery Watt Usage can prove it created it, and these tests plant every
shape of collision that rule exists for - a stranger's regular file, a symlink
aimed somewhere else, a directory - then check the real helpers, lifted out of
install.sh itself, refuse each one.
"""

import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ID = "io.github.rr-codebase.wattage"
CLI_NAME = "wattage"
MARK = "managed by " + PLUGIN_ID

PASSED, FAILED = 0, []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("[PASS] " + name)
    else:
        FAILED.append(name + ((": " + detail) if detail else ""))
        print("[FAIL] " + name + ((" - " + detail) if detail else ""))


# ---- the ownership helpers, lifted out of the real install.sh ---------------
# Extracted rather than reimplemented: a copy in the test would happily keep
# passing after the shipped ones drifted.

SH = (ROOT / "install.sh").read_text()
_start = SH.index('CLI_NAME="')
_body = SH.index("file_is_ours() {", _start)
_end = SH.index("\n}\n", _body) + 3
HELPERS = SH[_start:_end]
check("the ownership helpers were found in install.sh",
      "link_is_ours" in HELPERS and "file_is_ours" in HELPERS)

SB = Path(tempfile.mkdtemp(prefix="wattage-install-safety-"))
PLUGIN = SB / ".config/omarchy/plugins" / PLUGIN_ID / "bin"
PLUGIN.mkdir(parents=True)
CLI = PLUGIN / CLI_NAME
CLI.write_text("#!/bin/sh\n")
CLI.chmod(0o755)


def probe(predicate, path):
    """Run one helper out of install.sh against one planted path."""
    script = "\n".join([
        "set -uo pipefail",
        "HOME=" + shlex.quote(str(SB)),
        "PLUGIN_ID=" + shlex.quote(PLUGIN_ID),
        "CLI=" + shlex.quote(str(CLI)),
        HELPERS,
        predicate + " " + shlex.quote(str(path)),
    ])
    return subprocess.run(["bash", "-c", script],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


# ---- link_is_ours: only a symlink naming our own CLI counts -----------------

cases = SB / "cases"
cases.mkdir()

check("an absent path is not ours to replace",
      not probe("link_is_ours", cases / "absent"))

stranger = cases / "stranger"
stranger.write_text("#!/bin/sh\necho someone else's script\n")
check("a stranger's regular file on PATH is not ours",
      not probe("link_is_ours", stranger))

elsewhere = cases / "elsewhere"
elsewhere.symlink_to("/bin/sh")
check("a symlink pointing somewhere else is not ours",
      not probe("link_is_ours", elsewhere))

adir = cases / "adir"
adir.mkdir()
check("a directory in the way is not ours", not probe("link_is_ours", adir))

ours = cases / "ours"
ours.symlink_to(CLI)
check("our own symlink is recognised", probe("link_is_ours", ours))

dangling = cases / "dangling"
dangling.symlink_to("/gone/" + PLUGIN_ID + "/bin/" + CLI_NAME)
check("our own symlink is still recognised once the plugin folder is gone",
      probe("link_is_ours", dangling),
      "otherwise --uninstall would strand its own dangling link")

# ---- file_is_ours: only a marked regular file counts ------------------------

shipped = ROOT / "completions" / CLI_NAME
check("the shipped completion carries the ownership marker",
      MARK in shipped.read_text(),
      "without it install.sh could never recognise its own file")

check("an absent completion is not ours to delete",
      not probe("file_is_ours", cases / "no-completion"))

unmarked = cases / "unmarked"
unmarked.write_text("# somebody else's completion\ncomplete -W 'a b' wattage\n")
check("an unmarked completion belonging to someone else is left alone",
      not probe("file_is_ours", unmarked))

marked = cases / "marked"
shutil.copyfile(shipped, marked)
check("a completion we installed is recognised", probe("file_is_ours", marked))

symmarked = cases / "symmarked"
symmarked.symlink_to(marked)
check("a symlink to a marked file is not treated as ours",
      not probe("file_is_ours", symmarked),
      "removing it would delete a link the user made deliberately")

# ---- and that install.sh actually routes through them -----------------------

check("install.sh guards the symlink it creates",
      '! link_is_ours "$BIN_LINK"' in SH)
check("install.sh guards the completion it installs",
      '! file_is_ours "$COMPLETION"' in SH)
check("install.sh stages the completion in an exclusive temporary file",
      'mktemp "${COMPLETION%/*}/' in SH and 'mv -f "$tmp" "$COMPLETION"' in SH)
check("install.sh no longer uses a predictable staging name",
      'install -m 0644 "$SCRIPT_DIR/completions/' not in SH,
      "a fixed $COMPLETION.new can be pre-created as a symlink or a FIFO")
check("uninstall proves ownership before removing the symlink",
      re.search(r'if link_is_ours "\$BIN_LINK"; then\s+rm -f', SH) is not None)
check("uninstall proves ownership before removing the completion",
      re.search(r'if file_is_ours "\$COMPLETION"; then\s+rm -f', SH) is not None)
check("uninstall no longer deletes on mere existence",
      '[[ -L $BIN_LINK || -f $BIN_LINK ]] && { rm -f' not in SH)

# ---- the systemd unit, which lives under the same rule ----------------------

import importlib.machinery
import importlib.util

loader = importlib.machinery.SourceFileLoader("wattage_unit", str(ROOT / "bin/wattage"))
spec = importlib.util.spec_from_loader(loader.name, loader)
wattage = importlib.util.module_from_spec(spec)
loader.exec_module(wattage)

units = SB / "units"
units.mkdir()

CANON_CLI = "/home/someone/.config/omarchy/plugins/" + PLUGIN_ID + "/bin/wattage"

check("an absent unit reads as absent, not as somebody else's",
      wattage.unit_is_ours(units / "wattage.service", CANON_CLI) is None)

foreign_unit = units / "foreign.service"
foreign_unit.write_text("[Service]\nExecStart=/usr/bin/something-else\n")
check("a unit somebody else wrote is refused",
      wattage.unit_is_ours(foreign_unit, CANON_CLI) is False)

symunit = units / "sym.service"
symunit.symlink_to(foreign_unit)
check("a symlinked unit is refused rather than followed",
      wattage.unit_is_ours(symunit, CANON_CLI) is False)

marked_unit = units / "marked.service"
marked_unit.write_text(wattage.UNIT_MARK + "\n[Service]\nExecStart=/x\n")
check("a unit we wrote is recognised by its marker",
      wattage.unit_is_ours(marked_unit, CANON_CLI) is True)

buried = units / "buried.service"
buried.write_text("[Service]\nExecStart=/usr/bin/other\n" + wattage.UNIT_MARK + "\n")
check("a foreign unit quoting the marker further down is not ours",
      wattage.unit_is_ours(buried, CANON_CLI) is False,
      "the marker is only a claim on the first line, where we write it")

legacy_unit = units / "legacy.service"
legacy_unit.write_text(wattage.unit_body(CANON_CLI, wattage.LEGACY_UNIT_DESCRIPTION))
check("a marker-less 0.1.0 unit for this install is recognised as ours",
      wattage.unit_is_ours(legacy_unit, CANON_CLI) is True,
      "otherwise an upgrade would refuse to touch its own unit")

# The finding: an ExecStart that merely *ends* with the right words is not
# proof. /opt/custom/bin/wattage is a different program with the same basename.
impostor = units / "impostor.service"
impostor.write_text(
    wattage.unit_body("/opt/custom/bin/wattage", wattage.LEGACY_UNIT_DESCRIPTION))
check("a foreign CLI with the same basename is not accepted as ours",
      wattage.unit_is_ours(impostor, CANON_CLI) is False,
      "/opt/custom/bin/wattage sample --daemon must not look like our unit")

edited = units / "edited.service"
edited.write_text(
    wattage.unit_body(CANON_CLI, wattage.LEGACY_UNIT_DESCRIPTION).replace("Nice=19", "Nice=0"))
check("a marker-less unit the user has edited is left alone",
      wattage.unit_is_ours(edited, CANON_CLI) is False,
      "only the exact contents 0.1.0 wrote count as proof")

renamed_desc = units / "renamed.service"
renamed_desc.write_text(wattage.unit_body(CANON_CLI, wattage.UNIT_DESCRIPTION))
check("a marker-less unit carrying the current description is not ours either",
      wattage.unit_is_ours(renamed_desc, CANON_CLI) is False,
      "every unit this version writes is marked, so an unmarked one is not ours")

src = (ROOT / "bin/wattage").read_text()
check("the unit is staged in an exclusive temporary file",
      "tempfile.mkstemp(" in src and 'prefix=".wattage.service."' in src)
check("the staged unit is renamed into place",
      "os.replace(tmpname, unit)" in src)
check("the unit no longer uses a predictable staging name",
      'unit_dir / "wattage.service.new"' not in src,
      "a fixed name can be pre-created as a symlink or a FIFO")
check("the staging descriptor is checked before it is written through",
      "os.fstat(fh.fileno())" in src and "stat.S_ISREG(st.st_mode)" in src)
check("the unit is opened no-follow", "os.O_NOFOLLOW" in src)
check("service install refuses a unit that is not ours",
      "if unit_is_ours(unit, cli) is False:" in src)
check("service remove leaves a unit that is not ours alone",
      "owned = unit_is_ours(unit, cli)" in src)

# ---- report -----------------------------------------------------------------

shutil.rmtree(SB, ignore_errors=True)
print("\n%d passed, %d failed" % (PASSED, len(FAILED)))
for f in FAILED:
    print("  FAIL  " + f)
sys.exit(1 if FAILED else 0)
