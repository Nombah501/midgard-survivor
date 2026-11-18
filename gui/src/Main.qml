import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: win
    width: 1080
    height: 740
    minimumWidth: 900
    minimumHeight: 640
    visible: true
    title: qsTr("Midgard Farm")
    color: theme.background

    Material.theme: Material.Dark
    Material.accent: theme.accent
    Material.background: theme.background
    Material.foreground: theme.foreground
    Material.roundedScale: theme.radius

    property bool helpVisible: false
    property bool quitAfterStop: false

    function toggleFarm() {
        if (backend.busy)
            backend.stopRun();
        else if (targetPanel.canStart)
            backend.startRun(targetPanel.character, targetPanel.stage, targetPanel.danger);
    }

    function requestQuit() {
        if (backend.busy)
            quitDialog.open();
        else
            Qt.quit();
    }

    Shortcut {
        sequence: "Space"
        context: Qt.ApplicationShortcut
        enabled: !win.helpVisible && !settingsDialog.visible
        onActivated: win.toggleFarm()
    }
    Shortcut {
        sequence: "F5"
        context: Qt.ApplicationShortcut
        onActivated: backend.refresh()
    }
    Shortcut {
        sequence: "?"
        context: Qt.ApplicationShortcut
        enabled: !settingsDialog.visible
        onActivated: win.helpVisible = !win.helpVisible
    }
    Shortcut {
        sequence: "Q"
        context: Qt.ApplicationShortcut
        enabled: !win.helpVisible && !settingsDialog.visible
        onActivated: win.requestQuit()
    }
    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        enabled: win.helpVisible
        onActivated: win.helpVisible = false
    }

    onClosing: function(close) {
        if (backend.busy) {
            close.accepted = false;
            quitDialog.open();
        }
    }

    Connections {
        target: backend
        function onRunningChanged() {
            if (!backend.busy && win.quitAfterStop)
                Qt.quit();
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 72
            color: theme.background

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 14

                ColumnLayout {
                    spacing: 0
                    Label {
                        text: qsTr("Midgard Farm")
                        color: theme.foreground
                        font.pixelSize: 22
                        font.weight: Font.Bold
                    }
                    Label {
                        text: qsTr("Автономный фарм Midgard Survivors")
                        color: theme.muted
                        font.pixelSize: 11
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    implicitHeight: 28
                    implicitWidth: statusText.implicitWidth + 22
                    radius: Math.min(4, theme.radius)
                    color: backend.running ? theme.accent
                           : backend.starting ? theme.warning : theme.muted
                    Label {
                        id: statusText
                        anchors.centerIn: parent
                        text: backend.running ? qsTr("Фарм идёт")
                              : backend.starting ? qsTr("Запуск") : qsTr("Остановлен")
                        color: theme.background
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }

                Button {
                    text: qsTr("Обновить")
                    flat: true
                    onClicked: backend.refresh()
                }
                Button {
                    text: qsTr("Настройки")
                    flat: true
                    onClicked: settingsDialog.open()
                }
                Button {
                    text: "?"
                    flat: true
                    implicitWidth: 36
                    Accessible.name: qsTr("Помощь")
                    onClicked: win.helpVisible = true
                }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: theme.border
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: backend.error.length > 0
            implicitHeight: visible ? errorRow.implicitHeight + 16 : 0
            color: theme.red

            RowLayout {
                id: errorRow
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8
                Label {
                    text: backend.error
                    color: theme.background
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Button {
                    flat: true
                    implicitWidth: 30
                    implicitHeight: 30
                    onClicked: backend.clearError()
                    contentItem: Text {
                        text: "×"
                        color: theme.background
                        font.pixelSize: 18
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: backend.notice.length > 0
            implicitHeight: visible ? noticeRow.implicitHeight + 16 : 0
            color: theme.warning

            RowLayout {
                id: noticeRow
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8
                Label {
                    text: backend.notice
                    color: theme.background
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Button {
                    flat: true
                    implicitWidth: 30
                    implicitHeight: 30
                    onClicked: backend.clearNotice()
                    contentItem: Text {
                        text: "×"
                        color: theme.background
                        font.pixelSize: 18
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 16
            spacing: 14

            TargetPanel {
                id: targetPanel
                Layout.preferredWidth: 350
                Layout.fillHeight: true
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10
                StatusPanel { Layout.fillWidth: true }
                LogPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 30
            color: theme.background

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                spacing: 12

                Label {
                    text: qsTr("farmer: ") + backend.shortenPath(backend.farmerDir)
                    color: theme.muted
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
                Label {
                    text: qsTr("Space старт/стоп · F5 обновить · ? помощь · Q выход")
                    color: theme.muted
                    font.pixelSize: 10
                }
            }
        }
    }

    Dialog {
        id: settingsDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(620, win.width - 80)
        title: qsTr("Каталог фермера")
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: ColumnLayout {
            spacing: 10
            Label {
                text: qsTr("Путь к каталогу farmer с tools/farm.py и targets.json.")
                color: theme.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            TextField {
                id: farmerPath
                text: backend.farmerDir
                placeholderText: "/path/to/farmer"
                Layout.fillWidth: true
            }
            Label {
                text: backend.error
                visible: backend.error.length > 0
                color: theme.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        footer: RowLayout {
            spacing: 10
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Отмена")
                flat: true
                onClicked: settingsDialog.close()
            }
            Button {
                text: qsTr("Сохранить")
                onClicked: {
                    if (backend.saveFarmerDir(farmerPath.text))
                        settingsDialog.close();
                }
            }
        }

        onOpened: farmerPath.forceActiveFocus()
    }

    Dialog {
        id: quitDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(480, win.width - 80)
        title: qsTr("Ферма работает")

        contentItem: Label {
            text: qsTr("Остановить фарм и выйти?")
            color: theme.foreground
            wrapMode: Text.WordWrap
            padding: 16
        }

        footer: RowLayout {
            spacing: 10
            Item { Layout.fillWidth: true }
            Button {
                text: qsTr("Отмена")
                flat: true
                onClicked: quitDialog.close()
            }
            Button {
                text: qsTr("Остановить и выйти")
                highlighted: true
                onClicked: {
                    win.quitAfterStop = true;
                    backend.stopRun();
                    quitDialog.close();
                }
            }
        }
    }

    Rectangle {
        id: helpOverlay
        anchors.fill: parent
        visible: win.helpVisible
        color: Qt.rgba(0, 0, 0, 0.55)
        z: 100

        MouseArea {
            anchors.fill: parent
            onClicked: win.helpVisible = false
        }

        Rectangle {
            width: Math.min(560, win.width - 80)
            implicitHeight: helpColumn.implicitHeight + 40
            anchors.centerIn: parent
            color: theme.surface
            radius: theme.radius
            border.width: 1
            border.color: theme.border

            MouseArea {
                anchors.fill: parent
                onClicked: {}
            }

            ColumnLayout {
                id: helpColumn
                anchors.fill: parent
                anchors.margins: 20
                spacing: 6

                Label {
                    text: qsTr("Управление")
                    color: theme.foreground
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
                Label { text: qsTr("Space — начать / остановить фарм"); color: theme.foreground; font.pixelSize: 12 }
                Label { text: qsTr("F5 — обновить статус"); color: theme.foreground; font.pixelSize: 12 }
                Label { text: qsTr("? — эта справка"); color: theme.foreground; font.pixelSize: 12 }
                Label { text: qsTr("Q — выход (при работающей ферме предложит остановить)"); color: theme.foreground; font.pixelSize: 12 }
                Label {
                    text: qsTr("Sniper = archer/0. Класс и локация должны быть открыты в профиле.")
                    color: theme.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                }
                Button {
                    text: qsTr("Понятно")
                    Layout.alignment: Qt.AlignRight
                    Layout.topMargin: 8
                    onClicked: win.helpVisible = false
                }
            }
        }
    }
}
