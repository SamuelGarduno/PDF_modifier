from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QFileDialog
from PySide6.QtCore import Qt, Signal

class DropZone(QFrame):
    
    files_dropped = Signal(list)
    
    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        
        self.label_icon = QLabel("PDF")
        self.label_icon.setObjectName("DropZoneBadge")
        self.label_icon.setAlignment(Qt.AlignCenter)
        
        self.label_text = QLabel("Arrastra tus documentos PDF aquí")
        self.label_text.setObjectName("DropZoneTitle")

        self.label_hint = QLabel("o haz click para explorar en el equipo")
        self.label_hint.setObjectName("DropZoneHint")
        
        layout.addWidget(self.label_icon)
        layout.addWidget(self.label_text)
        layout.addWidget(self.label_hint)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            has_pdf = any(url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls())
            if has_pdf:
                self.setProperty("dragActive", True)
                self.style().polish(self)
                event.acceptProposedAction()
                return
        event.ignore()
        
    def dragLeaveEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().polish(self)
        event.accept()
        
    def dropEvent(self, event):
        self.setProperty("dragActive", False)
        self.style().polish(self)
        
        valid_files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith(".pdf")
        ]
        
        if valid_files:
            self.files_dropped.emit(valid_files)
            event.acceptProposedAction()
            
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            files, _ = QFileDialog.getOpenFileNames(
                self, "Seleccionnar archivos PDF","","Archivos PDF (*.pdf)"
            )
            if files:
                self.files_dropped.emit(files)