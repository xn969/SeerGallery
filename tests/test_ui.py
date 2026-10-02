import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from main import Window
from core import scan, valid_png, other_destination

GAME = Path(r'D:\seer\unity\SeerLauncher\games\NewSeer\Seer_Data\yoo')

@unittest.skipUnless(GAME.exists(), '需要本地游戏资源')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.catalog = scan(GAME)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        settings.setValue('source', str(GAME))
        settings.setValue('output', str(self.root / 'output'))
        self.window = Window(settings, auto_scan=False)
        self.window.scan_done(self.catalog)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_filters_and_selection(self):
        self.window.category.setCurrentIndex(2)
        self.assertEqual(self.window.table.rowCount(), 887)
        self.window.select_filtered()
        self.assertTrue(all(i > 10000 for i in self.window.selected))
        self.window.search.setText('1400834')
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(len(self.window.selected), 887)
        self.window.clear_selection()
        self.assertEqual(len(self.window.selected), 0)
        self.assertFalse(self.window.export_btn.isEnabled())

    def test_navigation_caption_removed_and_other_export(self):
        self.assertEqual(self.window.gallery_nav.text().strip(), '精灵图片')
        self.assertEqual(self.window.other_nav.text().strip(), '其他图片')
        self.assertFalse(hasattr(self.window, 'classification_label'))
        page = self.window.other
        self.window.navigate(1)
        page.search.setText('cb_mainpanel_bg')
        self.assertEqual(page.model.rowCount(), 1)
        item = page.model.rows[0]
        page.select_filtered()
        errors = []
        with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[2])):
            page.start_export()
            self.assertIsNotNone(self.window.worker)
            deadline = time.monotonic() + 30
            while self.window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNone(self.window.worker)
            page.category.setCurrentIndex(4)
            self.assertEqual(page.model.rowCount(), 1)  # exported size is now known
            page.start_sizes()
            while self.window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNone(self.window.worker)
        self.assertFalse(errors, errors)
        self.assertTrue(valid_png(other_destination(self.root / 'output', item)))
        self.window.navigate(2)
        self.assertTrue(self.window.settings_nav.isChecked())

    def test_actual_gui_export_background_and_settings(self):
        self.window.selected = {1, 1400834}
        self.window.skip.setChecked(False)
        self.window.refresh_table()
        self.window.save_settings()
        self.assertEqual(self.window.settings.value('output'), str(self.root / 'output'))
        errors = []
        with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[2])):
            self.window.start_export()
            self.assertIsNotNone(self.window.worker)
            self.assertFalse(self.window.export_btn.isEnabled())
            deadline = time.monotonic() + 30
            while self.window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNone(self.window.worker, '提取线程未按时结束')
        self.assertFalse(errors, errors)
        self.assertEqual(self.window.progress.value(), 100)
        for category, number in [('pets', 1), ('skins', 1400834)]:
            for kind in ('head', 'body'):
                self.assertTrue(valid_png(self.root / 'output' / category / str(number) / f'{kind}.png'))
        self.assertTrue(Path(self.window.last_report).is_file())

if __name__ == '__main__':
    unittest.main(verbosity=2)
