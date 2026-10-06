from pathlib import Path
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QProgressBar, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QObject, Signal, QThread
from ui.components.drop_zone import DropZone
from core.compressor import compress_pdf_file, format_size

class CompressWorker(QObject):
    finished = Signal(int, int, float)
    error = Signal(str)
    progress = Signal(int)
    
    def __init__(self, input_path: str, output_path: str):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        
    def run(self):
        try:
            init_s, fin_s, pct = compress_pdf_file(
                self.input_path,
                self.output_path,
                progress_callback=self.progress.emit
            )
            self.finished.emit(init_s, fin_s, pct)
        except Exception as e:
            self.error.emit(str(e))
            
class CompressView(QWidget):
    def __init__(self):
        super().__init__()
        self.current_pdf_path = None
        self.thread = None
        self.worker = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32,32,32,32)
        layout.setSpacing(16)
        
        title = QLabel("Comprimir Documento PDF")
        title.setObjectName("ViewTitle")
        layout.addWidget(title)
        
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.on_file_loaded)
        layout.addWidget(self.drop_zone)
        
        self.stats_card = QWidget()
        self.stats_card.setObjectName("InfoCard")
        stats_layout = QVBoxLayout(self.stats_card)
        stats_layout.setContentsMargins(16,12,16,12)
        stats_layout.setSpacing(4)
        
        self.lbl_file_name = QLabel("Ningún archivo seleccionado")
        self.lbl_file_name.setObjectName("InfoCardPrimary")
        self.lbl_original_size = QLabel("Tamaño actual: -")
        self.lbl_original_size.setObjectName("InfoCardSecondary")
        self.lbl_result_stat = QLabel("Reducción estimada: Pendiente de compresión")
        self.lbl_result_stat.setObjectName("StatsSuccess")
        
        stats_layout.addWidget(self.lbl_file_name)
        stats_layout.addWidget(self.lbl_original_size)
        stats_layout.addWidget(self.lbl_result_stat)
        layout.addWidget(self.stats_card)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("MergeProgressBar")
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        
        controls_layout = QHBoxLayout()
        self.btn_compress = QPushButton("Comprimir PDF")
        self.btn_compress.setObjectName("PrimaryButton")
        self.btn_compress.setEnabled(False)
        self.btn_compress.clicked.connect(self.start_compress_process)
        
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_compress)
        layout.addLayout(controls_layout)
        
    def on_file_loaded(self, paths):
        if not paths:
            return
        self.current_pdf_path = paths[0]
        size = os.path.getsize(self.current_pdf_path)
        
        self.lbl_file_name.setText(Path(self.current_pdf_path).name)
        self.lbl_original_size.setText(f"Tamaño original: {format_size(size)}")
        self.lbl_result_stat.setText("Listo para optimizar")
        self.btn_compress.setEnabled(True)
        
    def start_compress_process(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF comprimido", "documento_comprimido.pdf", "Archivos PDF (*.pdf)"
        )
        if not save_path:
            return
        
        self.btn_compress.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        self.thread = QThread()
        self.worker = CompressWorker(self.current_pdf_path, save_path)
        self.worker.moveToThread(self.thread)
        
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.on_compress_success)
        self.worker.error.connect(self.on_compress_error)
        
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()
        
    def on_compress_success(self, init_size, final_size, saving_pct):
        self.btn_compress.setEnabled(True)
        self.progress_bar.setValue(100)
        
        diff = init_size - final_size
        if diff > 0:
            msg = f"Reducido en un {saving_pct:.1f}% ({format_size(diff)} ahorrados)"
        else:
            msg = "No se logró reducir más el tamaño del archivo"
            
        self.lbl_result_stat.setText(f"Nuevo tamaño: {format_size(final_size)} - {msg}")
        QMessageBox.information(self, "Compresión lista", f"Proceso finalizado. \n{msg}")
        
    def on_compress_error(self, message):
        self.btn_compress.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Error al comprimir", f"Ocurrió un problema: {message}")