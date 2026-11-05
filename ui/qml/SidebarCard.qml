import QtQuick

Item {
    id: cardRoot
    objectName: "sidebarCard_" + toolId
    property string toolId: ""
    property string title: ""
    property string subtitle: ""
    property string badgeLetter: "P"
    property bool isActive: false
    property bool isHovered: cardHover.hovered
    signal selected(string id)

    width: isActive ? 232 : 228
    height: 46

    Behavior on width {
        NumberAnimation { duration: 160; easing.type: Easing.OutQuad }
    }

    Rectangle {
        id: cardBg
        width: parent.width
        height: parent.height
        y: cardRoot.isHovered ? -1 : 0
        radius: 9
        color: cardRoot.isActive
               ? themePalette.sidebarCardActiveBg
               : (cardRoot.isHovered ? "#3A1822" : themePalette.sidebarCardInactiveBg)
        border.width: cardRoot.isActive ? 1.5 : 1.0
        border.color: cardRoot.isActive ? themePalette.wineDeep : themePalette.sidebarCardInactiveBorder

        Behavior on y {
            NumberAnimation { duration: 140; easing.type: Easing.OutQuad }
        }
        Behavior on color {
            ColorAnimation { duration: 160 }
        }

        Row {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            spacing: 10

            // Círculo de letra inicial: transparente con borde/letra clara en inactivos; relleno vino oscuro en activo
            Rectangle {
                id: waxSealBadge
                width: 28
                height: 28
                radius: 14
                anchors.verticalCenter: parent.verticalCenter
                color: cardRoot.isActive ? themePalette.wineDeep : "transparent"
                border.width: 1.2
                border.color: cardRoot.isActive ? themePalette.wineDeep : "#C99AA7"

                Text {
                    anchors.centerIn: parent
                    text: cardRoot.badgeLetter
                    font.family: themePalette.serifFont
                    font.pixelSize: 12
                    font.bold: true
                    color: cardRoot.isActive ? "#FFFDFB" : "#F8EAE6"
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 50
                spacing: 1

                Text {
                    text: cardRoot.title
                    font.family: themePalette.serifFont
                    font.pixelSize: 13
                    font.bold: true
                    color: cardRoot.isActive ? "#2D1018" : "#FBF0F0"
                    elide: Text.ElideRight
                    width: parent.width
                }

                Text {
                    text: cardRoot.subtitle
                    font.family: themePalette.scriptFont
                    font.italic: true
                    font.pixelSize: 11
                    color: cardRoot.isActive ? themePalette.wineDeep : "#D4AEB8"
                    elide: Text.ElideRight
                    width: parent.width
                }
            }
        }
    }

    HoverHandler {
        id: cardHover
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: cardRoot.selected(cardRoot.toolId)
    }
}
