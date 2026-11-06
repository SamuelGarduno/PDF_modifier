pragma Singleton
import QtQuick

QtObject {
    id: themeRoot

    // Dimensiones de ventana
    readonly property int initialWidth: 1280
    readonly property int initialHeight: 720
    readonly property int minWindowWidth: 960
    readonly property int minWindowHeight: 600

    // Paleta Principal "Floral Stationery & Coquette"
    readonly property string surfaceLight: "#FBF0F0"
    readonly property string backgroundDark: "#1E0F16"
    readonly property string wineDarkCard: "#1E0F16"
    readonly property string primary: "#DF8293"
    readonly property string primaryRose: "#DF8293"
    readonly property string secondary: "#681D3A"
    readonly property string secondaryWine: "#681D3A"
    readonly property string accent: "#F8B8B0"
    readonly property string accentPeach: "#F8B8B0"
    readonly property string wineDeep: "#521928"
    readonly property string stationeryFrameBg: "#FBF4F0"
    readonly property string queueCardBg: "#FFFDFB"
    readonly property string surfaceCard: "#FFFDFB"
    readonly property string surfaceCardHover: "#FAF0EE"

    // Textos
    readonly property string textPrimary: "#2D1018"
    readonly property string textSecondary: "#681D3A"
    readonly property string textMuted: "#8C465A"
    readonly property string creamText: "#FFFDFB"
    readonly property string textCream: "#FFFDFB"
    readonly property string creamSubtle: "#F2DCE0"
    readonly property string textCreamMuted: "#F2DCE0"
    readonly property string mutedText: "#6E3546"

    // Estados de Alerta / Error y Foco
    readonly property string errorText: "#9E1B32"
    readonly property string errorBg: "#FDF0F2"
    readonly property string errorBorder: "#C84B62"
    readonly property string focusRing: "#681D3A"
    readonly property string focusRingColor: "#681D3A"

    // Familias Tipográficas
    readonly property string serifFont: "Georgia"
    readonly property string sansFont: "Segoe UI"
    readonly property string scriptFont: "Georgia"

    // Colores por familia de herramienta (base + fondo suave al ~25% + trazo oscuro)
    readonly property string colorMerge: "#D98891"
    readonly property string colorOrganizeSplit: "#8FA88A"
    readonly property string colorCompress: "#E8A988"
    readonly property string colorSecurity: "#A99BC4"
    readonly property string toolProtectAccent: "#A99BC4"
    readonly property string colorImages: "#8DA5BC"
    readonly property string colorWatermarkSign: "#7A2840"

    // Bordes (jerarquía de 2 pesos: 1.5px vino pleno vs 1px al ~38% de opacidad)
    readonly property real borderStrongWidth: 1.5
    readonly property real borderSubtleWidth: 1.0
    readonly property color borderStrongColor: "#681D3A"
    readonly property color borderSubtleColor: Qt.rgba(0.408, 0.114, 0.227, 0.38)

    // Radios, miniaturas y espaciados
    readonly property int outerMargin: 24
    readonly property int cardSpacing: 12
    readonly property int sectionSpacing: 16
    readonly property int queueCardRadius: 12
    readonly property int primarySuggestionRadius: 20
    readonly property int primaryCardRadius: 20
    readonly property int chipRadius: 18
    readonly property int actionBarHeight: 64
    readonly property int minTouchTarget: 32
    readonly property int thumbnailWidth: 56
    readonly property int thumbnailHeight: 72

    // Escala tipográfica en 3 niveles
    readonly property int fontWindowTitle: 22
    readonly property int fontWindowTitleSize: 22
    readonly property int fontHeroTitle: 20
    readonly property int fontCardTitleSize: 20
    readonly property int fontSectionHeader: 14
    readonly property int fontBody: 14
    readonly property int fontBodySize: 14
    readonly property int fontMetaItalic: 12
    readonly property int fontMetaSize: 12
    readonly property real metaOpacity: 0.68

    // Duraciones de animación (120-200 ms)
    readonly property int animFastMs: 140
    readonly property int animFast: 140
    readonly property int animNormalMs: 180
    readonly property int animNormal: 180

    function toolAccentColor(toolId) {
        switch (toolId) {
        case "merge":
            return colorMerge
        case "split":
        case "organize":
            return colorOrganizeSplit
        case "compress":
            return colorCompress
        case "protect":
        case "unlock":
            return colorSecurity
        case "pdf_to_images":
        case "images_to_pdf":
            return colorImages
        case "watermark":
        case "sign":
            return colorWatermarkSign
        default:
            return primary
        }
    }

    function toolSoftBgColor(toolId) {
        switch (toolId) {
        case "merge":
            return "#F6DFE2"
        case "split":
        case "organize":
            return "#E3ECE1"
        case "compress":
            return "#F9E7DD"
        case "protect":
        case "unlock":
            return "#EAE5F3"
        case "pdf_to_images":
        case "images_to_pdf":
            return "#E1E9F0"
        case "watermark":
        case "sign":
            return "#EED9DF"
        default:
            return "#F6DFE2"
        }
    }

    function toolIconDarkColor(toolId) {
        switch (toolId) {
        case "merge":
            return "#5C222B"
        case "split":
        case "organize":
            return "#2B4429"
        case "compress":
            return "#6B361C"
        case "protect":
        case "unlock":
            return "#392C54"
        case "pdf_to_images":
        case "images_to_pdf":
            return "#264159"
        case "watermark":
        case "sign":
            return "#4A1223"
        default:
            return "#521928"
        }
    }

    function toolIconSource(toolId) {
        switch (toolId) {
        case "merge":
            return "../../assets/icons/tool_merge.svg"
        case "split":
            return "../../assets/icons/tool_split.svg"
        case "organize":
            return "../../assets/icons/tool_organize.svg"
        case "compress":
            return "../../assets/icons/tool_compress.svg"
        case "protect":
            return "../../assets/icons/tool_protect.svg"
        case "unlock":
            return "../../assets/icons/tool_unlock.svg"
        case "pdf_to_images":
            return "../../assets/icons/tool_pdf_to_images.svg"
        case "images_to_pdf":
            return "../../assets/icons/tool_images_to_pdf.svg"
        case "watermark":
            return "../../assets/icons/tool_watermark.svg"
        case "sign":
            return "../../assets/icons/tool_sign.svg"
        default:
            return "../../assets/icons/tool_organize.svg"
        }
    }
}
