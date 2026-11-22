import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: shell
    required property QtObject backend
    readonly property var session: backend.snapshot
    readonly property var history: backend.history
    readonly property var updates: session.updates
    readonly property var quarantine: session.quarantine
    readonly property var diagnostics: backend.diagnostics
    readonly property color ground: "#1c1e1d"
    readonly property color raised: "#2b2e2c"
    readonly property color hairline: "#3a3e3b"
    readonly property color ink: "#e8e2d3"
    readonly property color muted: "#a9a597"
    readonly property color redOchre: "#b6432a"
    readonly property color ochre: "#c9943c"
    readonly property color danger: "#e07a5f"
    readonly property color edge: "#74766d"
    readonly property color hoverStone: "#353934"
    readonly property color warning: ochre
    readonly property int gutter: width >= 1280 ? 48 : width >= 1000 ? 32 : width >= 760 ? 24 : 16
    readonly property bool compact: width < 760
    readonly property bool runLocked: session.active && !session.paused
    readonly property int dropdownRowHeight: 36

    function amount(value) {
        return value === undefined ? "" : Number(value).toLocaleString(Qt.locale("en_US"), "f", 0)
    }

    function elapsed(seconds) {
        const hours = Math.floor(seconds / 3600)
        const minutes = Math.floor(seconds / 60) % 60
        return hours > 0 ? qsTr("%1 h %2 min").arg(hours).arg(minutes) : qsTr("%1 min").arg(minutes)
    }

    title: qsTr("Midgard Farm")
    visible: true
    width: 1100
    height: 820
    minimumWidth: 640
    minimumHeight: 520

    FontLoader { id: regularFont; source: "fonts/NotoSans-Regular.ttf" }
    FontLoader { id: boldFont; source: "fonts/NotoSans-Bold.ttf" }
    font.family: regularFont.name
    font.pixelSize: 14
    color: ground
    palette.window: ground
    palette.windowText: ink
    palette.base: ground
    palette.alternateBase: raised
    palette.text: ink
    palette.button: raised
    palette.buttonText: ink
    palette.mid: hairline
    palette.highlight: ochre
    palette.highlightedText: ground
    palette.placeholderText: muted

    component Frame: Rectangle {
        property bool focused: false
        radius: 2
        border.width: focused ? 2 : 1
    }

    component Chevron: Item {
        property color stroke: shell.muted
        property bool expanded: false
        implicitWidth: 10
        implicitHeight: 10
        rotation: expanded ? 225 : 45
        Rectangle { width: 6; height: 1; color: parent.stroke; anchors.right: parent.right; anchors.bottom: parent.bottom }
        Rectangle { width: 1; height: 6; color: parent.stroke; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }

    component Caption: Label {
        color: shell.muted
        font.pixelSize: 13
        textFormat: Text.PlainText
    }

    component ActionButton: Button {
        id: button
        property bool destructive: false
        property bool disclosure: false
        horizontalPadding: 12
        verticalPadding: 8
        spacing: 12
        font.bold: !disclosure
        contentItem: Label {
            text: button.text
            color: !button.enabled ? shell.muted
                   : button.highlighted ? "white"
                   : button.destructive ? shell.danger : shell.ink
            font: button.font
            textFormat: Text.PlainText
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: button.disclosure ? Text.AlignLeft : Text.AlignHCenter
        }
        background: Frame {
            implicitHeight: button.disclosure ? 36 : 40
            focused: button.visualFocus
            color: !button.enabled ? (button.disclosure ? shell.raised : "transparent")
                   : button.highlighted ? (button.down || button.hovered
                       ? Qt.darker(shell.redOchre, button.down ? 1.18 : 1.10) : shell.redOchre)
                   : button.down || button.hovered ? shell.hoverStone
                   : button.disclosure ? shell.raised : "transparent"
            border.color: button.visualFocus ? shell.ink
                          : !button.enabled ? shell.hairline
                          : button.destructive || button.highlighted ? shell.redOchre : shell.edge
        }
    }

    component Disclosure: ActionButton {
        id: disclosure
        property alias detail: disclosureDetail.text
        property alias detailObjectName: disclosureDetail.objectName
        disclosure: true
        checkable: true
        contentItem: RowLayout {
            spacing: 12
            SingleLine {
                text: disclosure.text
                color: disclosure.enabled ? shell.ink : shell.muted
            }
            Caption {
                id: disclosureDetail
                visible: text.length > 0
                elide: Text.ElideRight
                Layout.maximumWidth: disclosure.availableWidth * 0.7
                ToolTip.visible: disclosure.hovered && truncated
                ToolTip.text: text
                ToolTip.delay: 500
            }
            Chevron {
                visible: disclosure.enabled
                expanded: disclosure.checked
                Layout.rightMargin: 2
                Layout.bottomMargin: 4
            }
        }
    }

    component StoneTab: TabButton {
        id: tab
        width: implicitWidth
        implicitHeight: shell.compact ? 48 : 64
        horizontalPadding: shell.compact ? 8 : 16
        verticalPadding: 0
        font.bold: true
        contentItem: Label {
            text: tab.text
            font: tab.font
            color: tab.checked || tab.hovered ? shell.ink : shell.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: tab.checked ? shell.ground : tab.hovered ? shell.hoverStone : "transparent"
            border.color: shell.ink
            border.width: tab.visualFocus ? 2 : 0
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 3
                color: shell.redOchre
                visible: tab.checked
            }
        }
    }

    component StoneScrollBar: ScrollBar {
        id: bar
        padding: 2
        minimumSize: 0.05
        contentItem: Rectangle {
            implicitWidth: 5
            implicitHeight: 5
            radius: 2
            color: bar.pressed ? shell.ink : bar.hovered ? shell.muted : shell.edge
            visible: bar.size < 1
        }
        background: null
    }

    component PickOption: ItemDelegate {
        id: option
        horizontalPadding: 12
        verticalPadding: 8
        implicitHeight: shell.dropdownRowHeight
        contentItem: Label {
            text: option.text
            color: option.enabled ? shell.ink : shell.muted
            elide: Text.ElideRight
            textFormat: Text.PlainText
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            color: option.highlighted || option.hovered ? shell.hoverStone : shell.raised
        }
    }

    component StoneCombo: ComboBox {
        id: pick
        property int minimumPopupWidth: 0
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        leftPadding: 12
        rightPadding: 32
        verticalPadding: 8
        contentItem: Label {
            text: pick.displayText
            color: pick.enabled ? shell.ink : shell.muted
            textFormat: Text.PlainText
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        ToolTip.visible: pick.hovered && contentItem.truncated
        ToolTip.text: displayText
        ToolTip.delay: 500
        indicator: Chevron {
            x: pick.width - width - 14
            y: (pick.height - height) / 2 - 2
            expanded: pick.down
        }
        background: Frame {
            implicitWidth: 120
            implicitHeight: 36
            focused: pick.visualFocus
            color: pick.enabled && (pick.hovered || pick.down) ? shell.hoverStone : shell.raised
            border.color: pick.visualFocus ? shell.ink : pick.enabled ? shell.edge : shell.hairline
        }
        delegate: PickOption {
            required property int index
            width: ListView.view.width
            text: pick.textAt(index)
            highlighted: pick.highlightedIndex === index
        }
        popup: Popup {
            width: Math.max(pick.width, pick.minimumPopupWidth)
            topMargin: 8
            bottomMargin: 8
            padding: 1
            height: Math.min(contentItem.implicitHeight + 2, shell.height - topMargin - bottomMargin)
            onOpened: optionsList.forceLayout()
            contentItem: ListView {
                id: optionsList
                clip: true
                implicitHeight: pick.count * shell.dropdownRowHeight
                model: pick.delegateModel
                currentIndex: pick.highlightedIndex
                highlightRangeMode: ListView.ApplyRange
                highlightMoveDuration: 0
                ScrollBar.vertical: StoneScrollBar {
                    parent: optionsList
                    anchors.top: optionsList.top
                    anchors.right: optionsList.right
                    anchors.bottom: optionsList.bottom
                }
            }
            background: Frame { color: shell.raised; border.color: shell.edge }
        }
    }

    component StoneSwitch: Switch {
        id: toggle
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        padding: 0
        spacing: 8
        contentItem: Label {
            text: toggle.text
            color: toggle.enabled ? shell.ink : shell.muted
            rightPadding: toggle.indicator.width + toggle.spacing
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
        }
        indicator: Frame {
            implicitWidth: 32
            implicitHeight: 16
            x: toggle.width - width
            y: (toggle.height - height) / 2
            focused: toggle.visualFocus
            color: toggle.checked ? (toggle.enabled ? shell.ink : shell.muted)
                   : toggle.hovered && toggle.enabled ? shell.hoverStone : shell.ground
            border.color: toggle.visualFocus || (toggle.checked && toggle.enabled) ? shell.ink : shell.edge
            Rectangle {
                width: 10
                height: 10
                radius: 2
                x: 3 + (parent.width - width - 6) * toggle.visualPosition
                anchors.verticalCenter: parent.verticalCenter
                color: toggle.checked ? shell.ground : shell.muted
            }
        }
        background: Item { implicitHeight: 32 }
    }

    component StoneField: TextField {
        id: field
        padding: 8
        selectByMouse: true
        background: Frame {
            implicitHeight: 36
            focused: field.activeFocus
            border.color: field.activeFocus ? shell.ink : shell.edge
            color: shell.raised
        }
    }

    component StoneCheck: CheckBox {
        id: check
        padding: 4
        spacing: 8
        contentItem: Label {
            text: check.text
            color: check.enabled ? shell.ink : shell.muted
            leftPadding: check.indicator.width + check.spacing
            verticalAlignment: Text.AlignVCenter
        }
        indicator: Frame {
            implicitWidth: 16
            implicitHeight: 16
            x: check.leftPadding
            y: (check.height - height) / 2
            focused: check.visualFocus
            color: check.checked ? shell.ink : check.hovered ? shell.hoverStone : shell.ground
            border.color: check.visualFocus ? shell.ink : shell.edge
            Item {
                visible: check.checked
                width: 9
                height: 6
                anchors.centerIn: parent
                rotation: -45
                Rectangle { width: 2; height: 5; color: shell.ground }
                Rectangle { width: 9; height: 2; color: shell.ground; anchors.bottom: parent.bottom }
            }
        }
    }

    component ScreenPanel: Pane {
        Layout.fillWidth: true
        padding: 0
        background: null
    }

    component PageTitle: Label {
        font.pixelSize: 30
        font.bold: true
        textFormat: Text.PlainText
    }

    component SectionTitle: Label {
        font.pixelSize: 16
        font.bold: true
        textFormat: Text.PlainText
    }

    component Rule: Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: shell.palette.mid
    }

    component BodyText: Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }

    component SingleLine: Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        elide: Text.ElideRight
        HoverHandler { id: lineHover }
        ToolTip.visible: lineHover.hovered && truncated
        ToolTip.delay: 500
        ToolTip.text: text
    }

    component Metric: ColumnLayout {
        required property string title
        required property string value
        property string detail: ""
        property alias valueObjectName: reading.objectName
        property alias detailObjectName: subtext.objectName
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 4
        Caption {
            Layout.fillWidth: true
            text: parent.title
            wrapMode: Text.Wrap
        }
        Label {
            id: reading
            Layout.fillWidth: true
            text: parent.value
            textFormat: Text.PlainText
            font.pixelSize: 17
            font.bold: true
            font.features: {"tnum": 1}
            wrapMode: Text.Wrap
        }
        Caption {
            id: subtext
            Layout.fillWidth: true
            visible: text.length > 0
            text: parent.detail
            wrapMode: Text.Wrap
        }
    }

    component SessionFacts: ColumnLayout {
        property alias stopReasonObjectName: stopReason.objectName
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 8
        GridLayout {
            Layout.fillWidth: true
            columns: 3
            uniformCellWidths: true
            columnSpacing: 12
            rowSpacing: 12
            Repeater {
                model: shell.history.session_facts
                delegate: Metric {
                    required property var modelData
                    title: modelData.label
                    value: modelData.value
                }
            }
        }
        Caption {
            id: stopReason
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: qsTr("Stop reason: %1").arg(shell.history.stop_reason)
        }
        Caption {
            Layout.fillWidth: true
            visible: shell.history.failure_reasons.length > 0
            wrapMode: Text.Wrap
            text: qsTr("Attempt failures: %1").arg(shell.history.failure_reasons)
        }
    }

    component NightReport: ColumnLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 8
        SectionTitle { text: qsTr("Night") }
        Caption {
            Layout.fillWidth: true
            text: shell.history.night.window
            wrapMode: Text.Wrap
        }
        Caption {
            Layout.fillWidth: true
            visible: shell.history.night.totals.length === 0
            text: qsTr("No recorded AFK sessions overlapped this window.")
            wrapMode: Text.Wrap
        }
        GridLayout {
            visible: shell.history.night.totals.length > 0
            Layout.fillWidth: true
            columns: 3
            uniformCellWidths: true
            columnSpacing: 12
            Repeater {
                model: shell.history.night.totals
                delegate: Metric {
                    required property var modelData
                    title: modelData.label
                    value: modelData.value
                }
            }
        }
    }

    header: Pane {
        horizontalPadding: shell.gutter
        topPadding: 0
        bottomPadding: 0
        background: Rectangle {
            color: shell.raised
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: shell.hairline }
        }
        contentItem: RowLayout {
            spacing: shell.width >= 1280 ? 24 : shell.compact ? 12 : 16
            SingleLine {
                Layout.fillWidth: false
                Layout.preferredWidth: shell.width >= 1280 ? 218 : implicitWidth
                text: shell.title
                font.pixelSize: shell.compact ? 20 : 23
                font.bold: true
            }
            TabBar {
                id: tabs
                objectName: "screenTabs"
                Accessible.name: qsTr("Screens")
                Layout.fillWidth: true
                Layout.preferredHeight: shell.compact ? 48 : 64
                background: null
                spacing: 4
                onCurrentIndexChanged: if (scroll.contentItem) scroll.contentItem.contentY = 0
                StoneTab { id: afkTab; objectName: "afkTab"; text: qsTr("AFK session"); height: tabs.height }
                StoneTab { objectName: "historyTab"; text: qsTr("History"); height: tabs.height }
                StoneTab { objectName: "updatesTab"; text: qsTr("Updates"); height: tabs.height }
                StoneTab { objectName: "quarantineTab"; text: qsTr("Health"); height: tabs.height }
            }
            Caption {
                Layout.alignment: Qt.AlignRight
                text: shell.compact ? qsTr("Local profile")
                      : Qt.platform.os === "windows" ? qsTr("Windows · local profile") : qsTr("Linux · local profile")
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        padding: 0
        ScrollBar.vertical: StoneScrollBar {
            parent: scroll
            anchors.top: scroll.top
            anchors.right: scroll.right
            anchors.bottom: scroll.bottom
        }
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        clip: true

        Item {
            implicitWidth: scroll.availableWidth
            implicitHeight: page.implicitHeight + 32

            ColumnLayout {
                id: page
                anchors.top: parent.top
                anchors.topMargin: 16
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: shell.gutter
                anchors.rightMargin: shell.gutter
                spacing: 16

                ColumnLayout {
                    id: afk
                    visible: tabs.currentIndex === 0
                    Layout.fillWidth: true
                    spacing: 16
                    readonly property var runParts: shell.session.current_run === "—"
                        ? [] : shell.session.current_run.split(" · ")
                    readonly property bool hasRun: runParts.length > 0
                    readonly property string zenyTotal: shell.session.active
                        ? shell.amount(shell.session.session_numbers.zeny)
                        : shell.history.latest_session_zeny
                    readonly property bool hasRate: shell.session.zeny !== "—"
                    readonly property int rotationCount: shell.session.locations
                        .filter(row => typeof row.id === "string" && row.enabled).length

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumHeight: shell.compact ? 100 : 120
                        spacing: shell.compact ? 12 : 24
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Rectangle {
                                    Layout.preferredWidth: 8
                                    Layout.preferredHeight: 8
                                    radius: 2
                                    color: shell.runLocked && shell.session.can_pause ? shell.redOchre
                                           : shell.session.paused ? shell.ochre
                                           : shell.session.service_missing || shell.quarantine.reason ? shell.danger
                                           : shell.muted
                                }
                                Label {
                                    objectName: "phaseValue"
                                    Layout.fillWidth: shell.compact
                                    Layout.minimumWidth: 0
                                    font.bold: true
                                    text: shell.session.phase
                                    textFormat: Text.PlainText
                                    elide: Text.ElideRight
                                }
                                Rectangle {
                                    visible: !shell.compact && shell.session.heartbeat_age !== "—"
                                    Layout.preferredWidth: 1
                                    Layout.preferredHeight: 16
                                    Layout.leftMargin: 8
                                    Layout.rightMargin: 4
                                    color: shell.edge
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    visible: !shell.compact && shell.session.heartbeat_age !== "—"
                                    elide: Text.ElideRight
                                    text: qsTr("Last heartbeat · %1").arg(shell.session.heartbeat_age)
                                }
                            }
                            Caption {
                                Layout.fillWidth: true
                                visible: shell.compact && shell.session.heartbeat_age !== "—"
                                text: qsTr("Last heartbeat · %1").arg(shell.session.heartbeat_age)
                                elide: Text.ElideRight
                            }
                            PageTitle {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: afk.hasRun ? afk.runParts.slice(0, 2).join(" · ")
                                      : shell.session.paused ? qsTr("AFK session paused")
                                      : shell.runLocked ? qsTr("AFK session active")
                                      : shell.session.service_missing ? qsTr("Start the background service")
                                      : shell.quarantine.reason ? qsTr("AFK session on hold")
                                      : qsTr("Set up an AFK session")
                            }
                            SingleLine {
                                visible: text.length > 0
                                color: shell.muted
                                font.pixelSize: 13
                                text: [shell.session.run_detail, afk.runParts.slice(2).join(" · ")]
                                    .filter(Boolean).join(" · ")
                            }
                            Caption {
                                objectName: "sessionValue"
                                Layout.fillWidth: true
                                visible: !afk.hasRun && text.length > 0
                                text: shell.session.session_id
                                elide: Text.ElideRight
                            }
                        }
                        ColumnLayout {
                            visible: afk.zenyTotal.length > 0 || afk.hasRate
                            Layout.preferredWidth: Math.min(implicitWidth, afk.width * (shell.compact ? 0.47 : 0.45))
                            Layout.minimumWidth: 0
                            spacing: 0
                            Caption {
                                Layout.alignment: Qt.AlignRight
                                visible: afk.zenyTotal.length > 0
                                text: shell.session.active ? qsTr("Zeny this session") : qsTr("Zeny latest session")
                            }
                            Label {
                                Layout.fillWidth: true
                                visible: afk.zenyTotal.length > 0
                                horizontalAlignment: Text.AlignRight
                                text: afk.zenyTotal
                                color: shell.ochre
                                font.family: boldFont.name
                                font.bold: true
                                font.pixelSize: shell.compact ? 44 : 56
                                font.features: {"tnum": 1}
                                fontSizeMode: Text.HorizontalFit
                                minimumPixelSize: 28
                                elide: Text.ElideLeft
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignRight
                                visible: afk.hasRate
                                spacing: 4
                                Caption { objectName: "zenyValue"; text: shell.session.zeny }
                                Caption { text: qsTr("zeny/h") }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Rule {}
                        RunBand {
                            objectName: "sessionRunBand"
                            theme: shell
                            runs: shell.session.session_runs
                            currentNumber: shell.session.current_number
                            heading: qsTr("Run rotation")
                            subtitle: !shell.compact && shell.session.active && afk.rotationCount > 0
                                ? qsTr("%1 locations").arg(afk.rotationCount) : ""
                            emptyText: shell.session.active ? qsTr("Waiting for the first run to appear.")
                                : shell.history.latest_session_id.length > 0 ? qsTr("No settled runs in the latest session.")
                                : qsTr("Completed runs will appear here in rotation order.")
                        }
                        Rule { Layout.topMargin: shell.width >= 1000 ? 12 : 4 }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: shell.width < 1000 ? 1 : 2
                        columnSpacing: shell.width >= 1280 ? 56 : 32
                        rowSpacing: 24
                        uniformCellWidths: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.minimumWidth: 0
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.bottomMargin: 4
                                spacing: 12
                                SectionTitle { text: qsTr("Run choice") }
                                Caption {
                                    Layout.fillWidth: true
                                    visible: shell.runLocked
                                    horizontalAlignment: Text.AlignRight
                                    text: qsTr("Locked while running · editable when paused")
                                    elide: Text.ElideRight
                                }
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                uniformCellWidths: true
                                columnSpacing: 16
                                rowSpacing: 8
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 4
                                    Caption { id: characterLabel; text: qsTr("Character") }
                                    StoneCombo {
                                        objectName: "characterPicker"
                                        Accessible.name: characterLabel.text
                                        model: shell.session.characters
                                        currentIndex: shell.session.character_index
                                        displayText: shell.session.tower_selected ? qsTr("From Tower snapshot") : currentText
                                        enabled: shell.session.can_pick_character
                                        onActivated: index => shell.backend.selectCharacter(index)
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 4
                                    Caption { id: presetLabel; text: qsTr("Preset") }
                                    StoneCombo {
                                        objectName: "presetPicker"
                                        Accessible.name: presetLabel.text
                                        model: shell.session.presets
                                        currentIndex: shell.session.preset_index
                                        enabled: shell.session.can_pick_preset
                                        onActivated: index => shell.backend.selectPreset(index)
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 4
                                    Caption { id: locationLabel; text: qsTr("Location") }
                                    StoneCombo {
                                        id: locationPicker
                                        objectName: "locationPicker"
                                        Accessible.name: locationLabel.text
                                        model: shell.session.locations
                                        textRole: "label"
                                        currentIndex: shell.session.location_index
                                        displayText: currentIndex < 0 ? qsTr("Saved location unavailable") : currentText
                                        enabled: shell.session.can_pick_location && (count > 1 || currentIndex < 0)
                                        minimumPopupWidth: 420

                                        delegate: PickOption {
                                            required property int index
                                            required property var modelData
                                            objectName: "locationOption" + index
                                            width: ListView.view.width
                                            text: enabled ? modelData.label : modelData.reason
                                                ? qsTr("%1 — %2").arg(modelData.label).arg(modelData.reason)
                                                : qsTr("%1 (locked)").arg(modelData.label)
                                            Accessible.description: modelData.reason || ""
                                            enabled: modelData.enabled
                                            highlighted: locationPicker.highlightedIndex === index
                                        }

                                        function stepLocation(step) {
                                            for (let i = currentIndex + step; i >= 0 && i < count; i += step) {
                                                if (model[i].enabled) {
                                                    shell.backend.selectLocation(i)
                                                    break
                                                }
                                            }
                                        }

                                        Keys.onUpPressed: event => {
                                            event.accepted = !popup.visible
                                            if (event.accepted)
                                                stepLocation(-1)
                                        }
                                        Keys.onDownPressed: event => {
                                            event.accepted = !popup.visible
                                            if (event.accepted)
                                                stepLocation(1)
                                        }
                                        onActivated: index => {
                                            if (model[index].enabled)
                                                shell.backend.selectLocation(index)
                                            else
                                                currentIndex = Qt.binding(() => shell.session.location_index)
                                        }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    visible: !shell.session.tower_selected
                                    spacing: 4
                                    Caption { id: difficultyLabel; text: qsTr("Difficulty") }
                                    StoneCombo {
                                        objectName: "difficultyPicker"
                                        Accessible.name: difficultyLabel.text
                                        model: shell.session.difficulties
                                        currentIndex: shell.session.difficulty_index
                                        displayText: currentIndex < 0 ? qsTr("Saved difficulty unavailable") : currentText
                                        enabled: shell.session.can_pick_run_choice && (count > 1 || currentIndex < 0)
                                        onActivated: index => shell.backend.selectDifficulty(textAt(index))
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    visible: shell.session.tower_normal
                                    spacing: 4
                                    Caption { id: towerFloorLabel; text: qsTr("Start floor") }
                                    StoneCombo {
                                        objectName: "towerFloorPicker"
                                        Accessible.name: towerFloorLabel.text
                                        model: shell.session.tower_floors
                                        currentIndex: shell.session.tower_floor_index
                                        displayText: currentIndex < 0 ? qsTr("Saved floor unavailable") : currentText
                                        enabled: shell.session.can_pick_location && count > 0 && (count > 1 || currentIndex < 0)
                                        onActivated: index => shell.backend.selectTowerFloor(Number(textAt(index)))
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                visible: shell.session.tower_selected
                                spacing: 4
                                Caption {
                                    objectName: "towerRules"
                                    Layout.fillWidth: true
                                    text: qsTr("The Tower sets Difficulty and Oaths.")
                                    wrapMode: Text.Wrap
                                }
                                Caption {
                                    objectName: "towerSnapshotCaption"
                                    Layout.fillWidth: true
                                    visible: shell.session.tower_snapshot.length > 0
                                    text: qsTr("Starting spends this snapshot")
                                    wrapMode: Text.Wrap
                                }
                                BodyText {
                                    objectName: "towerSnapshot"
                                    visible: text.length > 0
                                    text: shell.session.tower_snapshot
                                }
                            }

                            Disclosure {
                                id: oathPanel
                                objectName: "oathPanel"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                visible: shell.session.oaths.length > 0
                                enabled: !shell.runLocked && shell.session.can_pick_oaths
                                text: checked && enabled ? qsTr("Hide oaths") : qsTr("Oaths")
                                Accessible.name: checked && enabled ? text : qsTr("Show oaths")
                                Accessible.description: detail
                                detailObjectName: "oathPoints"
                                detail: shell.session.difficulties[shell.session.difficulty_index] === "30"
                                    ? qsTr("Oath points: %1").arg(shell.session.oath_points)
                                    : qsTr("Oaths require fixed difficulty 30.")
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                visible: oathPanel.visible && oathPanel.checked && oathPanel.enabled
                                columns: 2
                                uniformCellWidths: true
                                columnSpacing: 16
                                rowSpacing: 8
                                Repeater {
                                    model: shell.session.oaths.length
                                    delegate: ColumnLayout {
                                        id: oathRow
                                        required property int index
                                        readonly property var oath: shell.session.oaths[index]
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignTop
                                        Layout.minimumWidth: 0
                                        spacing: 4
                                        Caption {
                                            id: oathName
                                            objectName: "oathLabel" + oathRow.index
                                            Layout.fillWidth: true
                                            text: oathRow.oath.label
                                            wrapMode: Text.Wrap
                                        }
                                        StoneCombo {
                                            id: rankPicker
                                            objectName: "oathPicker" + oathRow.index
                                            Accessible.name: oathName.text
                                            model: oathRow.oath.ranks.length
                                            currentIndex: oathRow.oath.selected_index
                                            displayText: currentIndex < 0 ? qsTr("Saved rank unavailable") : rankText(currentIndex)
                                            onActivated: index => shell.backend.selectOath(oathRow.oath.id, oathRow.oath.ranks[index].rank)
                                            function rankText(index) {
                                                const rank = oathRow.oath.ranks[index]
                                                return rank.rank === 0 ? qsTr("Off") : qsTr("Rank %1 (%2 pts)").arg(rank.rank).arg(rank.points)
                                            }
                                            delegate: PickOption {
                                                required property int index
                                                width: ListView.view.width
                                                text: rankPicker.rankText(index)
                                                highlighted: rankPicker.highlightedIndex === index
                                            }
                                        }
                                        Caption {
                                            objectName: "oathRankDetail" + oathRow.index
                                            Layout.fillWidth: true
                                            text: rankPicker.currentIndex < 0 ? qsTr("Choose another rank or turn this oath off.")
                                                : oathRow.oath.ranks[rankPicker.currentIndex].description
                                            visible: text.length > 0
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                uniformCellWidths: true
                                columnSpacing: 16
                                StoneSwitch {
                                    objectName: "keepUnownedLegendaries"
                                    text: qsTr("Keep every legendary I don't own yet")
                                    checked: shell.session.keep_unowned_legendaries
                                    enabled: shell.session.can_pick_run_choice
                                    onToggled: shell.backend.setKeepUnownedLegendaries(checked)
                                    Layout.alignment: Qt.AlignTop
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Layout.alignment: Qt.AlignTop
                                    spacing: 0
                                    StoneSwitch {
                                        id: windowSwitch
                                        objectName: "showGameWindow"
                                        text: qsTr("Show game window")
                                        readonly property string helpText: qsTr("Applies at the next game launch. Closing the game window is treated as a game exit; the supervisor may restart it.")
                                        Accessible.description: checked ? helpText + " " + windowIncomeWarning.text : helpText
                                        ToolTip.text: helpText
                                        ToolTip.visible: hovered || activeFocus
                                        ToolTip.delay: 350
                                        checked: shell.session.show_game_window
                                        enabled: !shell.runLocked && shell.session.can_change_show_game_window
                                        onToggled: shell.backend.setShowGameWindow(checked)
                                    }
                                    Caption {
                                        id: windowIncomeWarning
                                        objectName: "windowIncomeWarning"
                                        Layout.fillWidth: true
                                        visible: windowSwitch.checked
                                        color: shell.warning
                                        text: qsTr("Windowed mode roughly halves income.")
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }

                            Rule {}
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 0
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Label { text: qsTr("Wishlist"); font.bold: true }
                                        Caption {
                                            Layout.fillWidth: true
                                            text: shell.session.wishlist_count === 1 ? qsTr("· 1 item")
                                                : qsTr("· %1 items").arg(shell.session.wishlist_count)
                                            elide: Text.ElideRight
                                        }
                                    }
                                    SingleLine {
                                        visible: text.length > 0
                                        color: shell.muted
                                        font.pixelSize: 13
                                        text: shell.session.wishlist_items.filter(row => row.selected)
                                            .map(row => row.label).join(", ")
                                    }
                                }
                                ActionButton {
                                    id: wishlistPanel
                                    objectName: "wishlistPanel"
                                    enabled: shell.session.can_edit_wishlist
                                    checkable: true
                                    disclosure: true
                                    text: checked && enabled ? qsTr("Hide wishlist") : qsTr("Search wishlist")
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: wishlistPanel.checked && wishlistPanel.enabled
                                spacing: 4

                                Caption { id: wishlistSearchLabel; text: qsTr("Search legendary items by name") }
                                StoneField {
                                    id: wishlistSearch
                                    objectName: "wishlistSearch"
                                    Accessible.name: wishlistSearchLabel.text
                                    Layout.fillWidth: true
                                }
                                StoneCheck {
                                    id: wishlistOnly
                                    text: qsTr("Show wishlist only")
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    StoneCombo {
                                        id: wishlistPicker
                                        objectName: "wishlistPicker"
                                        Accessible.name: qsTr("Matching legendary items")
                                        property string itemId: ""
                                        readonly property var option: model[currentIndex] ?? null
                                        model: {
                                            const query = wishlistSearch.text.trim().toLocaleLowerCase()
                                            return shell.session.wishlist_items.filter(row =>
                                                (!wishlistOnly.checked || row.selected) &&
                                                row.label.toLocaleLowerCase().includes(query))
                                        }
                                        textRole: "label"
                                        currentIndex: count ? Math.max(0, model.findIndex(row => row.id === itemId)) : -1
                                        onActivated: index => itemId = model[index].id
                                        displayText: option ? optionText(option) : qsTr("No matching items")
                                        enabled: count > 0

                                        function optionText(row) {
                                            return row.owned ? qsTr("%1 (owned)").arg(row.label) : row.label
                                        }
                                        delegate: PickOption {
                                            required property int index
                                            required property var modelData
                                            width: ListView.view.width
                                            text: wishlistPicker.optionText(modelData)
                                            highlighted: wishlistPicker.highlightedIndex === index
                                        }
                                    }
                                    ActionButton {
                                        objectName: "wishlistAction"
                                        enabled: wishlistPicker.option !== null
                                        text: wishlistPicker.option?.selected ? qsTr("Remove") : qsTr("Add")
                                        onClicked: {
                                            const item = wishlistPicker.option
                                            wishlistPicker.itemId = item.id
                                            shell.backend.setWishlisted(item.id, !item.selected)
                                        }
                                    }
                                }
                            }

                            Rule {}
                            Label {
                                visible: shell.runLocked
                                text: qsTr("Maintenance")
                                font.bold: true
                            }
                            Disclosure {
                                id: maintenancePanel
                                objectName: "maintenancePanel"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                visible: !shell.runLocked
                                enabled: shell.session.can_edit_maintenance
                                text: checked && enabled ? qsTr("Hide maintenance") : qsTr("Maintenance")
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                visible: shell.runLocked || (maintenancePanel.checked && maintenancePanel.enabled)
                                enabled: !shell.runLocked && shell.session.can_edit_maintenance
                                columns: 2
                                uniformCellWidths: true
                                columnSpacing: 16
                                rowSpacing: 0
                                Repeater {
                                    model: [
                                        { key: "upgrades", label: qsTr("Kafra/Sage upgrades") },
                                        { key: "card_fusion", label: qsTr("Card fusion") },
                                        { key: "star_smith", label: qsTr("Star Smith") },
                                        { key: "storage_cleanup", label: qsTr("Storage cleanup") }
                                    ]
                                    delegate: StoneSwitch {
                                        required property var modelData
                                        objectName: "maintenance-" + modelData.key
                                        text: modelData.label
                                        checked: shell.session.maintenance[modelData.key]
                                        onToggled: shell.backend.setMaintenance(modelData.key, checked)
                                    }
                                }
                            }
                            Caption {
                                Layout.fillWidth: true
                                visible: text.length > 0
                                text: shell.session.preset_description
                                wrapMode: Text.Wrap
                            }
                            Caption {
                                objectName: "catalogRefresh"
                                Layout.fillWidth: true
                                text: shell.session.catalog_refresh
                                    ? qsTr("Catalog refreshed: %1").arg(shell.session.catalog_refresh) : qsTr("No catalog yet")
                                wrapMode: Text.Wrap
                            }
                        }

                        ColumnLayout {
                            visible: !shell.session.active
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.alignment: Qt.AlignTop
                            spacing: 12
                            RowLayout {
                                Layout.fillWidth: true
                                SectionTitle {
                                    objectName: "latestSessionHeading"
                                    Layout.fillWidth: true
                                    text: qsTr("Latest session")
                                }
                                Caption { text: shell.history.latest_session_date }
                            }
                            Caption {
                                Layout.fillWidth: true
                                visible: shell.history.latest_session_id.length === 0
                                text: qsTr("No completed AFK session yet.")
                                wrapMode: Text.Wrap
                            }
                            SessionFacts {
                                visible: shell.history.latest_session_id.length > 0
                                stopReasonObjectName: "latestSessionStopReason"
                            }
                            Rule {}
                            NightReport { objectName: "afkNightReport" }
                        }

                        ColumnLayout {
                            id: tally
                            visible: shell.session.active
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.alignment: Qt.AlignTop
                            spacing: 8
                            readonly property var numbers: shell.session.session_numbers
                            readonly property var readings: shell.session.session_metrics
                            readonly property var measurementNames: {
                                const preferred = ["Kills", "Star Crumb", "Oridecon", "Elunium", "Legend Coin"]
                                const keys = Object.keys(readings)
                                return preferred.filter(key => keys.includes(key))
                                    .concat(keys.filter(key => key !== "Cards" && !preferred.includes(key)))
                                    .concat(keys.includes("Cards") ? ["Cards"] : [])
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.bottomMargin: 4
                                spacing: 12
                                SectionTitle {
                                    Layout.fillWidth: true
                                    text: qsTr("Session so far")
                                }
                                Caption {
                                    visible: shell.session.session_duration >= 60
                                    text: shell.elapsed(shell.session.session_duration)
                                }
                            }
                            Caption {
                                Layout.fillWidth: true
                                visible: tally.numbers.runs === undefined
                                wrapMode: Text.Wrap
                                text: qsTr("Totals appear as the farmer reports its progress.")
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: tally.numbers.runs !== undefined
                                spacing: 12
                                Repeater {
                                    model: [
                                        {key: "runs", label: qsTr("Runs")},
                                        {key: "wins", label: qsTr("Wins")},
                                        {key: "losses", label: qsTr("Losses")}
                                    ]
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        visible: tally.numbers[modelData.key] !== undefined
                                        spacing: 0
                                        Caption { text: parent.modelData.label }
                                        Label {
                                            text: shell.amount(tally.numbers[parent.modelData.key])
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                            font.pixelSize: 36
                                            font.bold: true
                                            font.features: {"tnum": 1}
                                        }
                                    }
                                }
                            }
                            Rule { visible: tally.measurementNames.length > 0 }
                            Repeater {
                                model: tally.measurementNames
                                delegate: RowLayout {
                                    required property string modelData
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 36
                                    spacing: 12
                                    SingleLine { text: parent.modelData }
                                    Caption {
                                        visible: parent.modelData === "Kills" && shell.session.kills !== "—"
                                        text: qsTr("%1/min").arg(shell.session.kills)
                                    }
                                    Label {
                                        text: modelData === "Cards" && tally.readings[modelData] > 0
                                            ? "+" + shell.amount(tally.readings[modelData])
                                            : shell.amount(tally.readings[modelData])
                                        font.pixelSize: 24
                                        font.bold: true
                                        font.features: {"tnum": 1}
                                    }
                                }
                            }
                        }
                    }
                }

                ScreenPanel {
                    id: historyPanel
                    visible: tabs.currentIndex === 1
                    property string expandedSession: ""
                    ColumnLayout {
                        width: parent.width
                        spacing: 12
                        PageTitle { text: qsTr("History") }
                        NightReport { objectName: "historyNightReport" }
                        Caption {
                            visible: shell.history.rows.length === 0
                            text: qsTr("Completed AFK sessions and update events will appear here.")
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        Repeater {
                            objectName: "historyRows"
                            model: shell.history.rows
                            delegate: ColumnLayout {
                                id: entry
                                required property var modelData
                                required property int index
                                readonly property bool latestSession: modelData.session_id !== ""
                                    && modelData.session_id === shell.history.latest_session_id
                                readonly property bool expandable: latestSession || modelData.run_choices.length > 0
                                readonly property bool expanded: expandable
                                    && historyPanel.expandedSession === modelData.session_id
                                Layout.fillWidth: true
                                spacing: 8
                                Layout.bottomMargin: 8
                                Rule {}
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Caption { text: entry.modelData.date; font.features: {"tnum": 1} }
                                    SingleLine {
                                        objectName: "historyRow" + entry.index
                                        font.bold: true
                                        text: entry.modelData.title + (entry.modelData.summary ? " · " + entry.modelData.summary : "")
                                    }
                                    ActionButton {
                                        objectName: entry.latestSession ? "latestSessionDisclosure" : ""
                                        visible: entry.expandable
                                        text: entry.expanded ? qsTr("Hide details")
                                              : entry.latestSession ? qsTr("Latest session") : qsTr("Run choices")
                                        Accessible.name: !entry.expanded && entry.latestSession
                                                         ? qsTr("Show details for the latest session") : text
                                        onClicked: historyPanel.expandedSession = entry.expanded ? "" : entry.modelData.session_id
                                    }
                                }
                                RunBand {
                                    theme: shell
                                    runs: entry.modelData.session_runs
                                    visible: runs.length > 0
                                    small: true
                                }
                                ColumnLayout {
                                    objectName: entry.latestSession ? "latestSessionDetails" : ""
                                    visible: entry.expanded
                                    Layout.fillWidth: true
                                    Layout.topMargin: 4
                                    Layout.bottomMargin: 8
                                    spacing: 12
                                    SessionFacts { visible: entry.latestSession && entry.expanded }
                                    GridLayout {
                                        visible: entry.latestSession
                                        Layout.fillWidth: true
                                        columns: shell.compact ? 3 : 5
                                        uniformCellWidths: true
                                        columnSpacing: 12
                                        rowSpacing: 12
                                        Repeater {
                                            model: entry.expanded && entry.latestSession ? shell.history.totals : []
                                            delegate: Metric {
                                                required property var modelData
                                                title: modelData.label
                                                value: modelData.value
                                            }
                                        }
                                    }
                                    Metric {
                                        visible: entry.latestSession
                                        title: qsTr("Rewards per elapsed hour")
                                        value: shell.history.rewards
                                        valueObjectName: "latestSessionRewards"
                                    }
                                    Metric {
                                        visible: entry.latestSession
                                        title: qsTr("Materials")
                                        value: shell.history.materials
                                        valueObjectName: "latestSessionMaterials"
                                    }
                                    Caption { text: qsTr("Session %1").arg(entry.modelData.session_id) }
                                    Repeater {
                                        model: entry.expanded ? entry.modelData.run_choices : []
                                        delegate: Caption {
                                            required property int index
                                            required property string modelData
                                            objectName: "historyRunChoice" + entry.index + "-" + index
                                            Layout.fillWidth: true
                                            text: modelData
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                ScreenPanel {
                    visible: tabs.currentIndex === 2
                    ColumnLayout {
                        width: parent.width
                        spacing: 14
                        PageTitle { text: qsTr("Updates") }
                        Rule {}
                        SectionTitle { text: qsTr("Game update") }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            uniformCellWidths: true
                            columnSpacing: 24
                            Metric {
                                title: qsTr("Patch state")
                                value: shell.updates.game_state
                                valueObjectName: "gameUpdateState"
                                detailObjectName: "gameUpdateDetail"
                                detail: shell.updates.game_detail
                            }
                            Metric {
                                title: qsTr("Last outcome")
                                value: shell.updates.last_outcome
                                valueObjectName: "gameUpdateOutcome"
                                detail: shell.updates.last_detail
                            }
                        }
                        BodyText {
                            objectName: "gameUpdateActivity"
                            visible: text.length > 0
                            text: shell.updates.activity
                            color: shell.warning
                        }
                        Caption {
                            visible: text.length > 0
                            text: shell.updates.activity_detail
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            spacing: 8
                            ActionButton {
                                objectName: "checkAgainButton"
                                text: qsTr("Check again")
                                enabled: !shell.updates.action_blocker
                                onClicked: shell.backend.patchCommand("check_again")
                            }
                            ActionButton {
                                objectName: "restoreOfficialButton"
                                text: qsTr("Restore official patch")
                                enabled: !shell.updates.action_blocker
                                onClicked: shell.backend.patchCommand("restore_official")
                            }
                        }
                        Caption {
                            objectName: "patchActionBlocker"
                            visible: text.length > 0
                            text: shell.updates.action_blocker
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        BodyText {
                            objectName: "patchFeedback"
                            visible: text.length > 0
                            text: shell.updates.feedback
                        }
                        BodyText {
                            visible: text.length > 0
                            text: shell.session.action_error
                            color: shell.danger
                        }
                        Rule {}
                        SectionTitle { text: qsTr("App update") }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            uniformCellWidths: true
                            columnSpacing: 24
                            rowSpacing: 12
                            Metric {
                                title: qsTr("Installed version")
                                value: shell.updates.app_version
                                valueObjectName: "installedAppVersion"
                            }
                            Metric {
                                title: qsTr("Latest available version")
                                value: shell.updates.latest_app_version
                                valueObjectName: "latestAppVersion"
                            }
                            Metric {
                                title: qsTr("Check status")
                                value: shell.updates.app_check
                                valueObjectName: "appUpdateCheck"
                                detailObjectName: "appUpdateCheckReason"
                                detail: shell.updates.app_check_reason
                            }
                            Metric {
                                title: qsTr("Last checked")
                                value: shell.updates.app_last_checked
                                valueObjectName: "appUpdateLastChecked"
                            }
                        }
                        BodyText {
                            text: shell.updates.app_update_detail
                            visible: text.length > 0
                        }
                        RowLayout {
                            spacing: 8
                            ActionButton {
                                objectName: "checkAppUpdatesButton"
                                text: qsTr("Check for updates")
                                enabled: shell.updates.can_check_app
                                onClicked: shell.backend.checkAppUpdates()
                            }
                            ActionButton {
                                objectName: "rollbackAppButton"
                                visible: Boolean(shell.updates.previous_app_version)
                                enabled: shell.updates.can_rollback
                                text: qsTr("Roll back to %1").arg(shell.updates.previous_app_version)
                                onClicked: shell.backend.rollbackApp()
                            }
                        }
                        BodyText {
                            text: shell.updates.rollback_feedback
                            visible: text.length > 0
                        }
                        ColumnLayout {
                            visible: Boolean(shell.updates.app_changelog)
                            Layout.fillWidth: true
                            Layout.maximumWidth: 660
                            Layout.topMargin: 6
                            spacing: 8
                            SectionTitle {
                                text: qsTr("Changelog for %1").arg(shell.updates.latest_app_version)
                            }
                            BodyText {
                                objectName: "appUpdateChangelog"
                                text: shell.updates.app_changelog
                            }
                        }
                    }
                }

                ScreenPanel {
                    visible: tabs.currentIndex === 3
                    ColumnLayout {
                        width: parent.width
                        spacing: 14
                        PageTitle { text: qsTr("Quarantine") }
                        Rule {}
                        Caption {
                            objectName: "noQuarantine"
                            visible: !shell.quarantine.reason
                            text: qsTr("No quarantine active.")
                        }
                        ColumnLayout {
                            visible: Boolean(shell.quarantine.reason)
                            Layout.fillWidth: true
                            spacing: 12
                            BodyText {
                                objectName: "quarantineReason"
                                text: shell.quarantine.reason
                                font.pixelSize: 17
                                font.bold: true
                                color: shell.danger
                            }
                            BodyText { objectName: "quarantineDetail"; text: shell.quarantine.detail }
                            ActionButton {
                                objectName: "quarantineNextAction"
                                text: shell.quarantine.action
                                highlighted: true
                                enabled: !shell.quarantine.needs_check_again || shell.quarantine.can_check_again
                                onClicked: {
                                    if (shell.quarantine.needs_check_again) {
                                        shell.backend.patchCommand("check_again")
                                    } else {
                                        tabs.setCurrentIndex(0)
                                        afkTab.forceActiveFocus()
                                    }
                                }
                            }
                            Caption {
                                visible: shell.quarantine.needs_check_again && !shell.quarantine.can_check_again
                                text: shell.updates.action_blocker
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                            }
                            BodyText {
                                objectName: "quarantineCheckFeedback"
                                visible: text.length > 0
                                text: shell.updates.check_again_feedback
                            }
                            BodyText {
                                visible: text.length > 0
                                text: shell.session.action_error
                                color: shell.danger
                            }
                            Rule {}
                            ActionButton {
                                id: diagnosticsDisclosure
                                objectName: "diagnosticsDisclosure"
                                checkable: true
                                text: checked ? qsTr("Hide attempts and log paths") : qsTr("Show attempts and log paths")
                            }
                            ColumnLayout {
                                objectName: "quarantineDiagnostics"
                                visible: diagnosticsDisclosure.checked
                                Layout.fillWidth: true
                                spacing: 8
                                SectionTitle { text: qsTr("Attempts") }
                                Caption { visible: shell.quarantine.attempts.length === 0; text: qsTr("No attempts recorded.") }
                                Repeater {
                                    model: shell.quarantine.attempts
                                    delegate: BodyText { required property string modelData; text: modelData }
                                }
                                SectionTitle { text: qsTr("Log paths") }
                                Caption { visible: shell.quarantine.paths.length === 0; text: qsTr("No log paths recorded.") }
                                Repeater {
                                    model: shell.quarantine.paths
                                    delegate: TextEdit {
                                        required property string modelData
                                        Layout.fillWidth: true
                                        text: modelData
                                        textFormat: TextEdit.PlainText
                                        color: shell.ink
                                        font: shell.font
                                        selectionColor: shell.ochre
                                        selectedTextColor: shell.ground
                                        wrapMode: TextEdit.WrapAnywhere
                                        readOnly: true
                                        selectByMouse: true
                                    }
                                }
                            }
                        }
                        Rule { Layout.topMargin: 6 }
                        SectionTitle { text: qsTr("Diagnostics") }
                        RowLayout {
                            spacing: 8
                            ActionButton {
                                objectName: "runChecksButton"
                                text: qsTr("Run checks")
                                enabled: !shell.backend.diagnosticsBusy
                                onClicked: shell.backend.runDiagnostics()
                            }
                            ActionButton {
                                objectName: "repairFarmerPackButton"
                                text: qsTr("Repair farmer pack")
                                enabled: !shell.backend.diagnosticsBusy && shell.diagnostics.can_repair
                                onClicked: shell.backend.repairFarmerPack()
                            }
                        }
                        Caption {
                            Layout.fillWidth: true
                            visible: shell.backend.diagnosticsBusy ||
                                     (diagnosticRows.count === 0 && !shell.diagnostics.check_error)
                            text: shell.backend.diagnosticsBusy ? qsTr("Working…")
                                  : qsTr("Run checks to inspect the local game, farmer patch and service.")
                            wrapMode: Text.Wrap
                        }
                        BodyText {
                            text: shell.diagnostics.check_error
                            visible: text.length > 0
                            color: shell.danger
                        }
                        BodyText {
                            objectName: "repairFeedback"
                            text: shell.diagnostics.repair_feedback
                            visible: text.length > 0
                        }
                        Caption {
                            objectName: "repairBlocker"
                            Layout.fillWidth: true
                            text: shell.diagnostics.repair_blocker
                            visible: text.length > 0
                            wrapMode: Text.Wrap
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            visible: diagnosticRows.count > 0
                            Repeater {
                                id: diagnosticRows
                                objectName: "diagnosticRows"
                                model: shell.diagnostics.checks
                                delegate: ColumnLayout {
                                    id: checkRow
                                    required property var modelData
                                    readonly property bool ok: modelData.status === "ok"
                                    readonly property bool failed: modelData.status === "fail"
                                    readonly property color markColor: failed ? shell.danger : shell.ochre
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Rule {}
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 12
                                        Rectangle {
                                            Layout.alignment: Qt.AlignTop
                                            Layout.topMargin: 4
                                            implicitWidth: 18
                                            implicitHeight: 12
                                            radius: 2
                                            color: checkRow.ok ? checkRow.markColor : "transparent"
                                            border.color: checkRow.markColor
                                            border.width: 1
                                            Accessible.ignored: true
                                            Rectangle {
                                                visible: checkRow.failed
                                                anchors.centerIn: parent
                                                width: 16
                                                height: 2
                                                rotation: -31
                                                color: checkRow.markColor
                                            }
                                        }
                                        Caption {
                                            objectName: "diagnosticStatus-" + checkRow.modelData.id
                                            Layout.alignment: Qt.AlignTop
                                            Layout.minimumWidth: 60
                                            text: checkRow.ok ? qsTr("OK") : checkRow.failed ? qsTr("Failed") : qsTr("Warning")
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            spacing: 4
                                            BodyText {
                                                objectName: "diagnosticSummary-" + checkRow.modelData.id
                                                text: checkRow.modelData.summary
                                            }
                                            Caption {
                                                objectName: "diagnosticNextAction-" + checkRow.modelData.id
                                                Layout.fillWidth: true
                                                text: checkRow.modelData.next_action
                                                visible: text.length > 0
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    component FeedbackLine: Label {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        visible: text.length > 0
        HoverHandler { id: feedbackHover }
        ToolTip.visible: feedbackHover.hovered && truncated
        ToolTip.delay: 500
        ToolTip.text: text
    }

    footer: Pane {
        id: actionBar
        readonly property bool stacked: shell.width < 840
        visible: tabs.currentIndex === 0
        horizontalPadding: shell.gutter
        verticalPadding: stacked ? 8 : 16
        implicitHeight: Math.max(stacked ? 0 : 84, implicitContentHeight + topPadding + bottomPadding)
        background: Rectangle {
            color: shell.raised
            Rectangle { width: parent.width; height: 1; color: shell.hairline }
        }
        contentItem: GridLayout {
            columns: 2
            columnSpacing: 24
            rowSpacing: 8
            ColumnLayout {
                Layout.row: 0
                Layout.column: 0
                Layout.columnSpan: actionBar.stacked ? 2 : 1
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 4
                FeedbackLine {
                    id: startRefusal
                    objectName: "startRefusal"
                    text: shell.session.start_refusal ? qsTr("Start refused: %1").arg(shell.session.start_refusal) : ""
                    color: shell.danger
                }
                FeedbackLine {
                    id: resumeRefusal
                    objectName: "resumeRefusal"
                    text: shell.session.resume_refusal ? qsTr("Resume refused: %1").arg(shell.session.resume_refusal) : ""
                    color: shell.danger
                }
                FeedbackLine {
                    id: startReason
                    text: !shell.session.active && !shell.session.service_missing
                        && shell.session.start_reason !== shell.session.start_refusal ? shell.session.start_reason : ""
                    color: shell.warning
                }
                FeedbackLine {
                    id: actionError
                    text: shell.session.action_error
                    color: shell.danger
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: !startRefusal.visible && !resumeRefusal.visible && !startReason.visible && !actionError.visible
                    spacing: 8
                    Label { text: qsTr("Last event ·"); font.bold: true }
                    SingleLine { text: shell.session.last_event || qsTr("No events yet.") }
                }
                Caption {
                    Layout.fillWidth: true
                    text: qsTr("Closing this window leaves the AFK session running in the background service.")
                    wrapMode: Text.Wrap
                }
            }
            RowLayout {
                Layout.row: actionBar.stacked ? 1 : 0
                Layout.column: actionBar.stacked ? 0 : 1
                Layout.columnSpan: actionBar.stacked ? 2 : 1
                Layout.alignment: Qt.AlignRight
                spacing: 8
                ActionButton {
                    objectName: "startButton"
                    text: qsTr("Start AFK session")
                    visible: !shell.session.active && !shell.session.service_missing
                    enabled: shell.session.can_start
                    highlighted: true
                    onClicked: shell.backend.start()
                }
                ActionButton {
                    objectName: "startServiceButton"
                    text: qsTr("Start service")
                    visible: shell.session.service_missing
                    highlighted: true
                    onClicked: shell.backend.startService()
                }
                ActionButton {
                    objectName: "pauseButton"
                    text: shell.session.paused ? qsTr("Resume") : qsTr("Pause")
                    Accessible.description: shell.session.paused ? "" : qsTr("Pause after the current run")
                    ToolTip.text: Accessible.description
                    ToolTip.visible: hovered && ToolTip.text.length > 0
                    ToolTip.delay: 500
                    visible: shell.session.active
                    enabled: shell.session.paused ? shell.session.can_resume : shell.session.can_pause
                    highlighted: true
                    onClicked: shell.backend.control(shell.session.paused ? "resume" : "pause", shell.session.session_id)
                }
                ActionButton {
                    objectName: "finishButton"
                    text: qsTr("Finish after this run")
                    visible: shell.session.active
                    enabled: shell.session.can_control
                    onClicked: shell.backend.control("finish", shell.session.session_id)
                }
                ActionButton {
                    objectName: "abortButton"
                    text: qsTr("Abort")
                    destructive: true
                    visible: shell.session.active
                    enabled: shell.session.can_control
                    onClicked: {
                        abortDialog.sessionId = shell.session.session_id
                        abortDialog.betweenAttempts = !shell.session.can_pause
                        abortDialog.open()
                    }
                }
            }
        }
    }

    Dialog {
        id: abortDialog
        objectName: "abortDialog"
        property string sessionId
        property bool betweenAttempts: false
        anchors.centerIn: Overlay.overlay
        width: Math.min(shell.width - 48, 440)
        modal: true
        closePolicy: Popup.CloseOnEscape
        title: qsTr("Abort AFK session?")
        padding: 24
        spacing: 16
        background: Frame { color: shell.raised; border.color: shell.edge }
        Overlay.modal: Rectangle { color: "#a6171817" }
        header: SectionTitle {
            text: abortDialog.title
            leftPadding: 24
            rightPadding: 24
            topPadding: 24
        }
        onOpened: cancelAbort.forceActiveFocus()
        onAccepted: shell.backend.control("abort", sessionId)

        Label {
            objectName: "abortLoss"
            width: abortDialog.availableWidth
            text: abortDialog.betweenAttempts
                  ? qsTr("There is no active run. Only rewards already banked by the game are kept.")
                  : qsTr("The current run settles; keep is skipped. Only rewards already banked by the game are kept.")
            wrapMode: Text.Wrap
        }
        footer: DialogButtonBox {
            alignment: Qt.AlignRight
            spacing: 8
            leftPadding: 24
            rightPadding: 24
            bottomPadding: 24
            background: null
            ActionButton {
                id: cancelAbort
                objectName: "cancelAbort"
                text: qsTr("Cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            ActionButton {
                objectName: "confirmAbort"
                text: qsTr("Abort session")
                destructive: true
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }
}
