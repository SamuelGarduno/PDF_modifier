from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Herramienta pal PDF")
        self.resize(850,600)
        self.setMinimumSize(600,450)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setAlignment(Qt.AlignCenter)
        
        label_test = QLabel("Bienvenido al entorno de desarrollo PDF Suite")
        label_test.setObjectName("TiteLabel")
        self.layout.addWidget(label_test)
        
        self.load_stylesheet()
        
    def load_stylesheet(self):
        qss_path = Path(__file__).parent / "styles" / "main.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())