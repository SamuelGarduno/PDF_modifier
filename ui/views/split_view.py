from PySide6.QtWidgets import QWidget, QBoxLayout, QLabel, QVBoxLayout
from PySide6.QtCore import Qt

class SplitView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        lbl = QLabel("Herramienta: Dividir / Extraer páginas")
        lbl.setObjectName("ViewTitle")
        layout.addWidget(lbl)
        
        