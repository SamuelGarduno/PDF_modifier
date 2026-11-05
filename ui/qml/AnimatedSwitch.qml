import QtQuick

Item {
    id: switchRoot
    property bool checked: false
    property string labelText: ""
    signal toggled(bool newValue)

    implicitWidth: rowContainer.implicitWidth
    implicitHeight: 28

    Row {
        id: rowContainer
        spacing: 10

        Rectangle {
            id: track
            width: 48
            height: 24
            radius: 12
            anchors.verticalCenter: parent.verticalCenter
            color: switchRoot.checked ? themePalette.secondary : themePalette.primary
            border.width: 1.2
            border.color: themePalette.secondary

            Behavior on color {
                ColorAnimation { duration: 180 }
            }

            Rectangle {
                id: knob
                width: 18
                height: 18
                radius: 9
                anchors.verticalCenter: parent.verticalCenter
                x: switchRoot.checked ? parent.width - width - 3 : 3
                color: themePalette.surfaceLight
                border.width: 1
                border.color: themePalette.backgroundDark

                Behavior on x {
                    NumberAnimation { duration: 160; easing.type: Easing.OutQuad }
                }
            }
        }

        Text {
            visible: switchRoot.labelText.length > 0
            anchors.verticalCenter: parent.verticalCenter
            text: switchRoot.labelText
            font.family: themePalette.sansFont
            font.pixelSize: 13
            color: themePalette.backgroundDark
        }
    }

    TapHandler {
        onTapped: {
            switchRoot.checked = !switchRoot.checked
            switchRoot.toggled(switchRoot.checked)
        }
    }
}

