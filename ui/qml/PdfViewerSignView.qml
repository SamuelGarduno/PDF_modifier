import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "."

Item {
    id: viewerRoot
    objectName: "pdfViewerSignView"
    property var currentStroke: []
    property var allStrokes: studioBridge ? studioBridge.currentPageStrokes : []
    property string strokeHexColor: "#000000"

    function syncDpr() {
        if (studioBridge && Screen.devicePixelRatio > 0) {
            studioBridge.setViewerDevicePixelRatio(Screen.devicePixelRatio)
        }
    }

    function drawSmoothStroke(ctx, pts, widthPt) {
        if (!pts || pts.length < 2) {
            return
        }
        var w = Math.max(1, signatureCanvas.width)
        var h = Math.max(1, signatureCanvas.height)
        var effPt = (widthPt !== undefined && widthPt > 0)
                    ? widthPt
                    : (studioBridge ? studioBridge.signatureStrokeWidthPt : Theme.strokeWidthFinePt)
        ctx.lineWidth = Math.max(1.0, (effPt / Theme.pdfReferencePageWidthPt) * w)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.beginPath()

        var p0x = pts[0].x * w
        var p0y = pts[0].y * h
        ctx.moveTo(p0x, p0y)

        if (pts.length === 2) {
            ctx.lineTo(pts[1].x * w, pts[1].y * h)
        } else {
            for (var i = 1; i < pts.length - 1; i++) {
                var cx = pts[i].x * w
                var cy = pts[i].y * h
                var nx = pts[i + 1].x * w
                var ny = pts[i + 1].y * h
                var midX = (cx + nx) * 0.5
                var midY = (cy + ny) * 0.5
                ctx.quadraticCurveTo(cx, cy, midX, midY)
            }
            var last = pts[pts.length - 1]
            ctx.lineTo(last.x * w, last.y * h)
        }
        ctx.stroke()
    }

    Shortcut {
        id: viewerUndoShortcut
        objectName: "viewerUndoShortcut"
        sequences: [StandardKey.Undo]
        enabled: viewerRoot.visible && !stampCustomTextInput.activeFocus
        onActivated: studioBridge.undoViewerAction()
    }

    Component.onCompleted: {
        syncDpr()
        signatureCanvas.requestPaint()
        stampPreviewBox.syncStampBoxWidthToText()
    }

    Connections {
        target: studioBridge
        function onViewerChanged() {
            viewerRoot.allStrokes = studioBridge.currentPageStrokes
            signatureCanvas.requestPaint()
            if (!stampCustomTextInput.activeFocus && stampCustomTextInput.text !== studioBridge.signatureStamp) {
                stampCustomTextInput.text = studioBridge.signatureStamp
            }
            stampPreviewBox.syncStampBoxWidthToText()
        }
    }

    FileDialog {
        id: pngSignatureDialog
        title: "Seleccionar firma o sello PNG transparente"
        fileMode: FileDialog.OpenFile
        currentFolder: studioBridge ? studioBridge.initialSignatureDialogFolderUrl : ""
        nameFilters: ["Imágenes PNG (*.png)"]
        onAccepted: {
            studioBridge.setSignatureImagePath(pngSignatureDialog.selectedFile.toString())
        }
        onRejected: {
            // Cancelar el diálogo no produce error ni altera el estado
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // Barra de herramientas del visor: paginación, zoom, modo, grosor, sello libre, PNG, deshacer y restaurar
        Rectangle {
            id: viewerToolbarBox
            objectName: "viewerToolbarBox"
            Layout.fillWidth: true
            Layout.preferredHeight: toolbarFlow.implicitHeight + 14
            radius: 8
            color: themePalette.surfaceLight
            border.width: 1
            border.color: themePalette.secondary

            Flow {
                id: toolbarFlow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 7
                spacing: 6

                // 1. Paginación
                Row {
                    spacing: 4
                    Rectangle {
                        width: 26; height: 26; radius: 6
                        color: themePalette.accent
                        border.color: themePalette.secondary
                        Text { anchors.centerIn: parent; text: "◀"; font.pixelSize: 11; color: themePalette.backgroundDark }
                        TapHandler { onTapped: studioBridge.setViewerPageIndex(studioBridge.viewerPageIndex - 1) }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
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
                }

                // 2. Controles de Zoom Fluido
                Row {
                    spacing: 4
                    Rectangle {
                        width: 26; height: 26; radius: 6
                        color: themePalette.primary
                        border.color: themePalette.secondary
                        Text { anchors.centerIn: parent; text: "−"; font.bold: true; color: themePalette.backgroundDark }
                        TapHandler { onTapped: studioBridge.setViewerZoom(studioBridge.viewerZoom - 0.15) }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
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
                }

                // 3. Selector de Modo: "Modo Trazar Firma" vs "Modo Mover Hoja"
                Rectangle {
                    id: modeToggleButton
                    objectName: "viewerModeToggleButton"
                    width: 144
                    height: 26
                    radius: 13
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

                // 4. Selector de Grosor de Trazo: Fino (predeterminado), Medio, Grueso
                Row {
                    spacing: 4
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Trazo:"
                        font.family: themePalette.sansFont
                        font.pixelSize: 10
                        font.bold: true
                        color: themePalette.secondary
                    }
                    Repeater {
                        model: [
                            { key: "fine", label: "Fino" },
                            { key: "medium", label: "Medio" },
                            { key: "bold", label: "Grueso" }
                        ]
                        delegate: Rectangle {
                            objectName: "strokeWidthOption_" + modelData.key
                            width: 48
                            height: 26
                            radius: 13
                            color: studioBridge.signatureStrokeWidthKey === modelData.key
                                   ? themePalette.secondary
                                   : themePalette.surfaceLight
                            border.width: 1
                            border.color: themePalette.secondary

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.family: themePalette.sansFont
                                font.pixelSize: 10
                                font.bold: true
                                color: studioBridge.signatureStrokeWidthKey === modelData.key
                                       ? themePalette.surfaceLight
                                       : themePalette.backgroundDark
                            }

                            TapHandler {
                                onTapped: studioBridge.setSignatureStrokeWidthKey(modelData.key)
                            }
                        }
                    }
                }

                // 5. Sello con texto libre editable + chips rápidos de sugerencia
                Row {
                    spacing: 4

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Sello:"
                        font.family: themePalette.sansFont
                        font.pixelSize: 10
                        font.bold: true
                        color: themePalette.secondary
                    }

                    Rectangle {
                        id: stampTextInputBox
                        width: 148
                        height: 26
                        radius: 6
                        color: "#FFFFFF"
                        border.width: stampCustomTextInput.activeFocus ? 1.5 : 1
                        border.color: stampCustomTextInput.activeFocus ? Theme.focusRingColor : themePalette.secondary

                        TextInput {
                            id: stampCustomTextInput
                            objectName: "stampCustomTextInput"
                            anchors.fill: parent
                            anchors.leftMargin: 7
                            anchors.rightMargin: 7
                            verticalAlignment: TextInput.AlignVCenter
                            selectByMouse: true
                            clip: true
                            font.family: themePalette.sansFont
                            font.pixelSize: 11
                            color: themePalette.backgroundDark
                            Component.onCompleted: text = studioBridge ? studioBridge.signatureStamp : ""
                            onActiveFocusChanged: {
                                if (!studioBridge)
                                    return
                                if (activeFocus) {
                                    studioBridge.captureViewerUndoCheckpoint()
                                } else {
                                    studioBridge.setSignatureStampLive(text.trim())
                                    studioBridge.commitViewerUndoCheckpoint("stamp")
                                    text = studioBridge.signatureStamp
                                }
                            }
                            onTextEdited: {
                                if (studioBridge)
                                    studioBridge.setSignatureStampLive(text)
                            }
                            onAccepted: focus = false
                        }

                        Text {
                            visible: stampCustomTextInput.text.length === 0 && !stampCustomTextInput.activeFocus
                            anchors.left: parent.left
                            anchors.leftMargin: 7
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Escribe tu sello..."
                            font.family: themePalette.sansFont
                            font.pixelSize: 11
                            color: Theme.textMuted
                            opacity: 0.7
                        }
                    }

                    Repeater {
                        model: [
                            { key: "", label: "SIN SELLO" },
                            { key: "APROBADO", label: "APROBADO" },
                            { key: "CONFIDENCIAL", label: "CONFIDENCIAL" },
                            { key: "REVISADO", label: "REVISADO" }
                        ]
                        delegate: Rectangle {
                            objectName: "stampOption_" + (modelData.key.length > 0 ? modelData.key : "NONE")
                            width: modelData.key === "CONFIDENCIAL" ? 84 : 64
                            height: 26
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
                                    stampCustomTextInput.focus = false
                                    if (modelData.key === "" || studioBridge.signatureStamp === modelData.key) {
                                        studioBridge.clearSignatureStamp()
                                    } else {
                                        studioBridge.setSignatureStamp(modelData.key)
                                    }
                                }
                            }
                        }
                    }
                }

                // 6. Acciones: Firma PNG, Deshacer (Ctrl+Z), Limpiar Trazo y Restaurar original
                Row {
                    spacing: 6
                    PillButton {
                        objectName: "pngSignatureButton"
                        height: 26
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 11
                        text: "Firma PNG"
                        primaryStyle: false
                        solidShadow: false
                        onClicked: pngSignatureDialog.open()
                    }

                    PillButton {
                        id: undoViewerButton
                        objectName: "undoViewerButton"
                        height: 26
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 11
                        text: "Deshacer (Ctrl+Z)"
                        primaryStyle: false
                        solidShadow: false
                        enabledButton: studioBridge.canUndoViewer
                        disabledHint: "No hay acciones para deshacer"
                        onClicked: studioBridge.undoViewerAction()
                    }

                    PillButton {
                        objectName: "clearStrokesButton"
                        height: 26
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 11
                        text: "Limpiar Trazo"
                        primaryStyle: false
                        solidShadow: false
                        onClicked: {
                            viewerRoot.allStrokes = []
                            viewerRoot.currentStroke = []
                            signatureCanvas.requestPaint()
                            studioBridge.clearFreehandStrokes()
                        }
                    }

                    PillButton {
                        id: restoreViewerOriginalBtn
                        objectName: "restoreViewerOriginalBtn"
                        height: 26
                        minWidth: 0
                        horizontalPadding: 10
                        fontPixelSize: 11
                        text: "Restaurar original"
                        primaryStyle: false
                        solidShadow: false
                        enabledButton: studioBridge.hasViewerChanges
                        disabledHint: "La hoja ya está en su estado original"
                        onClicked: {
                            stampCustomTextInput.focus = false
                            viewerRoot.currentStroke = []
                            studioBridge.restoreViewerOriginal()
                        }
                    }
                }
            }
        }

        // Lienzo de inspección con zoom fluido; interactive se bloquea al dibujar o arrastrar firma/sello
        Flickable {
            id: pageFlickable
            objectName: "viewerFlickable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: Math.max(width, paperSheet.width + 32)
            contentHeight: Math.max(height, paperSheet.height + 32)
            clip: true
            interactive: !studioBridge.viewerDrawMode
                         && !signatureMouseArea.pressed
                         && !pngDragMouseArea.pressed
                         && !pngResizeMouseArea.pressed
                         && !stampDragMouseArea.pressed
                         && !stampResizeMouseArea.pressed
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
                    objectName: "viewerPdfRenderImage"
                    anchors.fill: parent
                    fillMode: Image.Stretch
                    smooth: true
                    antialiasing: true
                    mipmap: true
                    asynchronous: true
                    source: studioBridge.currentViewerPageUrl
                }

                // Sello movible y redimensionable con texto libre editable (transparente al exportar)
                Item {
                    id: stampPreviewBox
                    objectName: "stampPreviewBox"
                    z: 5
                    visible: studioBridge.signatureStamp.length > 0
                    width: parent.width * studioBridge.signatureStampRect.width
                    height: parent.height * studioBridge.signatureStampRect.height
                    x: parent.width * studioBridge.signatureStampRect.x
                    y: parent.height * studioBridge.signatureStampRect.y

                    property string lastMeasuredStampText: ""

                    TextMetrics {
                        id: stampTextMetrics
                        font.family: themePalette.serifFont
                        font.pixelSize: Math.max(10, Math.round(stampPreviewBox.height * 0.28))
                        font.bold: true
                        text: "✦ " + studioBridge.signatureStamp + " ✦"
                    }

                    function syncStampBoxWidthToText() {
                        if (!studioBridge || paperSheet.width <= 0)
                            return
                        var currentStamp = studioBridge.signatureStamp
                        if (!currentStamp || currentStamp.length === 0) {
                            lastMeasuredStampText = ""
                            return
                        }
                        if (!studioBridge.hasViewerChanges) {
                            lastMeasuredStampText = currentStamp
                            return
                        }
                        if (currentStamp === lastMeasuredStampText)
                            return
                        lastMeasuredStampText = currentStamp
                        var neededPx = stampTextMetrics.advanceWidth + 28
                        var desiredW = Math.max(0.14, Math.min(0.92, neededPx / paperSheet.width))
                        var curRect = studioBridge.signatureStampRect
                        if (Math.abs(desiredW - curRect.width) > 0.015) {
                            var cx = curRect.x + curRect.width * 0.5
                            var newX = Math.max(0.02, Math.min(0.98 - desiredW, cx - desiredW * 0.5))
                            studioBridge.setSignatureStampRect(newX, curRect.y, desiredW, curRect.height)
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: 6
                        color: stampDragMouseArea.pressed ? "#18681D3A" : "transparent"
                        border.width: 1
                        border.color: Qt.rgba(0.408, 0.114, 0.227, 0.35)
                    }

                    Text {
                        anchors.centerIn: parent
                        width: Math.max(16, parent.width - 14)
                        height: Math.max(14, parent.height - 8)
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 8
                        elide: Text.ElideRight
                        text: "✦ " + studioBridge.signatureStamp + " ✦"
                        font.family: themePalette.serifFont
                        font.pixelSize: Math.max(10, Math.round(parent.height * 0.28))
                        font.bold: true
                        color: themePalette.secondary
                    }

                    // Área para arrastrar y reposicionar el sello libremente sobre la página
                    MouseArea {
                        id: stampDragMouseArea
                        objectName: "stampDragMouseArea"
                        anchors.fill: parent
                        preventStealing: true
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.SizeAllCursor

                        property real startMouseX: 0
                        property real startMouseY: 0
                        property real startBoxX: 0
                        property real startBoxY: 0

                        onPressed: function(mouse) {
                            stampCustomTextInput.focus = false
                            studioBridge.captureViewerUndoCheckpoint()
                            var ptInSheet = stampDragMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                            startMouseX = ptInSheet.x
                            startMouseY = ptInSheet.y
                            startBoxX = stampPreviewBox.x
                            startBoxY = stampPreviewBox.y
                        }

                        onPositionChanged: function(mouse) {
                            if (!pressed || paperSheet.width <= 0 || paperSheet.height <= 0)
                                return
                            var ptInSheet = stampDragMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                            var dx = ptInSheet.x - startMouseX
                            var dy = ptInSheet.y - startMouseY
                            var newX = Math.max(0, Math.min(paperSheet.width - stampPreviewBox.width, startBoxX + dx))
                            var newY = Math.max(0, Math.min(paperSheet.height - stampPreviewBox.height, startBoxY + dy))
                            studioBridge.setSignatureStampRect(
                                newX / paperSheet.width,
                                newY / paperSheet.height,
                                stampPreviewBox.width / paperSheet.width,
                                stampPreviewBox.height / paperSheet.height
                            )
                        }

                        onReleased: studioBridge.commitViewerUndoCheckpoint("stamp_move")
                        onCanceled: studioBridge.commitViewerUndoCheckpoint("stamp_move")
                        onDoubleClicked: {
                            stampCustomTextInput.forceActiveFocus()
                            stampCustomTextInput.selectAll()
                        }
                    }

                    // Esquina inferior derecha para ajustar el tamaño del marco del sello
                    Rectangle {
                        id: stampResizeHandle
                        objectName: "stampResizeHandle"
                        z: 2
                        width: Theme.signatureHandleSize
                        height: Theme.signatureHandleSize
                        radius: Theme.signatureHandleSize / 2
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: -5
                        color: Theme.secondaryWine
                        border.width: 1
                        border.color: Theme.surfaceCard

                        MouseArea {
                            id: stampResizeMouseArea
                            objectName: "stampResizeMouseArea"
                            anchors.fill: parent
                            anchors.margins: -4
                            preventStealing: true
                            cursorShape: Qt.SizeFDiagCursor

                            property real startMouseX: 0
                            property real startMouseY: 0
                            property real startWidth: 0
                            property real startHeight: 0

                            onPressed: function(mouse) {
                                studioBridge.captureViewerUndoCheckpoint()
                                var ptInSheet = stampResizeMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                                startMouseX = ptInSheet.x
                                startMouseY = ptInSheet.y
                                startWidth = stampPreviewBox.width
                                startHeight = stampPreviewBox.height
                            }

                            onPositionChanged: function(mouse) {
                                if (!pressed || paperSheet.width <= 0 || paperSheet.height <= 0)
                                    return
                                var ptInSheet = stampResizeMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                                var dx = ptInSheet.x - startMouseX
                                var dy = ptInSheet.y - startMouseY
                                var minW = Math.max(48, paperSheet.width * 0.12)
                                var maxW = Math.max(minW, paperSheet.width - stampPreviewBox.x)
                                var minH = Math.max(24, paperSheet.height * 0.05)
                                var maxH = Math.max(minH, paperSheet.height - stampPreviewBox.y)
                                var newW = Math.max(minW, Math.min(maxW, startWidth + dx))
                                var newH = Math.max(minH, Math.min(maxH, startHeight + dy))
                                studioBridge.setSignatureStampRect(
                                    stampPreviewBox.x / paperSheet.width,
                                    stampPreviewBox.y / paperSheet.height,
                                    newW / paperSheet.width,
                                    newH / paperSheet.height
                                )
                            }

                            onReleased: studioBridge.commitViewerUndoCheckpoint("stamp_resize")
                            onCanceled: studioBridge.commitViewerUndoCheckpoint("stamp_resize")
                        }
                    }

                    // Botón directo para quitar el sello desde la vista previa
                    Rectangle {
                        objectName: "clearStampPreviewBtn"
                        z: 2
                        width: Theme.signatureDeleteBtnSize
                        height: Theme.signatureDeleteBtnSize
                        radius: Theme.signatureDeleteBtnSize / 2
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: -6
                        color: themePalette.secondary
                        border.width: 1
                        border.color: Theme.surfaceCard

                        Text {
                            anchors.centerIn: parent
                            text: "✕"
                            font.pixelSize: 9
                            font.bold: true
                            color: themePalette.surfaceLight
                        }

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -3
                            preventStealing: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: studioBridge.clearSignatureStamp()
                        }
                    }
                }

                // Capa Canvas interactiva para firma manuscrita a mano alzada con curvas Bézier suaves
                Canvas {
                    id: signatureCanvas
                    objectName: "signatureCanvas"
                    z: 2
                    anchors.fill: parent
                    antialiasing: true
                    smooth: true

                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()

                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.strokeStyle = viewerRoot.strokeHexColor

                        var strokes = viewerRoot.allStrokes || []
                        for (var s = 0; s < strokes.length; s++) {
                            var item = strokes[s]
                            var pts = item && item.points ? item.points : item
                            var wPt = item && item.widthPt ? item.widthPt : studioBridge.signatureStrokeWidthPt
                            viewerRoot.drawSmoothStroke(ctx, pts, wPt)
                        }

                        if (viewerRoot.currentStroke && viewerRoot.currentStroke.length >= 2) {
                            viewerRoot.drawSmoothStroke(
                                ctx,
                                viewerRoot.currentStroke,
                                studioBridge.signatureStrokeWidthPt
                            )
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
                                x: Math.max(0, Math.min(1, mouse.x / Math.max(1, width))),
                                y: Math.max(0, Math.min(1, mouse.y / Math.max(1, height)))
                            }]
                        }
                        onPositionChanged: function(mouse) {
                            if (!pressed) {
                                return
                            }
                            var pts = viewerRoot.currentStroke
                            if (pts.length > 0) {
                                var lastPt = pts[pts.length - 1]
                                var dx = mouse.x - (lastPt.x * width)
                                var dy = mouse.y - (lastPt.y * height)
                                if (Math.sqrt(dx * dx + dy * dy) < Theme.strokeMinPointDistPx) {
                                    return
                                }
                            }
                            pts.push({
                                x: Math.max(0, Math.min(1, mouse.x / Math.max(1, width))),
                                y: Math.max(0, Math.min(1, mouse.y / Math.max(1, height)))
                            })
                            viewerRoot.currentStroke = pts
                            signatureCanvas.requestPaint()
                        }
                        onReleased: function(mouse) {
                            var pts = viewerRoot.currentStroke
                            if (pts.length === 1) {
                                var p0 = pts[0]
                                var dx = mouse.x - (p0.x * width)
                                var dy = mouse.y - (p0.y * height)
                                if (Math.sqrt(dx * dx + dy * dy) >= 0.5) {
                                    pts.push({
                                        x: Math.max(0, Math.min(1, mouse.x / Math.max(1, width))),
                                        y: Math.max(0, Math.min(1, mouse.y / Math.max(1, height)))
                                    })
                                }
                            }
                            if (pts.length >= 2) {
                                studioBridge.addFreehandStroke(pts)
                            }
                            viewerRoot.currentStroke = []
                            signatureCanvas.requestPaint()
                        }
                    }
                }

                // Caja interactiva para Firma PNG transparente (arrastrable, redimensionable en proporción y eliminable)
                Item {
                    id: pngSignatureBox
                    objectName: "pngSignatureBox"
                    z: 6
                    visible: studioBridge.signatureImagePath.length > 0
                    x: parent.width * studioBridge.signatureImageRect.x
                    y: parent.height * studioBridge.signatureImageRect.y
                    width: parent.width * studioBridge.signatureImageRect.width
                    height: parent.height * studioBridge.signatureImageRect.height

                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        radius: 4
                        border.width: Theme.borderSubtleWidth
                        border.color: Theme.borderSubtleColor
                    }

                    Image {
                        id: pngSignatureImage
                        objectName: "pngSignatureImage"
                        anchors.fill: parent
                        anchors.margins: 2
                        source: studioBridge.signatureImageUrl
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        antialiasing: true
                        mipmap: true
                        asynchronous: false
                    }

                    // Área para arrastrar la firma PNG dentro de la página
                    MouseArea {
                        id: pngDragMouseArea
                        objectName: "pngDragMouseArea"
                        anchors.fill: parent
                        preventStealing: true
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.SizeAllCursor

                        property real startMouseX: 0
                        property real startMouseY: 0
                        property real startBoxX: 0
                        property real startBoxY: 0

                        onPressed: function(mouse) {
                            studioBridge.captureViewerUndoCheckpoint()
                            var ptInSheet = pngDragMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                            startMouseX = ptInSheet.x
                            startMouseY = ptInSheet.y
                            startBoxX = pngSignatureBox.x
                            startBoxY = pngSignatureBox.y
                        }

                        onPositionChanged: function(mouse) {
                            if (!pressed || paperSheet.width <= 0 || paperSheet.height <= 0) {
                                return
                            }
                            var ptInSheet = pngDragMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                            var dx = ptInSheet.x - startMouseX
                            var dy = ptInSheet.y - startMouseY
                            var newX = Math.max(0, Math.min(paperSheet.width - pngSignatureBox.width, startBoxX + dx))
                            var newY = Math.max(0, Math.min(paperSheet.height - pngSignatureBox.height, startBoxY + dy))
                            studioBridge.setSignatureImageRect(
                                newX / paperSheet.width,
                                newY / paperSheet.height,
                                pngSignatureBox.width / paperSheet.width,
                                pngSignatureBox.height / paperSheet.height
                            )
                        }

                        onReleased: studioBridge.commitViewerUndoCheckpoint("image_move")
                        onCanceled: studioBridge.commitViewerUndoCheckpoint("image_move")
                    }

                    // Esquina inferior derecha para cambiar tamaño manteniendo la proporción
                    Rectangle {
                        id: pngResizeHandle
                        objectName: "pngResizeHandle"
                        z: 2
                        width: Theme.signatureHandleSize
                        height: Theme.signatureHandleSize
                        radius: Theme.signatureHandleSize / 2
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: -5
                        color: Theme.secondaryWine
                        border.width: 1
                        border.color: Theme.surfaceCard

                        MouseArea {
                            id: pngResizeMouseArea
                            objectName: "pngResizeMouseArea"
                            anchors.fill: parent
                            anchors.margins: -4
                            preventStealing: true
                            cursorShape: Qt.SizeFDiagCursor

                            property real startMouseX: 0
                            property real startWidth: 0

                            onPressed: function(mouse) {
                                studioBridge.captureViewerUndoCheckpoint()
                                var ptInSheet = pngResizeMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                                startMouseX = ptInSheet.x
                                startWidth = pngSignatureBox.width
                            }

                            onPositionChanged: function(mouse) {
                                if (!pressed || paperSheet.width <= 0 || paperSheet.height <= 0) {
                                    return
                                }
                                var ptInSheet = pngResizeMouseArea.mapToItem(paperSheet, mouse.x, mouse.y)
                                var dx = ptInSheet.x - startMouseX
                                var minW = Math.max(32, paperSheet.width * 0.08)
                                var maxW = Math.max(minW, paperSheet.width - pngSignatureBox.x)
                                var newW = Math.max(minW, Math.min(maxW, startWidth + dx))
                                var imgAspect = Math.max(0.1, studioBridge.signatureImageRect.aspect || 2.0)
                                var newH = newW / imgAspect
                                if (pngSignatureBox.y + newH > paperSheet.height) {
                                    newH = Math.max(20, paperSheet.height - pngSignatureBox.y)
                                    newW = newH * imgAspect
                                }
                                studioBridge.setSignatureImageRect(
                                    pngSignatureBox.x / paperSheet.width,
                                    pngSignatureBox.y / paperSheet.height,
                                    newW / paperSheet.width,
                                    newH / paperSheet.height
                                )
                            }

                            onReleased: studioBridge.commitViewerUndoCheckpoint("image_resize")
                            onCanceled: studioBridge.commitViewerUndoCheckpoint("image_resize")
                        }
                    }

                    // Botón ✕ para quitar la firma PNG de la página actual
                    Rectangle {
                        id: clearPngSignatureBtn
                        objectName: "clearPngSignatureBtn"
                        z: 2
                        width: Theme.signatureDeleteBtnSize
                        height: Theme.signatureDeleteBtnSize
                        radius: Theme.signatureDeleteBtnSize / 2
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: -6
                        color: Theme.secondaryWine
                        border.width: 1
                        border.color: Theme.surfaceCard

                        Text {
                            anchors.centerIn: parent
                            text: "✕"
                            font.pixelSize: 10
                            font.bold: true
                            color: Theme.surfaceLight
                        }

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -3
                            preventStealing: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: studioBridge.clearSignatureImage()
                        }
                    }
                }
            }
        }
    }
}
