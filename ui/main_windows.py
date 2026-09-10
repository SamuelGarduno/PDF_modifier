from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QStackedWidget, QButtonGroup
from PySide6.QtCore import Qt
from ui.views.merge_view import MergeView
from ui.views.split_view import SplitView

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Herramienta pal PDF")
        self.resize(850,600)
        self.setMinimumSize(600,450)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.main_layout.setSpacing(0)
        
        self.setup_sidebar()
        
        self.setup_content_area()
        
        self.load_stylesheet()
        
    def setup_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16,24,16,24)
        layout.setSpacing(8)
        
        app_title = QLabel("Herramienta PDF")
        app_title.setObjectName("SidebarTitle")
        layout.addWidget(app_title)
        layout.addSpacing(20)
        
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        
        self.btn_merge = QPushButton("Unir PDFs")
        self.btn_merge.setCheckable(True)
        self.btn_merge.setChecked(True)
        self.btn_merge.setObjectName("NavButton")
        
        self.btn_split = QPushButton("Separar PDFs")
        self.btn_split.setCheckable(True)
        self.btn_split.setObjectName("NavButton")
        
        self.nav_group.addButton(self.btn_merge, 0)
        self.nav_group.addButton(self.btn_split, 1)
        
        layout.addWidget(self.btn_merge)
        layout.addWidget(self.btn_split)
        layout.addStretch()
        self.main_layout.addWidget(sidebar)
        
        
    def setup_content_area(self):
        self.pages = QStackedWidget()
        self.pages.setObjectName("ContentArea")
        
        self.view_merge = MergeView()
        self.view_split = SplitView()
        
        self.pages.addWidget(self.view_merge)
        self.pages.addWidget(self.view_split)
        
        self.nav_group.idClicked.connect(self.pages.setCurrentIndex)
        
        self.main_layout.addWidget(self.pages)
        
        
    def load_stylesheet(self):
        qss_path = Path(__file__).parent / "styles" / "main.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())