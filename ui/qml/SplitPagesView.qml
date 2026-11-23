import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: splitPagesRoot
    objectName: "splitPagesView"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "Dividir y Extraer (" + studioBridge.primaryDocumentPageCount + " páginas) — Seleccionadas: " + studioBridge.splitSelectedCount
                font.family: themePalette.serifFont
                font.pixelSize: 14
                font.bold: true
                color: themePalette.backgroundDark
                elide: Text.ElideRight
            }

            PillButton {
                id: selectAllSplitPagesBtn
                objectName: "selectAllSplitPagesBtn"
                height: 30
                minWidth: 0
                horizontalPadding: 12
                fontPixelSize: 12
                text: "Seleccionar todas"
                primaryStyle: false
                solidShadow: false
                enabledButton: studioBridge.primaryDocumentPageCount > 0
                onClicked: studioBridge.selectAllSplitPages()
            }

            PillButton {
                id: clearSplitSelectionBtn
                objectName: "clearSplitSelectionBtn"
                height: 30
                minWidth: 0
                horizontalPadding: 12
                fontPixelSize: 12
                text: "Limpiar selección"
                primaryStyle: false
                solidShadow: false
                enabledButton: studioBridge.splitSelectedCount > 0
                onClicked: studioBridge.clearSplitSelection()
            }
        }

        GridView {
            id: splitGrid
            objectName: "splitPagesGridView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            cellWidth: 156
            cellHeight: 194
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 320
            model: studioBridge.splitPages

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 8
            }

            delegate: Item {
                id: splitDelegateItem
                objectName: "splitPageDelegate_" + modelData.pageIndex
                width: 144
                height: 182
                property bool cardHovered: splitHover.hovered

                Rectangle {
                    anchors.fill: splitPageCard
                    anchors.topMargin: 3
                    anchors.leftMargin: 2
                    radius: 8
                    color: "#1B681D3A"
                }

                Rectangle {
                    id: splitPageCard
                    objectName: "splitPageCard_" + modelData.pageIndex
                    anchors.fill: parent
                    radius: 8
                    color: modelData.selected ? themePalette.accent : themePalette.surfaceLight
                    border.width: modelData.selected ? 2.2 : 1.2
                    border.color: modelData.selected ? themePalette.secondary : Theme.borderSubtleColor

                    transform: Translate {
                        y: splitDelegateItem.cardHovered ? -2 : 0
                    }

                    Behavior on color {
                        ColorAnimation { duration: 140 }
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 4

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 5
                            color: "#FFFFFF"
                            border.width: 1
                            border.color: "#E8C7CA"
                            clip: true

                            Image {
                                anchors.fill: parent
                                anchors.margins: 3
                                source: modelData.thumbnailUrl
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                cache: true
                                smooth: true
                            }

                            Rectangle {
                                visible: Boolean(modelData.selected)
                                objectName: "splitPageCheck_" + modelData.pageIndex
                                width: 22
                                height: 22
                                radius: 11
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: 5
                                color: themePalette.secondary
                                border.width: 1
                                border.color: themePalette.surfaceLight

                                Text {
                                    anchors.centerIn: parent
                                    text: "✓"
                                    font.family: themePalette.sansFont
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: themePalette.surfaceLight
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 20

                            Text {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: "Pág. " + modelData.pageNumber
                                font.family: themePalette.sansFont
                                font.pixelSize: 12
                                font.bold: Boolean(modelData.selected)
                                color: modelData.selected ? themePalette.secondary : themePalette.backgroundDark
                            }
                        }
                    }

                    HoverHandler {
                        id: splitHover
                        cursorShape: Qt.PointingHandCursor
                    }

                    TapHandler {
                        onTapped: studioBridge.toggleSplitPage(modelData.pageIndex)
                    }
                }
            }
        }
    }
}
