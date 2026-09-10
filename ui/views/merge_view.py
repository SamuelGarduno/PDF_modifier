from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt
from pathlib import Path
from ui.components.drop_zone import DropZone

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
        
        controls_layout = QHBoxLayout()
        
        self.btn_clear = QPushButton("Limpiar Lista")
        self.btn_clear.setObjectName("SecondaryButton")
        self.btn_clear.clicked.connect(self.clear_list)
        
        self.btn_merge = QPushButton("Unir archivos")
        self.btn_merge.setObjectName("PrimaryButton")
        
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
        