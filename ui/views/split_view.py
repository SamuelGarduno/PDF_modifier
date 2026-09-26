from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QProgressBar, QMessageBox, QFileDialog
)
from pathlib import Path
from pypdf import PdfReader
from PySide6.QtCore import Qt, QObject, Signal, QThread
from ui.components.drop_zone import DropZone
from core.splitter import split_pdf_pages

class SplitWorker(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)
    
    def __init__(self, input_path: str, output_path: str, range_str: str):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.range_str = range_str
        
    def run(self):
        try:
            split_pdf_pages(
                self.input_path,
                self.output_path,
                self.range_str,
                progress_callback=self.progress.emit
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            

class SplitView(QWidget):
    def __init__(self):
        super().__init__()
        self.current_pdf_path = None
        self.total_pages = 0
        self.thread = None
        self.worker = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32,32,32,32)
        layout.setSpacing(16)
        
        title = QLabel("Herramienta: Dividir / Extraer páginas")
        title.setObjectName("ViewTitle")
        layout.addWidget(title)
        
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.on_file_loaded)
        layout.addWidget(self.drop_zone)
        
        self.info_card = QWidget()
        self.info_card.setObjectName("InfoCard")
        info_layout = QVBoxLayout(self.info_card)
        info_layout.setContentsMargins(16,12,16,12)
        
        self.lbl_file_name = QLabel("Ningún documento seleccionado")
        self.lbl_file_name.setObjectName("InfoCardPrimary")
        self.lbl_page_count = QLabel("Páginas disponibles: -")
        self.lbl_page_count.setObjectName("InfoCardSecondary")
        
        info_layout.addWidget(self.lbl_file_name)
        info_layout.addWidget(self.lbl_page_count)
        layout.addWidget(self.info_card)
        
        range_layout = QVBoxLayout()
        range_layout.setSpacing(6)
        
        lbl_range = QLabel("Rango de páginas a extraer (ej. 1-3,5,8):")
        lbl_range.setObjectName("FieldLabel")
        
        self.input_range = QLineEdit()
        self.input_range.setObjectName("RangeInput")
        self.input_range.setPlaceholderText("Ejemplo: 1-3,5,8-10")
        self.input_range.setEnabled(False)
        
        range_layout.addWidget(lbl_range)
        range_layout.addWidget(self.input_range)
        layout.addLayout(range_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("MergeProgressBar")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        
        controls_layout = QHBoxLayout()
        self.btn_extract = QPushButton("Extraer Páginas")
        self.btn_extract.setObjectName("PrimaryButton")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self.start_split_process)
        
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_extract)
        layout.addLayout(controls_layout)
        
    def on_file_loaded(self, paths):
        if not paths:
            return
        
        self.current_pdf_path = paths[0]
        try:
            reader = PdfReader(self.current_pdf_path)
            self.total_pages = len(reader.pages)
            
            self.lbl_file_name.setText(Path(self.current_pdf_path).name)
            self.lbl_page_count.setText(f"Páginas totales disponibles: {self.total_pages}")
            
            self.input_range.setEnabled(True)
            self.input_range.setText(f"1-{self.total_pages}")
            self.btn_extract.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Error al leer PDF", f"No se pudo analizar el atchivo: \n{e}")
            
    def start_split_process(self):
        range_text = self.input_range.text().strip()
        
        if not range_text:
            QMessageBox.warning(self, "Campo requerido", "Introduce el menos un rango válido")
            return
        save_path, _ =QFileDialog.getSaveFileName(
            self,"Guardar PDF extraido", "páginas_extraidas.pdf","Documentos PDF (*.pdf)"
        )
        if not save_path:
            return
        
        self.btn_extract.setEnabled(False)
        self.input_range.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        self.thread = QThread()
        self.worker = SplitWorker(self.current_pdf_path,save_path, range_text)
        self.worker.moveToThread(self.thread)
        
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.on_split_success)
        self.worker.error.connect(self.on_split_error)
        
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()
        
    def on_split_success(self):
        self.btn_extract.setEnabled(True)
        self.input_range.setEnabled(True)
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Proceso completado", "Las páginas seleccionadas fueron extraídas con éxito.")

    def on_split_error(self, message):
        self.btn_extract.setEnabled(True)
        self.input_range.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Error de extracción", f"Ocurrió un problema:\n{message}")