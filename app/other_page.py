"""Other image resources: path browsing, size inspection, preview and export."""
from pathlib import Path
from collections import Counter
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex, QTimer
from PySide6.QtGui import QColor, QPixmap, QFontMetrics
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QComboBox, QCheckBox, QTableView, QHeaderView,
    QAbstractItemView, QSplitter, QProgressBar, QMessageBox, QDialog, QScrollArea, QSizePolicy)
from core import preview_image, inspect_sizes, export_images, ensure_output, resolve_resource_root, ResourceError

NAMES = {'background': '背景', 'scene': '场景 / 地图', 'illustration': '剧情 / 插画', 'ui': 'UI / 图标'}

def text(value, name=None):
    item = QLabel(value)
    if name:
        item.setObjectName(name)
    return item

def button(value, callback, primary=False):
    item = QPushButton(value)
    item.clicked.connect(callback)
    if primary:
        item.setObjectName('primary')
    return item

def card():
    item = QFrame()
    item.setObjectName('card')
    return item

class ImageModel(QAbstractTableModel):
    checked = Signal()
    headers = ['选择', '图片名称', '类别', '原始尺寸', '状态']

    def __init__(self, selected):
        super().__init__()
        self.rows = []
        self.selected = selected

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return
        item = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if item.key in self.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.package + '\n' + item.asset.path + ('\n' + item.error if item.error else '')
        if role == Qt.ItemDataRole.ForegroundRole and col == 4:
            return QColor('#20815e' if item.asset.cached else '#aa7843')
        if role == Qt.ItemDataRole.DisplayRole:
            size = f'{item.width} × {item.height}' if item.width is not None else '读取失败' if item.error else '未识别'
            return ['', item.name, NAMES[item.category], size, '可提取' if item.asset.cached else '未缓存'][col]

    def flags(self, index):
        result = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            result |= Qt.ItemFlag.ItemIsUserCheckable
        return result

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            key = self.rows[index.row()].key
            if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
                self.selected.add(key)
            else:
                self.selected.discard(key)
            self.dataChanged.emit(index, index, [role])
            self.checked.emit()
            return True
        return False

    def reset(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

class OtherImagesPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.catalog = None
        self.selected = set()
        self.lookup = {}
        self.preview_key = None
        self.preview_pixmap = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.request_preview)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 27, 30, 25)
        layout.setSpacing(18)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(text('其他图片资源', 'title'))
        titles.addWidget(text('浏览背景、地图、剧情插画与界面图片，按原始路径导出。', 'muted'))
        header.addLayout(titles)
        header.addStretch()
        self.scan_btn = button('扫描资源', lambda: host.scan_resources(1))
        header.addWidget(self.scan_btn)
        header.addWidget(button('打开输出文件夹', host.open_output))
        layout.addLayout(header)
        stats = QHBoxLayout()
        self.metrics = []
        for title in ('背景 / 场景', '其他图片总数', '已识别的宽屏大图'):
            frame = card()
            box = QVBoxLayout(frame)
            box.setContentsMargins(18, 14, 18, 14)
            box.addWidget(text(title, 'muted'))
            metric = text('—', 'metric')
            self.metrics.append(metric)
            box.addWidget(metric)
            stats.addWidget(frame)
        layout.addLayout(stats)
        self.note = text('先扫描资源，再搜索名称或原始路径。', 'muted')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索图片名称或路径，如 bg、map/1、mainStoryLine')
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.addItems(['全部其他图片', '背景 / 场景', '剧情 / 插画', 'UI / 图标', '宽屏大图 / 全屏候选'])
        self.category.setCurrentIndex(1)
        self.category.setToolTip('背景/场景、插画按路径分类；全屏候选按图片尺寸筛选，不代表完整界面截图。')
        self.category.currentIndexChanged.connect(self.refresh)
        self.cached = QCheckBox('仅本地缓存')
        self.cached.setChecked(True)
        self.cached.toggled.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        filters.addWidget(self.cached)
        layout.addLayout(filters)
        splitter = QSplitter()
        table_card = card()
        box = QVBoxLayout(table_card)
        box.setContentsMargins(0, 8, 0, 8)
        actions = QHBoxLayout()
        actions.setContentsMargins(14, 0, 14, 6)
        self.all_btn = button('选择筛选结果', self.select_filtered)
        self.clear_btn = button('清空', self.clear_selection)
        self.sizes_btn = button('识别尺寸', self.start_sizes)
        self.sizes_btn.setToolTip('读取当前筛选范围的原始尺寸；切换到全屏候选时，会识别所有匹配搜索条件的图片。支持取消。')
        actions.addWidget(self.all_btn)
        actions.addWidget(self.clear_btn)
        actions.addWidget(self.sizes_btn)
        actions.addStretch()
        self.selection_note = text('已选 0', 'muted')
        actions.addWidget(self.selection_note)
        box.addLayout(actions)
        self.model = ImageModel(self.selected)
        self.model.checked.connect(self.selection_counts)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setStyleSheet('QTableView { background: white; alternate-background-color: #f8faff; border: none; selection-background-color: #e4efff; selection-color: #202d3d; }')
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 52), (2, 85), (3, 107), (4, 72)):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().selectionChanged.connect(lambda *args: self.timer.start())
        box.addWidget(self.table)
        splitter.addWidget(table_card)
        detail = card()
        detail.setMinimumWidth(260)
        detail_box = QVBoxLayout(detail)
        detail_box.setContentsMargins(18, 18, 18, 18)
        detail_box.addWidget(text('图片预览', 'muted'))
        self.detail_title = text('选择一张图片', 'brand')
        detail_box.addWidget(self.detail_title)
        self.image = QLabel('点击图片行查看预览')
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(170)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.setStyleSheet('background: #f5f8fc; border-radius: 10px; color: #8a98ac;')
        detail_box.addWidget(self.image, 1)
        self.dimension_label = text('原始尺寸：—', 'muted')
        detail_box.addWidget(self.dimension_label)
        self.path_label = text('导出会保留原始目录层级。', 'muted')
        self.path_label.setWordWrap(True)
        self.path_label.setMinimumHeight(44)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_box.addWidget(self.path_label)
        self.zoom_btn = button('放大预览', self.zoom)
        self.zoom_btn.setEnabled(False)
        detail_box.addWidget(self.zoom_btn)
        splitter.addWidget(detail)
        splitter.setSizes([660, 280])
        layout.addWidget(splitter, 1)
        footer = card()
        box = QVBoxLayout(footer)
        box.setContentsMargins(18, 14, 18, 14)
        row = QHBoxLayout()
        self.status = text('准备就绪 · 输出位于 other 子文件夹', 'muted')
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.cancel_btn = button('取消', self.cancel_task)
        self.cancel_btn.setEnabled(False)
        self.export_btn = button('导出所选图片', self.start_export, True)
        self.export_btn.setEnabled(False)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.export_btn)
        box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        box.addWidget(self.progress)
        layout.addWidget(footer)

    def set_catalog(self, catalog):
        self.catalog = catalog
        self.selected.clear()
        self.lookup = {item.key: item for item in catalog.images}
        self.preview_key = None
        self.refresh()
        self.counts()
        self.status.setText('扫描完成 · 识别尺寸后可筛选全屏候选图片')
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

    def counts(self):
        if not self.catalog:
            return
        images = self.catalog.images
        counts = Counter(item.category for item in images)
        for metric, value in zip(self.metrics, (counts['background'] + counts['scene'], len(images), sum(i.screen_like for i in images))):
            metric.setText(f'{value:,}')
        self.note.setText(f'当前列表 {len(self.model.rows):,} 张 · 已识别尺寸 {sum(i.width is not None for i in images):,} / {len(images):,} · DefaultPackage + StartupPackage')

    def filtered(self, for_sizes=False):
        if not self.catalog:
            return []
        category = self.category.currentIndex()
        query = self.search.text().strip().lower()
        return [item for item in self.catalog.images if (not query or query in item.key.lower())
                and (not self.cached.isChecked() or item.asset.cached)
                and (category == 0 or category == 1 and item.category in ('background', 'scene')
                     or category == 2 and item.category == 'illustration'
                     or category == 3 and item.category == 'ui'
                     or category == 4 and (for_sizes or item.screen_like))]

    def refresh(self):
        if not hasattr(self, 'model'):
            return
        self.timer.stop()
        self.model.reset(self.filtered())
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.preview_pixmap = None
        self.image.clear()
        self.image.setText('点击图片行查看预览')
        self.detail_title.setText('选择一张图片')
        self.dimension_label.setText('原始尺寸：—')
        self.path_label.setText('导出会保留原始目录层级。')
        self.zoom_btn.setEnabled(False)
        self.selection_counts()
        self.counts()

    def selection_counts(self):
        self.selection_note.setText(f'已选 {len(self.selected):,}')
        self.selection_note.setToolTip('隐藏的已选图片仍会导出；可以清空后重新选择。')
        self.export_btn.setEnabled(self.host.worker is None and bool(self.selected))

    def select_filtered(self):
        self.selected.update(i.key for i in self.model.rows)
        self.model.reset(self.model.rows)
        self.selection_counts()

    def clear_selection(self):
        self.selected.clear()
        self.model.reset(self.model.rows)
        self.selection_counts()

    def set_busy(self, busy):
        previewing = self.host.mode in ('preview', 'other-preview')
        for widget in (self.scan_btn, self.all_btn, self.clear_btn, self.sizes_btn):
            widget.setEnabled(not busy)
        for widget in (self.search, self.category, self.cached, self.table):
            widget.setEnabled(not busy or previewing)
        self.export_btn.setEnabled(not busy and bool(self.selected))
        self.cancel_btn.setEnabled(busy and self.host.mode in ('other-export', 'other-sizes'))

    def current_key(self):
        index = self.table.currentIndex()
        return self.model.rows[index.row()].key if index.isValid() and index.row() < len(self.model.rows) else None

    def request_preview(self):
        key = self.current_key()
        if key is None or self.host.worker is not None:
            return
        self.preview_key = key
        resource = self.lookup[key]
        self.detail_title.setText(QFontMetrics(self.detail_title.font()).elidedText(resource.name, Qt.TextElideMode.ElideMiddle, 235))
        self.detail_title.setToolTip(resource.name)
        self.path_label.setText(resource.package + '\n' + resource.asset.path)
        self.path_label.setToolTip(resource.asset.path)
        self.image.clear()
        self.image.setText('正在加载图片…')
        self.zoom_btn.setEnabled(False)
        self.host.run_task('other-preview', lambda task: preview_image(resource), lambda result: self.preview_done(key, result))

    def preview_done(self, key, result):
        resource = self.lookup[key]
        resource.width, resource.height = result['width'], result['height']
        resource.error = ''
        self.counts()
        if key != self.current_key():
            return
        pixmap = QPixmap()
        pixmap.loadFromData(result['data'])
        self.preview_pixmap = pixmap
        self.image.setPixmap(pixmap.scaled(260, 235, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.dimension_label.setText(f"原始尺寸：{result['width']} × {result['height']}" + (' · 宽屏大图' if resource.screen_like else ''))
        self.zoom_btn.setEnabled(True)
        self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(max(0, len(self.model.rows) - 1), 4))

    def zoom(self):
        if self.preview_pixmap is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('图片预览 · ' + self.detail_title.toolTip())
        dialog.resize(1050, 720)
        box = QVBoxLayout(dialog)
        scroll = QScrollArea()
        image = QLabel()
        image.setPixmap(self.preview_pixmap)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(image)
        scroll.setWidgetResizable(True)
        box.addWidget(scroll)
        box.addWidget(text(self.dimension_label.text(), 'muted'))
        dialog.exec()

    def start_sizes(self):
        if self.host.worker is not None or not self.catalog:
            return
        items = self.filtered(for_sizes=True)
        if not items:
            self.status.setText('当前筛选范围没有图片')
            return
        self.timer.stop()
        self.progress.setValue(0)
        self.status.setText(f'正在识别 {len(items):,} 张图片的尺寸…')
        self.host.run_task('other-sizes', lambda task: inspect_sizes(items, task.cancel, task.progress.emit), self.sizes_done)

    def sizes_done(self, result):
        self.refresh()
        self.progress.setValue(0 if result['cancelled'] else 100)
        self.status.setText(f"{'已取消' if result['cancelled'] else '尺寸识别完成'} · 已识别 {result['inspected']:,} 张 / 宽屏大图 {result['large']:,} 张 / 未读取 {result['failed']:,} 张")

    def start_export(self):
        if self.host.worker is not None or not self.catalog or not self.selected:
            return
        try:
            if resolve_resource_root(self.host.source.text().strip()) != self.catalog.root:
                raise ResourceError('资源目录已更改，请先重新扫描')
            if not self.host.output.text().strip():
                raise ResourceError('请选择输出文件夹')
            output = ensure_output(Path(self.host.output.text().strip()), self.catalog.protected)
        except Exception as error:
            QMessageBox.warning(self, '请检查设置', str(error))
            return
        self.host.save_settings()
        items = [self.lookup[key] for key in sorted(self.selected)]
        skip = self.host.skip.isChecked()
        self.timer.stop()
        self.progress.setValue(0)
        self.host.run_task('other-export', lambda task: export_images(self.catalog, items, output, skip, task.cancel, task.progress.emit), self.export_done)

    def export_done(self, result):
        self.host.last_report = result['report']
        self.progress.setValue(0 if result['cancelled'] else 100)
        self.counts()
        title = '已取消，已完成的图片已保留' if result['cancelled'] else '图片导出完成'
        message = f"{title} · 新增 {result['saved']} / 跳过 {result['skipped']} / 缺失 {result['missing']} / 失败 {result['failed']}"
        self.status.setText(message)
        if not self.host.closing:
            QMessageBox.information(self, title, message + '\n\n报告：\n' + result['report'])

    def update_progress(self, done, total, message):
        self.progress.setRange(0, 100)
        percent = round(done * 100 / total) if total else 100
        self.progress.setValue(percent)
        self.status.setText(f'{percent}% · {done:,} / {total:,} · {message}')

    def task_error(self, message):
        self.progress.setRange(0, 100)
        if self.host.mode == 'other-preview':
            self.image.setText('预览不可用')
            self.dimension_label.setText(message)
        else:
            self.status.setText('操作失败：' + message)
            if not self.host.closing:
                QMessageBox.warning(self, '操作未完成', message)

    def task_finished(self):
        self.progress.setRange(0, 100)
        if self.host.mode == 'other-preview' and self.preview_key != self.current_key():
            self.timer.start()

    def cancel_task(self):
        if self.host.worker and self.host.mode.startswith('other-'):
            self.host.worker.cancel.set()
            self.cancel_btn.setEnabled(False)
            self.status.setText('正在取消…当前图片处理结束后停止')
