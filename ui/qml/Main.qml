import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "."

Window {
    id: rootWindow
    objectName: "coquetteMainWindow"

    readonly property real availableScreenWidth: (Screen.width > 0 && Screen.desktopAvailableWidth > 0)
                                                 ? Math.min(Screen.width, Screen.desktopAvailableWidth)
                                                 : 1920
    readonly property real availableScreenHeight: Screen.desktopAvailableHeight > 0
                                                  ? Screen.desktopAvailableHeight
                                                  : 1080

    width: Math.min(Theme.initialWidth, Math.round(availableScreenWidth * 0.9))
    height: Math.min(Theme.initialHeight, Math.round(availableScreenHeight * 0.9))
    minimumWidth: Math.min(Theme.minWindowWidth, Math.round(availableScreenWidth * 0.9))
    minimumHeight: Math.min(Theme.minWindowHeight, Math.round(availableScreenHeight * 0.9))
    visible: true
    title: "Coquette PDF Studio — Floral Stationery Suite"
    color: Theme.surfaceLight
    flags: Qt.Window | Qt.FramelessWindowHint

    Component.onCompleted: {
        if (rootWindow.availableScreenWidth > 0 && rootWindow.availableScreenHeight > 0) {
            rootWindow.x = Math.max(0, Math.round(Screen.virtualX + (rootWindow.availableScreenWidth - rootWindow.width) / 2))
            rootWindow.y = Math.max(0, Math.round(Screen.virtualY + (rootWindow.availableScreenHeight - rootWindow.height) / 2))
        }
    }

    property string pendingPasswordFilePath: ""
    property string pendingPasswordFileName: ""
    property bool showSuccessModal: false
    property string completedSummaryText: ""
    property string friendlyNoticeText: ""

    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (passwordPopup.opened) {
                passwordPopup.close()
            } else if (completionPopup.opened) {
                completionPopup.close()
            } else if (studioBridge.isBusy) {
                studioBridge.cancelActiveOperation()
            } else if (studioBridge.isToolSelected) {
                studioBridge.returnToWorkbench()
            }
        }
    }

    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        onActivated: {
            if (!passwordPopup.opened && !completionPopup.opened && studioBridge.validFileCount > 0) {
                studioBridge.triggerPrimaryAction()
            }
        }
    }

    Timer {
        id: friendlyNoticeTimer
        interval: 4500
        repeat: false
        onTriggered: {
            rootWindow.friendlyNoticeText = ""
            studioBridge.clearNoticeMessage()
        }
    }

    Connections {
        target: studioBridge
        function onPasswordRequired(filePath, fileName) {
            rootWindow.pendingPasswordFilePath = filePath
            rootWindow.pendingPasswordFileName = fileName
            passwordModalInput.text = ""
            passwordPopup.open()
            passwordModalInput.forceActiveFocus()
        }
        function onOperationCompleted(message, firstFile, folderPath) {
            rootWindow.completedSummaryText = message
            rootWindow.showSuccessModal = true
            completionPopup.open()
            waxSealStampAnim.restart()
        }
        function onErrorOccurred(errorMessage) {
            rootWindow.friendlyNoticeText = errorMessage
            friendlyNoticeTimer.restart()
        }
        function onFilesChanged() {
            if (!studioBridge.hasLockedFiles && passwordPopup.opened) {
                passwordPopup.close()
            }
        }
    }

    // LIENZO PRINCIPAL UNIFICADO (100% del ancho de la ventana sin barra lateral)
    Rectangle {
        id: mainWorkspace
        objectName: "mainWorkspace"
        anchors.fill: parent
        color: Theme.surfaceLight

        // Fondo rayado reutilizable estilo hoja de cuaderno en toda la ventana
        PaperBackground {
            id: mainPaperBackground
            objectName: "mainPaperBackground"
            anchors.fill: parent
        }

        // Detalle gráfico pintado de espiral de libreta en el borde izquierdo del cuaderno
        Canvas {
            id: spiralCanvas
            objectName: "spiralBindingCanvas"
            width: 24
            height: parent.height
            anchors.left: parent.left
            z: 5
            layer.enabled: true
            layer.smooth: true
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var step = 28
                for (var y = 22; y < height - 16; y += step) {
                    ctx.fillStyle = "#3D1220"
                    ctx.beginPath()
                    ctx.arc(17, y, 3.8, 0, Math.PI * 2)
                    ctx.fill()

                    ctx.strokeStyle = "#681D3A"
                    ctx.lineWidth = 2.4
                    ctx.beginPath()
                    ctx.moveTo(2, y - 4)
                    ctx.bezierCurveTo(9, y - 8, 16, y - 5, 17, y)
                    ctx.bezierCurveTo(16, y + 5, 9, y + 8, 2, y + 4)
                    ctx.stroke()

                    ctx.strokeStyle = "#F8B8B0"
                    ctx.lineWidth = 1.4
                    ctx.beginPath()
                    ctx.moveTo(2, y - 4)
                    ctx.bezierCurveTo(9, y - 8, 16, y - 5, 17, y)
                    ctx.bezierCurveTo(16, y + 5, 9, y + 8, 2, y + 4)
                    ctx.stroke()
                }
            }
            onHeightChanged: requestPaint()
        }

        // 1. Barra de Título Personalizada (FramelessWindowHint) con subtítulo corto
        Rectangle {
            id: customTitleBar
            objectName: "customTitleBar"
            width: parent.width
            height: 62
            color: "transparent"

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

            RowLayout {
                id: headerTitleRow
                objectName: "headerTitleRow"
                anchors.left: parent.left
                anchors.leftMargin: 32
                anchors.right: windowControlsRow.left
                anchors.rightMargin: 12
                anchors.top: parent.top
                anchors.topMargin: customTitleBar.headerTopMargin
                height: 32
                spacing: 10

                PillButton {
                    id: backToWorkbenchButton
                    objectName: "backToWorkbenchButton"
                    visible: studioBridge.isToolSelected && studioBridge.fileCount > 0
                    Layout.alignment: Qt.AlignVCenter
                    height: 30
                    horizontalPadding: 14
                    text: "← Volver a la mesa de trabajo"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: studioBridge.returnToWorkbench()
                }

                Text {
                    id: headerPrimaryTitle
                    objectName: "headerPrimaryTitle"
                    Layout.alignment: Qt.AlignVCenter
                    text: studioBridge.isToolSelected && studioBridge.fileCount > 0
                          ? studioBridge.activeToolTitle
                          : "Mesa de Trabajo Floral"
                    font.family: Theme.serifFont
                    font.pixelSize: Theme.fontWindowTitleSize
                    font.bold: true
                    color: Theme.textPrimary
                }

                Text {
                    id: headerSubtitleText
                    objectName: "headerSubtitleText"
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    text: "— " + (studioBridge.isToolSelected && studioBridge.fileCount > 0
                                  ? studioBridge.activeToolSubtitle
                                  : studioBridge.workbenchSubtitle)
                    font.family: Theme.scriptFont
                    font.italic: true
                    font.pixelSize: 14
                    color: Theme.textSecondary
                    elide: Text.ElideRight
                }
            }

            // Controles de ventana (minimizar, maximizar, cerrar)
            Row {
                id: windowControlsRow
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.top: parent.top
                anchors.topMargin: customTitleBar.headerTopMargin + 1
                spacing: 8

                Rectangle {
                    id: minBtn
                    width: 26; height: 26; radius: 13
                    color: Theme.accentPeach
                    border.width: 1; border.color: Theme.borderSubtleColor
                    Text { anchors.centerIn: parent; text: "—"; font.bold: true; color: Theme.textPrimary }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: rootWindow.showMinimized() }
                }

                Rectangle {
                    id: maxBtn
                    width: 26; height: 26; radius: 13
                    color: Theme.primaryRose
                    border.width: 1; border.color: Theme.borderSubtleColor
                    Text { anchors.centerIn: parent; text: "▢"; font.bold: true; color: Theme.textPrimary }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
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
                    color: Theme.secondaryWine
                    border.width: 1; border.color: Theme.wineDarkCard
                    Text { anchors.centerIn: parent; text: "✕"; font.bold: true; color: Theme.surfaceCard }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: rootWindow.close() }
                }
            }

            // Línea divisoria fina debajo de la cabecera
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 30
                anchors.rightMargin: 20
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 2
                height: 1
                color: Theme.borderSubtleColor
            }
        }

        // Banner amigable de aviso para formatos no soportados, duplicados o archivos dañados
        Rectangle {
            id: friendlyNoticeBanner
            objectName: "friendlyNoticeBanner"
            visible: rootWindow.friendlyNoticeText.length > 0
            z: 20
            anchors.top: customTitleBar.bottom
            anchors.topMargin: 8
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width - 80, Math.max(380, noticeBannerLabel.implicitWidth + 96))
            height: 36
            radius: 18
            color: studioBridge.lastNoticeIsError ? Theme.errorBg : "#FAF3F2"
            border.width: Theme.borderSubtleWidth
            border.color: studioBridge.lastNoticeIsError ? Theme.errorBorder : Theme.borderSubtleColor

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 12
                spacing: 8

                Text {
                    text: "✿"
                    font.pixelSize: 13
                    color: studioBridge.lastNoticeIsError ? Theme.errorText : Theme.secondaryWine
                }

                Text {
                    id: noticeBannerLabel
                    objectName: "friendlyNoticeTextItem"
                    Layout.fillWidth: true
                    text: rootWindow.friendlyNoticeText
                    font.family: Theme.sansFont
                    font.pixelSize: 12
                    font.bold: true
                    color: studioBridge.lastNoticeIsError ? Theme.errorText : Theme.textPrimary
                    elide: Text.ElideRight
                }

                Rectangle {
                    width: 24; height: 24; radius: 12
                    color: "transparent"
                    border.width: 1; border.color: Theme.borderSubtleColor
                    Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: 10; font.bold: true; color: Theme.textPrimary }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        onTapped: {
                            friendlyNoticeTimer.stop()
                            rootWindow.friendlyNoticeText = ""
                            studioBridge.clearNoticeMessage()
                        }
                    }
                }
            }
        }

        // 2. Contenedor principal de trabajo y barra de acción inferior
        Item {
            anchors.top: friendlyNoticeBanner.visible ? friendlyNoticeBanner.bottom : customTitleBar.bottom
            anchors.topMargin: 6
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 30
            anchors.rightMargin: 20
            anchors.bottomMargin: 14

            // Zona 3 - Barra de Acción (siempre visible, anclada abajo, ~64 px)
            FooterBar {
                id: bottomFooterBar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: Theme.actionBarHeight
            }

            // Barra de ajustes específicos (SOLO visible cuando se abre una herramienta con opciones)
            ConfigPanels {
                id: bottomConfigPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: bottomFooterBar.top
                anchors.bottomMargin: visible ? 10 : 0
                height: visible ? 72 : 0
            }

            // Lienzo principal de trabajo (sin cajas anidadas cuando hay archivos en la mesa)
            Rectangle {
                id: outerPaperFrame
                objectName: "outerPaperFrame"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: bottomConfigPanel.visible ? bottomConfigPanel.top : bottomFooterBar.top
                anchors.bottomMargin: 10
                radius: 14
                color: "transparent"
                border.width: (studioBridge.fileCount === 0 || studioBridge.isToolSelected)
                              ? Theme.borderSubtleWidth
                              : 0
                border.color: Theme.borderSubtleColor

                // Ramitas botánicas en las esquinas: SOLO visibles en el estado vacío
                Repeater {
                    model: [
                        { name: "TopLeft",     sx: 1,  sy: -1 },
                        { name: "TopRight",    sx: -1, sy: -1 },
                        { name: "BottomLeft",  sx: 1,  sy: 1 },
                        { name: "BottomRight", sx: -1, sy: 1 }
                    ]
                    delegate: Image {
                        objectName: "botanicalCorner" + modelData.name
                        visible: studioBridge.fileCount === 0
                        readonly property int cornerSize: 76
                        readonly property int cornerMargin: 14
                        z: 0
                        width: cornerSize
                        height: cornerSize
                        sourceSize.width: cornerSize * 2
                        sourceSize.height: cornerSize * 2
                        source: "../../assets/icons/botanical_corner.svg"
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        cache: true
                        smooth: true
                        opacity: 0.22
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

                Item {
                    id: innerPaperFrame
                    anchors.fill: parent
                    anchors.margins: (studioBridge.fileCount === 0 || studioBridge.isToolSelected) ? 8 : 0

                    DropzoneView {
                        anchors.fill: parent
                        visible: !studioBridge.isToolSelected || studioBridge.workspaceMode === "dropzone" || studioBridge.fileCount === 0
                    }

                    PageOrganizerView {
                        anchors.fill: parent
                        visible: studioBridge.isToolSelected && studioBridge.workspaceMode === "organizer" && studioBridge.fileCount > 0
                    }

                    PdfViewerSignView {
                        anchors.fill: parent
                        visible: studioBridge.isToolSelected && studioBridge.workspaceMode === "viewer" && studioBridge.fileCount > 0
                    }
                }
            }
        }

        // Controladores de redimensionamiento de ventana (FramelessWindowHint)
        MouseArea {
            id: resizeLeftEdge
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            width: 6
            cursorShape: Qt.SizeHorCursor
            enabled: rootWindow.visibility !== Window.Maximized
            onPressed: rootWindow.startSystemResize(Qt.LeftEdge)
        }
        MouseArea {
            id: resizeRightEdge
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            width: 6
            cursorShape: Qt.SizeHorCursor
            enabled: rootWindow.visibility !== Window.Maximized
            onPressed: rootWindow.startSystemResize(Qt.RightEdge)
        }
        MouseArea {
            id: resizeBottomEdge
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            height: 6
            cursorShape: Qt.SizeVerCursor
            enabled: rootWindow.visibility !== Window.Maximized
            onPressed: rootWindow.startSystemResize(Qt.BottomEdge)
        }
        MouseArea {
            id: resizeBottomRightCorner
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: 12
            height: 12
            cursorShape: Qt.SizeFDiagCursor
            enabled: rootWindow.visibility !== Window.Maximized
            onPressed: rootWindow.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
        }
        MouseArea {
            id: resizeBottomLeftCorner
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            width: 12
            height: 12
            cursorShape: Qt.SizeBDiagCursor
            enabled: rootWindow.visibility !== Window.Maximized
            onPressed: rootWindow.startSystemResize(Qt.LeftEdge | Qt.BottomEdge)
        }
    }

    // Modal Estilizado Centrado para Desbloquear PDF Protegido ("Abrir sello")
    Popup {
        id: passwordPopup
        objectName: "passwordPopup"
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        width: 440
        height: 224
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape

        Overlay.modal: Rectangle {
            color: "#881E0F16"
        }

        background: Rectangle {
            radius: 16
            color: Theme.surfaceLight
            border.width: Theme.borderStrongWidth
            border.color: Theme.secondaryWine
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12

            Text {
                text: "Abrir sello del pliego"
                font.family: Theme.serifFont
                font.pixelSize: 18
                font.bold: true
                color: Theme.textPrimary
            }

            Text {
                Layout.fillWidth: true
                text: "Ingresa la clave para leer '" + rootWindow.pendingPasswordFileName + "':"
                font.family: Theme.sansFont
                font.pixelSize: 13
                color: Theme.textSecondary
                elide: Text.ElideMiddle
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                radius: 8
                color: "#FFFFFF"
                border.width: Theme.borderSubtleWidth
                border.color: Theme.borderSubtleColor

                TextInput {
                    id: passwordModalInput
                    objectName: "passwordModalInput"
                    anchors.fill: parent
                    anchors.margins: 8
                    verticalAlignment: TextInput.AlignVCenter
                    echoMode: TextInput.Password
                    font.family: Theme.sansFont
                    font.pixelSize: 14
                    color: Theme.textPrimary
                    onAccepted: unlockSubmitBtn.clicked()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Item { Layout.fillWidth: true }

                PillButton {
                    height: 36
                    text: "Más tarde"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: passwordPopup.close()
                }

                PillButton {
                    id: unlockSubmitBtn
                    objectName: "unlockSubmitBtn"
                    height: 36
                    text: "Abrir sello"
                    primaryStyle: true
                    solidShadow: true
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

    // Popup de Éxito Centrado con animación de sello de lacre y "Original intacto ✓"
    Popup {
        id: completionPopup
        objectName: "completionPopup"
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        width: 520
        height: 244
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: rootWindow.showSuccessModal = false

        ParallelAnimation {
            id: waxSealStampAnim
            NumberAnimation {
                target: waxSealBadge
                property: "scale"
                from: 1.45
                to: 1.0
                duration: 180
                easing.type: Easing.OutBack
            }
            NumberAnimation {
                target: waxSealBadge
                property: "opacity"
                from: 0.2
                to: 1.0
                duration: 150
            }
        }

        Overlay.modal: Rectangle {
            color: "#771E0F16"
        }

        background: Rectangle {
            radius: 16
            color: Theme.surfaceLight
            border.width: Theme.borderStrongWidth
            border.color: Theme.secondaryWine
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 10

                Rectangle {
                    id: waxSealBadge
                    objectName: "waxSealBadge"
                    width: 36; height: 36; radius: 18
                    color: Theme.secondaryWine
                    border.width: 1.5
                    border.color: Theme.accentPeach
                    Text { anchors.centerIn: parent; text: "✓"; font.pixelSize: 16; font.bold: true; color: Theme.surfaceCard }
                }

                Text {
                    text: "¡Pliego procesado con éxito!"
                    font.family: Theme.serifFont
                    font.pixelSize: 19
                    font.bold: true
                    color: Theme.textPrimary
                }
            }

            Rectangle {
                objectName: "modalOriginalIntactBadge"
                Layout.alignment: Qt.AlignHCenter
                height: 26
                width: modalIntactLabel.implicitWidth + 18
                radius: 13
                color: "#EDF5EE"
                border.width: 1
                border.color: "#8FA88A"

                Text {
                    id: modalIntactLabel
                    anchors.centerIn: parent
                    text: "Original intacto ✓"
                    font.family: Theme.sansFont
                    font.pixelSize: 12
                    font.bold: true
                    color: "#2F5233"
                }
            }

            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: rootWindow.completedSummaryText
                font.family: Theme.sansFont
                font.pixelSize: 13
                color: Theme.textSecondary
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 10

                PillButton {
                    objectName: "modalOpenFileBtn"
                    height: 36
                    text: "Abrir archivo"
                    primaryStyle: true
                    solidShadow: true
                    onClicked: {
                        studioBridge.openFileInSystem(studioBridge.lastOutputFile)
                        completionPopup.close()
                    }
                }

                PillButton {
                    objectName: "modalShowFolderBtn"
                    height: 36
                    text: "Mostrar en carpeta"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: {
                        studioBridge.showFileInFolder(studioBridge.lastOutputFile)
                        completionPopup.close()
                    }
                }

                PillButton {
                    height: 36
                    text: "Cerrar"
                    primaryStyle: false
                    solidShadow: false
                    onClicked: completionPopup.close()
                }
            }
        }
    }
}
