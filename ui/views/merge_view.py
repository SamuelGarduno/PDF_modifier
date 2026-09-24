from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel,QFileDialog, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QProgressBar, QMessageBox
from PySide6.QtCore import Qt, QObject, Signal, QThread
from pathlib import Path
from core.merger import merge_pdf_files
from ui.components.drop_zone import DropZone

class MergeWorker(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)
    
    def __init__(self, file_paths:list, output_path: str):
        super().__init__()
        self.file_paths = file_paths
        self.output_path = output_path
        
    def run(self):
        try:
            merge_pdf_files(
                self.file_paths,
                self.output_path,
                progress_callback=self.progress.emit
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class MergeView(QWidget):
    def __init__(self):
        super().__init__()
        self.pdf_paths = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32,32,32,32)
        layout.setSpacing(16)
        
        title = QLabel("Unir Documentos PDF")
        title.setObjectName("ViewTitle")
        layout.addWidget(title)
        
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        layout.addWidget(self.drop_zone)
        
        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")
        self.file_list.setDragDropMode(QListWidget.InternalMove)
        layout.addWidget(self.file_list)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("MergeProgressBar")
        self.progress_bar.setValue(0)
        self.progress_bar.setValue(False)
        layout.addWidget(self.progress_bar)
        
        controls_layout = QHBoxLayout()
        
        self.btn_clear = QPushButton("Limpiar Lista")
        self.btn_clear.setObjectName("SecondaryButton")
        self.btn_clear.clicked.connect(self.clear_list)
        
        self.btn_merge = QPushButton("Unir archivos")
        self.btn_merge.setObjectName("PrimaryButton")
        self.btn_merge.clicked.connect(self.star_merge_process)
        
        controls_layout.addWidget(self.btn_clear)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_merge)
        
        layout.addLayout(controls_layout)
        
    def add_files(self, paths):
        for path in paths:
            if path not in self.pdf_paths:
                self.pdf_paths.append(path)
                item = QListWidgetItem(Path(path).name)
                item.setToolTip(path)
                self.file_list.addItem(item)
                
    def clear_list(self):
        self.pdf_paths.clear()
        self.file_list.clear()
        
    def get_ordered_paths(self):
        return [self.file_list.item(i).toolTip() for i in range(self.file_list.count())]
    
    def star_merge_process(self):
        file_paths = self.get_ordered_paths()
        if len(file_paths) < 2:
            QMessageBox.warning(
                self,
                "Archivos insuficientes"
                "Agrega al menos 2 archivos PDF para realizar la unión"
            )
            return
        
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF unido", "documento_unido.pdf", "Dcoumentos PDF (*.pdf)"
        )
        if not save_path:
            return
        
        self.btn_merge.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        self.thread = QThread()
        self.worker = MergeWorker(file_paths, save_path)
        self.worker.moveToThread(self.thread)
        
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_bar.setValue)
        
        self.worker.finished.connect(self.on_merge_success)
        self.worker.error.connect(self.on_merge_error)
        
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()
        
    def on_merge_success(self):
        self.btn_merge.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.progress_bar.setValue(100)
        QMessageBox.information(self,"Éxito","El archivo PDF fue unido y guardado correctamente.")
        self.clear_list()
        
    def on_merge_error(self,message):
        self.btn_clear.setEnabled(True)
        self.btn_merge.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Error al procesar", f"Ocurrió un problema: \n{message}")