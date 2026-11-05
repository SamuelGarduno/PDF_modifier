import QtQuick

Rectangle {
    id: footerRoot
    objectName: "footerBar"
    radius: 10
    color: themePalette.stationeryFrameBg
    border.width: 1.2
    border.color: "#8E4A5E"

    // Botón CTA principal tipo píldora anclado al borde derecho (nunca se recorta)
    PillButton {
        id: mainCtaButton
        objectName: "mainCtaButton"
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        width: implicitWidth
        height: 38
        text: studioBridge.isBusy ? "Cancelar Tarea" : "Procesar " + studioBridge.activeToolTitle
        primaryStyle: true
        solidShadow: true
        enabledButton: studioBridge.fileCount > 0 || studioBridge.isBusy
        disabledHint: "Agrega archivos a la cola para poder procesar"
        onClicked: {
            if (studioBridge.isBusy) {
                studioBridge.cancelActiveOperation()
            } else {
                studioBridge.executeActiveOperation()
            }
        }
    }

    // Acciones rápidas al finalizar ("Abrir archivo" y "Mostrar en carpeta")
    Row {
        id: quickActionsRow
        visible: studioBridge.lastOutputFile.length > 0 && !studioBridge.isBusy
        anchors.right: mainCtaButton.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        PillButton {
            height: 34
            text: "Abrir Archivo"
            primaryStyle: false
            onClicked: studioBridge.openFileInSystem(studioBridge.lastOutputFile)
        }

        PillButton {
            height: 34
            text: "Mostrar en Carpeta"
            primaryStyle: false
            onClicked: studioBridge.showFileInFolder(studioBridge.lastOutputFile)
        }
    }

    // Columna de estado y barra de progreso animada (se adapta dinámicamente al espacio restante)
    Column {
        id: statusColumn
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: quickActionsRow.visible ? quickActionsRow.left : mainCtaButton.left
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        Item {
            width: parent.width
            height: 18

            Text {
                id: footerStatusText
                objectName: "footerStatusText"
                anchors.left: parent.left
                anchors.right: footerProgressPercentText.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: studioBridge.statusMessage
                font.family: themePalette.sansFont
                font.pixelSize: 12
                font.bold: true
                color: themePalette.backgroundDark
                elide: Text.ElideRight
            }

            Text {
                id: footerProgressPercentText
                objectName: "footerProgressPercentText"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: studioBridge.progressPercent + "%"
                font.family: themePalette.sansFont
                font.pixelSize: 12
                font.bold: true
                color: themePalette.secondary
            }
        }

        Rectangle {
            width: parent.width
            height: 8
            radius: 4
            color: "#EAD5D7"
            border.width: 1
            border.color: themePalette.secondary

            Rectangle {
                width: parent.width * (studioBridge.progressPercent / 100.0)
                height: parent.height
                radius: 4
                color: themePalette.secondary

                Behavior on width {
                    NumberAnimation { duration: 180; easing.type: Easing.OutQuad }
                }
            }
        }
    }
}
