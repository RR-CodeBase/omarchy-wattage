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

### Measuring a single widget

Every bar widget shares one Quickshell process, so no per-process accounting
can separate them:

```bash
wattage bisect io.github.someone.expensive-widget
```

turns the widget off, measures the shell with and without it, and reports the
difference — including "that is within noise", which is the answer more often
than people expect.

## Install

```bash
git clone https://github.com/RR-CodeBase/omarchy-wattage
cd omarchy-wattage
./install.sh
```

This registers the plugin, places the bar widget, and installs a systemd user
service that samples every 20 seconds at `Nice 19`. `./install.sh --uninstall`
removes all of it. Your history is kept at
`~/.local/state/omarchy/wattage.db` either way.

## Using it

| | |
|---|---|
| **Bar icon** | `󱐋` on battery, `󰚥` on AC, `󰤄` when quiet mode is on |
| **Click** | current draw and the top five using it |
| **Middle-click** | toggle quiet mode (once you have nominated something) |

```
wattage now                  current draw and top consumers
wattage top --since 24h      where the power went (1h 6h 24h today 7d 14d)
wattage bisect <plugin-id>   measure one bar widget by turning it off
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
python3 tests/test_wattage.py
```

67 assertions. The attribution arithmetic is checked against hand-computed
values through a scripted battery and scripted processes, because the
interesting behaviour only happens on battery and a test machine is usually
plugged in. Also covers the cgroup-to-app-name mapping against strings taken
off a running machine, and that a suspend does not book six hours of drain to
whatever was running when the lid closed.

## Licence

MIT. See `LICENSE`, and `NOTICE`.
