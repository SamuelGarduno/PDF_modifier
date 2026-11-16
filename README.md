<div align="center">

# Mesa de Trabajo Floral

**Herramientas de PDF e imágenes para Windows — Sencilla, ligera y 100% sin conexión**

![Plataforma](https://img.shields.io/badge/Plataforma-Windows%2010%20%7C%2011-D47A8C?style=for-the-badge)
![Privacidad](https://img.shields.io/badge/Privacidad-100%25%20Sin%20Internet-8FA893?style=for-the-badge)
![Licencia](https://img.shields.io/badge/Licencia-GPLv3-B5838D?style=for-the-badge)

Tus archivos **nunca se suben a ningún servidor** ni se modifican los originales: todo ocurre de forma privada dentro de tu propia computadora.

<br>

[![Descargar última versión](https://img.shields.io/badge/Descargar_para_Windows-GitHub_Releases-C95D76?style=for-the-badge)](https://github.com/SamuelGarduno/PDF_modifier/releases)

<br>

<img width="860" alt="Vista principal de Mesa de Trabajo Floral" src="https://github.com/user-attachments/assets/4f72e043-529f-43aa-8959-5c52557dec00" />

</div>

---

## Cómo usarla en 3 pasos (*"Suelta primero, elige después"*)

| Paso 1. Suelta tus archivos | Paso 2. Elige la herramienta | Paso 3. Guarda con seguridad |
| :--- | :--- | :--- |
| Arrastra tus documentos **PDF** o imágenes (**PNG, JPG, JPEG, WEBP**) a la mesa de trabajo, o pulsa **"Seleccionar archivos..."**. | La aplicación detecta lo que soltaste y te sugiere automáticamente la acción ideal según el tipo y cantidad de archivos. | Por defecto se guarda en la misma carpeta del original (puedes cambiarla en **"Guardar en:"**). Pulsa el botón principal para procesar. |

> [!IMPORTANT]
> **Garantía de seguridad:** La aplicación **nunca sobrescribe ni borra tus archivos originales**. Siempre crea un archivo nuevo añadiendo un sufijo automático seguro (por ejemplo `_comprimido`, `_unido` o `_firmado`).

---

## Herramientas incluidas

### Organización y estructura

| Herramienta | Qué puedes hacer |
| :--- | :--- |
| **Unir PDF** | Junta varios documentos PDF en un solo archivo ordenado. Si mezclas PDFs con imágenes (`PNG`, `JPG`, `WEBP`), los integra todos en un único PDF. |
| **Organizar Páginas** | Visualiza todas las hojas en miniatura para reordenarlas arrastrando, rotarlas 90°, duplicarlas o eliminar las que no necesites. |
| **Dividir y Extraer** | Extrae únicamente las páginas que te interesan indicando un rango sencillo (por ejemplo `1-5, 8`) o guarda cada hoja como un PDF independiente. |

### Optimización y conversión

| Herramienta | Qué puedes hacer |
| :--- | :--- |
| **Comprimir PDF** | Reduce el peso del archivo para enviarlo fácil por correo o WhatsApp, eligiendo entre tres niveles reales (*Extrema*, *Recomendada* y *Baja pérdida*) con estimación previa del ahorro. Si ya es muy ligero, te avisa sin dañarlo. |
| **PDF a Imágenes** | Convierte cada página de un documento PDF en imágenes individuales en formato **PNG** o **JPG**. |
| **Imágenes a PDF** | Transforma una o varias fotos e imágenes (`PNG`, `JPG`, `JPEG`, `WEBP`) en un solo documento PDF. |

### Edición, marcas y firmas

| Herramienta | Qué puedes hacer |
| :--- | :--- |
| **Marca de Agua** | Añade un texto personalizado (por ejemplo *"CONFIDENCIAL"*) ajustando transparencia, ángulo y ubicación en una cuadrícula de 9 zonas. |
| **Visor y Firma** | Lee tu PDF con zoom, dibuja tu firma a mano alzada en tres grosores (*Fino*, *Medio*, *Grueso*), estampa sellos (*Aprobado*, *Confidencial*, *Revisado*) o coloca tu firma en imagen **PNG** transparente ajustando su posición y tamaño sobre la hoja. |

---

## Descarga e instalación (sin conocimientos técnicos)

No necesitas instalar Python ni programas adicionales:

1. Entra a la página de descargas del proyecto: **[GitHub Releases — Última versión](https://github.com/SamuelGarduno/PDF_modifier/releases)**.
2. Haz clic en el archivo descargable de la versión más reciente (`.zip` o `.exe`).
3. Si descargaste un `.zip`, haz clic derecho sobre él y elige **"Extraer todo..."** en la carpeta que prefieras.
4. Abre la carpeta extraída y haz doble clic en **`MesaDeTrabajoFloral.exe`**.

> [!TIP]
> **¿Qué hago si Windows muestra *"Windows protegió su PC"*?**
>
> Al abrir el programa por primera vez, es normal que aparezca una ventana azul de SmartScreen. Esto ocurre únicamente porque es una aplicación independiente sin firma comercial de pago, **no porque contenga virus ni riesgo alguno**.
>
> 1. Haz clic en **"Más información"** (texto subrayado debajo del aviso).
> 2. Presiona el botón **"Ejecutar de todas formas"** que aparecerá abajo.
>
> A partir de ese momento, abrirá directamente sin volver a preguntar.

---

## Preguntas frecuentes (FAQ)

**¿Mis archivos se suben a internet?**
No. Todo el procesamiento se realiza de forma local en tu computadora. Puedes usar la aplicación incluso sin conexión Wi-Fi.

**¿Se borra o modifica mi archivo original?**
Nunca. Cada operación genera un archivo nuevo con un nombre seguro en la carpeta de destino que elijas.

**¿Necesito instalar algo más para que funcione?**
No. Al descargar el programa desde [Releases](https://github.com/SamuelGarduno/PDF_modifier/releases) ya incluye todo lo necesario para funcionar en Windows 10 y Windows 11.

**¿Qué pasa si abro un PDF protegido con contraseña?**
La aplicación te pedirá la clave en una ventana segura únicamente para poder leerlo y procesarlo en memoria durante tu sesión.

---

<details>
<summary><strong>Información para desarrolladores (ejecutar desde el código fuente)</strong></summary>

<br>

**Requisitos:** Python 3.14+ en Windows.

```bash
# 1. Clonar el repositorio
git clone [https://github.com/SamuelGarduno/PDF_modifier.git](https://github.com/SamuelGarduno/PDF_modifier.git)
cd PDF_modifier

# 2. Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar la aplicación
python main.py
```

Para ejecutar la suite de pruebas automatizadas:

```bash
pytest -q
```

</details>

---

<div align="center">

**Mesa de Trabajo Floral** — Copyright (C) 2026 **Samuel Garduño Gamboa**

</div>