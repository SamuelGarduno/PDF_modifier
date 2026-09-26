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
        