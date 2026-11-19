import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: shell
    required property QtObject backend
    readonly property var session: backend.snapshot
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

    component Metric: ColumnLayout {
        required property string title
        required property string value
        property string detail: ""
        property alias valueObjectName: reading.objectName
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
                    Accessible.name: qsTr("Screens")
                    Layout.preferredWidth: 130
                    TabButton { text: qsTr("AFK session"); height: 44 }
                }

                Pane {
                    Layout.fillWidth: true
                    padding: 20
                    background: Rectangle {
                        color: shell.palette.base
                        radius: 12
                        border.color: shell.palette.mid
                    }

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

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
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
                        }

                        Caption {
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: shell.session.preset_description
                            wrapMode: Text.Wrap
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
                        Caption {
                            Layout.fillWidth: true
                            visible: !shell.session.active && !shell.session.service_missing
                                     && text.length > 0 && text !== shell.session.start_refusal
                            text: shell.session.start_reason
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
                                enabled: shell.session.can_pause
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

                Caption {
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
