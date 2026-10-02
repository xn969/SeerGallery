from __future__ import annotations
import os
import sys
import threading
from collections import Counter
from pathlib import Path

if '--smoke-test' in sys.argv:
    def smoke_exception(kind, value, trace):
        import traceback
        folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
        (folder / 'smoke-error.txt').write_text(''.join(traceback.format_exception(kind, value, trace)), encoding='utf8')
        os._exit(1)
    sys.excepthook = smoke_exception

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl
from PySide6.QtGui import QFont, QPixmap, QDesktopServices, QColor, QFontDatabase, QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QFileDialog, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox,
    QCheckBox, QProgressBar, QMessageBox, QFrame, QSplitter, QStyle)

from core import scan, export, preview, ensure_output, ResourceError
from other_page import OtherImagesPage

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = r'D:\seer\unity\SeerLauncher\games\NewSeer\Seer_Data\yoo'

STYLE = '''
QWidget { font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; color: #202d3d; }
QMainWindow, QWidget#surface { background: #f4f6fa; }
QFrame#sidebar { background: #edf1f7; border-right: 1px solid #dce3ec; }
QFrame#card { background: white; border: 1px solid #e2e7ef; border-radius: 12px; }
QLabel#title { font-size: 27px; font-weight: 650; }
QLabel#muted { color: #758195; }
QLabel#metric { font-size: 26px; font-weight: 650; color: #1769cc; }
QLabel#brand { font-size: 20px; font-weight: 650; }
QLabel#badge { color: #1769cc; background: #e9f2ff; border-radius: 8px; padding: 5px 10px; }
QPushButton { background: white; border: 1px solid #d8e0ea; border-radius: 7px; padding: 9px 15px; }
QPushButton:hover { background: #edf4ff; border-color: #a4c6f2; }
QPushButton:pressed { background: #dbeaff; }
QPushButton:disabled { color: #a0a8b5; background: #f0f2f6; border-color: #e2e6ed; }
QPushButton#primary { color: white; background: #1769cc; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #2479dc; }
QPushButton#primary:disabled { background: #aec7e7; }
QPushButton#nav { background: transparent; border: none; text-align: left; padding: 13px 17px; }
QPushButton#nav:checked { background: #dceaff; color: #1769cc; font-weight: 600; }
QLineEdit, QComboBox { background: white; border: 1px solid #d8e0ea; border-radius: 7px; padding: 9px; min-height: 18px; }
QLineEdit:focus { border: 1px solid #1769cc; }
QComboBox::drop-down { border: none; width: 25px; }
QTableWidget { background: white; alternate-background-color: #f8faff; border: none; gridline-color: #edf0f5; selection-background-color: #e4efff; selection-color: #202d3d; }
QHeaderView::section { background: #f7f9fc; color: #65738a; border: none; border-bottom: 1px solid #e5eaf2; padding: 12px 8px; font-weight: 600; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #f0f3f8; }
QProgressBar { background: #e4eaf3; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: #1769cc; border-radius: 4px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSplitter::handle { background: #f4f6fa; width: 12px; }
QScrollBar:vertical { width: 9px; background: transparent; }
QScrollBar::handle:vertical { background: #c4cdd9; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''

class Task(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.action(self))
        except Exception as error:
            self.error.emit(str(error))

def label(text, name=None):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    return item

def button(text, callback=None, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName('primary')
    if callback:
        item.clicked.connect(callback)
    return item

def card():
    frame = QFrame()
    frame.setObjectName('card')
    return frame

class Window(QMainWindow):
    def __init__(self, settings=None, auto_scan=True):
        super().__init__()
        self.setWindowTitle('Seer Gallery · 游戏图片提取')
        self.resize(1280, 840)
        self.setMinimumSize(1080, 730)
        icon_path = Path(__file__).resolve().parent / 'assets' / 'app.svg'
        if icon_path.exists():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            QSvgRenderer(str(icon_path)).render(painter)
            painter.end()
            self.setWindowIcon(QIcon(pixmap))
        self.settings = settings if settings is not None else QSettings('SeerGallery', 'Extractor')
        self.catalog = None
        self.selected = set()
        self.worker = None
        self.mode = ''
        self.preview_id = None
        self.last_report = None
        self.closing = False
        surface = QWidget()
        surface.setObjectName('surface')
        self.setCentralWidget(surface)
        shell = QHBoxLayout(surface)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(202)
        rail = QVBoxLayout(sidebar)
        rail.setContentsMargins(18, 32, 18, 24)
        rail.addWidget(label('Seer Gallery', 'brand'))
        rail.addWidget(label('游戏图片提取工具', 'muted'))
        rail.addSpacing(36)
        self.gallery_nav = button('  精灵图片', lambda: self.navigate(0))
        self.gallery_nav.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.other_nav = button('  其他图片', lambda: self.navigate(1))
        self.other_nav.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.settings_nav = button('  设置', lambda: self.navigate(2))
        self.settings_nav.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        for nav in (self.gallery_nav, self.other_nav, self.settings_nav):
            nav.setObjectName('nav')
            nav.setCheckable(True)
            rail.addWidget(nav)
        rail.addStretch()
        rail.addWidget(label('本地运行 · 游戏目录只读', 'muted'))
        rail.addWidget(label('VERSION 0.1.0', 'muted'))
        shell.addWidget(sidebar)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages, 1)
        self.build_gallery()
        self.other = OtherImagesPage(self)
        self.pages.addWidget(self.other)
        self.build_settings()
        self.navigate(0)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.request_preview)
        self.apply_counts()
        if auto_scan and '--smoke-test' not in sys.argv and Path(self.source.text()).exists():
            QTimer.singleShot(150, self.scan_resources)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.gallery_nav.setChecked(index == 0)
        self.other_nav.setChecked(index == 1)
        self.settings_nav.setChecked(index == 2)

    def build_gallery(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 25)
        layout.setSpacing(18)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label('精灵资源库', 'title'))
        titles.addWidget(label('选择编号，一次提取头像与精灵全身图。', 'muted'))
        header.addLayout(titles)
        header.addStretch()
        self.scan_btn = button('扫描资源', self.scan_resources)
        header.addWidget(self.scan_btn)
        header.addWidget(button('打开输出文件夹', self.open_output))
        layout.addLayout(header)
        stats = QHBoxLayout()
        self.metrics = []
        for title in ('宠物本体', '皮肤资源', '头像 + 全身图齐全'):
            frame = card()
            box = QVBoxLayout(frame)
            box.setContentsMargins(18, 14, 18, 14)
            metric = label('—', 'metric')
            self.metrics.append(metric)
            box.addWidget(label(title, 'muted'))
            box.addWidget(metric)
            stats.addWidget(frame)
        layout.addLayout(stats)
        self.catalog_label = label('尚未扫描 · 请在设置中选择游戏资源目录', 'muted')
        self.catalog_label.setWordWrap(True)
        layout.addWidget(self.catalog_label)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索编号，如 1、10001 或 1400834')
        self.search.textChanged.connect(self.refresh_table)
        self.category = QComboBox()
        self.category.addItems(['全部资源', '宠物本体', '皮肤资源', '边界编号'])
        self.category.currentIndexChanged.connect(self.refresh_table)
        self.complete = QCheckBox('仅显示双图齐全')
        self.complete.toggled.connect(self.refresh_table)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        filters.addWidget(self.complete)
        layout.addLayout(filters)
        splitter = QSplitter()
        table_card = card()
        table_box = QVBoxLayout(table_card)
        table_box.setContentsMargins(0, 8, 0, 8)
        actions = QHBoxLayout()
        actions.setContentsMargins(14, 0, 14, 6)
        self.select_all = button('选择筛选结果', self.select_filtered)
        self.clear_btn = button('清空选择', self.clear_selection)
        actions.addWidget(self.select_all)
        actions.addWidget(self.clear_btn)
        actions.addStretch()
        self.selection_label = label('已选 0 个', 'muted')
        actions.addWidget(self.selection_label)
        table_box.addLayout(actions)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['选择', '资源编号', '类别', '头像', '精灵图'])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 56)
        self.table.itemChanged.connect(self.check_changed)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        table_box.addWidget(self.table)
        splitter.addWidget(table_card)
        detail = card()
        detail.setMinimumWidth(250)
        info = QVBoxLayout(detail)
        info.setContentsMargins(18, 18, 18, 18)
        info.addWidget(label('资源预览', 'muted'))
        self.detail_title = label('选择一个精灵', 'brand')
        info.addWidget(self.detail_title)
        self.image = QLabel('扫描后点击资源行\n查看精灵图片')
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(220)
        self.image.setStyleSheet('background: #f5f8fc; border-radius: 10px; color: #8a98ac;')
        info.addWidget(self.image, 1)
        self.detail_text = label('头像与全身图始终一起提取。\n可在设置中附加半身图。', 'muted')
        self.detail_text.setWordWrap(True)
        info.addWidget(self.detail_text)
        splitter.addWidget(detail)
        splitter.setSizes([650, 280])
        layout.addWidget(splitter, 1)
        footer = card()
        footer_box = QVBoxLayout(footer)
        footer_box.setContentsMargins(18, 14, 18, 14)
        row = QHBoxLayout()
        self.status = label('准备就绪', 'muted')
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.cancel_btn = button('取消提取', self.cancel_export)
        self.cancel_btn.setEnabled(False)
        row.addWidget(self.cancel_btn)
        self.export_btn = button('提取所选 · 双图', self.start_export, True)
        row.addWidget(self.export_btn)
        footer_box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        footer_box.addWidget(self.progress)
        layout.addWidget(footer)
        self.pages.addWidget(page)

    def build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 30, 32, 30)
        layout.setSpacing(22)
        layout.addWidget(label('设置', 'title'))
        layout.addWidget(label('目录与导出偏好会自动保存，仅保存在当前用户的应用设置中。', 'muted'))
        paths = card()
        box = QVBoxLayout(paths)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(12)
        box.addWidget(label('游戏资源文件夹', 'brand'))
        box.addWidget(label('支持选择 NewSeer、Seer_Data 或 yoo 目录。', 'muted'))
        source_row = QHBoxLayout()
        self.source = QLineEdit(self.settings.value('source', DEFAULT_SOURCE))
        self.source.editingFinished.connect(self.save_settings)
        source_row.addWidget(self.source, 1)
        self.source_browse = button('浏览…', lambda: self.browse(self.source))
        source_row.addWidget(self.source_browse)
        box.addLayout(source_row)
        box.addSpacing(14)
        box.addWidget(label('输出文件夹', 'brand'))
        self.output = QLineEdit(self.settings.value('output', str(BASE / 'output')))
        self.output.editingFinished.connect(self.save_settings)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output, 1)
        self.output_browse = button('浏览…', lambda: self.browse(self.output))
        output_row.addWidget(self.output_browse)
        box.addLayout(output_row)
        box.addWidget(label('输出结构：pets / 编号、skins / 编号保存精灵双图；\nother / 资源包 / 原始目录保存其他图片；reports 保存结果报告。', 'muted'))
        layout.addWidget(paths)
        options = card()
        box = QVBoxLayout(options)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(14)
        box.addWidget(label('导出偏好', 'brand'))
        self.half = QCheckBox('附加提取半身图（half.png）')
        self.half.setChecked(self.settings.value('half', False, type=bool))
        self.skip = QCheckBox('跳过已存在且完整的 PNG，支持再次运行补齐资源')
        self.skip.setChecked(self.settings.value('skip', True, type=bool))
        for option in (self.half, self.skip):
            option.toggled.connect(self.save_settings)
            box.addWidget(option)
        box.addWidget(label('图片统一导出 PNG，保留原始分辨率及已有透明通道。\n半身图选项仅影响精灵图片；其他图片按所选路径单独导出。', 'muted'))
        layout.addWidget(options)
        note = card()
        box = QVBoxLayout(note)
        box.setContentsMargins(24, 20, 24, 20)
        box.addWidget(label('只读提取', 'brand'))
        text = label('应用只读取游戏清单和缓存资源，不修改游戏文件。\n输出目录禁止设在游戏安装目录内。缺失的头像或精灵图会写入报告，不会生成占位图。', 'muted')
        text.setWordWrap(True)
        box.addWidget(text)
        layout.addWidget(note)
        layout.addWidget(button('保存并扫描资源', self.scan_resources, True), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self.pages.addWidget(page)

    def save_settings(self):
        for key, value in [('source', self.source.text()), ('output', self.output.text()),
                           ('half', self.half.isChecked()), ('skip', self.skip.isChecked())]:
            self.settings.setValue(key, value)
        self.settings.sync()

    def browse(self, field):
        folder = QFileDialog.getExistingDirectory(self, '选择文件夹', field.text())
        if folder:
            field.setText(folder)
            self.save_settings()

    def set_busy(self, busy):
        for control in (self.scan_btn, self.source, self.output, self.source_browse,
                        self.output_browse, self.half, self.skip, self.select_all, self.clear_btn):
            control.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy and self.mode == 'export')
        self.export_btn.setEnabled(not busy and self.catalog is not None and bool(self.selected))
        for control in (self.table, self.search, self.category, self.complete):
            control.setEnabled(not busy or self.mode in ('preview', 'other-preview'))
        self.other.set_busy(busy)

    def run_task(self, mode, action, callback):
        if self.worker is not None:
            return False
        self.mode = mode
        task = Task(action, self)
        self.worker = task
        task.result.connect(callback)
        task.error.connect(self.task_error)
        task.progress.connect(self.other.update_progress if mode.startswith('other-') else self.update_progress)
        task.finished.connect(self.task_finished)
        self.set_busy(True)
        task.start()
        return True

    def task_error(self, message):
        if self.mode.startswith('other-'):
            self.other.task_error(message)
            return
        self.progress.setRange(0, 100)
        if self.mode == 'scan':
            self.other.progress.setRange(0, 100)
            self.other.status.setText('扫描失败：' + message)
        if self.mode == 'preview':
            self.image.setText('预览不可用')
            self.detail_text.setText(message)
        else:
            self.status.setText('操作失败：' + message)
            QMessageBox.warning(self, '操作未完成', message)

    def task_finished(self):
        task = self.worker
        self.worker = None
        if task:
            task.deleteLater()
        self.progress.setRange(0, 100)
        self.set_busy(False)
        self.other.task_finished()
        if self.closing:
            self.close()
        elif self.mode == 'preview' and self.preview_id != self.current_id():
            self.timer.start()

    def scan_resources(self, target_page=0):
        if self.worker is not None:
            return
        self.timer.stop()
        self.other.timer.stop()
        self.save_settings()
        self.navigate(int(target_page))
        source = self.source.text().strip()
        self.status.setText('正在读取清单并核对本地缓存…')
        self.progress.setRange(0, 0)
        self.other.progress.setRange(0, 0)
        self.other.status.setText('正在读取清单并核对本地图片…')
        self.run_task('scan', lambda task: scan(source), self.scan_done)

    def scan_done(self, catalog):
        self.catalog = catalog
        self.selected.clear()
        self.lookup = {pet.id: pet for pet in catalog.pets}
        self.other.set_catalog(catalog)
        self.source.setText(str(catalog.root))
        self.save_settings()
        self.catalog_label.setText(f'版本 {catalog.version}  ·  {len(catalog.pets):,} 个编号  ·  {catalog.root}')
        self.apply_counts()
        self.refresh_table()
        self.progress.setValue(0)
        self.status.setText('扫描完成 · 选择资源后提取头像与精灵图')

    def apply_counts(self):
        pets = self.catalog.pets if self.catalog else []
        counts = Counter(p.category for p in pets)
        for metric, value in zip(self.metrics, (counts['pets'], counts['skins'], sum(p.paired for p in pets))):
            metric.setText(f'{value:,}' if self.catalog else '—')

    def filtered(self):
        if not self.catalog:
            return []
        category = [None, 'pets', 'skins', 'unknown'][self.category.currentIndex()]
        text = self.search.text().strip()
        return [p for p in self.catalog.pets if (category is None or p.category == category)
                and (not text or text in str(p.id)) and (not self.complete.isChecked() or p.paired)]

    def refresh_table(self):
        self.table.blockSignals(True)
        if hasattr(self, 'timer'):
            self.timer.stop()
        pets = self.filtered()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(pets))
        for row, pet in enumerate(pets):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if pet.id in self.selected else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, pet.id)
            self.table.setItem(row, 0, check)
            values = [str(pet.id), {'pets': '宠物本体', 'skins': '皮肤资源', 'unknown': '边界编号'}[pet.category]]
            for kind in ('head', 'body'):
                asset = pet.assets.get(kind)
                values.append('可提取' if asset and asset.cached else '未缓存' if asset else '无此资源')
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                if col >= 3:
                    item.setForeground(QColor('#20815e' if value == '可提取' else '#aa7843'))
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 43)
        self.table.setUpdatesEnabled(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.update_selection_count()
        if self.preview_id is not None and self.current_id() is None:
            self.image.clear()
            self.image.setText('点击资源行查看预览')
            self.detail_title.setText('选择一个精灵')
            self.detail_text.setText('头像与全身图始终一起提取。\n可在设置中附加半身图。')

    def check_changed(self, item):
        if item.column() != 0:
            return
        number = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.selected.add(number)
        else:
            self.selected.discard(number)
        self.update_selection_count()

    def update_selection_count(self):
        self.selection_label.setText(f'已选 {len(self.selected):,} 个')
        self.selection_label.setToolTip(f'当前筛选结果 {self.table.rowCount():,} 个，隐藏的已选项目仍会提取')
        self.export_btn.setEnabled(self.worker is None and bool(self.selected) and self.catalog is not None)

    def select_filtered(self):
        self.selected.update(p.id for p in self.filtered())
        self.refresh_table()

    def clear_selection(self):
        self.selected.clear()
        self.refresh_table()

    def current_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection_changed(self):
        if hasattr(self, 'timer'):
            self.timer.start()

    def request_preview(self):
        number = self.current_id()
        if number is None or self.worker is not None:
            return
        self.preview_id = number
        pet = self.lookup[number]
        self.detail_title.setText(f'编号 {number}')
        self.detail_text.setText(('宠物本体' if pet.category == 'pets' else '皮肤资源' if pet.category == 'skins' else '边界编号') + '\n预览来自原始静态全身图。')
        self.image.clear()
        self.image.setText('正在加载图片…')
        self.run_task('preview', lambda task: preview(pet), lambda data: self.preview_done(number, data))

    def preview_done(self, number, data):
        if number != self.current_id():
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.image.setPixmap(pixmap.scaled(260, 290, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def start_export(self):
        if not self.catalog or self.worker is not None or not self.selected:
            return
        try:
            source_root = self.source.text().strip()
            from core import resolve_resource_root
            if resolve_resource_root(source_root) != self.catalog.root:
                raise ResourceError('资源目录已更改，请先重新扫描')
            output = ensure_output(Path(self.output.text().strip()), self.catalog.protected)
            if not self.output.text().strip():
                raise ResourceError('请选择输出文件夹')
        except Exception as error:
            QMessageBox.warning(self, '请检查设置', str(error))
            return
        self.save_settings()
        pets = [self.lookup[number] for number in sorted(self.selected)]
        catalog, half, skip = self.catalog, self.half.isChecked(), self.skip.isChecked()
        self.timer.stop()
        self.progress.setValue(0)
        self.status.setText(f'准备提取 {len(pets):,} 个编号…')
        self.run_task('export', lambda task: export(catalog, pets, output, half, skip, task.cancel,
                                                    task.progress.emit), self.export_done)

    def update_progress(self, done, total, message):
        self.progress.setRange(0, 100)
        percent = int(done * 100 / total) if total else 100
        self.progress.setValue(percent)
        self.status.setText(f'{percent}% · {done:,} / {total:,} · {message}')

    def export_done(self, result):
        self.last_report = result['report']
        title = '已取消，已完成的图片已保留' if result['cancelled'] else '提取完成'
        message = f"{title} · 新增 {result['saved']} 张 / 跳过 {result['skipped']} 张 / 缺失 {result['missing']} 张 / 失败 {result['failed']} 张"
        self.status.setText(message)
        self.progress.setValue(0 if result['cancelled'] else 100)
        if not self.closing:
            QMessageBox.information(self, title, message + '\n\n结果报告：\n' + result['report'])

    def cancel_export(self):
        if self.worker and self.mode == 'export':
            self.worker.cancel.set()
            self.cancel_btn.setEnabled(False)
            self.status.setText('正在取消…当前图片处理结束后停止')

    def open_output(self):
        path = Path(self.output.text()).expanduser().resolve()
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.status.setText('输出文件夹尚未创建，首次提取时会自动创建')

    def closeEvent(self, event):
        if self.worker is not None:
            self.closing = True
            self.worker.cancel.set()
            self.status.setText('正在结束当前操作并保存报告…')
            self.other.status.setText('正在结束当前操作并保存报告…')
            event.ignore()
        else:
            self.save_settings()
            event.accept()

def main():
    app = QApplication(sys.argv)
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        # The offscreen plugin does not enumerate Windows system fonts.
        for filename in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf', 'seguisb.ttf'):
            font = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / filename
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = Window()
    window.show()
    if '--smoke-test' in sys.argv:
        def smoke():
            window.scan_done(scan(DEFAULT_SOURCE))
            window.category.setCurrentIndex(2)
            window.search.setText('14008')
            window.select_filtered()
            window.table.selectRow(0)
            number = window.current_id()
            window.preview_id = number
            window.detail_title.setText(f'编号 {number}')
            window.detail_text.setText('皮肤资源\n预览来自原始静态全身图。')
            window.preview_done(number, preview(window.lookup[number]))
            window.grab().save(str(BASE / 'ui-preview.png'))
            window.navigate(1)
            window.other.search.setText('cb_mainpanel_bg')
            window.other.table.selectRow(0)
            key = window.other.current_key()
            window.other.preview_key = key
            resource = window.other.lookup[key]
            window.other.detail_title.setText(resource.name)
            window.other.path_label.setText(resource.asset.path)
            from core import preview_image, export_images
            window.other.preview_done(key, preview_image(resource))
            verification = export_images(window.catalog, [resource], BASE / 'output')
            if verification['failed'] or verification['missing']:
                raise RuntimeError('发布版其他图片导出验证失败')
            window.grab().save(str(BASE / 'ui-other-preview.png'))
            window.navigate(2)
            window.grab().save(str(BASE / 'ui-settings-preview.png'))
            print(f'UI_OK rows={window.table.rowCount()} selected={len(window.selected)}', flush=True)
            app.quit()
        QTimer.singleShot(200, smoke)
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
