import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: footerRoot
    objectName: "footerBar"
    implicitHeight: Theme.actionBarHeight
    radius: 14
    color: Theme.stationeryFrameBg
    border.width: Theme.borderSubtleWidth
    border.color: Theme.borderSubtleColor

    FolderDialog {
        id: actionFolderDialog
        title: "Seleccionar carpeta de destino"
        onAccepted: {
            studioBridge.setOutputDirectory(actionFolderDialog.selectedFolder.toString())
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        spacing: 14

        // =====================================================================
        // IZQUIERDA: "Guardar en: [ruta] [Elegir...]"
        // =====================================================================
        RowLayout {
            id: folderPickerSection
            objectName: "folderPickerSection"
            spacing: 8
            Layout.alignment: Qt.AlignVCenter
            Layout.maximumWidth: Math.max(300, Math.floor(footerRoot.width * 0.40))

            Text {
                text: "Guardar en:"
                font.family: Theme.sansFont
                font.pixelSize: Theme.fontBodySize
                color: Theme.textPrimary
                Layout.alignment: Qt.AlignVCenter
            }

            Rectangle {
                id: outputFolderDisplayBox
                objectName: "outputFolderDisplayBox"
                Layout.preferredWidth: Math.max(150, Math.min(240, Math.floor(footerRoot.width * 0.21)))
                Layout.preferredHeight: 34
                radius: 8
                color: studioBridge.isOutputDirectoryValid ? "#FAF3F2" : Theme.errorBg
                border.width: Theme.borderSubtleWidth
                border.color: studioBridge.isOutputDirectoryValid ? Theme.borderSubtleColor : Theme.errorBorder

                Text {
                    id: outputFolderPathText
                    objectName: "outputFolderPathText"
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: Text.AlignVCenter
                    text: studioBridge.outputDirectory.length > 0
                          ? studioBridge.outputDirectory
                          : "Misma carpeta del original"
                    font.family: Theme.sansFont
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    color: studioBridge.isOutputDirectoryValid ? Theme.textPrimary : Theme.errorText
                }

                HoverHandler {
                    id: folderBoxHover
                }

                ToolTip.visible: folderBoxHover.hovered
                ToolTip.delay: 200
                ToolTip.text: !studioBridge.isOutputDirectoryValid
                              ? studioBridge.outputDirectoryError
                              : (studioBridge.outputDirectory.length > 0
                                 ? (studioBridge.outputDirectory + " (sufijo automático seguro)")
                                 : "Se guardará junto al archivo original con sufijo seguro (nunca sobrescribe)")
            }

            PillButton {
                id: chooseOutputFolderButton
                objectName: "chooseOutputFolderButton"
                height: 34
                horizontalPadding: 14
                text: "Elegir..."
                primaryStyle: false
                solidShadow: false
                onClicked: actionFolderDialog.open()
            }
        }

        // =====================================================================
        // CENTRO: Progreso (visible mientras procesa), Estado de Error o Éxito
        // =====================================================================
        Item {
            id: centerStatusContainer
            Layout.fillWidth: true
            Layout.fillHeight: true

            // 1. Vista de progreso activo (visible mientras studioBridge.isBusy es true)
            Column {
                id: statusColumn
                visible: studioBridge.isBusy
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5

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
                        font.family: Theme.sansFont
                        font.pixelSize: 12
                        color: Theme.textPrimary
                        elide: Text.ElideRight
                    }

                    Text {
                        id: footerProgressPercentText
                        objectName: "footerProgressPercentText"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: studioBridge.progressPercent + "%"
                        font.family: Theme.sansFont
                        font.pixelSize: 12
                        font.bold: true
                        color: Theme.secondaryWine
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 7
                    radius: 3.5
                    color: "#EAD5D7"
                    border.width: 1
                    border.color: Theme.borderSubtleColor

                    Rectangle {
                        width: parent.width * (studioBridge.progressPercent / 100.0)
                        height: parent.height
                        radius: 3.5
                        color: Theme.secondaryWine

                        Behavior on width {
                            NumberAnimation { duration: Theme.animNormal; easing.type: Easing.OutQuad }
                        }
                    }
                }
            }

            // 2. Vista de error durante proceso o carpeta inválida + botón "Reintentar"
            RowLayout {
                id: errorStatusRow
                objectName: "errorStatusRow"
                visible: !studioBridge.isBusy && (studioBridge.hasProcessingError || !studioBridge.isOutputDirectoryValid)
                anchors.fill: parent
                spacing: 8

                Text {
                    objectName: "errorStatusMessageText"
                    Layout.fillWidth: true
                    text: !studioBridge.isOutputDirectoryValid
                          ? studioBridge.outputDirectoryError
                          : studioBridge.statusMessage
                    font.family: Theme.sansFont
                    font.pixelSize: 12
                    color: Theme.errorText
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                PillButton {
                    id: retryOperationButton
                    objectName: "retryOperationButton"
                    visible: studioBridge.hasProcessingError && studioBridge.isOutputDirectoryValid
                    height: 32
                    horizontalPadding: 14
                    text: "Reintentar"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.retryLastOperation()
                }
            }

            // 3. Vista de operación completada con éxito ("Original intacto ✓", "Abrir archivo", "Mostrar en carpeta")
            RowLayout {
                id: quickActionsRow
                objectName: "quickActionsRow"
                visible: !studioBridge.isBusy && !studioBridge.hasProcessingError && studioBridge.isOutputDirectoryValid && studioBridge.lastOutputFile.length > 0
                anchors.centerIn: parent
                spacing: 8

                Rectangle {
                    objectName: "originalIntactBadge"
                    height: 28
                    width: intactText.implicitWidth + 18
                    radius: 14
                    color: "#EDF5EE"
                    border.width: 1
                    border.color: "#8FA88A"

                    Text {
                        id: intactText
                        anchors.centerIn: parent
                        text: "Original intacto ✓"
                        font.family: Theme.sansFont
                        font.pixelSize: 12
                        color: "#2F5233"
                    }
                }

                PillButton {
                    objectName: "footerOpenFileBtn"
                    height: 32
                    horizontalPadding: 14
                    text: "Abrir archivo"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.openFileInSystem(studioBridge.lastOutputFile)
                }

                PillButton {
                    objectName: "footerShowFolderBtn"
                    height: 32
                    horizontalPadding: 14
                    text: "Mostrar en carpeta"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.showFileInFolder(studioBridge.lastOutputFile)
                }
            }

            // 4. Estado en reposo discreto (recordatorio de protección del original)
            Text {
                visible: !studioBridge.isBusy && !errorStatusRow.visible && !quickActionsRow.visible
                anchors.centerIn: parent
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: studioBridge.fileCount > 0 ? "Original intacto · Sufijo automático seguro" : ""
                font.family: Theme.scriptFont
                font.italic: true
                font.pixelSize: Theme.fontMetaSize
                color: Theme.textPrimary
                opacity: Theme.metaOpacity
                elide: Text.ElideRight
            }
        }

        // =====================================================================
        // DERECHA: Botón Principal Relleno (único botón relleno de la pantalla)
        // =====================================================================
        PillButton {
            id: mainCtaButton
            objectName: "mainCtaButton"
            Layout.alignment: Qt.AlignVCenter
            height: 40
            horizontalPadding: 22
            text: studioBridge.primaryCtaText
            primaryStyle: true
            solidShadow: true
            enabledButton: (studioBridge.validFileCount > 0 && studioBridge.isOutputDirectoryValid) || studioBridge.isBusy
            disabledHint: !studioBridge.isOutputDirectoryValid
                          ? studioBridge.outputDirectoryError
                          : "Agrega archivos a la cola para poder procesar"
            onClicked: studioBridge.triggerPrimaryAction()
        }
    }
}
