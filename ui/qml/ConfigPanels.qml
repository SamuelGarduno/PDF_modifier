import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Rectangle {
    id: configRoot
    property bool showPasswordPlain: false

    radius: 10
    color: themePalette.stationeryFrameBg
    border.width: 1.2
    border.color: "#8E4A5E"

    FolderDialog {
        id: outputFolderDialog
        title: "Seleccionar carpeta de destino"
        onAccepted: {
            studioBridge.setOutputDirectory(outputFolderDialog.selectedFolder.toString())
        }
    }

    Row {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 16

        // Columna izquierda: Configuración dinámica según la herramienta activa
        Item {
            width: parent.width * 0.62
            height: parent.height

            // 1. SPLIT: Rango de páginas con validación en tiempo real + switch separar
            Column {
                visible: studioBridge.activeTool === "split"
                anchors.fill: parent
                spacing: 8

                Text {
                    text: "Rango de Páginas a Extraer (ej. 1-5, 8, 11-13):"
                    font.family: themePalette.serifFont
                    font.pixelSize: 13
                    font.bold: true
                    color: themePalette.backgroundDark
                }

                Row {
                    spacing: 12
                    width: parent.width

                    Rectangle {
                        width: 240
                        height: 34
                        radius: 8
                        color: "#FFFFFF"
                        border.width: 1.4
                        border.color: studioBridge.isRangeValid ? themePalette.secondary : "#B00020"

                        TextInput {
                            id: rangeField
                            anchors.fill: parent
                            anchors.margins: 8
                            text: studioBridge.rangeExpr
                            font.family: themePalette.sansFont
                            font.pixelSize: 13
                            color: themePalette.backgroundDark
                            onTextEdited: studioBridge.setRangeExpr(text)
                        }
                    }

                    AnimatedSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: studioBridge.splitSeparateFiles
                        labelText: "Un PDF por página extraída"
                        onToggled: function(val) { studioBridge.setSplitSeparateFiles(val) }
                    }
                }

                Text {
                    text: studioBridge.rangeFeedback
                    font.family: themePalette.sansFont
                    font.pixelSize: 11
                    color: studioBridge.isRangeValid ? themePalette.secondary : "#B00020"
                }
            }

            // 2. COMPRESS: Nivel de compresión con cálculo estimado de reducción
            Column {
                visible: studioBridge.activeTool === "compress"
                anchors.fill: parent
                spacing: 8

                Text {
                    text: "Nivel de Compresión de Pliegos:"
                    font.family: themePalette.serifFont
                    font.pixelSize: 13
                    font.bold: true
                    color: themePalette.backgroundDark
                }

                Row {
                    spacing: 10
                    Repeater {
                        model: [
                            { key: "extreme", label: "Extrema (~62%)" },
                            { key: "recommended", label: "Recomendada (~38%)" },
                            { key: "low_loss", label: "Baja Pérdida (~16%)" }
                        ]
                        delegate: Rectangle {
                            width: 145
                            height: 32
                            radius: 16
                            color: studioBridge.compressionLevel === modelData.key
                                   ? themePalette.secondary
                                   : themePalette.accent
                            border.width: 1
                            border.color: themePalette.secondary

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.family: themePalette.sansFont
                                font.pixelSize: 11
                                font.bold: true
                                color: studioBridge.compressionLevel === modelData.key
                                       ? themePalette.surfaceLight
                                       : themePalette.backgroundDark
                            }

                            TapHandler { onTapped: studioBridge.setCompressionLevel(modelData.key) }
                        }
                    }
                }

                Text {
                    text: studioBridge.estimatedCompressionSummary
                    font.family: themePalette.sansFont
                    font.pixelSize: 12
                    color: themePalette.secondary
                }
            }

            // 3. PROTECT / UNLOCK: Input de contraseña con toggle de visibilidad
            Column {
                visible: studioBridge.activeTool === "protect" || studioBridge.activeTool === "unlock"
                anchors.fill: parent
                spacing: 8

                Text {
                    text: studioBridge.activeTool === "protect"
                          ? "Contraseña para Cifrar Documento (AES-256):"
                          : "Contraseña Actual para Desbloquear Documento:"
                    font.family: themePalette.serifFont
                    font.pixelSize: 13
                    font.bold: true
                    color: themePalette.backgroundDark
                }

                Row {
                    spacing: 12

                    Rectangle {
                        width: 240
                        height: 34
                        radius: 8
                        color: "#FFFFFF"
                        border.width: 1.3
                        border.color: themePalette.secondary

                        TextInput {
                            id: passwordField
                            anchors.fill: parent
                            anchors.margins: 8
                            text: studioBridge.passwordInput
                            echoMode: configRoot.showPasswordPlain ? TextInput.Normal : TextInput.Password
                            font.family: themePalette.sansFont
                            font.pixelSize: 13
                            color: themePalette.backgroundDark
                            onTextEdited: studioBridge.setPasswordInput(text)
                        }
                    }

                    AnimatedSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: configRoot.showPasswordPlain
                        labelText: "Mostrar contraseña"
                        onToggled: function(val) { configRoot.showPasswordPlain = val }
                    }
                }
            }

            // 4. PDF_TO_IMAGES / IMAGES_TO_PDF: Selector de formato PNG / JPG
            Column {
                visible: studioBridge.activeTool === "pdf_to_images" || studioBridge.activeTool === "images_to_pdf"
                anchors.fill: parent
                spacing: 8

                Text {
                    text: studioBridge.activeTool === "pdf_to_images"
                          ? "Formato de Láminas Exportadas:"
                          : "Conversión de Álbum de Imágenes a PDF:"
                    font.family: themePalette.serifFont
                    font.pixelSize: 13
                    font.bold: true
                    color: themePalette.backgroundDark
                }

                Row {
                    visible: studioBridge.activeTool === "pdf_to_images"
                    spacing: 10

                    Repeater {
                        model: ["png", "jpg"]
                        delegate: Rectangle {
                            width: 110; height: 32; radius: 16
                            color: studioBridge.imageFormat === modelData ? themePalette.secondary : themePalette.accent
                            border.width: 1; border.color: themePalette.secondary
                            Text {
                                anchors.centerIn: parent
                                text: modelData.toUpperCase()
                                font.family: themePalette.sansFont
                                font.pixelSize: 12
                                font.bold: true
                                color: studioBridge.imageFormat === modelData ? themePalette.surfaceLight : themePalette.backgroundDark
                            }
                            TapHandler { onTapped: studioBridge.setImageFormat(modelData) }
                        }
                    }
                }

                Text {
                    text: studioBridge.activeTool === "pdf_to_images"
                          ? "Cada página se renderizará a 160 DPI libre de artefactos."
                          : "Las imágenes en la cola se encuadernarán respetando su proporción."
                    font.family: themePalette.sansFont
                    font.pixelSize: 12
                    color: themePalette.secondary
                }
            }

            // 5. WATERMARK: Texto, opacidad, ángulo y posición en cuadrícula 3x3
            Row {
                visible: studioBridge.activeTool === "watermark"
                anchors.fill: parent
                spacing: 14

                Column {
                    width: parent.width - 110
                    spacing: 6

                    Text {
                        text: "Filigrana / Marca de Agua:"
                        font.family: themePalette.serifFont
                        font.pixelSize: 13
                        font.bold: true
                        color: themePalette.backgroundDark
                    }

                    Row {
                        spacing: 8
                        Rectangle {
                            width: 170; height: 30; radius: 6
                            color: "#FFFFFF"; border.color: themePalette.secondary
                            TextInput {
                                anchors.fill: parent; anchors.margins: 6
                                text: studioBridge.watermarkText
                                font.family: themePalette.sansFont; font.pixelSize: 12
                                color: themePalette.backgroundDark
                                onTextEdited: studioBridge.setWatermarkText(text)
                            }
                        }

                        Rectangle {
                            width: 74; height: 30; radius: 6
                            color: themePalette.accent; border.color: themePalette.secondary
                            Text {
                                anchors.centerIn: parent
                                text: "Opac: " + Math.round(studioBridge.watermarkOpacity * 100) + "%"
                                font.family: themePalette.sansFont; font.pixelSize: 11
                            }
                            TapHandler {
                                onTapped: {
                                    var nextOp = studioBridge.watermarkOpacity >= 0.75 ? 0.20 : studioBridge.watermarkOpacity + 0.15
                                    studioBridge.setWatermarkOpacity(nextOp)
                                }
                            }
                        }

                        Rectangle {
                            width: 74; height: 30; radius: 6
                            color: themePalette.primary; border.color: themePalette.secondary
                            Text {
                                anchors.centerIn: parent
                                text: "Áng: " + Math.round(studioBridge.watermarkAngle) + "°"
                                font.family: themePalette.sansFont; font.pixelSize: 11
                            }
                            TapHandler {
                                onTapped: {
                                    var nextAng = studioBridge.watermarkAngle === 45 ? 0 : (studioBridge.watermarkAngle === 0 ? -45 : 45)
                                    studioBridge.setWatermarkAngle(nextAng)
                                }
                            }
                        }
                    }
                }

                // Cuadrícula 3x3 de posición de marca de agua
                Grid {
                    columns: 3
                    spacing: 3
                    anchors.verticalCenter: parent.verticalCenter

                    Repeater {
                        model: [
                            "top_left", "top_center", "top_right",
                            "middle_left", "center", "middle_right",
                            "bottom_left", "bottom_center", "bottom_right"
                        ]
                        delegate: Rectangle {
                            width: 22; height: 22; radius: 4
                            color: studioBridge.watermarkPosition === modelData
                                   ? themePalette.secondary
                                   : themePalette.accent
                            border.width: 1
                            border.color: themePalette.secondary
                            TapHandler { onTapped: studioBridge.setWatermarkPosition(modelData) }
                        }
                    }
                }
            }

            // 6. MERGE / ORGANIZE / SIGN: Resumen contextual de herramienta con jerarquía de 3 niveles
            Column {
                visible: studioBridge.activeTool === "merge" || studioBridge.activeTool === "organize" || studioBridge.activeTool === "sign"
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 2

                Text {
                    objectName: "activeModeHeaderLabel"
                    text: "MODO ACTIVO"
                    font.family: themePalette.sansFont
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.8
                    color: "#8C465A"
                }

                Text {
                    objectName: "activeModeToolTitle"
                    text: studioBridge.activeToolTitle
                    font.family: themePalette.serifFont
                    font.pixelSize: 16
                    font.bold: true
                    color: "#3D1220"
                }

                Text {
                    objectName: "activeModeDescription"
                    text: studioBridge.activeTool === "merge"
                          ? "Los documentos de la cola se unirán en el orden listado. Nunca se sobrescribe el original."
                          : (studioBridge.activeTool === "organize"
                             ? "Usa los botones flotantes o arrastra tarjetas para reordenar, rotar 90°, duplicar o descartar."
                             : "Dibuja tu rúbrica sobre el papel, elige un sello de lacre o adjunta una firma PNG transparente.")
                    font.family: themePalette.sansFont
                    font.pixelSize: 12
                    color: "#681D3A"
                    wrapMode: Text.WordWrap
                    width: parent.width
                }
            }
        }

        // Separador vertical fino punteado
        Canvas {
            width: 2
            height: parent.height - 6
            anchors.verticalCenter: parent.verticalCenter
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = "#9E586D"
                ctx.lineWidth = 1.1
                ctx.setLineDash([3, 3])
                ctx.beginPath()
                ctx.moveTo(1, 0)
                ctx.lineTo(1, height)
                ctx.stroke()
            }
            onHeightChanged: requestPaint()
        }

        // Columna derecha: Selector de ruta de guardado y protección de archivos originales
        Column {
            width: parent.width * 0.35 - 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            Row {
                spacing: 4

                Text {
                    text: "Carpeta de guardado "
                    font.family: themePalette.serifFont
                    font.pixelSize: 12
                    font.bold: true
                    color: "#3D1220"
                }

                Text {
                    anchors.baseline: parent.children[0].baseline
                    text: "(sufijo automático seguro)"
                    font.family: themePalette.scriptFont
                    font.italic: true
                    font.pixelSize: 12
                    color: "#8C465A"
                }
            }

            Row {
                spacing: 8
                width: parent.width

                Rectangle {
                    width: parent.width - 96
                    height: 30
                    radius: 8
                    color: "#FFFDFB"
                    border.width: 1
                    border.color: "#B88492"

                    Text {
                        anchors.fill: parent
                        anchors.margins: 6
                        verticalAlignment: Text.AlignVCenter
                        text: studioBridge.outputDirectory.length > 0
                              ? studioBridge.outputDirectory
                              : "Misma carpeta del documento original"
                        font.family: themePalette.sansFont
                        font.pixelSize: 11
                        elide: Text.ElideLeft
                        color: "#3D1220"
                    }
                }

                PillButton {
                    width: 88
                    height: 30
                    text: "Elegir..."
                    primaryStyle: false
                    solidShadow: false
                    onClicked: outputFolderDialog.open()
                }
            }
        }
    }
}

