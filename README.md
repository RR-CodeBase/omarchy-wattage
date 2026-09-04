# Wattage

**Not how much battery is left. What ate it.**

Every battery widget shows you the same number the kernel already knows.
Wattage answers the question people actually ask at 3pm: *what is draining
this thing?*

```
Where the power went - last 24h  (7.4h sampled, 3.1h on battery)
Average draw while on battery: 8.7 W

  brave           2.41 Wh   38.2%  ████████████ 812s cpu
  quickshell      1.18 Wh   18.7%  ██████ 402s cpu
  Chromium        0.94 Wh   14.9%  ████ 318s cpu
  ghostty         0.51 Wh    8.1%  ██ 171s cpu
  Hyprland        0.33 Wh    5.2%  █ 112s cpu
```

## How it can possibly know

It can't, exactly — and it says so rather than pretending.

No laptop has a per-process power meter. What it does have is the battery's
own reported draw, which is ground truth for the whole machine, and per-process
CPU time. Wattage samples both every 20 seconds and splits the machine's
**active** draw between processes in proportion to the CPU they burned:

```
idle floor      = the lowest draw seen while the machine was doing nothing
active draw     = measured draw − idle floor
app's share     = active draw × (app CPU ÷ all CPU)
```

The idle floor stays unattributed, because the screen and the radios are not
any one app's fault. The result is an estimate built on a real measurement,
and it is more than enough to find the process costing you an hour of runtime.

Two honest limitations, stated up front:

- **On AC there is nothing to measure.** Most firmware reports zero draw while
  plugged in. Wattage learns what a CPU-second costs while you are on battery
  and uses that to estimate on AC, marking those figures as estimates. Before
  it has learned, it ranks by CPU time and says that is what it is doing.
- **Very short-lived processes are missed.** A process that starts and exits
  between two samples is never seen. A build that spawns thousands of compiler
  invocations will show up as the shell that spawned them, not as `cc1`.

## Quiet mode: what it is for

Finding the culprit is half of it. The other half is doing something about it.

The premise is that a modern Omarchy bar runs a dozen QML widgets inside one
long-lived shell process, some of them animating or polling continuously, and
that on battery you would trade a few of them for runtime. Quiet mode turns off
the ones you nominate when you unplug and puts them back when you plug in.

Whether that is worth anything is a measurable question, so measure it. On the
machine this was written on, the shell was using **37% of a core, continuously**.
One plugin — an animated wallpaper drawing rain and fog — accounted for
**45% of a core, 1613 CPU-seconds an hour**. With its effects off the shell
dropped from 7.25 to 0.53 CPU-seconds per 15 seconds. That is what quiet mode
is for. Equally: if `wattage bisect` tells you a widget costs nothing, quiet
mode has nothing to offer you, and it says so rather than pretending.

It is **opt-in and does nothing until you nominate something** — switching it on
with an empty list used to write its marker, turn nothing off, and leave the bar
icon lit forever. Now it refuses and tells you where to start:

```bash
wattage quiet suggest              # the bar widgets you are running
wattage bisect <plugin-id>         # what one of them actually costs
wattage quiet add <plugin-id>      # nominate it
wattage quiet auto                 # apply it automatically on battery
```

### Turning down, not just turning off

A whole plugin is a blunt instrument. Usually the cost is one *setting* inside
one plugin, and that plugin already has a switch for it. So a quiet target can
be a pair of commands instead of a plugin id, in
`~/.config/omarchy/wattage/settings.json`:

```json
"quiet": {
  "auto": true,
  "belowPercent": 80,
  "plugins": [],
  "commands": [
    { "off":   "wallpaper-weather enabled off",
      "on":    "wallpaper-weather enabled on",
      "label": "wallpaper effects" }
  ]
}
```

Whatever was actually turned off is recorded in
`~/.local/state/omarchy/wattage-quiet.json`, and that record — not the config —
is what gets undone. So editing the list while quiet mode is on cannot strand
anything, and if the machine dies with quiet mode still on, the sampler puts
everything back the next time it starts on AC.

## Seeing what each plugin costs

Every bar widget runs inside the one Quickshell process. No amount of
per-process accounting can separate them — so Wattage does the only thing that
can, and switches one off to look:

```bash
wattage plugins             # the table, from what has been measured
wattage plugins --measure   # measure every enabled widget (slow)
wattage bisect <plugin-id>  # just one
```

```
What each bar widget costs the shell

  io.github.rr-codebase.wallpaper-weather   +34.5% of a core  ██████████████████████
  omarchy.clock                              -1.7% of a core  █  (noise)

  Everything measurable adds up to 34% of a core.
  Anything not listed has not been measured yet.
```

