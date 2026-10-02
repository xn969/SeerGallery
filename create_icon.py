import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

app = QApplication([])
folder = Path(__file__).parent / 'app' / 'assets'
pixmap = QPixmap(256, 256)
pixmap.fill(Qt.GlobalColor.transparent)
painter = QPainter(pixmap)
QSvgRenderer(str(folder / 'app.svg')).render(painter)
painter.end()
pixmap.save(str(folder / 'app.png'))
Image.open(folder / 'app.png').save(folder / 'app.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
