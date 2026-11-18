import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: panel
    spacing: 10

    property var totals: backend.status.totals || ({})
    property var rates: backend.status.rates || ({})
    property var mats: totals.materials || ({})
    property var last: backend.status.last || ({})
    property var lastMats: last.materials || ({})
    property var game: backend.status.game || ({})

    GridLayout {
        Layout.fillWidth: true
        columns: 3
        columnSpacing: 10
        rowSpacing: 10

        StatCard {
            Layout.fillWidth: true
            title: qsTr("Зеньги")
            value: backend.fmt(totals.zeny || 0)
            hint: backend.fmt1(rates.zeny_h || 0) + " / ч"
        }
        StatCard {
            Layout.fillWidth: true
            title: qsTr("Убийства")
            value: backend.fmt(totals.kills || 0)
            hint: backend.fmt1(rates.kills_min || 0) + " / мин"
        }
        StatCard {
            Layout.fillWidth: true
            title: qsTr("Руда")
            value: backend.fmt(mats.oridecon || 0) + " / " + backend.fmt(mats.elunium || 0)
            hint: "ori / elu · " + backend.fmt1(rates.ore_h || 0) + " / ч"
        }
        StatCard {
            Layout.fillWidth: true
            title: qsTr("Star Crumb")
            value: backend.fmt(mats.star_crumb || 0)
            hint: backend.fmt1(rates.crumbs_h || 0) + " / ч"
            valueColor: theme.accent
        }
        StatCard {
            Layout.fillWidth: true
            title: qsTr("XP")
            value: backend.fmt(totals.xp || 0)
            hint: backend.fmt1((rates.xp_h || 0) / 1000000) + " M / ч"
        }
        StatCard {
            Layout.fillWidth: true
            title: qsTr("Забеги")
            value: (totals.runs || 0) + " / " + (totals.wins || 0) + " W"
            hint: (totals.losses || 0) + " L"
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 10

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 96
            color: theme.surface
            radius: theme.radius
            border.width: 1
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 2
                Label {
                    text: qsTr("Последний забег")
                    color: theme.muted
                    font.pixelSize: 11
                }
                Label {
                    text: last.kills !== undefined
                          ? (last.died ? qsTr("смерть") : last.victory ? qsTr("победа") : qsTr("остановлен"))
                            + " · " + backend.fmt(last.kills) + " " + qsTr("убийств")
                          : "—"
                    color: theme.foreground
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Label {
                    text: last.kills !== undefined
                          ? backend.fmt(last.zeny_gain || 0) + " z · "
                            + backend.fmt(lastMats.star_crumb || 0) + " crumb · "
                            + backend.fmtTime(last.game_s || 0)
                          : ""
                    color: theme.muted
                    font.pixelSize: 11
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 96
            color: theme.surface
            radius: theme.radius
            border.width: 1
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 2
                Label {
                    text: qsTr("Игра")
                    color: theme.muted
                    font.pixelSize: 11
                }
                Label {
                    text: game.level !== undefined
                          ? qsTr("Уровень ") + game.level + " · " + backend.fmtTime(game.time || 0)
                          : "—"
                    color: theme.foreground
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Label {
                    text: game.level !== undefined
                          ? qsTr("HP ") + Math.round(100 * (game.hp || 0) / Math.max(1, game.max_hp || 1))
                            + "% · " + Math.round(game.fps || 0) + " fps"
                          : ""
                    color: theme.muted
                    font.pixelSize: 11
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }
}
