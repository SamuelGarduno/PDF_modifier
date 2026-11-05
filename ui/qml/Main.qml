import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: rootWindow
    objectName: "coquetteMainWindow"
    width: themePalette.initialWidth
    height: themePalette.initialHeight
    minimumWidth: 1024
    minimumHeight: 600
    visible: true
    title: "Coquette PDF Studio — Floral Stationery Suite"
    color: themePalette.surfaceLight
    flags: Qt.Window | Qt.FramelessWindowHint

    property string pendingPasswordFilePath: ""
    property string pendingPasswordFileName: ""
    property bool showSuccessModal: false
    property string completedSummaryText: ""

    // Atajo global Ctrl + K para enfocar el buscador rápido de herramientas
    Shortcut {
        sequence: "Ctrl+K"
        onActivated: {
            quickSearchInput.forceActiveFocus()
            quickSearchInput.selectAll()
        }
    }

    Connections {
        target: studioBridge
        function onPasswordRequired(filePath, fileName) {
            rootWindow.pendingPasswordFilePath = filePath
            rootWindow.pendingPasswordFileName = fileName
            passwordModalInput.text = ""
            passwordPopup.open()
        }
        function onOperationCompleted(message, firstFile, folderPath) {
            rootWindow.completedSummaryText = message
            rootWindow.showSuccessModal = true
            completionPopup.open()
        }
    }

    // Layout Principal (Split-View Asimétrico: Sidebar fijo de 260px + Lienzo Central fluido)
    Row {
        anchors.fill: parent
        spacing: 0

        // 1. PANEL LATERAL IZQUIERDO (Sidebar fijo de 260px en #1E0F16 simulando pasta de cuaderno)
        Rectangle {
            id: leftSidebar
            objectName: "leftSidebar"
            width: themePalette.sidebarWidth
            height: parent.height
            color: themePalette.backgroundDark

            // Detalle gráfico pintado de espiral de libreta en el borde izquierdo
            Canvas {
                id: spiralCanvas
                width: 24
                height: parent.height
                anchors.left: parent.left
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var step = 28
                    for (var y = 22; y < height - 16; y += step) {
                        // Perforación circular
                        ctx.fillStyle = "#0D0609"
                        ctx.beginPath()
                        ctx.arc(17, y, 4.0, 0, Math.PI * 2)
                        ctx.fill()

                        // Anillo metálico en tono coral pastel (#F8B8B0) y vino (#681D3A)
                        ctx.strokeStyle = "#F8B8B0"
                        ctx.lineWidth = 2.0
                        ctx.beginPath()
                        ctx.moveTo(2, y - 4)
                        ctx.bezierCurveTo(9, y - 8, 16, y - 5, 17, y)
                        ctx.bezierCurveTo(16, y + 5, 9, y + 8, 2, y + 4)
                        ctx.stroke()
                    }
                }
                onHeightChanged: requestPaint()
            }

            Item {
                id: sidebarContentArea
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 6
                anchors.topMargin: 10
                anchors.bottomMargin: 8

                // Título editorial de la aplicación en la parte superior del cuaderno
                Column {
                    id: headerTitleColumn
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 1

                    Text {
                        objectName: "sidebarTitleText"
                        // Ancho acotado + salto de línea: evita truncar a mitad de palabra con DPI alto
                        width: parent.width
                        text: "Herramientas para PDFs"
                        font.family: themePalette.serifFont
                        font.pixelSize: 17
                        font.bold: true
                        color: themePalette.surfaceLight
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }

                    Text {
                        width: parent.width
                        text: "Herramientas de Estación Floral"
                        font.family: themePalette.scriptFont
                        font.italic: true
                        font.pixelSize: 12
                        color: themePalette.accent
                        elide: Text.ElideRight
                    }
                }

                // Divisor horizontal con ícono de flor central (✿) en tono rosa pastel
                Item {
                    id: sidebarFloralDivider
                    anchors.top: headerTitleColumn.bottom
                    anchors.topMargin: 5
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.rightMargin: 6
                    height: 14

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: dividerFlowerText.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        height: 1
                        color: "#5A2D3A"
                    }

                    Text {
                        id: dividerFlowerText
                        anchors.centerIn: parent
                        text: "✿"
                        font.pixelSize: 11
                        color: themePalette.accent
                    }

                    Rectangle {
                        anchors.left: dividerFlowerText.right
                        anchors.leftMargin: 8
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        height: 1
                        color: "#5A2D3A"
                    }
                }

                // Buscador Rápido de Herramientas (Ctrl + K) con fondo oscuro #3A1822 y borde #6E3B49
                Rectangle {
                    id: searchBoxContainer
                    anchors.top: sidebarFloralDivider.bottom
                    anchors.topMargin: 5
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    height: 32
                    radius: 8
                    color: themePalette.searchBgDark
                    border.width: quickSearchInput.activeFocus ? 1.8 : 1.0
                    border.color: quickSearchInput.activeFocus ? themePalette.accent : themePalette.searchBorderDark

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        spacing: 6

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "⌕"
                            font.pixelSize: 14
                            color: "#D8B4BE"
                        }

                        TextInput {
                            id: quickSearchInput
                            objectName: "quickSearchInput"
                            width: parent.width - 72
                            anchors.verticalCenter: parent.verticalCenter
                            font.family: themePalette.sansFont
                            font.pixelSize: 12
                            color: "#FBF0F0"
                            onTextChanged: studioBridge.setSearchQuery(text)

                            Text {
                                visible: parent.text.length === 0 && !parent.activeFocus
                                text: "Buscar herramienta..."
                                font.family: themePalette.sansFont
                                font.pixelSize: 11
                                color: "#C69DA8"
                            }
                        }

                        Rectangle {
                            width: 44
                            height: 18
                            radius: 9
                            anchors.verticalCenter: parent.verticalCenter
                            color: themePalette.searchBadgeSalmon
                            Text {
                                anchors.centerIn: parent
                                text: "Ctrl+K"
                                font.family: themePalette.sansFont
                                font.pixelSize: 9
                                font.bold: true
                                color: "#2D1018"
                            }
                        }
                    }
                }

                // Contenedor desplazable (Flickable con clip: true) para que ninguna tarjeta quede cortada
                Flickable {
                    id: sidebarToolsList
                    objectName: "sidebarToolsList"
                    anchors.top: searchBoxContainer.bottom
                    anchors.topMargin: 8
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    contentWidth: width
                    contentHeight: sidebarCardsColumn.implicitHeight + 6
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        width: 6
                    }

                    Column {
                        id: sidebarCardsColumn
                        objectName: "sidebarCardsColumn"
                        width: parent.width
                        spacing: 4

                        Repeater {
                            model: studioBridge.filteredTools
                            delegate: SidebarCard {
                                toolId: modelData.id
                                title: modelData.title
                                subtitle: modelData.subtitle
                                badgeLetter: modelData.badge
                                isActive: studioBridge.activeTool === modelData.id
                                onSelected: function(id) { studioBridge.setActiveTool(id) }
                            }
                        }
                    }
                }
            }
        }

        // 2. LIENZO CENTRAL (Main Workspace fluido en #FBF0F0 con renglones sutiles de cuaderno)
        Rectangle {
            id: mainWorkspace
            objectName: "mainWorkspace"
            width: parent.width - leftSidebar.width
            height: parent.height
            color: themePalette.surfaceLight

            // Renglones horizontales muy sutiles estilo hoja de cuaderno y detalles botánicos
            Canvas {
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()

                    // Renglones horizontales sutiles en todo el lienzo
                    ctx.strokeStyle = "#E8D2D5"
                    ctx.lineWidth = 1.0
                    ctx.globalAlpha = 0.52
                    for (var lineY = 56; lineY < height; lineY += 24) {
                        ctx.beginPath()
                        ctx.moveTo(0, lineY)
                        ctx.lineTo(width, lineY)
                        ctx.stroke()
                    }
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }

            // 2.1 Barra de Título Personalizada (FramelessWindowHint) con doble línea horizontal fina debajo
            Rectangle {
                id: customTitleBar
                objectName: "customTitleBar"
                width: parent.width
                height: 64
                color: "transparent"

                // Margen superior de la cabecera para dar respiración visual al título
                readonly property int headerTopMargin: 20

                MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: 140
                    onPressed: rootWindow.startSystemMove()
                    onDoubleClicked: {
                        if (rootWindow.visibility === Window.Maximized) {
                            rootWindow.showNormal()
                        } else {
                            rootWindow.showMaximized()
                        }
                    }
                }

                Row {
                    objectName: "headerTitleRow"
                    anchors.left: parent.left
                    anchors.leftMargin: 22
                    anchors.top: parent.top
                    anchors.topMargin: customTitleBar.headerTopMargin
                    spacing: 10

                    Text {
                        text: studioBridge.activeToolTitle
                        font.family: themePalette.serifFont
                        font.pixelSize: 22
                        font.bold: true
                        color: "#3D1220"
                    }

                    Text {
                        anchors.baseline: parent.children[0].baseline
                        text: "— " + studioBridge.activeToolSubtitle
                        font.family: themePalette.scriptFont
                        font.italic: true
                        font.pixelSize: 15
                        color: "#8C465A"
                    }
                }

                // Controles de ventana (minimizar, maximizar, cerrar) integrados en la estética
                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.top: parent.top
                    anchors.topMargin: customTitleBar.headerTopMargin + 1
                    spacing: 8

                    Rectangle {
                        id: minBtn
                        width: 26; height: 26; radius: 13
                        color: themePalette.accent
                        border.width: 1; border.color: themePalette.secondary
                        Text { anchors.centerIn: parent; text: "—"; font.bold: true; color: themePalette.backgroundDark }
                        TapHandler { onTapped: rootWindow.showMinimized() }
                    }

                    Rectangle {
                        id: maxBtn
                        width: 26; height: 26; radius: 13
                        color: themePalette.primary
                        border.width: 1; border.color: themePalette.secondary
                        Text { anchors.centerIn: parent; text: "▢"; font.bold: true; color: themePalette.backgroundDark }
                        TapHandler {
                            onTapped: {
                                if (rootWindow.visibility === Window.Maximized) {
                                    rootWindow.showNormal()
                                } else {
                                    rootWindow.showMaximized()
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: closeBtn
                        width: 26; height: 26; radius: 13
                        color: themePalette.secondary
                        border.width: 1; border.color: themePalette.backgroundDark
                        Text { anchors.centerIn: parent; text: "✕"; font.bold: true; color: themePalette.surfaceLight }
                        TapHandler { onTapped: rootWindow.close() }
                    }
                }

                // Doble línea horizontal fina de lado a lado debajo de la cabecera
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 20
                    anchors.rightMargin: 20
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    height: 1
                    color: "#B98592"
                    opacity: 0.75
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 20
                    anchors.rightMargin: 20
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 1
                    height: 1
                    color: "#D8AEB8"
                    opacity: 0.75
                }
            }

            // 2.2 Contenedor central tipo hoja de papel enmarcado
            Item {
                anchors.top: customTitleBar.bottom
                anchors.topMargin: 6
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                anchors.bottomMargin: 14

                Rectangle {
                    id: outerPaperFrame
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: parent.height - 166
                    radius: 12
                    color: themePalette.stationeryFrameBg
                    border.width: 1.3
                    border.color: "#8E4A5E"

                    // Esquinas botánicas (SVG 1.2 Tiny): un solo motivo reflejado con Scale.
                    // Quedan bajo las vistas (z menor) y con margen interno para no recortarse.
                    Repeater {
                        model: [
                            { name: "TopLeft",     sx: 1,  sy: -1 },
                            { name: "TopRight",    sx: -1, sy: -1 },
                            { name: "BottomLeft",  sx: 1,  sy: 1 },
                            { name: "BottomRight", sx: -1, sy: 1 }
                        ]
                        delegate: Image {
                            objectName: "botanicalCorner" + modelData.name
                            readonly property int cornerSize: 76
                            readonly property int cornerMargin: 14
                            z: 0
                            width: cornerSize
                            height: cornerSize
                            sourceSize.width: cornerSize * 2
                            sourceSize.height: cornerSize * 2
                            source: "../../assets/icons/botanical_corner.svg"
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            opacity: 0.22
                            // El motivo base apunta a la esquina inferior-izquierda; sy = -1 lo lleva arriba
                            x: modelData.sx > 0 ? cornerMargin : parent.width - cornerSize - cornerMargin
                            y: modelData.sy < 0 ? cornerMargin : parent.height - cornerSize - cornerMargin
                            transform: Scale {
                                origin.x: width / 2
                                origin.y: height / 2
                                xScale: modelData.sx
                                yScale: modelData.sy
                            }
                        }
                    }
                    // Marco interior para las vistas de trabajo
                    Item {
                        id: innerPaperFrame
                        anchors.fill: parent
                        anchors.margins: 8

                        // Vistas intercambiables según la herramienta activa
                        DropzoneView {
                            anchors.fill: parent
                            visible: studioBridge.workspaceMode === "dropzone" || studioBridge.fileCount === 0
                        }

                        PageOrganizerView {
                            anchors.fill: parent
                            visible: studioBridge.workspaceMode === "organizer" && studioBridge.fileCount > 0
                        }

                        PdfViewerSignView {
                            anchors.fill: parent
                            visible: studioBridge.workspaceMode === "viewer" && studioBridge.fileCount > 0
                        }
                    }
                }

                // 2.3 Paneles de Configuración Inferior (Tarjetas modulares dinámicas)
                ConfigPanels {
                    id: bottomConfigPanel
                    anchors.top: outerPaperFrame.bottom
                    anchors.topMargin: 10
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 92
                }

                // 2.4 Barra de Estado y Progreso (Footer)
                FooterBar {
                    id: bottomFooterBar
                    anchors.top: bottomConfigPanel.bottom
                    anchors.topMargin: 10
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 54
                }
            }
        }
    }

    // Modal Estilizado Centrado para Desbloquear PDF Protegido al cargarlo
    Popup {
        id: passwordPopup
        objectName: "passwordPopup"
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        width: 440
        height: 220
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape

        Overlay.modal: Rectangle {
            color: "#881E0F16"
        }

        background: Rectangle {
            radius: 14
            color: themePalette.surfaceLight
            border.width: 2
            border.color: themePalette.secondary
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12

            Text {
                text: "Documento Sellado con Contraseña"
                font.family: themePalette.serifFont
                font.pixelSize: 17
                font.bold: true
                color: themePalette.backgroundDark
            }

            Text {
                Layout.fillWidth: true
                text: "Ingresa la clave para abrir '" + rootWindow.pendingPasswordFileName + "':"
                font.family: themePalette.sansFont
                font.pixelSize: 12
                color: themePalette.secondary
                elide: Text.ElideMiddle
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                radius: 8
                color: "#FFFFFF"
                border.width: 1.4
                border.color: themePalette.secondary

                TextInput {
                    id: passwordModalInput
                    anchors.fill: parent
                    anchors.margins: 8
                    echoMode: TextInput.Password
                    font.family: themePalette.sansFont
                    font.pixelSize: 13
                    color: themePalette.backgroundDark
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Item { Layout.fillWidth: true }

                PillButton {
                    height: 34
                    text: "Omitir"
                    primaryStyle: false
                    onClicked: passwordPopup.close()
                }

                PillButton {
                    height: 34
                    text: "Desbloquear Pliego"
                    primaryStyle: true
                    onClicked: {
                        var ok = studioBridge.supplyFilePassword(
                            rootWindow.pendingPasswordFilePath,
                            passwordModalInput.text
                        )
                        if (ok) {
                            passwordPopup.close()
                        }
                    }
                }
            }
        }
    }

    // Popup de Éxito Centrado en Overlay.overlay ("¡Pliego Procesado con Éxito!")
    Popup {
        id: completionPopup
        objectName: "completionPopup"
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        width: 520
        height: 220
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: rootWindow.showSuccessModal = false

        Overlay.modal: Rectangle {
            color: "#771E0F16"
        }

        background: Rectangle {
            radius: 14
            color: themePalette.surfaceLight
            border.width: 2
            border.color: themePalette.secondary
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 10

                Rectangle {
                    width: 32; height: 32; radius: 16
                    color: themePalette.secondary
                    Text { anchors.centerIn: parent; text: "✓"; font.bold: true; color: themePalette.surfaceLight }
                }

                Text {
                    text: "¡Pliego Procesado con Éxito!"
                    font.family: themePalette.serifFont
                    font.pixelSize: 18
                    font.bold: true
                    color: themePalette.backgroundDark
                }
            }

            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: rootWindow.completedSummaryText
                font.family: themePalette.sansFont
                font.pixelSize: 13
                color: themePalette.secondary
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 10

                PillButton {
                    height: 34
                    text: "Abrir Archivo"
                    primaryStyle: true
                    onClicked: {
                        studioBridge.openFileInSystem(studioBridge.lastOutputFile)
                        completionPopup.close()
                    }
                }

                PillButton {
                    height: 34
                    text: "Mostrar en Carpeta"
                    primaryStyle: false
                    onClicked: {
                        studioBridge.showFileInFolder(studioBridge.lastOutputFile)
                        completionPopup.close()
                    }
                }

                PillButton {
                    height: 34
                    text: "Cerrar"
                    primaryStyle: false
                    onClicked: completionPopup.close()
                }
            }
        }
    }
}
