# Mesa de Trabajo Floral — Editor de PDFs para Windows

Una aplicación de escritorio sencilla, rápida y **100% sin conexión a internet** para trabajar con tus documentos PDF e imágenes en Windows 10 y Windows 11.

Tus archivos **nunca se suben a ningún servidor** ni se modifican los originales: todo ocurre dentro de tu propia computadora.

<img width="899" height="638" alt="image" src="https://github.com/user-attachments/assets/4f72e043-529f-43aa-8959-5c52557dec00" />


---

## Descarga e instalación (sin conocimientos técnicos)

No necesitas instalar Python ni programas adicionales.

1. Entra a la página de descargas del proyecto:
   **[Ir a GitHub Releases (Descargar última versión)](https://github.com/SamuelGarduno/PDF_modifier/releases)**
2. En la versión más reciente, haz clic en el archivo descargable (`.zip` o `.exe`).
3. Si descargaste un archivo `.zip`, haz clic derecho sobre él y elige **"Extraer todo..."** en la carpeta que prefieras.
4. Abre la carpeta extraída y haz doble clic en **`MesaDeTrabajoFloral.exe`**.

### ¿Qué hago si Windows muestra *"Windows protegió su PC"*?

Al abrir el programa por primera vez, es normal que Windows muestre una ventana azul de SmartScreen diciendo *"Windows protegió su PC"*. Esto ocurre únicamente porque es una aplicación independiente que no cuenta con una firma comercial de pago, **no porque tenga virus ni peligro alguno**.

Para abrirla con seguridad:
1. Haz clic en **"Más información"** (texto subrayado debajo del aviso).
2. Presiona el botón **"Ejecutar de todas formas"** que aparecerá abajo.

A partir de ese momento, el programa abrirá directamente sin volver a preguntarte.

---

## Cómo usarla en 3 pasos (*"Suelta primero, elige después"*)

1. **Suelta tus archivos:** Arrastra tus documentos **PDF** o imágenes (**PNG, JPG, JPEG, WEBP**) a la mesa de trabajo, o haz clic en **"Seleccionar archivos..."**.
2. **Elige qué quieres hacer:** La aplicación detecta lo que soltaste y te sugiere automáticamente la herramienta ideal (por ejemplo, si sueltas varios PDFs te propondrá unirlos; si sueltas un solo PDF te mostrará todas las opciones).
3. **Elige dónde guardar y listo:** Por defecto se guarda en la misma carpeta del archivo original (puedes cambiarla en **"Guardar en:"** -> **"Elegir..."**). Presiona el botón principal de la esquina inferior derecha.

> **Garantía de seguridad:** La aplicación **nunca sobrescribe ni borra tus archivos originales**. Siempre crea un archivo nuevo añadiendo un sufijo automático seguro (por ejemplo `_comprimido`, `_unido`, `_firmado`).

---

## Herramientas incluidas


- **Unir PDF:** Junta varios documentos PDF en un solo archivo ordenado. Si mezclas PDFs con imágenes (`PNG`, `JPG`, `WEBP`), los integra todos en un único PDF.
- **Organizar Páginas:** Mira todas las hojas en miniatura para reordenarlas arrastrando, rotarlas 90°, duplicarlas o eliminar las que no necesites.
- **Dividir y Extraer:** Saca únicamente las páginas que te interesan indicando un rango sencillo (por ejemplo `1-5, 8`) o guarda cada hoja como un PDF separado.
- **Comprimir PDF:** Reduce el peso del archivo para enviarlo fácil por correo o WhatsApp, eligiendo entre tres niveles reales (*Extrema*, *Recomendada* y *Baja pérdida*) con estimación previa del ahorro. Si el archivo ya es muy ligero, te avisa sin dañarlo.
- **PDF a Imágenes:** Convierte cada página de un PDF en imágenes individuales en formato **PNG** o **JPG**.
- **Imágenes a PDF:** Transforma una o varias fotos e imágenes (`PNG`, `JPG`, `JPEG`, `WEBP`) en un solo documento PDF.
- **Marca de Agua:** Añade un texto personalizado (por ejemplo *"CONFIDENCIAL"*) ajustando transparencia, ángulo y posición en una cuadrícula de 9 zonas.
- **Visor y Firma:** Lee tu PDF con zoom, dibuja tu firma a mano alzada con tres grosores (*Fino*, *Medio*, *Grueso*), estampa sellos (*Aprobado*, *Confidencial*, *Revisado*) o coloca tu firma en imagen **PNG** transparente moviéndola y ajustando su tamaño sobre la hoja.

---

## Preguntas frecuentes (FAQ)

**¿Mis archivos se suben a internet?**
No. Todo el procesamiento se realiza localmente en tu computadora. Puedes usar la aplicación incluso sin conexión Wi-Fi.

**¿Se borra o modifica mi archivo original?**
Nunca. Cada operación genera un archivo nuevo con un nombre seguro en la carpeta de destino que elijas.

**¿Necesito instalar algo más para que funcione?**
No, si descargas el ejecutable desde [Releases](https://github.com/SamuelGarduno/PDF_modifier/releases) ya incluye todo lo necesario para funcionar en Windows 10 y Windows 11.

**¿Qué pasa si abro un PDF con contraseña?**
La aplicación te pedirá la clave en una ventana segura únicamente para poder leerlo y procesarlo en memoria durante tu sesión.

---

<details>
<summary><strong>Información para desarrolladores (ejecutar desde el código fuente)</strong></summary>

Requisitos: Python 3.14+ en Windows.

```bash
# 1. Clonar el repositorio
git clone https://github.com/SamuelGarduno/PDF_modifier.git
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
