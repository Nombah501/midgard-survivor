import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card

    property string title
    property string value
    property string hint: ""
    property color valueColor: theme.foreground

    color: theme.surface
    radius: theme.radius
    border.width: 1
    border.color: theme.border
    implicitHeight: 82

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        spacing: 1

        Label {
            text: card.title
            color: theme.muted
            font.pixelSize: 11
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Label {
            text: card.value
            color: card.valueColor
            font.pixelSize: 19
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Label {
            text: card.hint
            visible: card.hint.length > 0
            color: theme.muted
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }
}
