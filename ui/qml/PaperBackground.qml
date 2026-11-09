import QtQuick
import "."

Item {
    id: paperBgRoot
    objectName: "paperBackground"

    property color baseColor: Theme.surfaceLight
    property color lineColor: Theme.paperLineColor
    property color marginLineColor: Theme.paperMarginLineColor
    property int lineSpacing: Theme.paperLineSpacing
    property int marginX: Theme.paperMarginLeft
    property bool showMarginLine: true

    Rectangle {
        id: bgFill
        anchors.fill: parent
        color: paperBgRoot.baseColor
    }

    Canvas {
        id: paperLinesCanvas
        objectName: "paperLinesCanvas"
        anchors.fill: parent

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            // 1. Renglones horizontales cada ~28 px en color vino/rosa con baja opacidad (~7%)
            ctx.strokeStyle = paperBgRoot.lineColor
            ctx.lineWidth = 1.0
            var spacing = Math.max(16, paperBgRoot.lineSpacing)
            for (var lineY = 56; lineY < height; lineY += spacing) {
                ctx.beginPath()
                ctx.moveTo(0, lineY)
                ctx.lineTo(width, lineY)
                ctx.stroke()
            }

            // 2. Línea vertical de margen izquierda tenue estilo cuaderno
            if (paperBgRoot.showMarginLine && paperBgRoot.marginX > 0 && paperBgRoot.marginX < width) {
                ctx.strokeStyle = paperBgRoot.marginLineColor
                ctx.lineWidth = 1.0
                ctx.beginPath()
                ctx.moveTo(paperBgRoot.marginX, 0)
                ctx.lineTo(paperBgRoot.marginX, height)
                ctx.stroke()
            }
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
}
