import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Rectangle {
    id: footerRoot
    objectName: "footerBar"
    readonly property bool showOutputNameRow: studioBridge.validFileCount > 0
    implicitHeight: showOutputNameRow ? Theme.actionBarExpandedHeight : Theme.actionBarHeight
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

    Connections {
        target: studioBridge
        function onConfigChanged() {
            if (!outputNameInput.activeFocus && outputNameInput.text !== studioBridge.outputFileName) {
                outputNameInput.text = studioBridge.outputFileName
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: footerRoot.showOutputNameRow ? 8 : 0
        anchors.bottomMargin: footerRoot.showOutputNameRow ? 6 : 0
        spacing: 6

        // =====================================================================
        // FILA SUPERIOR: Nombre editable del archivo de salida
        // =====================================================================
        RowLayout {
            id: outputNameRow
            objectName: "outputNameRow"
            visible: footerRoot.showOutputNameRow
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            spacing: 8

            Text {
                text: studioBridge.isBatchMultiFileOutput ? "Nombre base:" : "Nombre:"
                font.family: Theme.sansFont
                font.pixelSize: 13
                font.bold: true
                color: Theme.textPrimary
                Layout.alignment: Qt.AlignVCenter
            }

            Rectangle {
                id: outputNameInputBox
                objectName: "outputNameInputBox"
                Layout.fillWidth: true
                Layout.maximumWidth: 390
                Layout.preferredHeight: 30
                Layout.alignment: Qt.AlignVCenter
                radius: 8
                color: "#FFFFFF"
                border.width: outputNameInput.activeFocus ? 1.5 : Theme.borderSubtleWidth
                border.color: outputNameInput.activeFocus ? Theme.focusRingColor : Theme.borderSubtleColor

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 9
                    anchors.rightMargin: 6
                    spacing: 6

                    TextInput {
                        id: outputNameInput
                        objectName: "outputFileNameInput"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        verticalAlignment: TextInput.AlignVCenter
                        selectByMouse: true
                        clip: true
                        font.family: Theme.sansFont
                        font.pixelSize: 12
                        color: Theme.textPrimary
                        Component.onCompleted: text = studioBridge.outputFileName
                        onTextEdited: studioBridge.setOutputFileName(text)
                        onEditingFinished: {
                            studioBridge.commitOutputFileName()
                            text = studioBridge.outputFileName
                        }
                        onAccepted: focus = false
                        Keys.onEscapePressed: function(event) {
                            text = studioBridge.outputFileName
                            focus = false
                            event.accepted = true
                        }
                    }

                    Rectangle {
                        id: outputExtBadge
                        objectName: "outputFileExtBadge"
                        visible: studioBridge.outputFileExtension.length > 0 || studioBridge.activeTool === "pdf_to_images"
                        Layout.alignment: Qt.AlignVCenter
                        height: 20
                        width: extLabelText.implicitWidth + 10
                        radius: 6
                        color: "#F5E3E1"
                        border.width: 1
                        border.color: Theme.borderSubtleColor

                        Text {
                            id: extLabelText
                            anchors.centerIn: parent
                            text: studioBridge.outputFileExtension.length > 0
                                  ? studioBridge.outputFileExtension
                                  : "/carpeta"
                            font.family: Theme.sansFont
                            font.pixelSize: 11
                            font.bold: true
                            color: Theme.secondaryWine
                        }
                    }
                }

                Text {
                    visible: outputNameInput.text.length === 0 && !outputNameInput.activeFocus
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    text: studioBridge.suggestedOutputName
                    font.family: Theme.sansFont
                    font.pixelSize: 12
                    color: Theme.textMuted
                    opacity: 0.7
                }
            }

            PillButton {
                id: resetOutputNameBtn
                objectName: "resetOutputNameBtn"
                visible: studioBridge.isOutputNameCustomized
                Layout.alignment: Qt.AlignVCenter
                height: 26
                minWidth: 0
                horizontalPadding: 10
                fontPixelSize: 11
                text: "Restablecer"
                primaryStyle: false
                solidShadow: false
                onClicked: {
                    studioBridge.resetOutputFileName()
                    outputNameInput.text = studioBridge.outputFileName
                }
            }

            Item { Layout.fillWidth: true }

            Text {
                visible: footerRoot.width >= 740
                Layout.alignment: Qt.AlignVCenter
                text: studioBridge.isBatchMultiFileOutput
                      ? "En lote agrega _1, _2 · si ya existe, añade (1)"
                      : "Original intacto · si ya existe, añade (1)"
                font.family: Theme.scriptFont
                font.italic: true
                font.pixelSize: 11
                color: Theme.textPrimary
                opacity: Theme.metaOpacity
            }
        }

        Rectangle {
            visible: footerRoot.showOutputNameRow
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.borderSubtleColor
            opacity: 0.38
        }

        // =====================================================================
        // FILA INFERIOR: Carpeta destino · Estado / Acciones rápidas · CTA
        // =====================================================================
        RowLayout {
            id: footerActionsRow
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            // IZQUIERDA: "Guardar en: [ruta] [Elegir...]"
            RowLayout {
                id: folderPickerSection
                objectName: "folderPickerSection"
                spacing: 8
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: implicitWidth
                Layout.maximumWidth: implicitWidth

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
                    Layout.preferredWidth: quickActionsRow.visible
                                           ? Math.max(104, Math.min(170, Math.floor(footerRoot.width * 0.14)))
                                           : Math.max(130, Math.min(220, Math.floor(footerRoot.width * 0.20)))
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
                    height: 32
                    minWidth: 0
                    horizontalPadding: 11
                    fontPixelSize: 12
                    text: "Elegir..."
                    primaryStyle: false
                    solidShadow: false
                    onClicked: actionFolderDialog.open()
                }
            }

            // CENTRO: Progreso (visible mientras procesa), Estado de Error o Éxito
            Item {
                id: centerStatusContainer
                objectName: "centerStatusContainer"
                clip: true
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
                Row {
                    id: quickActionsRow
                    objectName: "quickActionsRow"
                    visible: !studioBridge.isBusy && !studioBridge.hasProcessingError && studioBridge.isOutputDirectoryValid && studioBridge.lastOutputFilePath.length > 0
                    anchors.centerIn: parent
                    spacing: 6

                    Rectangle {
                        id: originalIntactBadge
                        objectName: "originalIntactBadge"
                        anchors.verticalCenter: parent.verticalCenter
                        height: 28
                        width: intactText.implicitWidth + 14
                        radius: 14
                        color: "#EDF5EE"
                        border.width: 1
                        border.color: "#8FA88A"

                        Text {
                            id: intactText
                            anchors.centerIn: parent
                            text: centerStatusContainer.width < 340 ? "✓ Intacto" : "Original intacto ✓"
                            font.family: Theme.sansFont
                            font.pixelSize: 11
                            color: "#2F5233"
                        }
                    }

                    PillButton {
                        objectName: "footerOpenFileBtn"
                        anchors.verticalCenter: parent.verticalCenter
                        height: 30
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 12
                        text: "Abrir archivo"
                        primaryStyle: false
                        solidShadow: false
                        onClicked: studioBridge.openFileInSystem(studioBridge.lastOutputFilePath)
                    }

                    PillButton {
                        objectName: "footerShowFolderBtn"
                        anchors.verticalCenter: parent.verticalCenter
                        height: 30
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 12
                        text: "Mostrar en carpeta"
                        primaryStyle: false
                        solidShadow: false
                        onClicked: studioBridge.showFileInFolder(studioBridge.lastOutputFilePath)
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

            // DERECHA: Botón Principal Relleno (único botón relleno de la pantalla)
            PillButton {
                id: mainCtaButton
                objectName: "mainCtaButton"
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: implicitWidth
                height: 40
                horizontalPadding: 18
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
}
