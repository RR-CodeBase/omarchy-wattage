import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar icon plus a popup panel, shaped like Omarchy's own power and audio
// panels. The icon is a glyph rather than a number: every other widget in
// this bar is a round glyph, and the watts belong in the panel where there is
// room to say what they mean.
//
// Everything is read from the file the sampler writes. The widget never runs
// a measurement of its own -- a power meter that spends power to draw itself
// would be a poor joke.
Panel {
  id: root
  moduleName: "io.github.rr-codebase.wattage"
  ipcTarget: "io.github.rr-codebase.wattage"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // barForeground contrasts with the wallpaper; popup text sits on
  // Color.popups.background and needs the other one.
  readonly property color panelText: Color.popups.text

  readonly property string cli:
    Qt.resolvedUrl("bin/wattage").toString().replace(/^file:\/\//, "")

  property real watts: 0
  property bool measured: false
  property bool discharging: false
  property int percent: -1
  property string batteryStatus: "unknown"
  property bool quiet: false
  property var consumers: []
  property real updatedAt: 0

  readonly property bool stale: updatedAt > 0
    && (Date.now() / 1000 - updatedAt) > 300

  readonly property string glyph: quiet ? "󰤄" : (discharging ? "󱐋" : "󰚥")

  readonly property string wattsText:
    !measured ? "" : (watts >= 1 ? watts.toFixed(1) + " W"
                                 : Math.round(watts * 1000) + " mW")

  readonly property string headline: {
    if (updatedAt === 0) return "No samples yet"
    if (stale) return "Sampler is not running"
    if (measured) return "Drawing " + wattsText
    return "On AC — draw estimated"
  }

  function run(args) {
    if (root.bar) root.bar.run("'" + root.cli.replace(/'/g, "'\\''") + "' " + args)
  }

  function shell(cmd) {
    if (root.bar) root.bar.run(cmd)
  }

  FileView {
    id: stateFile
    path: Quickshell.env("HOME") + "/.local/state/omarchy/wattage.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      try {
        var s = JSON.parse(text() || "{}") || {}
        var w = Number(s.watts)
        root.watts = isFinite(w) ? w : 0
        root.measured = s.measured === true
        root.discharging = s.discharging === true
        var p = Number(s.percent)
        root.percent = isFinite(p) ? p : -1
        root.batteryStatus = typeof s.status === "string" ? s.status : "unknown"
        root.quiet = s.quiet === true
        var at = Number(s.at)
        root.updatedAt = isFinite(at) ? at : 0
        var list = []
        var incoming = s.top || []
        for (var i = 0; i < incoming.length && i < 5; i++) {
          var m = Number(incoming[i].mwh)
          list.push({
            app: String(incoming[i].app || ""),
            mwh: isFinite(m) ? m : 0
          })
        }
        root.consumers = list
      } catch (error) {
        // A half-written file is transient; keep the last good reading.
      }
    }
    onFileChanged: reload()
  }

  // Re-evaluate `stale` without waiting for the next sample, so a stopped
  // sampler is visible rather than a frozen number pretending to be live.
  Timer {
    interval: 60000
    running: true
    repeat: true
    onTriggered: root.updatedAt = root.updatedAt
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    active: root.quiet || (root.discharging && root.measured)
    activeColor: root.quiet ? Color.popups.text : Color.accent
    opacity: root.stale ? 0.55 : 1.0
    tooltipText: root.headline
      + (root.percent >= 0 ? "\nBattery " + root.percent + "%" : "")
      + (root.quiet ? "\nQuiet mode on" : "")
      + "\nClick for what is using it"
    onPressed: function (b) {
      if (b === Qt.MiddleButton) root.run("quiet toggle")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }

      Column {
        id: panelColumn
        width: parent.width
        spacing: Style.spacing.controlGap

        PanelSectionHeader {
          text: root.headline
          foreground: root.panelText
          fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        }

        Text {
          visible: root.percent >= 0
          width: panelColumn.width
          text: "Battery " + root.percent + "% · " + root.batteryStatus
          textFormat: Text.PlainText
          color: root.panelText
          opacity: 0.72
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        // Say plainly when the numbers are inferred rather than measured.
        // A power meter that hides its error bars is not worth trusting.
        Text {
          visible: !root.measured && root.updatedAt > 0 && !root.stale
          width: panelColumn.width
          text: "Estimated from CPU use. Unplug to measure."
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          color: root.panelText
          opacity: 0.6
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.italic: true
        }

        Text {
          visible: root.stale || root.updatedAt === 0
          width: panelColumn.width
          text: "Start the sampler: wattage service install"
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          color: root.panelText
          opacity: 0.7
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        PanelSeparator {
          width: panelColumn.width
          foreground: root.panelText
        }

        PanelSectionHeader {
          visible: root.consumers.length > 0
          text: "Using it now"
          foreground: root.panelText
          fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        }

        Repeater {
          model: root.consumers

          Item {
            required property var modelData
            width: panelColumn.width
            height: Style.spacing.controlHeight

            Text {
              width: parent.width * 0.62
              text: modelData.app
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: root.panelText
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: modelData.mwh >= 1000
                ? (modelData.mwh / 1000).toFixed(2) + " Wh"
                : Math.round(modelData.mwh) + " mWh"
              textFormat: Text.PlainText
              horizontalAlignment: Text.AlignRight
              color: root.panelText
              opacity: 0.78
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        PanelSeparator {
          width: panelColumn.width
          foreground: root.panelText
        }

        Item {
          width: panelColumn.width
          height: Style.spacing.controlHeight

          Text {
            id: quietIcon
            text: "󰤄"
            textFormat: Text.PlainText
            color: root.quiet ? Color.accent : root.panelText
            opacity: root.quiet ? 1.0 : 0.78
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.icon
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Text {
            text: "Quiet mode"
            textFormat: Text.PlainText
            color: root.panelText
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            anchors.left: quietIcon.right
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
          }

          ToggleSwitch {
            checked: root.quiet
            foreground: root.panelText
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            onToggled: root.run("quiet toggle")
          }
        }

        Row {
          width: panelColumn.width
          spacing: Style.spacing.sm

          PanelActionButton {
            iconText: "󰾅"
            tooltipText: "Where the power went, last 24h"
            foreground: root.panelText
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            onClicked: {
              root.close()
              root.shell("omarchy-launch-floating-terminal-with-presentation '"
                + root.cli.replace(/'/g, "'\\''") + "' top --since 24h")
            }
          }

          PanelActionButton {
            iconText: "󰄬"
            tooltipText: "Check the install"
            foreground: root.panelText
            fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
            onClicked: {
              root.close()
              root.shell("omarchy-launch-floating-terminal-with-presentation '"
                + root.cli.replace(/'/g, "'\\''") + "' doctor")
            }
          }
        }
      }
    }
  }
}
