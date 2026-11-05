import QtQuick
import QtQuick.Controls

Item {
    id: pillRoot
    property string text: "Acción"
    property bool primaryStyle: true
    property bool enabledButton: true
    property bool solidShadow: primaryStyle
    property int horizontalPadding: 20
    property bool hoveredState: hoverHandler.hovered
    // Texto informativo opcional (p. ej. condición faltante cuando el botón está inactivo)
    property string disabledHint: ""
    signal clicked()

    ToolTip.visible: hoverHandler.hovered && !enabledButton && disabledHint.length > 0
    ToolTip.text: disabledHint
    ToolTip.delay: 250

    implicitWidth: Math.max(116, Math.ceil(labelItem.implicitWidth) + horizontalPadding * 2)
    implicitHeight: 38

    // Sombra inferior sólida desplazada (2.5px) en vino oscuro #521928 para efecto relieve de papelería/sello
    Rectangle {
        id: stampReliefShadow
        visible: pillRoot.solidShadow && pillRoot.enabledButton
        width: pillRoot.width
        height: pillRoot.height - 2
        radius: height / 2
        x: 0
        y: 3
        color: themePalette.wineDeep
    }

    Rectangle {
        id: pillBg
        width: pillRoot.width
        height: pillRoot.solidShadow && pillRoot.enabledButton ? pillRoot.height - 2 : pillRoot.height
        radius: height / 2
        y: pillRoot.hoveredState && pillRoot.enabledButton ? -1 : 0
        color: !pillRoot.enabledButton
               ? "#E5D2D5"
               : (pillRoot.hoveredState
                  ? themePalette.secondary
                  : (pillRoot.primaryStyle ? themePalette.buttonPrimaryRose : themePalette.accent))
        border.width: 1.3
        border.color: !pillRoot.enabledButton ? "#B8989F" : themePalette.wineDeep

        Behavior on y {
            NumberAnimation { duration: 150; easing.type: Easing.OutQuad }
        }
        Behavior on color {
            ColorAnimation { duration: 180 }
        }

        Text {
            id: labelItem
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: pillRoot.horizontalPadding
            anchors.rightMargin: pillRoot.horizontalPadding
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: pillRoot.text
            font.family: themePalette.sansFont
            font.pixelSize: 13
            font.bold: true
            color: !pillRoot.enabledButton
                   ? "#8E6D76"
                   : (pillRoot.hoveredState
                      ? themePalette.surfaceLight
                      : "#2D1018")

            Behavior on color {
                ColorAnimation { duration: 160 }
            }
        }
    }

    HoverHandler {
        id: hoverHandler
        cursorShape: pillRoot.enabledButton ? Qt.PointingHandCursor : Qt.ForbiddenCursor
    }

    TapHandler {
        enabled: pillRoot.enabledButton
        onTapped: pillRoot.clicked()
    }
}
