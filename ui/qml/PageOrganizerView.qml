import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: organizerRoot
    objectName: "pageOrganizerView"
    property int draggedPageIndex: -1
    property int dropTargetIndex: -1
    property bool isDraggingCard: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        // Barra superior de acciones de organización por lote
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "Organizador de Pliegos (" + studioBridge.organizerPageCount + " páginas) — Arrastra para reordenar o usa Ctrl/Shift + clic"
                font.family: themePalette.serifFont
                font.pixelSize: 14
                font.bold: true
                color: themePalette.backgroundDark
                elide: Text.ElideRight
            }

            PillButton {
                id: restoreOrganizerOriginalBtn
                objectName: "restoreOrganizerOriginalBtn"
                height: 30
                minWidth: 0
                horizontalPadding: 12
                fontPixelSize: 12
                text: "Restaurar original"
                primaryStyle: false
                solidShadow: false
                enabledButton: studioBridge.hasOrganizerChanges
                disabledHint: "Las páginas ya están en su estado original"
                onClicked: studioBridge.restoreOrganizerOriginal()
            }

            PillButton {
                height: 30
                minWidth: 0
                horizontalPadding: 12
                fontPixelSize: 12
                text: "Rotar Seleccionadas 90°"
                primaryStyle: false
                solidShadow: false
                onClicked: studioBridge.rotateSelectedPages()
            }

            PillButton {
                height: 30
                minWidth: 0
                horizontalPadding: 12
                fontPixelSize: 12
                text: "Eliminar Seleccionadas"
                primaryStyle: false
                solidShadow: false
                onClicked: studioBridge.deleteSelectedPages()
            }
        }

        // Cuadrícula interactiva de miniaturas con Drag & Drop directo sin selección previa
        GridView {
            id: pagesGrid
            objectName: "organizerGridView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            cellWidth: 166
            cellHeight: 202
            clip: true
            interactive: !organizerRoot.isDraggingCard
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 320
            model: studioBridge.organizerPages

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 8
            }

            delegate: Item {
                id: delegateItem
                objectName: "organizerPageDelegate_" + index
                width: 154
                height: 192
                z: dragArea.drag.active ? 100 : 1
                property int delegateIndex: index
                property bool cardHovered: cardHoverHandler.hovered
                property bool isDropTarget: organizerRoot.isDraggingCard && organizerRoot.dropTargetIndex === index && organizerRoot.draggedPageIndex !== index

                // Zona receptora de Drop para reordenamiento entre tarjetas
                DropArea {
                    id: cardDropArea
                    anchors.fill: parent
                    keys: ["organizerPageCard"]
                    onEntered: function(drag) {
                        organizerRoot.dropTargetIndex = index
                    }
                    onExited: {
                        if (organizerRoot.dropTargetIndex === index) {
                            organizerRoot.dropTargetIndex = -1
                        }
                    }
                    onDropped: function(drop) {
                        var fromIdx = organizerRoot.draggedPageIndex
                        if (fromIdx >= 0 && fromIdx !== index) {
                            organizerRoot.draggedPageIndex = -1
                            organizerRoot.dropTargetIndex = -1
                            organizerRoot.isDraggingCard = false
                            studioBridge.move_page(fromIdx, index)
                        }
                    }
                }

                // Sombra suave equivalente a 0 4px 10px rgba(104, 29, 58, 0.12)
                Rectangle {
                    anchors.fill: pageCard
                    anchors.topMargin: 4
                    anchors.leftMargin: 2
                    radius: 8
                    color: "#1F681D3A"
                }

                Rectangle {
                    id: pageCard
                    width: delegateItem.width
                    height: delegateItem.height
                    x: 0
                    y: 0
                    radius: 8
                    color: delegateItem.isDropTarget
                           ? themePalette.primary
                           : (modelData.selected ? themePalette.accent : themePalette.surfaceLight)
                    border.width: (modelData.selected || delegateItem.isDropTarget) ? 2.2 : 1.2
                    border.color: themePalette.secondary

                    transform: Translate {
                        y: delegateItem.cardHovered && !dragArea.drag.active ? -2 : 0
                    }

                    Drag.active: dragArea.drag.active
                    Drag.source: delegateItem
                    Drag.hotSpot.x: width / 2
                    Drag.hotSpot.y: height / 2
                    Drag.keys: ["organizerPageCard"]

                    Behavior on color {
                        ColorAnimation { duration: 150 }
                    }

                    // Miniatura PDF renderizada con DPI controlado
                    Rectangle {
                        anchors.top: parent.top
                        anchors.topMargin: 8
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 124
                        height: 144
                        color: "#FFFFFF"
                        border.width: 1
                        border.color: "#E3C8CE"
                        clip: true

                        Image {
                            id: thumbImg
                            anchors.centerIn: parent
                            width: parent.width - 6
                            height: parent.height - 6
                            sourceSize.width: 124 * 2
                            sourceSize.height: 144 * 2
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            cache: true
                            source: modelData.thumbnailUrl
                            rotation: modelData.rotation
                        }
                    }

                    // Etiqueta inferior correlativa ("Pág. X") siempre visible sin recortes
                    Rectangle {
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: parent.width - 14
                        height: 24
                        radius: 6
                        color: modelData.selected ? themePalette.surfaceLight : "#F5E1E4"
                        border.width: 1
                        border.color: themePalette.secondary

                        Text {
                            id: pageNumberLabel
                            objectName: "pageNumberLabel_" + index
                            anchors.centerIn: parent
                            text: "Pág. " + (index + 1) + (modelData.rotation > 0 ? " (" + modelData.rotation + "°)" : "")
                            font.family: themePalette.sansFont
                            font.pixelSize: 12
                            font.bold: true
                            color: themePalette.backgroundDark
                        }
                    }

                    // Área de arrastre directo (umbral ~5 px) y selección al soltar clic sin arrastre
                    MouseArea {
                        id: dragArea
                        objectName: "organizerCardDragArea_" + index
                        z: 5
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        preventStealing: true
                        drag.target: pageCard
                        drag.axis: Drag.XAndYAxis
                        drag.threshold: Theme.organizerDragThresholdPx
                        cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor

                        property real pressStartX: 0
                        property real pressStartY: 0
                        property int pressModifiers: 0
                        property bool movedBeyondThreshold: false

                        onPressed: function(mouse) {
                            pressStartX = mouse.x
                            pressStartY = mouse.y
                            pressModifiers = mouse.modifiers
                            movedBeyondThreshold = false
                            organizerRoot.draggedPageIndex = index
                            organizerRoot.dropTargetIndex = index
                        }

                        onPositionChanged: function(mouse) {
                            var dist = Math.hypot(mouse.x - pressStartX, mouse.y - pressStartY)
                            if (drag.active || dist >= Theme.organizerDragThresholdPx) {
                                movedBeyondThreshold = true
                                organizerRoot.isDraggingCard = true
                                var ptInGrid = delegateItem.mapToItem(
                                    pagesGrid.contentItem,
                                    pageCard.x + pageCard.width / 2,
                                    pageCard.y + pageCard.height / 2
                                )
                                var hoveredIdx = pagesGrid.indexAt(ptInGrid.x, ptInGrid.y)
                                if (hoveredIdx >= 0) {
                                    organizerRoot.dropTargetIndex = hoveredIdx
                                }
                            }
                        }

                        onReleased: function(mouse) {
                            var root = organizerRoot
                            var bridge = studioBridge
                            var card = pageCard
                            var myIdx = index
                            var fromIdx = root.draggedPageIndex
                            var targetIdx = root.dropTargetIndex
                            var wasDragged = movedBeyondThreshold || drag.active
                            var mods = pressModifiers

                            if (wasDragged && (targetIdx < 0 || targetIdx === fromIdx)) {
                                var ptInGrid = delegateItem.mapToItem(
                                    pagesGrid.contentItem,
                                    card.x + card.width / 2,
                                    card.y + card.height / 2
                                )
                                var resolvedIdx = pagesGrid.indexAt(ptInGrid.x, ptInGrid.y)
                                if (resolvedIdx >= 0) {
                                    targetIdx = resolvedIdx
                                }
                            }

                            card.Drag.drop()
                            var handledByDrop = (root.draggedPageIndex < 0)
                            if (card) {
                                card.x = 0
                                card.y = 0
                            }
                            root.isDraggingCard = false
                            root.draggedPageIndex = -1
                            root.dropTargetIndex = -1

                            if (!handledByDrop && fromIdx >= 0 && targetIdx >= 0 && fromIdx !== targetIdx) {
                                bridge.move_page(fromIdx, targetIdx)
                            } else if (!wasDragged && !handledByDrop) {
                                var ctrl = (mods & Qt.ControlModifier) !== 0
                                var shift = (mods & Qt.ShiftModifier) !== 0
                                bridge.selectOrganizerPage(myIdx, ctrl, shift)
                            }
                        }

                        onCanceled: {
                            pageCard.x = 0
                            pageCard.y = 0
                            organizerRoot.isDraggingCard = false
                            organizerRoot.draggedPageIndex = -1
                            organizerRoot.dropTargetIndex = -1
                        }
                    }

                    // Botones flotantes por tarjeta para rotar 90°, duplicar o eliminar página
                    Row {
                        z: 10
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: 6
                        spacing: 4
                        opacity: delegateItem.cardHovered || modelData.selected ? 1.0 : 0.92

                        Rectangle {
                            id: rotateBtn
                            objectName: "rotatePageBtn_" + index
                            width: 26; height: 26; radius: 13
                            color: rotArea.containsMouse ? "#E897A6" : Theme.primaryRose
                            border.width: 1.2; border.color: Theme.secondaryWine

                            Text {
                                anchors.centerIn: parent
                                text: "↻"
                                font.pixelSize: 12
                                font.bold: true
                                color: Theme.backgroundDark
                            }

                            MouseArea {
                                id: rotArea
                                anchors.fill: parent
                                hoverEnabled: true
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: studioBridge.rotatePageAt(index)
                            }

                            ToolTip.visible: rotArea.containsMouse
                            ToolTip.delay: 250
                            ToolTip.text: "Rotar página 90°"
                        }

                        Rectangle {
                            id: duplicateBtn
                            objectName: "duplicatePageBtn_" + index
                            width: 28; height: 26; radius: 13
                            color: dupArea.pressed
                                   ? "#EED3D0"
                                   : (dupArea.containsMouse ? Theme.accentPeach : Theme.surfaceCard)
                            border.width: 1.4
                            border.color: Theme.secondaryWine

                            Image {
                                id: duplicateIconImg
                                objectName: "duplicatePageIcon_" + index
                                anchors.centerIn: parent
                                width: 17
                                height: 17
                                sourceSize.width: 34
                                sourceSize.height: 34
                                source: "../../assets/icons/page_duplicate.svg"
                                fillMode: Image.PreserveAspectFit
                                cache: true
                                smooth: true
                            }

                            MouseArea {
                                id: dupArea
                                anchors.fill: parent
                                hoverEnabled: true
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: studioBridge.duplicatePageAt(index)
                            }

                            ToolTip.visible: dupArea.containsMouse
                            ToolTip.delay: 200
                            ToolTip.text: "Duplicar página"
                        }

                        Rectangle {
                            id: deleteBtn
                            objectName: "deletePageBtn_" + index
                            width: 26; height: 26; radius: 13
                            color: delArea.containsMouse ? "#4A1223" : Theme.secondaryWine
                            border.width: 1.2; border.color: Theme.surfaceLight

                            Text {
                                anchors.centerIn: parent
                                text: "✕"
                                font.pixelSize: 11
                                font.bold: true
                                color: Theme.surfaceLight
                            }

                            MouseArea {
                                id: delArea
                                anchors.fill: parent
                                hoverEnabled: true
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: studioBridge.deletePageAt(index)
                            }

                            ToolTip.visible: delArea.containsMouse
                            ToolTip.delay: 250
                            ToolTip.text: "Eliminar página"
                        }
                    }
                }

                HoverHandler {
                    id: cardHoverHandler
                }
            }
        }
    }
}
