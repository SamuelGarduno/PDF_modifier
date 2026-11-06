import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Rectangle {
    id: configRoot
    objectName: "configPanels"

    readonly property bool hasActiveConfig: studioBridge.isToolSelected
                                            && studioBridge.fileCount > 0
                                            && (studioBridge.activeTool === "split"
                                                || studioBridge.activeTool === "compress"
                                                || studioBridge.activeTool === "pdf_to_images"
                                                || studioBridge.activeTool === "watermark")

    visible: hasActiveConfig
    radius: 14
    color: Theme.stationeryFrameBg
    border.width: Theme.borderSubtleWidth
    border.color: Theme.borderSubtleColor

    Item {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 10
        anchors.bottomMargin: 10

        // 1. SPLIT: Rango de páginas con validación en tiempo real + switch separar
        RowLayout {
            visible: studioBridge.activeTool === "split"
            anchors.fill: parent
            spacing: 18

            Column {
                spacing: 4
                Layout.alignment: Qt.AlignVCenter

                Text {
                    text: "Rango de páginas a extraer:"
                    font.family: Theme.sansFont
                    font.pixelSize: Theme.fontBodySize
                    font.bold: true
                    color: Theme.textPrimary
                }

                Text {
                    text: studioBridge.rangeFeedback
                    font.family: Theme.scriptFont
                    font.italic: true
                    font.pixelSize: Theme.fontMetaSize
                    color: studioBridge.isRangeValid ? Theme.secondaryWine : Theme.errorText
                    opacity: studioBridge.isRangeValid ? Theme.metaOpacity : 1.0
                }
            }

            Rectangle {
                Layout.preferredWidth: 220
                Layout.preferredHeight: 36
                Layout.alignment: Qt.AlignVCenter
                radius: 8
                color: "#FFFFFF"
                border.width: Theme.borderSubtleWidth
                border.color: studioBridge.isRangeValid ? Theme.borderSubtleColor : Theme.errorBorder

                TextInput {
                    id: rangeField
                    objectName: "splitRangeInput"
                    anchors.fill: parent
                    anchors.margins: 8
                    verticalAlignment: TextInput.AlignVCenter
                    text: studioBridge.rangeExpr
                    font.family: Theme.sansFont
                    font.pixelSize: Theme.fontBodySize
                    color: Theme.textPrimary
                    onTextEdited: studioBridge.setRangeExpr(text)
                }
            }

            AnimatedSwitch {
                Layout.alignment: Qt.AlignVCenter
                checked: studioBridge.splitSeparateFiles
                labelText: "Un PDF por página extraída"
                onToggled: function(val) { studioBridge.setSplitSeparateFiles(val) }
            }

            Item { Layout.fillWidth: true }
        }

        // 2. COMPRESS: Nivel de compresión con cálculo estimado de reducción
        RowLayout {
            visible: studioBridge.activeTool === "compress"
            anchors.fill: parent
            spacing: 16

            Column {
                spacing: 4
                Layout.alignment: Qt.AlignVCenter

                Text {
                    text: "Nivel de compresión:"
                    font.family: Theme.sansFont
                    font.pixelSize: Theme.fontBodySize
                    font.bold: true
                    color: Theme.textPrimary
                }

                Text {
                    text: studioBridge.estimatedCompressionSummary
                    font.family: Theme.scriptFont
                    font.italic: true
                    font.pixelSize: Theme.fontMetaSize
                    color: Theme.textPrimary
                    opacity: Theme.metaOpacity
                }
            }

            Row {
                spacing: 8
                Layout.alignment: Qt.AlignVCenter
                Repeater {
                    model: [
                        { key: "extreme", label: "Extrema (~62%)" },
                        { key: "recommended", label: "Recomendada (~38%)" },
                        { key: "low_loss", label: "Baja pérdida (~16%)" }
                    ]
                    delegate: Rectangle {
                        width: 148
                        height: 34
                        radius: 17
                        color: studioBridge.compressionLevel === modelData.key
                               ? Theme.secondaryWine
                               : "#FAF3F2"
                        border.width: Theme.borderSubtleWidth
                        border.color: studioBridge.compressionLevel === modelData.key
                                      ? Theme.secondaryWine
                                      : Theme.borderSubtleColor

                        Text {
                            anchors.centerIn: parent
                            text: modelData.label
                            font.family: Theme.sansFont
                            font.pixelSize: 12
                            font.bold: studioBridge.compressionLevel === modelData.key
                            color: studioBridge.compressionLevel === modelData.key
                                   ? Theme.surfaceCard
                                   : Theme.textPrimary
                        }

                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: studioBridge.setCompressionLevel(modelData.key) }
                    }
                }
            }

            Item { Layout.fillWidth: true }
        }

        // 3. PDF_TO_IMAGES: Selector de formato PNG / JPG
        RowLayout {
            visible: studioBridge.activeTool === "pdf_to_images"
            anchors.fill: parent
            spacing: 16

            Column {
                spacing: 4
                Layout.alignment: Qt.AlignVCenter

                Text {
                    text: "Formato de láminas exportadas:"
                    font.family: Theme.sansFont
                    font.pixelSize: Theme.fontBodySize
                    font.bold: true
                    color: Theme.textPrimary
                }

                Text {
                    text: "Cada página se revelará a 160 DPI libre de artefactos."
                    font.family: Theme.scriptFont
                    font.italic: true
                    font.pixelSize: Theme.fontMetaSize
                    color: Theme.textPrimary
                    opacity: Theme.metaOpacity
                }
            }

            Row {
                spacing: 8
                Layout.alignment: Qt.AlignVCenter

                Repeater {
                    model: ["png", "jpg"]
                    delegate: Rectangle {
                        width: 100; height: 34; radius: 17
                        color: studioBridge.imageFormat === modelData ? Theme.secondaryWine : "#FAF3F2"
                        border.width: Theme.borderSubtleWidth
                        border.color: studioBridge.imageFormat === modelData ? Theme.secondaryWine : Theme.borderSubtleColor
                        Text {
                            anchors.centerIn: parent
                            text: modelData.toUpperCase()
                            font.family: Theme.sansFont
                            font.pixelSize: 13
                            font.bold: studioBridge.imageFormat === modelData
                            color: studioBridge.imageFormat === modelData ? Theme.surfaceCard : Theme.textPrimary
                        }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: studioBridge.setImageFormat(modelData) }
                    }
                }
            }

            Item { Layout.fillWidth: true }
        }

        // 4. WATERMARK: Texto, opacidad, ángulo y posición en cuadrícula 3x3
        RowLayout {
            visible: studioBridge.activeTool === "watermark"
            anchors.fill: parent
            spacing: 16

            Text {
                text: "Filigrana:"
                font.family: Theme.sansFont
                font.pixelSize: Theme.fontBodySize
                font.bold: true
                color: Theme.textPrimary
                Layout.alignment: Qt.AlignVCenter
            }

            Rectangle {
                Layout.preferredWidth: 200
                Layout.preferredHeight: 34
                Layout.alignment: Qt.AlignVCenter
                radius: 8
                color: "#FFFFFF"
                border.width: Theme.borderSubtleWidth
                border.color: Theme.borderSubtleColor

                TextInput {
                    anchors.fill: parent
                    anchors.margins: 8
                    verticalAlignment: TextInput.AlignVCenter
                    text: studioBridge.watermarkText
                    font.family: Theme.sansFont
                    font.pixelSize: 13
                    color: Theme.textPrimary
                    onTextEdited: studioBridge.setWatermarkText(text)
                }
            }

            PillButton {
                Layout.alignment: Qt.AlignVCenter
                height: 34
                horizontalPadding: 14
                primaryStyle: false
                solidShadow: false
                text: "Opacidad: " + Math.round(studioBridge.watermarkOpacity * 100) + "%"
                onClicked: {
                    var nextOp = studioBridge.watermarkOpacity >= 0.75 ? 0.20 : studioBridge.watermarkOpacity + 0.15
                    studioBridge.setWatermarkOpacity(nextOp)
                }
            }

            PillButton {
                Layout.alignment: Qt.AlignVCenter
                height: 34
                horizontalPadding: 14
                primaryStyle: false
                solidShadow: false
                text: "Ángulo: " + Math.round(studioBridge.watermarkAngle) + "°"
                onClicked: {
                    var nextAng = studioBridge.watermarkAngle === 45 ? 0 : (studioBridge.watermarkAngle === 0 ? -45 : 45)
                    studioBridge.setWatermarkAngle(nextAng)
                }
            }

            Row {
                spacing: 8
                Layout.alignment: Qt.AlignVCenter

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Posición:"
                    font.family: Theme.scriptFont
                    font.italic: true
                    font.pixelSize: Theme.fontMetaSize
                    color: Theme.textPrimary
                    opacity: Theme.metaOpacity
                }

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
                            width: 18; height: 18; radius: 4
                            color: studioBridge.watermarkPosition === modelData
                                   ? Theme.secondaryWine
                                   : "#FAF3F2"
                            border.width: 1
                            border.color: Theme.borderSubtleColor
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: studioBridge.setWatermarkPosition(modelData) }
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }
        }
    }
}
