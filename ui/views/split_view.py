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
    
    def __int__(self, input_path: str, output_path: str, range_str: str):
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
        
        