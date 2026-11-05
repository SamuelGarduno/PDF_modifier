import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: dropzoneRoot
    objectName: "dropzoneView"

    property int draggedFileIndex: -1

    FileDialog {
        id: filePickerDialog
        title: "Seleccionar documentos PDF o Imágenes"
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            "Documentos y Láminas (*.pdf *.png *.jpg *.jpeg)",
            "Archivos PDF (*.pdf)",
            "Imágenes (*.png *.jpg *.jpeg)"
        ]
        onAccepted: {
            studioBridge.addFileUrls(filePickerDialog.selectedFiles)
        }
    }

    DropArea {
        id: dropArea
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) {
                studioBridge.addFileUrls(drop.urls)
            }
        }
    }

    // Marco interior punteado fino (guiones cortos) y ramitas botánicas con hojas en las esquinas inferiores
    Canvas {
        id: dashedFrameCanvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            var rx = 8
            var ry = 10
            var rw = width - 16
            var rh = height - 18
            var rad = 10

            // Borde punteado fino con guiones cortos y esquinas redondeadas
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

    // Washi tape (SVG con bordes dentados, #F8B8B0 translúcido, ligera inclinación y sombra sutil)
    Repeater {
        model: [
            { name: "leftWashiTape",  xRatio: 0.23, angle: -2.2 },
            { name: "rightWashiTape", xRatio: 0.77, angle: 2.2 }
        ]
        delegate: Item {
            objectName: modelData.name
            width: 96
            height: 25
            x: dropzoneRoot.width * modelData.xRatio - width / 2
            y: 1
            rotation: modelData.angle

            // Sombra suave desplazada bajo la cinta para dar sensación de papel adherido
            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 2
                anchors.leftMargin: 2
                radius: 2
                color: themePalette.wineDeep
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
    // ESTADO 1: VISTA VACÍA (studioBridge.fileCount === 0)
    // =========================================================================
    Item {
        id: emptyStateContainer
        objectName: "emptyStateContainer"
        visible: studioBridge.fileCount === 0
        anchors.fill: parent
        anchors.margins: 20

        Column {
            anchors.centerIn: parent
            spacing: 12

            // Ícono central: anillo exterior fino, círculo interior #DA7B88 con borde vino, y flor blanca de 5 pétalos
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

                        // Círculo exterior de línea fina
                        ctx.strokeStyle = "#8C465A"
                        ctx.lineWidth = 1.2
                        ctx.beginPath()
                        ctx.arc(cx, cy, 36, 0, Math.PI * 2)
                        ctx.stroke()

                        // Círculo interior relleno en rosa viejo (#DA7B88) con borde vino oscuro (#521928)
                        ctx.fillStyle = "#DA7B88"
                        ctx.strokeStyle = "#521928"
                        ctx.lineWidth = 1.6
                        ctx.beginPath()
                        ctx.arc(cx, cy, 28, 0, Math.PI * 2)
                        ctx.fill()
                        ctx.stroke()

                        // Flor blanca de 5 pétalos
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

                        // Centro vino oscuro de la flor
                        ctx.fillStyle = "#521928"
                        ctx.beginPath()
                        ctx.arc(cx, cy, 4.2, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }
            }

            // Texto principal
            Text {
                objectName: "emptyStateTitleText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Arrastra y suelta tus pliegos PDF o postales aquí"
                font.family: themePalette.serifFont
                font.pixelSize: 18
                font.bold: true
                color: "#3D1220"
            }

            // Subtítulo en cursiva
            Text {
                objectName: "emptyStateSubtitleText"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Se unirán en el orden en que aparezcan en la cola"
                font.family: themePalette.scriptFont
                font.italic: true
                font.pixelSize: 14
                color: "#7C3B4E"
            }

            Item { width: 1; height: 4 }

            // Botón "Seleccionar archivos..." con sombra inferior sólida desplazada (#521928)
            PillButton {
                id: selectFilesEmptyButton
                objectName: "selectFilesEmptyButton"
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Seleccionar archivos..."
                primaryStyle: true
                solidShadow: true
                horizontalPadding: 24
                onClicked: filePickerDialog.open()
            }
        }
    }

    // =========================================================================
    // ESTADO 2: VISTA CON ARCHIVOS EN COLA (studioBridge.fileCount > 0)
    // =========================================================================
    ColumnLayout {
        id: queuedStateContainer
        objectName: "queuedStateContainer"
        visible: studioBridge.fileCount > 0
        anchors.fill: parent
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.topMargin: 20
        anchors.bottomMargin: 20
        spacing: 10

        // Cabecera interna de la cola: "✿ Cola de pliegos · N documentos" y enlace "Vaciar cola"
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: 6

            Text {
                text: "✿"
                font.pixelSize: 14
                color: "#DA7B88"
            }

            Text {
                text: "Cola de pliegos"
                font.family: themePalette.serifFont
                font.pixelSize: 15
                font.bold: true
                color: "#3D1220"
            }

            Text {
                objectName: "queueHeaderCountText"
                text: "· " + studioBridge.fileCount + (studioBridge.fileCount === 1 ? " documento" : " documentos")
                font.family: themePalette.serifFont
                font.pixelSize: 14
                color: "#7C3B4E"
            }

            Item { Layout.fillWidth: true }

            // Enlace subrayado "Vaciar cola"
            Text {
                id: clearQueueLink
                objectName: "clearQueueLink"
                text: "Vaciar cola"
                font.family: themePalette.sansFont
                font.pixelSize: 13
                font.underline: true
                color: clearHover.hovered ? "#3D1220" : "#681D3A"

                HoverHandler {
                    id: clearHover
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler {
                    onTapped: studioBridge.clearFiles()
                }
            }
        }

        // Lista de tarjetas de archivos en cola (#FFFDFB)
        ListView {
            id: queueListView
            objectName: "queueListView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: studioBridge.queuedFiles

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 6
            }

            delegate: Rectangle {
                id: fileCardDelegate
                objectName: "queuedFileCard_" + modelData.index
                width: queueListView.width
                height: 54
                radius: 10
                color: dropzoneRoot.draggedFileIndex === modelData.index ? "#FDF2EE" : themePalette.queueCardBg
                border.width: 1.1
                border.color: modelData.isEncrypted ? themePalette.primary : "#D9B2BC"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 10

                    // 1. Manejador de arrastre (drag handle ⋮⋮ de 6 puntos verticales)
                    Item {
                        id: dragHandleItem
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 28

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                ctx.fillStyle = "#B88492"
                                var cols = [5, 11]
                                var rows = [7, 14, 21]
                                for (var r = 0; r < rows.length; r++) {
                                    for (var c = 0; c < cols.length; c++) {
                                        ctx.beginPath()
                                        ctx.arc(cols[c], rows[r], 1.6, 0, Math.PI * 2)
                                        ctx.fill()
                                    }
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -4
                            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                            onPressed: {
                                dropzoneRoot.draggedFileIndex = modelData.index
                            }
                            onPositionChanged: function(mouse) {
                                if (!pressed || dropzoneRoot.draggedFileIndex < 0)
                                    return
                                var listPos = mapToItem(queueListView.contentItem, mouse.x, mouse.y)
                                var targetIdx = queueListView.indexAt(queueListView.width / 2, listPos.y)
                                if (targetIdx >= 0 && targetIdx !== dropzoneRoot.draggedFileIndex) {
                                    var fromIdx = dropzoneRoot.draggedFileIndex
                                    dropzoneRoot.draggedFileIndex = targetIdx
                                    studioBridge.moveFile(fromIdx, targetIdx)
                                }
                            }
                            onReleased: {
                                dropzoneRoot.draggedFileIndex = -1
                            }
                            onCanceled: {
                                dropzoneRoot.draggedFileIndex = -1
                            }
                        }
                    }

                    // 2. Círculo numerado relleno en vino oscuro (#521928)
                    Rectangle {
                        Layout.preferredWidth: 26
                        Layout.preferredHeight: 26
                        radius: 13
                        color: themePalette.wineDeep

                        Text {
                            anchors.centerIn: parent
                            text: (modelData.index + 1).toString()
                            font.family: themePalette.sansFont
                            font.pixelSize: 12
                            font.bold: true
                            color: "#FFFDFB"
                        }
                    }

                    // 3. Ícono de documento/hoja con líneas y esquina doblada
                    Item {
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 26

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                ctx.fillStyle = "#FBF0F0"
                                ctx.strokeStyle = "#681D3A"
                                ctx.lineWidth = 1.2

                                // Contorno de hoja con esquina superior derecha doblada
                                ctx.beginPath()
                                ctx.moveTo(3, 2)
                                ctx.lineTo(14, 2)
                                ctx.lineTo(19, 7)
                                ctx.lineTo(19, 24)
                                ctx.lineTo(3, 24)
                                ctx.closePath()
                                ctx.fill()
                                ctx.stroke()

                                // Pliegue de la esquina
                                ctx.beginPath()
                                ctx.moveTo(14, 2)
                                ctx.lineTo(14, 7)
                                ctx.lineTo(19, 7)
                                ctx.stroke()

                                // Líneas internas simulando texto
                                ctx.lineWidth = 1.0
                                ctx.strokeStyle = "#9E586D"
                                ctx.beginPath()
                                ctx.moveTo(6, 11)
                                ctx.lineTo(15, 11)
                                ctx.moveTo(6, 15)
                                ctx.lineTo(16, 15)
                                ctx.moveTo(6, 19)
                                ctx.lineTo(12, 19)
                                ctx.stroke()
                            }
                        }
                    }

                    // 4. Información del archivo: nombre en negrita (con elipsis) + metadatos debajo
                    Column {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            width: parent.width
                            text: modelData.name
                            font.family: themePalette.sansFont
                            font.pixelSize: 13
                            font.bold: true
                            elide: Text.ElideRight
                            color: "#2D1018"
                        }

                        Row {
                            spacing: 4

                            Text {
                                text: modelData.pageCount + (modelData.pageCount === 1 ? " página" : " páginas")
                                font.family: themePalette.scriptFont
                                font.italic: true
                                font.pixelSize: 12
                                color: "#7C3B4E"
                            }

                            Text {
                                text: "· " + modelData.sizeFormatted
                                font.family: themePalette.sansFont
                                font.pixelSize: 11
                                color: "#8C5363"
                            }
                        }
                    }

                    // 5. Acciones a la derecha: tres botones circulares con borde fino (^, v, ✕)
                    Row {
                        spacing: 6

                        // Botón Subir (^) - deshabilitado en el primer elemento
                        Rectangle {
                            id: moveUpBtn
                            objectName: "moveUpBtn_" + modelData.index
                            property bool canMoveUp: modelData.index > 0
                            width: 26
                            height: 26
                            radius: 13
                            color: !canMoveUp ? "#F5ECEA" : (upHover.hovered ? "#F6BCA8" : "#FAF0EE")
                            border.width: 1.0
                            border.color: !canMoveUp ? "#DEC8CE" : "#9E586D"
                            opacity: canMoveUp ? 1.0 : 0.45

                            Text {
                                anchors.centerIn: parent
                                text: "⌃"
                                font.pixelSize: 13
                                font.bold: true
                                color: "#521928"
                            }

                            HoverHandler {
                                id: upHover
                                cursorShape: moveUpBtn.canMoveUp ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            }
                            TapHandler {
                                enabled: moveUpBtn.canMoveUp
                                onTapped: studioBridge.moveFileUp(modelData.index)
                            }
                        }

                        // Botón Bajar (v) - deshabilitado en el último elemento
                        Rectangle {
                            id: moveDownBtn
                            objectName: "moveDownBtn_" + modelData.index
                            property bool canMoveDown: modelData.index < (studioBridge.fileCount - 1)
                            width: 26
                            height: 26
                            radius: 13
                            color: !canMoveDown ? "#F5ECEA" : (downHover.hovered ? "#F6BCA8" : "#FAF0EE")
                            border.width: 1.0
                            border.color: !canMoveDown ? "#DEC8CE" : "#9E586D"
                            opacity: canMoveDown ? 1.0 : 0.45

                            Text {
                                anchors.centerIn: parent
                                text: "⌄"
                                font.pixelSize: 13
                                font.bold: true
                                color: "#521928"
                            }

                            HoverHandler {
                                id: downHover
                                cursorShape: moveDownBtn.canMoveDown ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            }
                            TapHandler {
                                enabled: moveDownBtn.canMoveDown
                                onTapped: studioBridge.moveFileDown(modelData.index)
                            }
                        }

                        // Botón Eliminar (✕)
                        Rectangle {
                            id: deleteFileBtn
                            objectName: "deleteFileBtn_" + modelData.index
                            width: 26
                            height: 26
                            radius: 13
                            color: delHover.hovered ? "#DA7B88" : "#FAF0EE"
                            border.width: 1.0
                            border.color: "#9E586D"

                            Text {
                                anchors.centerIn: parent
                                text: "✕"
                                font.pixelSize: 11
                                font.bold: true
                                color: delHover.hovered ? "#FFFDFB" : "#521928"
                            }

                            HoverHandler {
                                id: delHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                onTapped: studioBridge.removeFileAt(modelData.index)
                            }
                        }
                    }
                }
            }
        }

        // Zona inferior compacta para añadir más archivos (Mini-dropzone)
        Item {
            id: compactMiniDropzone
            objectName: "compactMiniDropzone"
            Layout.fillWidth: true
            Layout.preferredHeight: 46

            Rectangle {
                anchors.fill: parent
                radius: 9
                color: "#FAF0EE"
            }

            Canvas {
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = "#A66376"
                    ctx.lineWidth = 1.1
                    ctx.setLineDash([4, 4])
                    ctx.strokeRect(1, 1, width - 2, height - 2)
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }

            Row {
                anchors.centerIn: parent
                spacing: 12

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Suelta más pliegos aquí o"
                    font.family: themePalette.scriptFont
                    font.italic: true
                    font.pixelSize: 14
                    color: "#681D3A"
                }

                PillButton {
                    id: addMoreFilesButton
                    objectName: "addMoreFilesButton"
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Añadir archivos..."
                    primaryStyle: false
                    solidShadow: false
                    height: 30
                    horizontalPadding: 16
                    onClicked: filePickerDialog.open()
                }
            }
        }
    }
}
