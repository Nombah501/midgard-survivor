import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: band
    required property var runs
    required property QtObject theme
    property bool small: false
    property string heading: ""
    property string subtitle: ""
    property string emptyText: ""
    signal runFocused(Item mark)
    property int keyboardIndex: 0
    readonly property int focusIndex: Math.min(keyboardIndex, runs.length - 1)
    readonly property bool hasCurrent: runs.length > 0 && runs[runs.length - 1].outcome === "current"
    readonly property int gap: small ? 3 : 4
    readonly property int markHeight: small ? 12 : theme.compact ? 24 : 32
    readonly property int columns: Math.max(1, Math.min(runs.length,
        Math.floor((width + gap) / ((small ? 12 : 20) + gap))))
    readonly property real markWidth: Math.min(small ? 20 : 40, (width - (columns - 1) * gap) / columns)
    readonly property real pitch: markWidth + gap
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    spacing: 8
    Accessible.role: Accessible.Grouping
    Accessible.name: {
        if (runs.length === 0)
            return emptyText
        let wins = 0
        let losses = 0
        let aborted = 0
        for (let i = 0; i < runs.length; i++) {
            switch (runs[i].outcome) {
            case "win": wins++; break
            case "loss": losses++; break
            case "aborted": aborted++; break
            }
        }
        const parts = [wins === 1 ? qsTr("1 win") : qsTr("%1 wins").arg(wins),
                       losses === 1 ? qsTr("1 loss") : qsTr("%1 losses").arg(losses)]
        if (aborted)
            parts.push(qsTr("%1 aborted").arg(aborted))
        if (hasCurrent) {
            const number = runs[runs.length - 1].number
            parts.push(number ? qsTr("run %1 in progress").arg(number) : qsTr("run in progress"))
        }
        return parts.join(", ")
    }

    function focusRun(index) {
        if (index < 0 || index >= runs.length)
            return false
        bandRows.itemAt(Math.floor(index / columns)).focusRun(index % columns)
        return true
    }

    function tickText(index) {
        const run = runs[index]
        return run.number ? run.number.padStart(2, "0") + " " + run.short : run.short
    }

    function runLabel(index) {
        const run = runs[index]
        if (!run)
            return ""
        const outcome = outcomeLabel(run.outcome)
        return run.number ? qsTr("Run %1 · %2 · %3").arg(run.number).arg(run.label).arg(outcome)
                          : qsTr("%1 · %2").arg(run.label).arg(outcome)
    }

    function outcomeLabel(outcome) {
        switch (outcome) {
        case "win": return qsTr("Win")
        case "loss": return qsTr("Loss")
        case "aborted": return qsTr("Aborted")
        default: return qsTr("In progress")
        }
    }

    function paintMark(ctx, x, y, w, h, outcome) {
        // Cut corners and a chisel tip preserve the inscription at History size.
        const cut = Math.min(6, h / 4, w / 4)
        const left = x + 0.5
        const top = y + 0.5
        const right = x + w - 0.5
        const bottom = y + h - 0.5
        ctx.beginPath()
        ctx.moveTo(left, top + cut)
        ctx.lineTo(left + cut, top)
        ctx.lineTo(right - cut / 2, top)
        ctx.lineTo(right, top + cut)
        if (outcome === "current") {
            ctx.lineTo(right - cut / 2, top + h / 2 - cut / 2)
            ctx.lineTo(right, top + h / 2)
            ctx.lineTo(right - cut / 2, top + h / 2 + cut / 2)
            ctx.lineTo(right - cut / 2, bottom - cut)
        } else {
            ctx.lineTo(right, bottom - cut)
        }
        ctx.lineTo(right - cut, bottom)
        ctx.lineTo(left + cut / 2, bottom)
        ctx.lineTo(left, bottom - cut)
        ctx.closePath()
        if (outcome === "win") {
            ctx.fillStyle = theme.ochre
            ctx.fill()
        } else {
            ctx.lineWidth = 1
            ctx.strokeStyle = outcome === "current" ? theme.ink : outcome === "aborted" ? theme.muted : theme.ochre
            ctx.setLineDash(outcome === "current" ? [4, 3] : [])
            ctx.stroke()
            if (outcome === "aborted") {
                ctx.beginPath()
                ctx.moveTo(left + 2, bottom - 2)
                ctx.lineTo(right - 2, top + 2)
                ctx.stroke()
            }
        }
    }

    RowLayout {
        visible: !band.small
        Layout.fillWidth: true
        spacing: 12
        Label {
            text: band.heading
            font.pixelSize: 16
            font.bold: true
        }
        Label {
            Layout.fillWidth: true
            visible: text.length > 0
            text: band.subtitle
            font.pixelSize: 13
            color: band.theme.muted
            elide: Text.ElideRight
        }
        Item { Layout.fillWidth: true; visible: band.subtitle.length === 0 }
        RowLayout {
            visible: band.runs.length > 0
            spacing: band.theme.compact ? 8 : 16
            Repeater {
                model: band.hasCurrent ? ["win", "loss", "current", "aborted"] : ["win", "loss", "aborted"]
                delegate: RowLayout {
                    required property string modelData
                    spacing: 4
                    Canvas {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 10
                        onPaint: {
                            const ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            band.paintMark(ctx, 0, 0, width, height, parent.modelData)
                        }
                    }
                    Label {
                        text: band.outcomeLabel(parent.modelData)
                        font.pixelSize: 13
                        color: band.theme.muted
                    }
                }
            }
        }
    }

    Repeater {
        id: bandRows
        model: Math.ceil(band.runs.length / band.columns)
        delegate: Canvas {
            id: row
            required property int index
            readonly property int first: index * band.columns
            readonly property int count: Math.min(band.columns, band.runs.length - first)
            function focusRun(column) {
                marks.itemAt(column).forceActiveFocus(Qt.OtherFocusReason)
            }
            Layout.fillWidth: true
            implicitHeight: band.markHeight + (band.small ? 0 : 20)
            onWidthChanged: requestPaint()
            onFirstChanged: requestPaint()
            onCountChanged: requestPaint()
            onVisibleChanged: if (visible) requestPaint()
            Connections {
                target: band
                function onRunsChanged() { row.requestPaint() }
                function onMarkHeightChanged() { row.requestPaint() }
                function onMarkWidthChanged() { row.requestPaint() }
            }
            Repeater {
                id: marks
                model: row.count
                delegate: Rectangle {
                    id: mark
                    required property int index
                    readonly property int runIndex: row.first + index
                    objectName: band.objectName + "-run-" + runIndex
                    x: index * band.pitch
                    width: Math.max(0, band.markWidth)
                    height: band.markHeight
                    color: "transparent"
                    border.width: activeFocus ? 2 : 0
                    border.color: band.theme.ink
                    activeFocusOnTab: runIndex === band.focusIndex
                    Accessible.role: Accessible.Graphic
                    Accessible.focusable: true
                    Accessible.name: band.runLabel(runIndex)
                    onActiveFocusChanged: {
                        if (activeFocus) {
                            band.keyboardIndex = runIndex
                            band.runFocused(mark)
                        }
                    }
                    Keys.onLeftPressed: event => event.accepted = band.focusRun(runIndex - 1)
                    Keys.onRightPressed: event => event.accepted = band.focusRun(runIndex + 1)
                    Keys.onUpPressed: event => event.accepted = band.focusRun(runIndex - band.columns)
                    Keys.onDownPressed: event => event.accepted = band.focusRun(runIndex + band.columns)
                    HoverHandler { id: runHover }
                    ToolTip.delay: activeFocus ? 0 : 350
                    ToolTip.visible: activeFocus || runHover.hovered
                    ToolTip.text: Accessible.name
                }
            }

            onPaint: {
                const ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                if (band.markWidth <= 0 || count <= 0)
                    return
                const step = band.pitch
                const right = (count - 1) * step + band.markWidth
                ctx.font = '13px "' + band.theme.font.family + '"'
                ctx.textAlign = "left"
                const endWidth = band.small ? 0 : ctx.measureText(band.tickText(first + count - 1)).width
                const endX = Math.max(0, Math.floor(right - endWidth))
                let tickEdge = 0
                for (let col = 0; col < count; col++) {
                    const i = first + col
                    const run = band.runs[i]
                    band.paintMark(ctx, col * step, 0, band.markWidth, band.markHeight, run.outcome)
                    const last = col === count - 1
                    if (band.small || (col !== 0 && (i + 1) % 6 !== 0 && !last))
                        continue
                    const tick = band.tickText(i)
                    const textWidth = last ? endWidth : ctx.measureText(tick).width
                    const x = last && col > 0 ? endX : Math.floor(col * step)
                    if (x < tickEdge || x + textWidth > width
                            || (!last && col > 0 && x + textWidth + 8 > endX))
                        continue
                    ctx.fillStyle = run.outcome === "current" ? band.theme.ink : band.theme.muted
                    ctx.fillText(tick, x, band.markHeight + 16)
                    tickEdge = x + textWidth + 8
                }
            }
        }
    }

    Label {
        visible: band.runs.length === 0 && !band.small
        Layout.fillWidth: true
        text: band.emptyText
        color: band.theme.muted
        font.pixelSize: 13
        wrapMode: Text.Wrap
    }
}
