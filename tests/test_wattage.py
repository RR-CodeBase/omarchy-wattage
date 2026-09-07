#!/usr/bin/env python3
"""Tests for Battery Watt Usage's attribution model.

Run: python3 tests/test_wattage.py

The machine these tests run on is usually plugged in, and the interesting
behaviour only happens on battery, so the system layer is faked: a scripted
battery that discharges at a known rate and a scripted set of processes that
burn a known number of jiffies. That makes the attribution arithmetic
checkable against numbers worked out by hand, which is the only way to know
the watts this thing reports mean anything.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

tmp = Path(tempfile.mkdtemp(prefix="wattage-test-"))
os.environ["XDG_CONFIG_HOME"] = str(tmp / "config")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
os.environ["WATTAGE_DB"] = str(tmp / "wattage.db")

_loader = importlib.machinery.SourceFileLoader("wattage", str(ROOT / "bin" / "wattage"))
wattage = importlib.util.module_from_spec(importlib.util.spec_from_loader("wattage", _loader))
_loader.exec_module(wattage)

TICK = wattage.CLK_TCK
PASSED, FAILED = 0, []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}{(': ' + detail) if detail else ''}")


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---- cgroup -> app name, against strings taken off a running machine -------

CGROUPS = {
    "app-ghostty-surface-transient-135447.scope": "ghostty",
    "app-ghostty-surface-transient-837320.scope": "ghostty",
    "app-Hyprland-brave-ec06e741.scope": "brave",
    "app-Hyprland-hyprsunset-5a4cf7ec.scope": "hyprsunset",
    "app-Hyprland-udiskie-7e48f5f6.scope": "udiskie",
    "app-Hyprland-xdg\\x2dterminal\\x2dexec-94b95655.scope": "xdg-terminal-exec",
    "app-Hyprland-omarchy\\x2dhyprland\\x2dmonitor\\x2dwatch-58277e9c.scope":
        "omarchy-hyprland-monitor-watch",
    "app-org.chromium.Chromium-2053133.scope": "Chromium",
    "app-1password-1326.scope": "1password",
    "app-1password@autostart.service": "1password",
    "app-jetbrains\\x2dtoolbox@autostart.service": "jetbrains-toolbox",
    "app-Hyprland-gtk\\x2dlaunch-438cd9d8.scope (deleted)": "gtk-launch",
}
for leaf, expected in CGROUPS.items():
    got = wattage.app_from_cgroup(f"0::/user.slice/user-1000.slice/user@1000.service/app.slice/{leaf}")
    check(f"cgroup {leaf[:44]}", got == expected, f"got {got!r}, wanted {expected!r}")

# Things that are not an app scope must fall through to the process name.
for leaf in ["wayland-wm@hyprland.desktop.service",
             "dbus-:1.22-org.a11y.atspi.Registry@0.service",
             "session.slice", "", "init.scope"]:
    check(f"non-app cgroup {leaf[:36]!r} -> None",
          wattage.app_from_cgroup(f"0::/user.slice/{leaf}") is None,
          str(wattage.app_from_cgroup(f"0::/user.slice/{leaf}")))

# ---- the attribution arithmetic -------------------------------------------
# 10 W of active draw over 3600s, split between two processes that burned 3
# and 1 CPU-seconds: 7.5 W and 2.5 W, so 7500 and 2500 mWh.

prev = {1: ("brave", 0), 2: ("ghostty", 0)}
now = {1: ("brave", 3 * TICK), 2: ("ghostty", 1 * TICK)}
rows, total_cpu = wattage.attribute(prev, now, active_watts=10.0, seconds=3600)
by_app = {a: (c, m) for a, c, m in rows}
check("attribution: total cpu", close(total_cpu, 4.0), str(total_cpu))
check("attribution: 75% share -> 7500 mWh", close(by_app["brave"][1], 7500.0),
      str(by_app["brave"][1]))
check("attribution: 25% share -> 2500 mWh", close(by_app["ghostty"][1], 2500.0),
      str(by_app["ghostty"][1]))
check("attribution: energy sums to the draw",
      close(sum(m for _a, _c, m in rows), 10000.0))

# A process that did not exist at the previous sample cannot be charged for
# CPU it may have burned before we saw it.
rows, total_cpu = wattage.attribute({1: ("brave", 0)},
                                    {1: ("brave", TICK), 99: ("new", 500 * TICK)},
                                    active_watts=10.0, seconds=3600)
check("attribution: unseen pid is skipped", [a for a, _c, _m in rows] == ["brave"],
      str(rows))

# Two processes of the same app are one line.
rows, _ = wattage.attribute({1: ("brave", 0), 2: ("brave", 0)},
                            {1: ("brave", TICK), 2: ("brave", TICK)},
                            active_watts=8.0, seconds=3600)
check("attribution: same app is summed", len(rows) == 1 and close(rows[0][1], 2.0),
      str(rows))

# Nothing ran: no division by zero, no energy invented.
rows, total_cpu = wattage.attribute({1: ("idle", 5)}, {1: ("idle", 5)}, 10.0, 3600)
check("attribution: idle interval attributes nothing", rows == [] and total_cpu == 0)

# No measurement to divide up.
rows, _ = wattage.attribute(prev, now, active_watts=0.0, seconds=3600)
check("attribution: zero watts -> zero energy",
      all(close(m, 0.0) for _a, _c, m in rows))


# ---- a scripted machine ----------------------------------------------------

class FakeSystem(wattage.System):
    def __init__(self):
        self.busy = 0
        self.total = 0
        self.procs = {}
        self._power = {"battery": "BAT0", "status": "Discharging", "discharging": True,
                       "watts": 10.0, "measured": True, "percent": 80,
                       "energy_mwh": 30000, "full_mwh": 38000}

    def cpu_total_jiffies(self):
        return self.busy, self.total

    def processes(self):
        return dict(self.procs)

    def power(self):
        return dict(self._power)

    def advance(self, seconds, cpu_seconds_by_app):
        self.total += int(seconds * TICK * 16)
        self.busy += int(sum(cpu_seconds_by_app.values()) * TICK)
        for i, (app, secs) in enumerate(cpu_seconds_by_app.items(), start=1):
            name, jiffies = self.procs.get(i, (app, 0))
            self.procs[i] = (app, jiffies + int(secs * TICK))


fake = FakeSystem()
conn = wattage.db()

BASE = time.time() - 600
first = wattage.sample_once(fake, conn, now=BASE)
check("first sample has nothing to compare against", first.get("first") is True, str(first))

# Nearly idle while discharging: this reading teaches the idle floor.
fake._power["watts"] = 4.0
# Both processes must already exist, or the next interval rightly
# refuses to charge them for CPU burned before we first saw them.
fake.advance(60, {"brave": 0.2, "ghostty": 0.0})
result = wattage.sample_once(fake, conn, now=BASE + 60)
check("idle floor is learned", close(float(wattage.settings()["idleWatts"]), 4.0),
      str(wattage.settings()["idleWatts"]))

# Now something works hard: 12 W total, 4 W of which is the floor, so 8 W of
# active draw over 60s = 133.33 mWh, split 3:1.
fake._power["watts"] = 12.0
fake.advance(60, {"brave": 30.0, "ghostty": 10.0})
result = wattage.sample_once(fake, conn, now=BASE + 120)
top = {e["app"]: e["mwh"] for e in result["top"]}
check("busy sample is measured", result["measured"] is True, str(result))
check("active draw excludes the idle floor", close(result["active_watts"], 8.0),
      str(result["active_watts"]))
check("heavy app gets three quarters", close(top.get("brave", 0), 100.0, 0.6), str(top))
check("light app gets one quarter", close(top.get("ghostty", 0), 33.33, 0.6), str(top))
check("watts per cpu-second is learned",
      float(wattage.settings()["wattsPerCpuSecond"]) > 0,
      str(wattage.settings()["wattsPerCpuSecond"]))

# On AC there is no measurement, so the learned rate is used and the sample is
# flagged as an estimate rather than silently presented as fact.
fake._power.update({"status": "Full", "discharging": False, "watts": None, "measured": False})
fake.advance(60, {"brave": 20.0})
result = wattage.sample_once(fake, conn, now=BASE + 180)
check("AC sample is not marked measured", result["measured"] is False, str(result))
check("AC sample still attributes something", result["active_watts"] > 0,
      str(result["active_watts"]))

# A suspend, or a clock jump, must not book six hours of drain to whatever
# happened to be running when the lid closed.
fake.advance(60, {"brave": 5.0})
result = wattage.sample_once(fake, conn, now=BASE + 180 + 7200)
check("a long gap resets instead of attributing", result.get("reset") is True, str(result))

# ---- storage and reporting -------------------------------------------------

rows, meta = wattage.report(conn, since=0)
apps = {a: m for a, m, _c in rows}
check("report aggregates by app", "brave" in apps and "ghostty" in apps, str(apps))
check("report ranks brave first", rows[0][0] == "brave", str(rows[:2]))
check("report counts measured time", meta["measured"] > 0, str(meta))
check("report counts covered time", meta["covered"] >= meta["measured"], str(meta))
check("average watts is only over measured samples",
      meta["avg_watts"] is not None and 3.0 <= meta["avg_watts"] <= 13.0,
      str(meta["avg_watts"]))

# ---- state file the widget reads -------------------------------------------

state = json.loads(wattage.STATE_FILE.read_text())
for key in ["watts", "measured", "discharging", "percent", "top", "quiet", "at"]:
    check(f"state file has {key}", key in state, str(state)[:120])
check("state top is a list of app/mwh",
      isinstance(state["top"], list) and all("app" in e and "mwh" in e for e in state["top"]),
      str(state["top"])[:120])

# ---- settings --------------------------------------------------------------

check("settings merge nested defaults", "auto" in wattage.settings()["quiet"])
wattage.save_settings({**wattage.settings(), "quiet": {"auto": True}})
merged = wattage.settings()
check("a partial quiet block keeps its other keys",
      merged["quiet"]["auto"] is True and "plugins" in merged["quiet"], str(merged["quiet"]))

# ---- quiet mode ------------------------------------------------------------
# It used to accept being switched on with nothing nominated: it wrote the
# marker, turned nothing off, and left the bar icon showing quiet mode forever.

wattage.save_settings(dict(wattage.DEFAULT_SETTINGS))
check("nothing configured by default", not wattage.quiet_configured())
plugins, commands = wattage.quiet_targets()
check("no targets by default", plugins == [] and commands == [])

s2 = wattage.settings()
s2["quiet"]["plugins"] = ["acme.heavy"]
wattage.save_settings(s2)
check("a nominated plugin counts as configured", wattage.quiet_configured())
check("targets list the plugin", wattage.quiet_targets()[0] == ["acme.heavy"])

s2 = wattage.settings()
s2["quiet"] = {"plugins": [], "commands": [{"off": "true", "on": "true", "label": "x"}]}
wattage.save_settings(s2)
check("a command pair counts as configured", wattage.quiet_configured())
check("targets list the command", len(wattage.quiet_targets()[1]) == 1)

# A command entry with no way back up is not a target: quiet mode has to be
# reversible or it is just breakage.
s2 = wattage.settings()
s2["quiet"] = {"plugins": [], "commands": [{"on": "true"}]}
wattage.save_settings(s2)
check("a command with no off is ignored", not wattage.quiet_configured(),
      str(wattage.quiet_targets()))

# Round-trip through real commands, so the marker records what to undo.
marker = wattage.QUIET_MARKER
touched_file = tmp / "quiet-was-here"
s2 = wattage.settings()
s2["quiet"] = {"plugins": [], "commands": [
    {"off": f"touch {touched_file}", "on": f"rm -f {touched_file}", "label": "marker"}]}
wattage.save_settings(s2)

wattage.set_quiet(True)
check("quiet on runs the off command", touched_file.exists())
check("quiet on writes the marker", marker.exists())
record = json.loads(marker.read_text())
check("marker remembers the command to undo", len(record.get("commands", [])) == 1,
      str(record))

wattage.set_quiet(False)
check("quiet off runs the on command", not touched_file.exists())
check("quiet off clears the marker", not marker.exists())

# Config changing while quiet mode is on must not strand anything: the undo
# comes from the marker, not from whatever the settings say later.
wattage.set_quiet(True)
s2 = wattage.settings()
s2["quiet"] = {"plugins": [], "commands": []}
wattage.save_settings(s2)
wattage.set_quiet(False)
check("undo survives the config being emptied", not touched_file.exists())

wattage.save_settings(dict(wattage.DEFAULT_SETTINGS))

# ---- per-widget cost -------------------------------------------------------
# Bar widgets share one process, so the only way to tell them apart is to
# switch one off and look. Slow, so the answer is written down.

wattage.record_cost("acme.expensive", on_cpu=6.0, off_cpu=1.0, seconds=10)
wattage.record_cost("acme.cheap", on_cpu=2.05, off_cpu=2.0, seconds=10)
wattage.record_cost("acme.negative", on_cpu=1.9, off_cpu=2.0, seconds=10)

rows = wattage.db().execute(
    "SELECT id, cpu_delta FROM plugin_cost ORDER BY cpu_delta DESC").fetchall()
costs = dict(rows)
check("cost is stored per second of sample",
      close(costs["acme.expensive"], 0.5), str(costs.get("acme.expensive")))
check("a cheap widget lands near zero",
      close(costs["acme.cheap"], 0.005), str(costs.get("acme.cheap")))
check("ranked most expensive first", rows[0][0] == "acme.expensive", str(rows))
check("re-measuring replaces rather than duplicates",
      len(rows) == 3 and (wattage.record_cost("acme.cheap", 3.0, 1.0, 10) or
                          wattage.db().execute("SELECT COUNT(*) FROM plugin_cost")
                          .fetchone()[0] == 3))

# Noise has to be called noise. A widget measuring -1.7% of a core is the
# measurement moving, not a widget that gives power back.
check("a tiny share reads as noise", "noise" in wattage.describe_cost(0.005),
      wattage.describe_cost(0.005))
check("a negative share reads as noise", "noise" in wattage.describe_cost(-0.017),
      wattage.describe_cost(-0.017))
check("a real share is reported in CPU-seconds an hour",
      "an hour" in wattage.describe_cost(0.345), wattage.describe_cost(0.345))
check("noise floor is 2% of a core", close(wattage.noise_floor(0), 0.02))

# ---- helper processes ------------------------------------------------------
# Not attribution: most children do not name the plugin that started them.
# What it does catch is the ones that leak, which is worth knowing on its own.

PS = """2466028    3442 voxtype status --follow --extended --format json
2466065    3441 voxtype status --follow --extended --format json
2508452    2655 voxtype status --follow --extended --format json
2465501    3442 wl-paste --type text --watch /usr/share/omarchy/shell/plugins/clipboard/capture.sh text
2465175    3443 /usr/bin/inotifywait -m -r -q -e close_write /home/ruan/.config/omarchy/plugins
"""
helpers = wattage.helper_processes(PS)
by_command = {h["command"]: h for h in helpers}
check("identical helpers are grouped", len(helpers) == 3, str([h["command"] for h in helpers]))
check("duplicates are counted",
      by_command["voxtype status --follow"]["count"] == 3,
      str(by_command.get("voxtype status --follow")))
check("the most duplicated comes first", helpers[0]["count"] == 3)
check("age is the oldest of the group",
      by_command["voxtype status --follow"]["oldest"] == 3442)
check("a helper naming a plugin path is attributed",
      by_command["wl-paste --type text"].get("plugin") == "clipboard",
      str(by_command.get("wl-paste --type text")))
check("a helper naming no plugin is left unattributed",
      "plugin" not in by_command["/usr/bin/inotifywait -m -r"],
      str(by_command.get("/usr/bin/inotifywait -m -r")))
check("empty ps output is not a crash", wattage.helper_processes("") == [])
check("a malformed ps line is skipped", wattage.helper_processes("garbage\n") == [])

# ---- formatting ------------------------------------------------------------

check("watts formatting", wattage.human_watts(0.42) == "420 mW", wattage.human_watts(0.42))
check("watts formatting large", wattage.human_watts(12.34) == "12.3 W")
check("energy formatting", wattage.human_energy(950) == "950 mWh")
check("energy formatting large", wattage.human_energy(2500) == "2.50 Wh")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{PASSED} passed, {len(FAILED)} failed")
for f in FAILED:
    print(f"  FAIL  {f}")
sys.exit(1 if FAILED else 0)
