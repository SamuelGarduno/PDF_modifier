import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Layouts
import "."

Item {
    id: dropzoneRoot
    objectName: "dropzoneView"

    property int draggedFileIndex: -1
    property int dropTargetIndex: -1

    FileDialog {
        id: filePickerDialog
        title: "Seleccionar documentos PDF o imágenes"
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            "Documentos y Láminas (*.pdf *.png *.jpg *.jpeg *.webp)",
            "Archivos PDF (*.pdf)",
            "Imágenes (*.png *.jpg *.jpeg *.webp)"
        ]
        onAccepted: {
            studioBridge.addFileUrls(filePickerDialog.selectedFiles)
        }
    }

    DropArea {
        id: dropArea
        objectName: "workbenchDropArea"
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) {
                studioBridge.addFileUrls(drop.urls)
            }
        }
    }

    // =========================================================================
    // DECORACIÓN DEL ESTADO VACÍO (borde punteado y washi tapes SOLO sin archivos)
    // =========================================================================
    Canvas {
        id: dashedFrameCanvas
        objectName: "emptyDashedFrameCanvas"
        visible: studioBridge.fileCount === 0
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            var rx = 8
            var ry = 10
            var rw = width - 16
            var rh = height - 18
            var rad = 12

            ctx.strokeStyle = "#8C465A"
            ctx.lineWidth = 1.25
            ctx.setLineDash([5, 4])
            ctx.beginPath()
            ctx.moveTo(rx + rad, ry)
            ctx.lineTo(rx + rw - rad, ry)
            ctx.quadraticCurveTo(rx + rw, ry, rx + rw, ry + rad)
            ctx.lineTo(rx + rw, ry + rh - rad)
            ctx.quadraticCurveTo(rx + rw, ry + rh, rx + rw - rad, ry + rh)
            ctx.lineTo(rx + rad, ry + rh)
            ctx.quadraticCurveTo(rx, ry + rh, rx, ry + rh - rad)
            ctx.lineTo(rx, ry + rad)
            ctx.quadraticCurveTo(rx, ry, rx + rad, ry)
            ctx.closePath()
            ctx.stroke()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Repeater {
        model: [
            { name: "leftWashiTape",  xRatio: 0.23, angle: -2.2 },
            { name: "rightWashiTape", xRatio: 0.77, angle: 2.2 }
        ]
        delegate: Item {
            objectName: modelData.name
            visible: studioBridge.fileCount === 0
            width: 96
            height: 25
            x: dropzoneRoot.width * modelData.xRatio - width / 2
            y: 1
            rotation: modelData.angle

            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 2
                anchors.leftMargin: 2
                radius: 2
                color: Theme.wineDeep
                opacity: 0.10
            }

            Image {
                anchors.fill: parent
                source: "../../assets/icons/washi_tape.svg"
                sourceSize.width: parent.width * 2
                sourceSize.height: parent.height * 2
                fillMode: Image.Stretch
                smooth: true
                opacity: 0.72
            }
        }
    }

    // =========================================================================
    // OVERLAY "SUELTA AQUÍ" (visible al arrastrar archivos encima de la ventana)
    // =========================================================================
    Rectangle {
        id: dragHoverOverlay
        objectName: "dragHoverOverlay"
        visible: dropArea.containsDrag
        z: 50
        anchors.fill: parent
        anchors.margins: 6
        radius: 16
        color: "#ECFAF0EE"

        Canvas {
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = "#681D3A"
                ctx.lineWidth = 1.5
                ctx.setLineDash([6, 4])
                ctx.strokeRect(4, 4, width - 8, height - 8)
            }
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
        }

        Column {
            anchors.centerIn: parent
            spacing: 10

            Rectangle {
                width: 56
                height: 56
                radius: 28
                anchors.horizontalCenter: parent.horizontalCenter
                color: Theme.secondaryWine

                Text {
                    anchors.centerIn: parent
                    text: "+"
                    font.family: Theme.serifFont
                    font.pixelSize: 28
                    font.bold: true
                    color: Theme.surfaceCard
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Suelta aquí tus pliegos o postales"
                font.family: Theme.serifFont
                font.pixelSize: 20
                font.bold: true
                color: Theme.textPrimary
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Se añadirán a tu mesa de trabajo sin modificar los originales"
                font.family: Theme.scriptFont
                font.italic: true
                font.pixelSize: 13
                color: Theme.textSecondary
            }
        }
    }

    // =========================================================================
    // ESTADO 1: MESA VACÍA (studioBridge.fileCount === 0)
    // =========================================================================
    Item {
        id: emptyStateContainer
        objectName: "emptyStateContainer"
        visible: studioBridge.fileCount === 0
        anchors.fill: parent
        anchors.margins: Theme.outerMargin

        Behavior on opacity {
            NumberAnimation { duration: Theme.animNormal }
        }

        Column {
            anchors.centerIn: parent
            spacing: 12

            Item {
                width: 78
                height: 78
                anchors.horizontalCenter: parent.horizontalCenter

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        var cx = width / 2
                        var cy = height / 2

                        ctx.strokeStyle = "#8C465A"
                        ctx.lineWidth = 1.2
                        ctx.beginPath()
                        ctx.arc(cx, cy, 36, 0, Math.PI * 2)
                        ctx.stroke()

                        ctx.fillStyle = "#DA7B88"
                        ctx.strokeStyle = "#521928"
                        ctx.lineWidth = 1.5
                        ctx.beginPath()
                        ctx.arc(cx, cy, 28, 0, Math.PI * 2)
                        ctx.fill()
                        ctx.stroke()

                        ctx.fillStyle = "#FFFDFB"
                        ctx.strokeStyle = "#521928"
                        ctx.lineWidth = 1.1
                        var petalDist = 9.5
                        var petalRadius = 6.2
                        for (var i = 0; i < 5; i++) {
                            var angle = (i * 2 * Math.PI / 5) - Math.PI / 2
                            var px = cx + Math.cos(angle) * petalDist
                            var py = cy + Math.sin(angle) * petalDist
                            ctx.beginPath()
                            ctx.arc(px, py, petalRadius, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.stroke()
                        }

                        ctx.fillStyle = "#521928"
                        ctx.beginPath()
                        ctx.arc(cx, cy, 4.2, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }
            }

            Text {
                objectName: "emptyStateTitleText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Arrastra y suelta tus pliegos PDF o postales aquí"
                font.family: Theme.serifFont
                font.pixelSize: 19
                font.bold: true
                color: Theme.textPrimary
            }

            Text {
                objectName: "emptyStateSubtitleText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Suelta primero tus archivos (PDF, PNG, JPG, WEBP) y elige después qué hacer"
                font.family: Theme.scriptFont
                font.italic: true
                font.pixelSize: 13
                color: Theme.textPrimary
                opacity: Theme.metaOpacity
            }

            Item { width: 1; height: 4 }

            PillButton {
                id: selectFilesEmptyButton
                objectName: "selectFilesEmptyButton"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Seleccionar archivos..."
                primaryStyle: false
                solidShadow: false
                horizontalPadding: 24
                onClicked: filePickerDialog.open()
            }
        }
    }

    // =========================================================================
    // ESTADO 2: MESA CON ARCHIVOS (Zona 1: Tus pliegos + Zona 2: ¿Qué hacemos?)
    // =========================================================================
    ColumnLayout {
        id: queuedStateContainer
        objectName: "queuedStateContainer"
        visible: studioBridge.fileCount > 0
        anchors.fill: parent
        anchors.leftMargin: Theme.outerMargin
        anchors.rightMargin: Theme.outerMargin
        anchors.topMargin: 16
        anchors.bottomMargin: 12
        spacing: 14

        // ---------------------------------------------------------------------
        // ZONA 1 - TUS PLIEGOS (Cabecera + Lista Virtualizada + "+ Añadir más")
        // ---------------------------------------------------------------------
        RowLayout {
            id: zone1HeaderRow
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            spacing: 10

            Text {
                objectName: "zone1HeaderTitle"
                text: "Tus pliegos"
                font.family: Theme.sansFont
                font.pixelSize: Theme.fontBodySize
                font.bold: true
                color: Theme.textPrimary
            }

            // Botones rápidos de filtrado cuando hay mezcla de PDFs e imágenes
            Row {
                objectName: "mixedFilesFilterBar"
                visible: studioBridge.inputContextState === "mixed"
                spacing: 8

                PillButton {
                    objectName: "keepOnlyPdfsButton"
                    height: 28
                    horizontalPadding: 12
                    text: "Solo PDFs (" + studioBridge.pdfCount + ")"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.keepOnlyPdfs()
                }

                PillButton {
                    objectName: "keepOnlyImagesButton"
                    height: 28
                    horizontalPadding: 12
                    text: "Solo imágenes (" + studioBridge.imageCount + ")"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.keepOnlyImages()
                }
            }

            Item { Layout.fillWidth: true }

            Text {
                id: queueHeaderCountText
                objectName: "queueHeaderCountText"
                text: studioBridge.queueSummaryRightText
                font.family: Theme.scriptFont
                font.italic: true
                font.pixelSize: Theme.fontMetaSize
                color: Theme.textPrimary
                opacity: Theme.metaOpacity
            }

            Text {
                text: "·"
                font.family: Theme.sansFont
                font.pixelSize: Theme.fontMetaSize
                color: Theme.textMuted
            }

            FocusScope {
                id: clearQueueLink
                objectName: "clearQueueLink"
                implicitWidth: clearLinkLabel.implicitWidth + 12
                implicitHeight: 28
                activeFocusOnTab: true

                Keys.onReturnPressed: studioBridge.clearFiles()
                Keys.onEnterPressed: studioBridge.clearFiles()
                Keys.onSpacePressed: studioBridge.clearFiles()

                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: clearHover.hovered ? "#F5E3E1" : "transparent"
                    border.width: clearQueueLink.activeFocus ? 1.5 : 0
                    border.color: Theme.focusRingColor
                }

                Text {
                    id: clearLinkLabel
                    anchors.centerIn: parent
                    text: "Vaciar cola"
                    font.family: Theme.sansFont
                    font.pixelSize: 13
                    font.underline: clearHover.hovered
                    color: clearHover.hovered ? Theme.textPrimary : Theme.secondaryWine
                }

                HoverHandler {
                    id: clearHover
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler {
                    onTapped: studioBridge.clearFiles()
                }
            }
        }

        // Lista virtualizada de tarjetas de la cola (se ajusta al contenido sin crear hueco vacío)
        ListView {
            id: queueListView
            objectName: "queueListView"
            readonly property int maxAvailableListHeight: Math.max(
                92,
                queuedStateContainer.height
                - zone1HeaderRow.height
                - addMoreFilesButton.height
                - (contextualToolsPanel.visible ? contextualToolsPanel.height : 0)
                - 52
            )
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(Math.max(88, contentHeight), maxAvailableListHeight)
            Layout.maximumHeight: maxAvailableListHeight
            clip: true
            spacing: Theme.cardSpacing
            cacheBuffer: 420
            boundsBehavior: Flickable.StopAtBounds
            model: studioBridge.queuedFiles

            displaced: Transition {
                NumberAnimation { properties: "x,y"; duration: Theme.animNormal; easing.type: Easing.OutQuad }
            }

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 6
            }

            delegate: FocusScope {
                id: fileCardFocusScope
                objectName: "queuedFileCard_" + modelData.index
                width: queueListView.width
                height: 88
                activeFocusOnTab: true

                Keys.onDeletePressed: studioBridge.removeFileAt(modelData.index)
                Keys.onPressed: function(event) {
                    if ((event.modifiers & Qt.AltModifier) && event.key === Qt.Key_Up) {
                        studioBridge.moveFileUp(modelData.index)
                        event.accepted = true
                    } else if ((event.modifiers & Qt.AltModifier) && event.key === Qt.Key_Down) {
                        studioBridge.moveFileDown(modelData.index)
                        event.accepted = true
                    }
                }

                // Indicador visual de destino al arrastrar para reordenar
                Rectangle {
                    objectName: "dropTargetIndicator_" + modelData.index
                    visible: dropzoneRoot.draggedFileIndex >= 0
                             && dropzoneRoot.dropTargetIndex === modelData.index
                             && dropzoneRoot.draggedFileIndex !== modelData.index
                    anchors.top: parent.top
                    anchors.topMargin: -6
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 3
                    radius: 1.5
                    color: Theme.secondaryWine
                    z: 10
                }

                Rectangle {
                    id: fileCardBg
                    anchors.fill: parent
                    radius: Theme.queueCardRadius
                    color: modelData.isCorrupted
                           ? Theme.errorBg
                           : (dropzoneRoot.draggedFileIndex === modelData.index
                              ? "#FAF0EE"
                              : (cardSurfaceHover.hovered ? "#FFF9F8" : Theme.surfaceCard))
                    border.width: fileCardFocusScope.activeFocus
                                  ? 2.0
                                  : Theme.borderSubtleWidth
                    border.color: fileCardFocusScope.activeFocus
                                  ? Theme.focusRingColor
                                  : (modelData.isCorrupted
                                     ? Theme.errorBorder
                                     : (modelData.isLocked ? Theme.toolProtectAccent : Theme.borderSubtleColor))

                    Behavior on color {
                        ColorAnimation { duration: Theme.animFast }
                    }

                    HoverHandler {
                        id: cardSurfaceHover
                    }

                    TapHandler {
                        onTapped: fileCardFocusScope.forceActiveFocus()
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 12

                        // 1. Asa de arrastre (6 puntos ⋮⋮)
                        Item {
                            id: dragHandleItem
                            Layout.preferredWidth: 20
                            Layout.preferredHeight: 36

                            Canvas {
                                anchors.fill: parent
                                onPaint: {
                                    var ctx = getContext("2d")
                                    ctx.reset()
                                    ctx.fillStyle = "#A67684"
                                    var cols = [6, 13]
                                    var rows = [10, 18, 26]
                                    for (var r = 0; r < rows.length; r++) {
                                        for (var c = 0; c < cols.length; c++) {
                                            ctx.beginPath()
                                            ctx.arc(cols[c], rows[r], 1.7, 0, Math.PI * 2)
                                            ctx.fill()
                                        }
                                    }
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                anchors.margins: -6
                                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                onPressed: {
                                    fileCardFocusScope.forceActiveFocus()
                                    dropzoneRoot.draggedFileIndex = modelData.index
                                    dropzoneRoot.dropTargetIndex = modelData.index
                                }
                                onPositionChanged: function(mouse) {
                                    if (!pressed || dropzoneRoot.draggedFileIndex < 0)
                                        return
                                    var listPos = mapToItem(queueListView.contentItem, mouse.x, mouse.y)
                                    var targetIdx = queueListView.indexAt(queueListView.width / 2, listPos.y)
                                    if (targetIdx >= 0) {
                                        dropzoneRoot.dropTargetIndex = targetIdx
                                        if (targetIdx !== dropzoneRoot.draggedFileIndex) {
                                            var fromIdx = dropzoneRoot.draggedFileIndex
                                            dropzoneRoot.draggedFileIndex = targetIdx
                                            studioBridge.moveFile(fromIdx, targetIdx)
                                        }
                                    }
                                }
                                onReleased: {
                                    dropzoneRoot.draggedFileIndex = -1
                                    dropzoneRoot.dropTargetIndex = -1
                                }
                                onCanceled: {
                                    dropzoneRoot.draggedFileIndex = -1
                                    dropzoneRoot.dropTargetIndex = -1
                                }
                            }
                        }

                        // 2. Número en círculo (SOLO si hay 2 o más archivos en la cola)
                        Rectangle {
                            id: orderNumberBadge
                            objectName: "orderNumberBadge_" + modelData.index
                            visible: studioBridge.fileCount >= 2
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                            radius: 13
                            color: modelData.isCorrupted ? Theme.errorBorder : Theme.wineDeep

                            Text {
                                anchors.centerIn: parent
                                text: (modelData.index + 1).toString()
                                font.family: Theme.sansFont
                                font.pixelSize: 12
                                font.bold: true
                                color: Theme.surfaceCard
                            }
                        }

                        // 3. Miniatura de la primera página (56x72 px, asíncrona con placeholder)
                        Rectangle {
                            id: thumbnailContainer
                            objectName: "thumbnailContainer_" + modelData.index
                            Layout.preferredWidth: Theme.thumbnailWidth
                            Layout.preferredHeight: Theme.thumbnailHeight
                            radius: 6
                            color: modelData.isCorrupted ? "#F6D9D5" : "#F6ECEB"
                            border.width: 1
                            border.color: modelData.isCorrupted ? Theme.errorBorder : Theme.borderSubtleColor
                            clip: true

                            // Placeholder mientras carga o si está dañado
                            Column {
                                visible: thumbImage.status !== Image.Ready || modelData.isCorrupted
                                anchors.centerIn: parent
                                spacing: 3

                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.isCorrupted ? "!" : "···"
                                    font.family: Theme.serifFont
                                    font.pixelSize: modelData.isCorrupted ? 18 : 14
                                    font.bold: true
                                    color: modelData.isCorrupted ? Theme.errorText : Theme.textSecondary
                                }
                            }

                            Image {
                                id: thumbImage
                                objectName: "fileThumbImage_" + modelData.index
                                visible: !modelData.isCorrupted && modelData.thumbnailUrl.length > 0
                                anchors.fill: parent
                                anchors.margins: 2
                                source: modelData.thumbnailUrl
                                sourceSize.width: Theme.thumbnailWidth * 2
                                sourceSize.height: Theme.thumbnailHeight * 2
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                cache: true
                                smooth: true
                            }
                        }

                        // 4. Nombre del archivo (elipsis en el medio + tooltip) y metadatos debajo
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 4

                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 20

                                Text {
                                    id: fileNameLabel
                                    objectName: "queuedFileName_" + modelData.index
                                    anchors.fill: parent
                                    verticalAlignment: Text.AlignVCenter
                                    text: modelData.name
                                    font.family: Theme.sansFont
                                    font.pixelSize: Theme.fontBodySize
                                    font.bold: true
                                    elide: Text.ElideMiddle
                                    color: modelData.isCorrupted ? Theme.errorText : Theme.textPrimary
                                }

                                HoverHandler {
                                    id: fileNameHover
                                }

                                ToolTip.visible: fileNameHover.hovered
                                ToolTip.delay: 200
                                ToolTip.text: modelData.name
                            }

                            RowLayout {
                                spacing: 8

                                Text {
                                    objectName: "queuedFileMeta_" + modelData.index
                                    text: modelData.isCorrupted
                                          ? "No se pudo leer · Se excluirá del proceso"
                                          : (modelData.isLocked
                                             ? ("Protegido con clave · " + modelData.sizeFormatted)
                                             : ((modelData.isImage
                                                 ? "1 postal"
                                                 : (modelData.pageCount + (modelData.pageCount === 1 ? " página" : " páginas")))
                                                + " · " + modelData.sizeFormatted))
                                    font.family: Theme.scriptFont
                                    font.italic: true
                                    font.pixelSize: Theme.fontMetaSize
                                    color: modelData.isCorrupted
                                           ? Theme.errorText
                                           : (modelData.isLocked ? "#43345E" : Theme.textPrimary)
                                    opacity: (modelData.isCorrupted || modelData.isLocked) ? 1.0 : Theme.metaOpacity
                                }

                                PillButton {
                                    objectName: "unlockInlineBtn_" + modelData.index
                                    visible: modelData.isLocked
                                    height: 26
                                    horizontalPadding: 12
                                    text: "Abrir sello"
                                    primaryStyle: false
                                    solidShadow: false
                                    onClicked: studioBridge.requestUnlockAt(modelData.index)
                                }
                            }
                        }

                        // 5. Botones de acción a la derecha (↑, ↓, ✕ con área de toque de 32x32 px)
                        Row {
                            spacing: 6
                            Layout.alignment: Qt.AlignVCenter

                            // Botón Subir (↑)
                            Rectangle {
                                id: moveUpBtn
                                objectName: "moveUpBtn_" + modelData.index
                                property bool canMoveUp: modelData.index > 0
                                width: 32
                                height: 32
                                radius: 16
                                color: !canMoveUp
                                       ? "#F4ECEB"
                                       : (upTap.pressed ? "#EED3D0" : (upHover.hovered ? "#F5E2DF" : "#FAF3F2"))
                                border.width: Theme.borderSubtleWidth
                                border.color: !canMoveUp ? "#DFCFD3" : Theme.borderSubtleColor
                                opacity: canMoveUp ? 1.0 : 0.42

                                Text {
                                    anchors.centerIn: parent
                                    text: "↑"
                                    font.family: Theme.sansFont
                                    font.pixelSize: 14
                                    font.bold: true
                                    color: Theme.textPrimary
                                }

                                HoverHandler {
                                    id: upHover
                                    cursorShape: moveUpBtn.canMoveUp ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                                }
                                TapHandler {
                                    id: upTap
                                    enabled: moveUpBtn.canMoveUp
                                    onTapped: studioBridge.moveFileUp(modelData.index)
                                }
                                ToolTip.visible: upHover.hovered && moveUpBtn.canMoveUp
                                ToolTip.delay: 300
                                ToolTip.text: "Subir pliego (Alt+↑)"
                            }

                            // Botón Bajar (↓)
                            Rectangle {
                                id: moveDownBtn
                                objectName: "moveDownBtn_" + modelData.index
                                property bool canMoveDown: modelData.index < (studioBridge.fileCount - 1)
                                width: 32
                                height: 32
                                radius: 16
                                color: !canMoveDown
                                       ? "#F4ECEB"
                                       : (downTap.pressed ? "#EED3D0" : (downHover.hovered ? "#F5E2DF" : "#FAF3F2"))
                                border.width: Theme.borderSubtleWidth
                                border.color: !canMoveDown ? "#DFCFD3" : Theme.borderSubtleColor
                                opacity: canMoveDown ? 1.0 : 0.42

                                Text {
                                    anchors.centerIn: parent
                                    text: "↓"
                                    font.family: Theme.sansFont
                                    font.pixelSize: 14
                                    font.bold: true
                                    color: Theme.textPrimary
                                }

                                HoverHandler {
                                    id: downHover
                                    cursorShape: moveDownBtn.canMoveDown ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                                }
                                TapHandler {
                                    id: downTap
                                    enabled: moveDownBtn.canMoveDown
                                    onTapped: studioBridge.moveFileDown(modelData.index)
                                }
                                ToolTip.visible: downHover.hovered && moveDownBtn.canMoveDown
                                ToolTip.delay: 300
                                ToolTip.text: "Bajar pliego (Alt+↓)"
                            }

                            // Botón Eliminar (✕)
                            Rectangle {
                                id: deleteFileBtn
                                objectName: "deleteFileBtn_" + modelData.index
                                width: 32
                                height: 32
                                radius: 16
                                color: delTap.pressed
                                       ? Theme.secondaryWine
                                       : (delHover.hovered ? Theme.primaryRose : "#FAF3F2")
                                border.width: Theme.borderSubtleWidth
                                border.color: Theme.borderSubtleColor

                                Text {
                                    anchors.centerIn: parent
                                    text: "✕"
                                    font.family: Theme.sansFont
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: (delHover.hovered || delTap.pressed) ? Theme.surfaceCard : Theme.textPrimary
                                }

                                HoverHandler {
                                    id: delHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    id: delTap
                                    onTapped: studioBridge.removeFileAt(modelData.index)
                                }
                                ToolTip.visible: delHover.hovered
                                ToolTip.delay: 300
                                ToolTip.text: "Quitar de la mesa (Supr)"
                            }
                        }
                    }
                }
            }
        }

        // Fila discreta "+ Añadir más pliegos" (estilo fantasma, sin borde punteado grande)
        FocusScope {
            id: addMoreFilesButton
            objectName: "addMoreFilesButton"
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            activeFocusOnTab: true

            Keys.onReturnPressed: filePickerDialog.open()
            Keys.onEnterPressed: filePickerDialog.open()
            Keys.onSpacePressed: filePickerDialog.open()

            Rectangle {
                anchors.fill: parent
                radius: 10
                color: addMoreTap.pressed
                       ? "#EED3D0"
                       : (addMoreHover.hovered ? "#F5E4E2" : "transparent")
                border.width: addMoreFilesButton.activeFocus
                              ? 1.5
                              : (addMoreHover.hovered ? Theme.borderSubtleWidth : 0)
                border.color: addMoreFilesButton.activeFocus ? Theme.focusRingColor : Theme.borderSubtleColor

                Text {
                    anchors.centerIn: parent
                    text: "+ Añadir más pliegos"
                    font.family: Theme.sansFont
                    font.pixelSize: 13
                    color: Theme.secondaryWine
                }
            }

            HoverHandler {
                id: addMoreHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                id: addMoreTap
                onTapped: filePickerDialog.open()
            }
        }

        // ---------------------------------------------------------------------
        // ZONA 2 - ¿QUÉ HACEMOS? (Tarjeta destacada vino + "También puedes:" chips)
        // ---------------------------------------------------------------------
        ColumnLayout {
            id: contextualToolsPanel
            objectName: "contextualToolsPanel"
            visible: !studioBridge.isToolSelected && studioBridge.fileCount > 0
            Layout.fillWidth: true
            spacing: 8

            readonly property bool isNarrowLayout: dropzoneRoot.width < 720 || studioBridge.secondarySuggestedTools.length === 0
            readonly property string currentPrimaryId: studioBridge.hasLockedFiles
                                                       ? "unlock"
                                                       : (studioBridge.primarySuggestedTool.id || "organize")

            Text {
                objectName: "zone2HeaderTitle"
                text: "¿Qué hacemos?"
                font.family: Theme.sansFont
                font.pixelSize: Theme.fontBodySize
                font.bold: true
                color: Theme.textPrimary
            }

            GridLayout {
                id: zone2Layout
                Layout.fillWidth: true
                columns: contextualToolsPanel.isNarrowLayout ? 1 : 2
                columnSpacing: 18
                rowSpacing: 12

                // IZQUIERDA (~58%): Tarjeta grande con la acción sugerida
                FocusScope {
                    id: primarySuggestedCard
                    objectName: "suggestedToolCard_" + (studioBridge.primarySuggestedTool.id || "organize")
                    property string toolId: studioBridge.primarySuggestedTool.id || "organize"
                    property bool isPrimary: true
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: contextualToolsPanel.isNarrowLayout
                                           ? zone2Layout.width
                                           : Math.floor((zone2Layout.width - 18) * 0.56)
                    Layout.preferredHeight: 96
                    activeFocusOnTab: true

                    Keys.onReturnPressed: studioBridge.triggerPrimaryAction()
                    Keys.onEnterPressed: studioBridge.triggerPrimaryAction()
                    Keys.onSpacePressed: studioBridge.triggerPrimaryAction()

                    Rectangle {
                        id: primaryCardBg
                        objectName: "primarySuggestedCardBg"
                        anchors.fill: parent
                        radius: Theme.primaryCardRadius
                        color: primaryTap.pressed
                               ? "#160A10"
                               : (primaryHover.hovered ? "#2B121C" : Theme.wineDarkCard)
                        border.width: Theme.borderStrongWidth
                        border.color: primarySuggestedCard.activeFocus ? Theme.accentPeach : Theme.secondaryWine

                        Behavior on color {
                            ColorAnimation { duration: Theme.animFast }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 20
                            anchors.rightMargin: 20
                            spacing: 16

                            // Círculo de 48 px con fondo suave por familia y SVG botánico entintado
                            Rectangle {
                                id: primaryIconCircle
                                objectName: "primaryIconCircle"
                                Layout.preferredWidth: 48
                                Layout.preferredHeight: 48
                                radius: 24
                                color: Theme.toolSoftBgColor(contextualToolsPanel.currentPrimaryId)
                                border.width: 1
                                border.color: Theme.toolAccentColor(contextualToolsPanel.currentPrimaryId)

                                Image {
                                    id: primaryToolSvg
                                    anchors.centerIn: parent
                                    width: 28
                                    height: 28
                                    source: Theme.toolIconSource(contextualToolsPanel.currentPrimaryId)
                                    sourceSize.width: 56
                                    sourceSize.height: 56
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    visible: false
                                }

                                MultiEffect {
                                    anchors.fill: primaryToolSvg
                                    source: primaryToolSvg
                                    colorization: 1.0
                                    colorizationColor: Theme.toolIconDarkColor(contextualToolsPanel.currentPrimaryId)
                                }
                            }

                            // Título serif ~20 px en crema + 1 línea de descripción
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 4

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    Text {
                                        id: primarySuggestedTitle
                                        objectName: "primarySuggestedTitle"
                                        text: studioBridge.hasLockedFiles
                                              ? "Abrir sello del pliego"
                                              : (studioBridge.primarySuggestedTool.title || "")
                                        font.family: Theme.serifFont
                                        font.pixelSize: Theme.fontCardTitleSize
                                        font.bold: true
                                        color: Theme.textCream
                                        elide: Text.ElideRight
                                    }

                                    Rectangle {
                                        height: 20
                                        width: recBadgeText.implicitWidth + 14
                                        radius: 10
                                        color: Theme.toolSoftBgColor(contextualToolsPanel.currentPrimaryId)

                                        Text {
                                            id: recBadgeText
                                            anchors.centerIn: parent
                                            text: "Sugerida"
                                            font.family: Theme.sansFont
                                            font.pixelSize: 11
                                            font.bold: true
                                            color: Theme.toolIconDarkColor(contextualToolsPanel.currentPrimaryId)
                                        }
                                    }

                                    Item { Layout.fillWidth: true }
                                }

                                Text {
                                    id: primarySuggestedDescription
                                    objectName: "primarySuggestedDescription"
                                    Layout.fillWidth: true
                                    text: studioBridge.hasLockedFiles
                                          ? "Desbloquea el documento con su contraseña para continuar"
                                          : (studioBridge.primarySuggestedTool.subtitle || "")
                                    font.family: Theme.sansFont
                                    font.pixelSize: 13
                                    color: Theme.textCreamMuted
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    HoverHandler {
                        id: primaryHover
                        cursorShape: Qt.PointingHandCursor
                    }

                    TapHandler {
                        id: primaryTap
                        onTapped: {
                            primarySuggestedCard.forceActiveFocus()
                            studioBridge.triggerPrimaryAction()
                        }
                    }
                }

                // DERECHA (~44%): "También puedes:" con chips secundarios compactos
                ColumnLayout {
                    id: secondaryChipsSection
                    objectName: "secondaryChipsSection"
                    visible: studioBridge.secondarySuggestedTools.length > 0
                    Layout.fillWidth: true
                    Layout.preferredWidth: contextualToolsPanel.isNarrowLayout
                                           ? zone2Layout.width
                                           : Math.floor((zone2Layout.width - 18) * 0.44)
                    Layout.alignment: Qt.AlignTop
                    spacing: 8

                    Text {
                        text: "También puedes:"
                        font.family: Theme.sansFont
                        font.pixelSize: Theme.fontMetaSize
                        color: Theme.textSecondary
                    }

                    Flow {
                        id: suggestedToolsFlow
                        objectName: "suggestedToolsFlow"
                        Layout.fillWidth: true
                        spacing: 8

                        Repeater {
                            model: studioBridge.secondarySuggestedTools
                            delegate: FocusScope {
                                id: secondaryChip
                                objectName: "suggestedToolCard_" + modelData.id
                                property string toolId: modelData.id
                                property bool isPrimary: false
                                width: chipInnerRow.implicitWidth + 24
                                height: 36
                                activeFocusOnTab: true

                                Keys.onReturnPressed: {
                                    secondaryChip.forceActiveFocus()
                                    studioBridge.selectTool(modelData.id)
                                }
                                Keys.onEnterPressed: {
                                    secondaryChip.forceActiveFocus()
                                    studioBridge.selectTool(modelData.id)
                                }
                                Keys.onSpacePressed: {
                                    secondaryChip.forceActiveFocus()
                                    studioBridge.selectTool(modelData.id)
                                }

                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.chipRadius
                                    color: chipTap.pressed
                                           ? "#EED3D0"
                                           : (chipHover.hovered ? "#FAF0EE" : Theme.surfaceCard)
                                    border.width: secondaryChip.activeFocus ? 2.0 : Theme.borderSubtleWidth
                                    border.color: secondaryChip.activeFocus
                                                  ? Theme.focusRingColor
                                                  : Theme.borderSubtleColor

                                    Behavior on color {
                                        ColorAnimation { duration: Theme.animFast }
                                    }

                                    Row {
                                        id: chipInnerRow
                                        anchors.centerIn: parent
                                        spacing: 7

                                        Rectangle {
                                            width: 22
                                            height: 22
                                            radius: 11
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: Theme.toolSoftBgColor(modelData.id)

                                            Image {
                                                id: chipSvgIcon
                                                anchors.centerIn: parent
                                                width: 14
                                                height: 14
                                                source: Theme.toolIconSource(modelData.id)
                                                sourceSize.width: 28
                                                sourceSize.height: 28
                                                fillMode: Image.PreserveAspectFit
                                                smooth: true
                                                visible: false
                                            }

                                            MultiEffect {
                                                anchors.fill: chipSvgIcon
                                                source: chipSvgIcon
                                                colorization: 1.0
                                                colorizationColor: Theme.toolIconDarkColor(modelData.id)
                                            }
                                        }

                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.title
                                            font.family: Theme.sansFont
                                            font.pixelSize: Theme.fontBodySize
                                            color: Theme.textPrimary
                                        }
                                    }
                                }

                                HoverHandler {
                                    id: chipHover
                                    cursorShape: Qt.PointingHandCursor
                                }

                                TapHandler {
                                    id: chipTap
                                    onTapped: {
                                        secondaryChip.forceActiveFocus()
                                        studioBridge.selectTool(modelData.id)
                                    }
                                }

                                ToolTip.visible: chipHover.hovered
                                ToolTip.delay: 200
                                ToolTip.text: modelData.subtitle
                            }
                        }
                    }
                }
            }
        }

        // Espaciador flexible inferior para absorber el alto sobrante en pantallas grandes sin separar Zona 1 de Zona 2
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}
