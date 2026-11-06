import QtQuick
import QtQuick.Controls
import "."

FocusScope {
    id: pillRoot
    property string text: "Acción"
    property bool primaryStyle: true
    property bool enabledButton: true
    property bool solidShadow: primaryStyle
    property int horizontalPadding: 18
    property bool hoveredState: hoverHandler.hovered
    property bool pressedState: tapHandler.pressed
    property string disabledHint: ""
    signal clicked()

    activeFocusOnTab: enabledButton

    ToolTip.visible: hoverHandler.hovered && !enabledButton && disabledHint.length > 0
    ToolTip.text: disabledHint
    ToolTip.delay: 250

    implicitWidth: Math.max(104, Math.ceil(labelItem.implicitWidth) + horizontalPadding * 2)
    implicitHeight: 38

    Keys.onReturnPressed: {
        if (pillRoot.enabledButton)
            pillRoot.clicked()
    }
    Keys.onEnterPressed: {
        if (pillRoot.enabledButton)
            pillRoot.clicked()
    }
    Keys.onSpacePressed: {
        if (pillRoot.enabledButton)
            pillRoot.clicked()
    }

    // Sombra inferior sólida desplazada SOLO para el botón principal relleno
    Rectangle {
        id: stampReliefShadow
        visible: pillRoot.solidShadow && pillRoot.primaryStyle && pillRoot.enabledButton
        width: pillRoot.width
        height: pillRoot.height - 2
        radius: height / 2
        x: 0
        y: pillRoot.pressedState ? 1 : 3
        color: Theme.wineDeep
    }

    Rectangle {
        id: pillBg
        width: pillRoot.width
        height: (pillRoot.solidShadow && pillRoot.primaryStyle && pillRoot.enabledButton) ? pillRoot.height - 2 : pillRoot.height
        radius: height / 2
        y: !pillRoot.enabledButton
           ? 0
           : (pillRoot.pressedState ? 1 : (pillRoot.hoveredState ? -1 : 0))
        color: !pillRoot.enabledButton
               ? "#EAE0E2"
               : (pillRoot.primaryStyle
                  ? (pillRoot.pressedState
                     ? Theme.wineDeep
                     : (pillRoot.hoveredState ? Theme.secondaryWine : Theme.primaryRose))
                  : (pillRoot.pressedState
                     ? "#EED3D0"
                     : (pillRoot.hoveredState ? "#F5E3E1" : "#FFFDFB")))
        border.width: pillRoot.activeFocus
                      ? 2.0
                      : (pillRoot.primaryStyle ? Theme.borderStrongWidth : Theme.borderSubtleWidth)
        border.color: !pillRoot.enabledButton
                      ? "#C4AEB4"
                      : (pillRoot.activeFocus
                         ? Theme.focusRingColor
                         : (pillRoot.primaryStyle ? Theme.wineDeep : Theme.borderSubtleColor))

        Behavior on y {
            NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutQuad }
        }
        Behavior on color {
            ColorAnimation { duration: Theme.animNormal }
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
            font.family: Theme.sansFont
            font.pixelSize: Theme.fontBodySize
            font.bold: pillRoot.primaryStyle
            color: !pillRoot.enabledButton
                   ? "#8A6D75"
                   : (pillRoot.primaryStyle && (pillRoot.hoveredState || pillRoot.pressedState)
                      ? Theme.surfaceCard
                      : Theme.textPrimary)

            Behavior on color {
                ColorAnimation { duration: Theme.animFast }
            }
        }
    }

    HoverHandler {
        id: hoverHandler
        cursorShape: pillRoot.enabledButton ? Qt.PointingHandCursor : Qt.ForbiddenCursor
    }

    TapHandler {
        id: tapHandler
        enabled: pillRoot.enabledButton
        onTapped: {
            pillRoot.forceActiveFocus()
            pillRoot.clicked()
        }
    }
}