A sweep takes roughly half a minute per widget and makes the bar flicker
throughout, so it asks first and is never run behind your back. Results are
stored, so you measure once and read the table afterwards. Ctrl-C is safe:
whatever is switched off gets switched back on, in a `finally`.

A widget measuring below 2% of a core — or negative, which happens — is
reported as noise rather than as a finding. Most widgets are noise. That is
worth knowing too: it means quiet mode has nothing to offer for them.

### What the shell is keeping alive

```bash
wattage helpers
```

lists the long-lived processes the shell has spawned, grouped and counted:

```
  voxtype status --follow  ×4
  wl-paste --type text  [clipboard]
```

Most children do not name the plugin that started them, so this is not
attribution — but a helper running four times over is a widget respawning it
on every shell reload without stopping the old one, which costs CPU and memory
for nothing.

## Install

```sh
omarchy plugin add https://github.com/RR-CodeBase/omarchy-wattage.git --enable
```

Then start the sampler, which is what gives it anything to report:

```sh
~/.config/omarchy/plugins/io.github.rr-codebase.wattage/bin/wattage service install
```

Or from a clone, `git clone` then `./install.sh`, which registers the plugin,
places the widget and installs the sampler in one go.

## Usage

The bar icon shows `󱐋` on battery, `󰚥` on AC and `󰤄` when quiet mode is on.
Click it for the current draw and the top five using it; Escape closes the
panel. Middle-click toggles quiet mode.

```sh
wattage now                  # current draw and top consumers
wattage top --since 24h      # where the power went
wattage plugins              # what each bar widget costs
wattage doctor               # check the install
```

## Configure

```sh
omarchy bar move io.github.rr-codebase.wattage --section right
```

Settings live at `~/.config/omarchy/wattage/settings.json`; the table below
covers them.

## Remove

```sh
~/.config/omarchy/plugins/io.github.rr-codebase.wattage/install.sh --uninstall
```

That stops and removes the sampler service, restores anything quiet mode had
turned off, and removes the plugin. `omarchy plugin remove
io.github.rr-codebase.wattage` on its own leaves the service running. Your
history stays at `~/.local/state/omarchy/wattage.db` either way.

## Using it

| | |
|---|---|
| **Bar icon** | `󱐋` on battery, `󰚥` on AC, `󰤄` when quiet mode is on |
| **Click** | current draw and the top five using it |
| **Middle-click** | toggle quiet mode (once you have nominated something) |

```
wattage now                  current draw and top consumers
wattage top --since 24h      where the power went (1h 6h 24h today 7d 14d)
wattage plugins [--measure]  what each bar widget costs
wattage bisect <plugin-id>   measure one bar widget by turning it off
wattage helpers              long-lived processes the shell spawned
wattage quiet status|suggest|add <id>|remove <id>|on|off|toggle|auto
wattage sample [--daemon]    take a sample, or run the sampler
wattage service install|remove|status
wattage doctor               check the install
```

Add `--json` to `now` and `top` to get the numbers out.

## Settings

`~/.config/omarchy/wattage/settings.json`

| Key | Default | |
|---|---|---|
| `interval` | `20` | seconds between samples |
| `idleWatts` | learned | the unattributed floor |
| `wattsPerCpuSecond` | learned | used to estimate while on AC |
| `quiet.auto` | `false` | quieten automatically on battery |
| `quiet.belowPercent` | `100` | ...at or below this charge |
| `quiet.plugins` | `[]` | plugin ids quiet mode disables |
| `quiet.commands` | `[]` | `{off, on, label}` triples to turn down instead |

The two learned values are written back as Wattage observes your machine.
Delete them to re-learn.

## Cost of running it

One Python process waking every 20 seconds to read `/proc` and one sysfs file,
at `Nice 19`. It writes about 4 MB a month to SQLite and prunes to 14 days.

## Requirements

- Omarchy Quattro
- A battery that reports `power_now` or `current_now` (nearly all do)
- Python 3.11+ (standard library only)

RAPL would give a finer-grained reading, but `energy_uj` is root-only on Arch
(a side-channel mitigation), so Wattage uses the battery instead and needs no
privileges at all.

## Tests

```bash
python3 tests/test_wattage.py     # attribution, quiet mode, per-widget cost
python3 tests/test_plugin.py      # conformance with the Omarchy plugin guide
```

83 assertions. The attribution arithmetic is checked against hand-computed
values through a scripted battery and scripted processes, because the
interesting behaviour only happens on battery and a test machine is usually
plugged in. Also covers the cgroup-to-app-name mapping against strings taken
off a running machine, and that a suspend does not book six hours of drain to
whatever was running when the lid closed.

## Licence

MIT. See `LICENSE`, and `NOTICE`.
