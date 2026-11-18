import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: panel

    color: theme.surface
    radius: theme.radius
    border.width: 1
    border.color: theme.border

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: qsTr("Лог")
                color: theme.foreground
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            CheckBox {
                id: follow
                text: qsTr("Следовать")
                checked: true
                font.pixelSize: 11
            }
        }

        TabBar {
            id: tabs
            Layout.fillWidth: true
            TabButton { text: qsTr("Фермер") }
            TabButton { text: qsTr("Запуск") }
        }

        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            LogList {
                text: backend.logText
                follow: follow.checked
            }
            LogList {
                text: backend.runnerLog
                follow: follow.checked
            }
        }
    }

    component LogList: ListView {
        id: list

        property string text
        property bool follow: true

        model: text.length > 0 ? text.split("\n") : []
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        delegate: Text {
            required property string modelData
            width: list.width - 10
            text: modelData.length > 0 ? modelData : " "
            color: theme.foreground
            font.family: "monospace"
            font.pixelSize: 11
            wrapMode: Text.WrapAnywhere
            padding: 2
        }

        onCountChanged: if (follow) positionViewAtEnd()
        Component.onCompleted: positionViewAtEnd()
    }
}
