import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

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
            spacing: 12

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
                height: 30
                text: "Rotar Seleccionadas 90°"
                primaryStyle: false
                onClicked: studioBridge.rotateSelectedPages()
            }

            PillButton {
                height: 30
                text: "Eliminar Seleccionadas"
                primaryStyle: false
                onClicked: studioBridge.deleteSelectedPages()
            }
        }

        // Cuadrícula interactiva de miniaturas con Drag & Drop real y etiquetas correlativas
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
            cacheBuffer: 600
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
                    y: delegateItem.cardHovered && !dragArea.drag.active ? -2 : 0
                    radius: 8
                    color: delegateItem.isDropTarget
                           ? themePalette.primary
                           : (modelData.selected ? themePalette.accent : themePalette.surfaceLight)
                    border.width: (modelData.selected || delegateItem.isDropTarget) ? 2.2 : 1.2
                    border.color: themePalette.secondary

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

                    // Área de selección y arrastre (debajo de los botones de acción rápida)
                    MouseArea {
                        id: dragArea
                        anchors.fill: parent
                        anchors.topMargin: 32
                        acceptedButtons: Qt.LeftButton
                        drag.target: pageCard
                        drag.axis: Drag.XAndYAxis
                        cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor

                        onPressed: function(mouse) {
                            organizerRoot.draggedPageIndex = index
                            organizerRoot.dropTargetIndex = index
                            var ctrl = (mouse.modifiers & Qt.ControlModifier) !== 0
                            var shift = (mouse.modifiers & Qt.ShiftModifier) !== 0
                            studioBridge.selectOrganizerPage(index, ctrl, shift)
                        }

                        onPositionChanged: function(mouse) {
                            if (drag.active) {
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
                            var fromIdx = organizerRoot.draggedPageIndex
                            var targetIdx = organizerRoot.dropTargetIndex

                            if (targetIdx < 0 || targetIdx === fromIdx) {
                                var ptInGrid = delegateItem.mapToItem(
                                    pagesGrid.contentItem,
                                    pageCard.x + pageCard.width / 2,
                                    pageCard.y + pageCard.height / 2
                                )
                                var resolvedIdx = pagesGrid.indexAt(ptInGrid.x, ptInGrid.y)
                                if (resolvedIdx >= 0) {
                                    targetIdx = resolvedIdx
                                }
                            }

                            pageCard.Drag.drop()
                            pageCard.x = 0
                            pageCard.y = 0
                            organizerRoot.isDraggingCard = false
                            organizerRoot.draggedPageIndex = -1
                            organizerRoot.dropTargetIndex = -1

                            if (fromIdx >= 0 && targetIdx >= 0 && fromIdx !== targetIdx) {
                                studioBridge.move_page(fromIdx, targetIdx)
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
                        opacity: delegateItem.cardHovered || modelData.selected ? 1.0 : 0.85

                        Rectangle {
                            width: 24; height: 24; radius: 12
                            color: themePalette.primary
                            border.width: 1; border.color: themePalette.secondary
                            Text { anchors.centerIn: parent; text: "↻"; font.pixelSize: 12; font.bold: true; color: themePalette.backgroundDark }
                            TapHandler { onTapped: studioBridge.rotatePageAt(index) }
                        }

                        Rectangle {
                            width: 24; height: 24; radius: 12
                            color: themePalette.accent
                            border.width: 1; border.color: themePalette.secondary
                            Text { anchors.centerIn: parent; text: "+"; font.pixelSize: 13; font.bold: true; color: themePalette.backgroundDark }
                            TapHandler { onTapped: studioBridge.duplicatePageAt(index) }
                        }

                        Rectangle {
                            width: 24; height: 24; radius: 12
                            color: themePalette.secondary
                            border.width: 1; border.color: themePalette.surfaceLight
                            Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: 11; font.bold: true; color: themePalette.surfaceLight }
                            TapHandler { onTapped: studioBridge.deletePageAt(index) }
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
