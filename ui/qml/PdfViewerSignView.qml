import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: viewerRoot
    objectName: "pdfViewerSignView"
    property var currentStroke: []
    property var allStrokes: []
    property string strokeHexColor: "#000000"

    FileDialog {
        id: pngSignatureDialog
        title: "Seleccionar firma o sello PNG transparente"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Imágenes PNG (*.png)"]
        onAccepted: {
            studioBridge.setSignatureImagePath(pngSignatureDialog.selectedFile.toString())
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // Barra de herramientas del visor: paginación, zoom, modo (Desplazar vs. Firmar), sellos ("Sin Sello") y PNG
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            radius: 8
            color: themePalette.surfaceLight
            border.width: 1
            border.color: themePalette.secondary

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 6

                // Paginación
                Rectangle {
                    width: 26; height: 26; radius: 6
                    color: themePalette.accent
                    border.color: themePalette.secondary
                    Text { anchors.centerIn: parent; text: "◀"; font.pixelSize: 11; color: themePalette.backgroundDark }
                    TapHandler { onTapped: studioBridge.setViewerPageIndex(studioBridge.viewerPageIndex - 1) }
                }

                Text {
                    text: "Pág. " + (studioBridge.viewerPageIndex + 1) + "/" + Math.max(1, studioBridge.primaryDocumentPageCount)
                    font.family: themePalette.sansFont
                    font.pixelSize: 11
                    font.bold: true
                    color: themePalette.backgroundDark
                }

                Rectangle {
                    width: 26; height: 26; radius: 6
                    color: themePalette.accent
                    border.color: themePalette.secondary
                    Text { anchors.centerIn: parent; text: "▶"; font.pixelSize: 11; color: themePalette.backgroundDark }
                    TapHandler { onTapped: studioBridge.setViewerPageIndex(studioBridge.viewerPageIndex + 1) }
                }

                // Controles de Zoom Fluido
                Rectangle {
                    width: 26; height: 26; radius: 6
                    color: themePalette.primary
                    border.color: themePalette.secondary
                    Text { anchors.centerIn: parent; text: "−"; font.bold: true; color: themePalette.backgroundDark }
                    TapHandler { onTapped: studioBridge.setViewerZoom(studioBridge.viewerZoom - 0.15) }
                }

                Text {
                    text: Math.round(studioBridge.viewerZoom * 100) + "%"
                    font.family: themePalette.sansFont
                    font.pixelSize: 11
                    color: themePalette.secondary
                }

                Rectangle {
                    width: 26; height: 26; radius: 6
                    color: themePalette.primary
                    border.color: themePalette.secondary
                    Text { anchors.centerIn: parent; text: "+"; font.bold: true; color: themePalette.backgroundDark }
                    TapHandler { onTapped: studioBridge.setViewerZoom(studioBridge.viewerZoom + 0.15) }
                }

                // Selector de Modo: "Modo Trazar Firma" vs "Modo Mover Documento"
                Rectangle {
                    id: modeToggleButton
                    objectName: "viewerModeToggleButton"
                    Layout.preferredWidth: 148
                    Layout.preferredHeight: 28
                    radius: 14
                    color: studioBridge.viewerDrawMode ? themePalette.secondary : themePalette.accent
                    border.width: 1.2
                    border.color: themePalette.secondary

                    Text {
                        anchors.centerIn: parent
                        text: studioBridge.viewerDrawMode ? "✍ Modo Trazar Firma" : "✋ Modo Mover Hoja"
                        font.family: themePalette.sansFont
                        font.pixelSize: 11
                        font.bold: true
                        color: studioBridge.viewerDrawMode ? themePalette.surfaceLight : themePalette.backgroundDark
                    }

                    TapHandler {
                        onTapped: studioBridge.setViewerDrawMode(!studioBridge.viewerDrawMode)
                    }
                }

                // Selector de Sellos con opción explícita "Sin Sello"
                Repeater {
                    model: [
                        { key: "", label: "SIN SELLO" },
                        { key: "APROBADO", label: "APROBADO" },
                        { key: "CONFIDENCIAL", label: "CONFIDENCIAL" },
                        { key: "REVISADO", label: "REVISADO" }
                    ]
                    delegate: Rectangle {
                        objectName: "stampOption_" + (modelData.key.length > 0 ? modelData.key : "NONE")
                        Layout.preferredWidth: modelData.key === "CONFIDENCIAL" ? 92 : 76
                        Layout.preferredHeight: 26
                        radius: 13
                        color: studioBridge.signatureStamp === modelData.key
                               ? themePalette.secondary
                               : themePalette.surfaceLight
                        border.width: 1
                        border.color: themePalette.secondary

                        Text {
                            anchors.centerIn: parent
                            text: modelData.label
                            font.family: themePalette.sansFont
                            font.pixelSize: 9
                            font.bold: true
                            color: studioBridge.signatureStamp === modelData.key
                                   ? themePalette.surfaceLight
                                   : themePalette.backgroundDark
                        }

                        TapHandler {
                            onTapped: {
                                if (modelData.key === "" || studioBridge.signatureStamp === modelData.key) {
                                    studioBridge.clearSignatureStamp()
                                } else {
                                    studioBridge.setSignatureStamp(modelData.key)
                                }
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                PillButton {
                    height: 28
                    horizontalPadding: 10
                    text: "Firma PNG"
                    primaryStyle: false
                    onClicked: pngSignatureDialog.open()
                }

                PillButton {
                    height: 28
                    horizontalPadding: 10
                    text: "Limpiar Trazo"
                    primaryStyle: false
                    onClicked: {
                        viewerRoot.allStrokes = []
                        viewerRoot.currentStroke = []
                        signatureCanvas.requestPaint()
                        studioBridge.clearFreehandStrokes()
                    }
                }
            }
        }

        // Lienzo de inspección con zoom fluido; interactive se bloquea en Modo Trazar Firma
        Flickable {
            id: pageFlickable
            objectName: "viewerFlickable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: Math.max(width, paperSheet.width + 32)
            contentHeight: Math.max(height, paperSheet.height + 32)
            clip: true
            interactive: !studioBridge.viewerDrawMode && !signatureMouseArea.pressed
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

            Rectangle {
                id: paperSheet
                objectName: "viewerPaperSheet"
                anchors.centerIn: parent
                property real pageAspect: (pdfRenderImage.implicitWidth > 0 && pdfRenderImage.implicitHeight > 0)
                                          ? (pdfRenderImage.implicitWidth / pdfRenderImage.implicitHeight)
                                          : (595.0 / 842.0)
                width: Math.round(480 * pageAspect * studioBridge.viewerZoom)
                height: Math.round(480 * studioBridge.viewerZoom)
                color: "#FFFFFF"
                border.width: 1.5
                border.color: themePalette.secondary

                Image {
                    id: pdfRenderImage
                    anchors.fill: parent
                    fillMode: Image.Stretch
                    asynchronous: true
                    source: studioBridge.currentViewerPageUrl
                }

                // Previsualización transparente del sello opcional (sin fondo rosado opaco ni recorte)
                Item {
                    id: stampPreviewBox
                    objectName: "stampPreviewBox"
                    visible: studioBridge.signatureStamp.length > 0
                    width: parent.width * 0.32
                    height: parent.height * 0.14
                    x: parent.width * 0.60
                    y: parent.height * 0.78

                    Text {
                        anchors.centerIn: parent
                        text: "✦ " + studioBridge.signatureStamp + " ✦"
                        font.family: themePalette.serifFont
                        font.pixelSize: Math.max(10, Math.round(parent.height * 0.28))
                        font.bold: true
                        color: themePalette.secondary
                    }

                    // Botón directo para quitar el sello desde la vista previa
                    Rectangle {
                        width: 18; height: 18; radius: 9
                        anchors.top: parent.top
                        anchors.right: parent.right
                        color: themePalette.secondary
                        Text {
                            anchors.centerIn: parent
                            text: "✕"
                            font.pixelSize: 9
                            font.bold: true
                            color: themePalette.surfaceLight
                        }
                        TapHandler { onTapped: studioBridge.clearSignatureStamp() }
                    }
                }

                // Capa Canvas interactiva para firma manuscrita a mano alzada en negro puro (#000000)
                Canvas {
                    id: signatureCanvas
                    objectName: "signatureCanvas"
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.strokeStyle = viewerRoot.strokeHexColor
                        ctx.lineWidth = 2.4
                        ctx.lineCap = "round"
                        ctx.lineJoin = "round"

                        for (var s = 0; s < viewerRoot.allStrokes.length; s++) {
                            var stroke = viewerRoot.allStrokes[s]
                            if (stroke.length < 2) continue
                            ctx.beginPath()
                            ctx.moveTo(stroke[0].x * width, stroke[0].y * height)
                            for (var i = 1; i < stroke.length; i++) {
                                ctx.lineTo(stroke[i].x * width, stroke[i].y * height)
                            }
                            ctx.stroke()
                        }

                        if (viewerRoot.currentStroke.length >= 2) {
                            ctx.beginPath()
                            ctx.moveTo(viewerRoot.currentStroke[0].x * width, viewerRoot.currentStroke[0].y * height)
                            for (var j = 1; j < viewerRoot.currentStroke.length; j++) {
                                ctx.lineTo(viewerRoot.currentStroke[j].x * width, viewerRoot.currentStroke[j].y * height)
                            }
                            ctx.stroke()
                        }
                    }

                    MouseArea {
                        id: signatureMouseArea
                        objectName: "signatureMouseArea"
                        anchors.fill: parent
                        enabled: studioBridge.viewerDrawMode
                        preventStealing: true
                        cursorShape: studioBridge.viewerDrawMode ? Qt.CrossCursor : Qt.OpenHandCursor

                        onPressed: function(mouse) {
                            viewerRoot.currentStroke = [{
                                x: Math.max(0, Math.min(1, mouse.x / width)),
                                y: Math.max(0, Math.min(1, mouse.y / height))
                            }]
                        }
                        onPositionChanged: function(mouse) {
                            if (pressed) {
                                var pts = viewerRoot.currentStroke
                                pts.push({
                                    x: Math.max(0, Math.min(1, mouse.x / width)),
                                    y: Math.max(0, Math.min(1, mouse.y / height))
                                })
                                viewerRoot.currentStroke = pts
                                signatureCanvas.requestPaint()
                            }
                        }
                        onReleased: {
                            if (viewerRoot.currentStroke.length >= 2) {
                                var listCopy = viewerRoot.allStrokes
                                listCopy.push(viewerRoot.currentStroke)
                                viewerRoot.allStrokes = listCopy
                                studioBridge.addFreehandStroke(viewerRoot.currentStroke)
                            }
                            viewerRoot.currentStroke = []
                            signatureCanvas.requestPaint()
                        }
                    }
                }
            }
        }
    }
}
