import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: panel

    readonly property var currentCharacter: characterInfo()
    property string character: charBox.currentValue ? charBox.currentValue : ""
    property string stage: stageBox.currentValue ? stageBox.currentValue : ""
    property int danger: dangerBox.value
    property bool canStart: charBox.count > 0 && stageBox.count > 0 && !backend.busy

    function characterInfo() {
        const index = charBox.currentIndex;
        if (index < 0 || index >= backend.characters.length)
            return null;
        return backend.characters[index];
    }

    color: theme.surface
    radius: theme.radius
    border.width: 1
    border.color: theme.border

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        Label {
            text: qsTr("Цель фарма")
            color: theme.foreground
            font.pixelSize: 19
            font.weight: Font.DemiBold
        }
        Label {
            text: qsTr("Кто и где играет. Класс и локация должны быть открыты в профиле.")
            color: theme.muted
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label {
            text: qsTr("Персонаж")
            color: theme.muted
            font.pixelSize: 11
            Layout.topMargin: 4
        }
        ComboBox {
            id: charBox
            Layout.fillWidth: true
            model: backend.characters
            textRole: "label"
            valueRole: "id"
        }
        Label {
            text: panel.currentCharacter
                  ? panel.currentCharacter["class"] + "/" + panel.currentCharacter["job_path"]
                    + " · " + panel.currentCharacter.label
                  : ""
            color: theme.accent
            font.pixelSize: 11
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Label {
            text: qsTr("Локация")
            color: theme.muted
            font.pixelSize: 11
            Layout.topMargin: 4
        }
        ComboBox {
            id: stageBox
            Layout.fillWidth: true
            model: backend.stages
            textRole: "label"
            valueRole: "id"
        }

        Label {
            text: qsTr("Опасность")
            color: theme.muted
            font.pixelSize: 11
            Layout.topMargin: 4
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            SpinBox {
                id: dangerBox
                from: 1
                to: 30
                value: 25
                editable: true
                Layout.fillWidth: true
            }
            Label {
                text: "Hell " + Math.max(0, dangerBox.value - 15)
                color: dangerBox.value >= 25 ? theme.warning : theme.muted
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
        }
        Label {
            text: qsTr("25 = Hell 10. Выше — опаснее, больше добычи.")
            color: theme.muted
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 4
            implicitHeight: 38
            color: theme.background
            radius: theme.radius
            border.width: 1
            border.color: theme.border
            Label {
                anchors.centerIn: parent
                width: parent.width - 20
                text: (charBox.currentText || "—") + "  ·  " + (stageBox.currentText || "—")
                      + "  ·  D" + dangerBox.value
                color: theme.muted
                font.pixelSize: 11
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
            }
        }

        Item { Layout.fillHeight: true }

        Button {
            id: action
            Layout.fillWidth: true
            Layout.preferredHeight: 50
            enabled: backend.busy || panel.canStart
            text: backend.busy
                  ? (backend.stopping ? qsTr("Остановка…") : qsTr("Остановить"))
                  : qsTr("Начать фарм")
            onClicked: {
                if (backend.busy)
                    backend.stopRun();
                else
                    backend.startRun(panel.character, panel.stage, panel.danger);
            }
            background: Rectangle {
                color: backend.busy ? theme.red : theme.accent
                radius: theme.radius
                opacity: action.enabled ? 1.0 : 0.45
            }
            contentItem: Text {
                text: action.text
                color: backend.busy ? theme.background : theme.accentForeground
                font.pixelSize: 15
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
        Label {
            text: qsTr("Space — старт/стоп")
            color: theme.muted
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }
}
