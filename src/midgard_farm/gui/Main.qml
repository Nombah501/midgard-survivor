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
    readonly property bool linux: Qt.platform.os === "linux"
    readonly property color muted: linux ? "#acc9bd" : palette.windowText
    readonly property color warning: linux ? "#ffdbab" : palette.windowText
    readonly property color danger: linux ? "#ffb5b5" : palette.windowText

    title: qsTr("Midgard Farm")
    visible: true
    width: 860
    height: 660
    minimumWidth: 640
    minimumHeight: 520

    SystemPalette { id: systemColors }
    palette.window: linux ? "#13251f" : systemColors.window
    palette.windowText: linux ? "#eef7f2" : systemColors.windowText
    palette.base: linux ? "#1b3229" : systemColors.base
    palette.alternateBase: linux ? "#183027" : systemColors.alternateBase
    palette.text: linux ? "#eef7f2" : systemColors.text
    palette.button: linux ? "#254338" : systemColors.button
    palette.buttonText: linux ? "#eef7f2" : systemColors.buttonText
    palette.mid: linux ? "#44675a" : systemColors.mid
    palette.highlight: linux ? "#a4dec7" : systemColors.highlight
    palette.highlightedText: linux ? "#13251f" : systemColors.highlightedText

    component Caption: Label {
        color: shell.muted
        font.pixelSize: 13
        textFormat: Text.PlainText
    }

    component ActionButton: Button {
        leftPadding: 12
        rightPadding: 12
        Layout.minimumHeight: 44
    }

    component ScreenPanel: Pane {
        Layout.fillWidth: true
        padding: 20
        background: Rectangle {
            color: shell.palette.base
            radius: 12
            border.color: shell.palette.mid
        }
    }

    component PageTitle: Label {
        font.pixelSize: 22
        font.weight: Font.DemiBold
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
        Caption { text: parent.title }
        Label {
            id: reading
            Layout.fillWidth: true
            text: parent.value
            textFormat: Text.PlainText
            font.pixelSize: 17
            font.weight: Font.DemiBold
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

    ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        clip: true

        Item {
            implicitWidth: scroll.availableWidth
            implicitHeight: page.implicitHeight + 48

            ColumnLayout {
                id: page
                anchors.horizontalCenter: parent.horizontalCenter
                y: 24
                width: Math.min(parent.width - 48, 900)
                spacing: 16

                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("Midgard Farm")
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                    }
                    Caption { text: qsTr("One device · Local profile") }
                }

                TabBar {
                    id: tabs
                    objectName: "screenTabs"
                    Accessible.name: qsTr("Screens")
                    Layout.fillWidth: true
                    onCurrentIndexChanged: scroll.contentItem.contentY = 0
                    TabButton { id: afkTab; objectName: "afkTab"; text: qsTr("AFK session"); height: 44 }
                    TabButton { objectName: "historyTab"; text: qsTr("History"); height: 44 }
                    TabButton { objectName: "updatesTab"; text: qsTr("Updates"); height: 44 }
                    TabButton { objectName: "quarantineTab"; text: qsTr("Quarantine"); height: 44 }
                }

                ScreenPanel {
                    visible: tabs.currentIndex === 0

                    ColumnLayout {
                        width: parent.width
                        spacing: 14

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 24
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Caption { text: qsTr("Phase") }
                                Label {
                                    objectName: "phaseValue"
                                    Layout.fillWidth: true
                                    text: shell.session.phase
                                    textFormat: Text.PlainText
                                    color: shell.session.service_missing ? shell.warning : shell.palette.windowText
                                    font.pixelSize: 24
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.Wrap
                                }
                            }
                            Metric {
                                Layout.fillWidth: false
                                Layout.minimumWidth: 136
                                title: qsTr("Last heartbeat")
                                value: shell.session.heartbeat_age
                            }
                        }

                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: shell.palette.mid }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            uniformCellWidths: true
                            rowSpacing: 12
                            columnSpacing: 24
                            Metric {
                                title: qsTr("Zeny per hour")
                                value: shell.session.zeny
                                valueObjectName: "zenyValue"
                            }
                            Metric {
                                title: qsTr("Current run")
                                value: shell.session.current_run
                                detail: shell.session.run_detail
                            }
                            Metric { title: qsTr("Ore / Star Crumb per hour"); value: shell.session.materials }
                            Metric { title: qsTr("Run totals"); value: shell.session.run_totals }
                            Metric { title: qsTr("Kills per minute"); value: shell.session.kills }
                            Metric {
                                visible: value.length > 0
                                title: qsTr("Session ID")
                                value: shell.session.session_id
                                valueObjectName: "sessionValue"
                            }
                        }

                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: shell.palette.mid }

                        Label {
                            text: qsTr("Session setup")
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: width >= 700 ? 4 : 2
                            uniformCellWidths: true
                            columnSpacing: 12
                            rowSpacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: 4
                                Caption { id: characterLabel; text: qsTr("Character") }
                                ComboBox {
                                    objectName: "characterPicker"
                                    Accessible.name: characterLabel.text
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 44
                                    model: shell.session.characters
                                    currentIndex: shell.session.character_index
                                    enabled: shell.session.can_pick_character
                                    onActivated: index => shell.backend.selectCharacter(index)
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: 4
                                Caption { id: presetLabel; text: qsTr("Preset") }
                                ComboBox {
                                    objectName: "presetPicker"
                                    Accessible.name: presetLabel.text
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 44
                                    model: shell.session.presets
                                    currentIndex: shell.session.preset_index
                                    enabled: shell.session.can_pick_preset
                                    onActivated: index => shell.backend.selectPreset(index)
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: 4
                                Caption { id: locationLabel; text: qsTr("Location") }
                                ComboBox {
                                    id: locationPicker
                                    objectName: "locationPicker"
                                    Accessible.name: locationLabel.text
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 44
                                    model: shell.session.locations
                                    textRole: "label"
                                    currentIndex: shell.session.location_index
                                    displayText: currentIndex < 0 ? qsTr("Saved location unavailable") : currentText
                                    enabled: shell.session.can_pick_run_choice && (count > 1 || currentIndex < 0)

                                    delegate: ItemDelegate {
                                        required property int index
                                        required property var modelData
                                        objectName: "locationOption" + index
                                        width: locationPicker.width
                                        text: enabled ? modelData.label : qsTr("%1 (locked)").arg(modelData.label)
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
                                Layout.preferredWidth: 1
                                spacing: 4
                                Caption { id: difficultyLabel; text: qsTr("Difficulty") }
                                ComboBox {
                                    objectName: "difficultyPicker"
                                    Accessible.name: difficultyLabel.text
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 44
                                    model: shell.session.difficulties
                                    currentIndex: shell.session.difficulty_index
                                    displayText: currentIndex < 0 ? qsTr("Saved difficulty unavailable") : currentText
                                    enabled: shell.session.can_pick_run_choice && (count > 1 || currentIndex < 0)
                                    onActivated: index => shell.backend.selectDifficulty(textAt(index))
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
                                  ? qsTr("Catalog refreshed: %1").arg(shell.session.catalog_refresh)
                                  : qsTr("No catalog yet")
                            wrapMode: Text.Wrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: !shell.session.active || shell.session.paused
                            ActionButton {
                                id: oathPanel
                                objectName: "oathPanel"
                                visible: shell.session.oaths.length > 0
                                text: checked && enabled ? qsTr("Hide oaths") : qsTr("Show oaths")
                                checkable: true
                                enabled: shell.session.can_pick_oaths
                            }
                            Caption {
                                objectName: "oathPoints"
                                Layout.fillWidth: true
                                visible: oathPanel.visible
                                text: shell.session.difficulties[shell.session.difficulty_index] === "30"
                                      ? qsTr("Oath points: %1").arg(shell.session.oath_points)
                                      : qsTr("Oaths require fixed difficulty 30.")
                                wrapMode: Text.Wrap
                            }
                            Item { Layout.fillWidth: true; visible: !oathPanel.visible }
                            ActionButton {
                                id: wishlistPanel
                                objectName: "wishlistPanel"
                                enabled: shell.session.can_edit_wishlist
                                checkable: true
                                text: checked && enabled ? qsTr("Hide wishlist (%1)").arg(shell.session.wishlist_count)
                                      : qsTr("Wishlist (%1)").arg(shell.session.wishlist_count)
                            }
                            ActionButton {
                                id: maintenancePanel
                                objectName: "maintenancePanel"
                                enabled: shell.session.can_edit_maintenance
                                checkable: true
                                text: checked && enabled ? qsTr("Hide maintenance") : qsTr("Maintenance")
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            visible: oathPanel.checked && oathPanel.enabled
                            columns: width >= 700 ? 3 : 2
                            uniformCellWidths: true
                            columnSpacing: 12
                            rowSpacing: 10
                            Repeater {
                                model: shell.session.oaths.length
                                delegate: ColumnLayout {
                                    id: oathRow
                                    required property int index
                                    readonly property var oath: shell.session.oaths[index]
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignTop
                                    Layout.preferredWidth: 1
                                    spacing: 4
                                    Caption {
                                        id: oathName
                                        objectName: "oathLabel" + oathRow.index
                                        Layout.fillWidth: true
                                        text: oathRow.oath.label
                                        wrapMode: Text.Wrap
                                    }
                                    ComboBox {
                                        id: rankPicker
                                        objectName: "oathPicker" + oathRow.index
                                        Accessible.name: oathName.text
                                        Layout.fillWidth: true
                                        Layout.minimumHeight: 44
                                        model: oathRow.oath.ranks.length
                                        currentIndex: oathRow.oath.selected_index
                                        displayText: currentIndex < 0 ? qsTr("Saved rank unavailable") : rankText(currentIndex)
                                        onActivated: index => shell.backend.selectOath(oathRow.oath.id, oathRow.oath.ranks[index].rank)
                                        function rankText(index) {
                                            const rank = oathRow.oath.ranks[index]
                                            return rank.rank === 0 ? qsTr("Off") : qsTr("Rank %1 (%2 pts)").arg(rank.rank).arg(rank.points)
                                        }
                                        delegate: ItemDelegate {
                                            required property int index
                                            width: rankPicker.width
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

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: wishlistPanel.visible && wishlistPanel.checked && wishlistPanel.enabled
                            spacing: 4

                            Caption { id: wishlistSearchLabel; text: qsTr("Search legendary items by name") }
                            TextField {
                                id: wishlistSearch
                                objectName: "wishlistSearch"
                                Accessible.name: wishlistSearchLabel.text
                                Layout.fillWidth: true
                                Layout.minimumHeight: 44
                            }
                            CheckBox {
                                id: wishlistOnly
                                text: qsTr("Show wishlist only")
                                Layout.minimumHeight: 44
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                ComboBox {
                                    id: wishlistPicker
                                    objectName: "wishlistPicker"
                                    Accessible.name: qsTr("Matching legendary items")
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Layout.minimumHeight: 44
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
                                    delegate: ItemDelegate {
                                        required property int index
                                        required property var modelData
                                        width: wishlistPicker.width
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

                        GridLayout {
                            Layout.fillWidth: true
                            visible: maintenancePanel.visible && maintenancePanel.checked && maintenancePanel.enabled
                            columns: width >= 880 ? 4 : 2
                            uniformCellWidths: true
                            columnSpacing: 12
                            enabled: shell.session.can_edit_maintenance
                            Repeater {
                                model: [
                                    { key: "upgrades", label: qsTr("Kafra/Sage upgrades") },
                                    { key: "card_fusion", label: qsTr("Card fusion") },
                                    { key: "star_smith", label: qsTr("Star Smith") },
                                    { key: "storage_cleanup", label: qsTr("Storage cleanup") }
                                ]
                                delegate: Switch {
                                    required property var modelData
                                    objectName: "maintenance-" + modelData.key
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 44
                                    text: modelData.label
                                    checked: shell.session.maintenance[modelData.key]
                                    onToggled: shell.backend.setMaintenance(modelData.key, checked)
                                }
                            }
                        }

                        Label {
                            objectName: "startRefusal"
                            Layout.fillWidth: true
                            visible: shell.session.start_refusal.length > 0
                            text: visible ? qsTr("Start refused: %1").arg(shell.session.start_refusal) : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: shell.danger
                        }
                        Label {
                            objectName: "resumeRefusal"
                            Layout.fillWidth: true
                            visible: shell.session.resume_refusal.length > 0
                            text: visible ? qsTr("Resume refused: %1").arg(shell.session.resume_refusal) : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: shell.danger
                        }
                        Caption {
                            Layout.fillWidth: true
                            visible: !shell.session.active && !shell.session.service_missing
                                     && text.length > 0 && text !== shell.session.start_refusal
                            text: shell.session.start_reason
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: shell.warning
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: shell.session.action_error
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: shell.danger
                        }

                        RowLayout {
                            Layout.fillWidth: true
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
                                text: shell.session.paused ? qsTr("Resume") : qsTr("Pause after run")
                                visible: shell.session.active
                                enabled: shell.session.paused ? shell.session.can_resume : shell.session.can_pause
                                onClicked: shell.backend.control(shell.session.paused ? "resume" : "pause",
                                                                 shell.session.session_id)
                            }
                            ActionButton {
                                objectName: "finishButton"
                                text: qsTr("Finish")
                                visible: shell.session.active
                                enabled: shell.session.can_control
                                onClicked: shell.backend.control("finish", shell.session.session_id)
                            }
                            ActionButton {
                                objectName: "abortButton"
                                text: qsTr("Abort…")
                                palette.buttonText: shell.danger
                                visible: shell.session.active
                                enabled: shell.session.can_control
                                onClicked: {
                                    abortDialog.sessionId = shell.session.session_id
                                    abortDialog.betweenAttempts = !shell.session.can_pause
                                    abortDialog.open()
                                }
                            }
                            Item { Layout.fillWidth: true }
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
                                readonly property bool lastNight: modelData.session_id !== ""
                                    && modelData.session_id === shell.history.latest_session_id
                                readonly property bool expandable: lastNight || modelData.run_choices.length > 0
                                readonly property bool expanded: expandable
                                    && historyPanel.expandedSession === modelData.session_id
                                Layout.fillWidth: true
                                spacing: 10
                                Rule {}
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Caption { text: entry.modelData.date }
                                    SingleLine {
                                        objectName: "historyRow" + entry.index
                                        text: entry.modelData.title + (entry.modelData.summary ? " · " + entry.modelData.summary : "")
                                    }
                                    ActionButton {
                                        objectName: entry.lastNight ? "lastNightDisclosure" : ""
                                        visible: entry.expandable
                                        text: entry.expanded ? qsTr("Hide details")
                                              : entry.lastNight ? qsTr("Last night") : qsTr("Run choices")
                                        Accessible.name: !entry.expanded && entry.lastNight
                                                         ? qsTr("Show details for the last night") : text
                                        onClicked: historyPanel.expandedSession = entry.expanded ? "" : entry.modelData.session_id
                                    }
                                }
                                ColumnLayout {
                                    objectName: entry.lastNight ? "lastNightDetails" : ""
                                    visible: entry.expanded
                                    Layout.fillWidth: true
                                    Layout.topMargin: 4
                                    Layout.bottomMargin: 8
                                    spacing: 12
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
                                    GridLayout {
                                        visible: entry.lastNight
                                        Layout.fillWidth: true
                                        columns: 5
                                        uniformCellWidths: true
                                        columnSpacing: 12
                                        rowSpacing: 12
                                        Repeater {
                                            model: entry.expanded && entry.lastNight ? shell.history.totals : []
                                            delegate: Metric {
                                                required property var modelData
                                                title: modelData.label
                                                value: modelData.value
                                            }
                                        }
                                    }
                                    Metric {
                                        visible: entry.lastNight
                                        title: qsTr("Rewards per hour in runs")
                                        value: shell.history.rewards
                                        valueObjectName: "lastNightRewards"
                                    }
                                    Metric {
                                        visible: entry.lastNight
                                        title: qsTr("Materials")
                                        value: shell.history.materials
                                        valueObjectName: "lastNightMaterials"
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
                        Label { text: qsTr("Game update"); font.pixelSize: 16; font.weight: Font.DemiBold }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 24
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
                        Label { text: qsTr("App update"); font.pixelSize: 16; font.weight: Font.DemiBold }
                        Metric {
                            title: qsTr("Installed version")
                            value: shell.updates.app_version
                            valueObjectName: "installedAppVersion"
                        }
                        Caption {
                            objectName: "appUpdateCheck"
                            text: shell.updates.app_check
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                        }
                        ActionButton {
                            objectName: "rollbackAppButton"
                            visible: Boolean(shell.updates.previous_app_version)
                            enabled: shell.updates.can_rollback
                            text: qsTr("Roll back to %1").arg(shell.updates.previous_app_version)
                            onClicked: shell.backend.rollbackApp()
                        }
                        BodyText {
                            text: shell.updates.rollback_feedback
                            visible: text.length > 0
                        }
                    }
                }

                ScreenPanel {
                    visible: tabs.currentIndex === 3
                    ColumnLayout {
                        width: parent.width
                        spacing: 14
                        PageTitle { text: qsTr("Quarantine") }
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
                                font.weight: Font.DemiBold
                                color: shell.danger
                            }
                            SingleLine { objectName: "quarantineDetail"; text: shell.quarantine.detail }
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
                                Caption { text: qsTr("Attempts") }
                                Caption { visible: shell.quarantine.attempts.length === 0; text: qsTr("No attempts recorded.") }
                                Repeater {
                                    model: shell.quarantine.attempts
                                    delegate: BodyText { required property string modelData; text: modelData }
                                }
                                Caption { text: qsTr("Log paths") }
                                Caption { visible: shell.quarantine.paths.length === 0; text: qsTr("No log paths recorded.") }
                                Repeater {
                                    model: shell.quarantine.paths
                                    delegate: TextEdit {
                                        required property string modelData
                                        Layout.fillWidth: true
                                        text: modelData
                                        textFormat: TextEdit.PlainText
                                        color: shell.palette.text
                                        wrapMode: TextEdit.WrapAnywhere
                                        readOnly: true
                                        selectByMouse: true
                                    }
                                }
                            }
                        }
                    }
                }

                Caption {
                    visible: tabs.currentIndex === 0
                    Layout.fillWidth: true
                    text: qsTr("Closing this window leaves the AFK session running in the background service.")
                    wrapMode: Text.Wrap
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
            ActionButton {
                id: cancelAbort
                objectName: "cancelAbort"
                text: qsTr("Cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            ActionButton {
                objectName: "confirmAbort"
                text: qsTr("Abort session")
                palette.buttonText: shell.danger
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }
}
