import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import (scan, ImageResource, Asset, Catalog, other_destination, export_images,
                  inspect_sizes, ResourceError, valid_png)

GAME = Path(r'D:\seer\unity\SeerLauncher\games\NewSeer\Seer_Data\yoo')
BACKGROUND = 'Assets/Art/Ui/Background/cb_mainpanel_bg.jpg'
MAP = 'Assets/Art/Ui/Maps/map/1/map_01_bg_mc.jpg'
ICON = 'Assets/Art/Ui/assets/mainStoryLine/image/ChapterIcon/image1001_list.png'

class OtherSafetyTests(unittest.TestCase):
    def test_output_path_unique_safe_and_stable(self):
        def resource(path):
            return ImageResource('DefaultPackage', Asset('image', path, Path('bundle'), 'a'*32, False), 'ui')
        first, second = resource('Assets/UI/a:b.jpg'), resource('Assets/UI/a?b.png')
        self.assertNotEqual(other_destination(Path('output'), first), other_destination(Path('output'), second))
        self.assertEqual(other_destination(Path('output'), first), other_destination(Path('output'), first))
        for path in ('../game.png', '/game.png', 'Assets/../game.png'):
            with self.assertRaises(ResourceError):
                other_destination(Path('output'), resource(path))

    def test_missing_cancel_and_raw_image(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            raw = source / '__data'
            Image.new('RGBA', (1136, 640), (10, 20, 30, 120)).save(raw, format='PNG')
            resource = ImageResource('DefaultPackage', Asset('image', 'Assets/UI/bg.png', raw, 'a'*32, True, True), 'background')
            catalog = Catalog(source, source, 'test', [], 0, [resource])
            self.assertEqual(inspect_sizes([resource])['large'], 1)
            result = export_images(catalog, [resource], root / 'output')
            self.assertEqual(result['saved'], 1)
            self.assertTrue(valid_png(other_destination(root / 'output', resource)))
            event = threading.Event()
            event.set()
            cancelled = export_images(catalog, [resource], root / 'cancel', cancel=event)
            self.assertEqual(cancelled['rows'][0]['status'], 'cancelled')
            missing = ImageResource('DefaultPackage', Asset('image', 'Assets/UI/missing.png', source / 'missing', 'b'*32, False), 'ui')
            self.assertEqual(export_images(catalog, [missing], root / 'output')['missing'], 1)
            with self.assertRaises(ResourceError):
                export_images(catalog, [resource], source / 'output')

@unittest.skipUnless(GAME.exists(), '需要游戏资源')
class OtherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = scan(GAME)
        cls.lookup = {r.asset.path: r for r in cls.catalog.images}

    def test_catalog_categories_and_pet_exclusion(self):
        self.assertEqual(len(self.catalog.images), 35542)
        self.assertTrue(any(r.package == 'StartupPackage' for r in self.catalog.images))
        self.assertFalse(any('/assets/pet/' in r.asset.path.lower() for r in self.catalog.images))
        self.assertEqual(self.lookup[BACKGROUND].category, 'background')

    def test_real_sizes_export_and_readonly(self):
        import hashlib
        from PIL import Image
        resources = [self.lookup[p] for p in (BACKGROUND, MAP, ICON)]
        files = {r.asset.bundle for r in resources}
        before = {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
        result = inspect_sizes(resources)
        self.assertEqual(result['inspected'], 3)
        self.assertEqual(result['large'], 2)
        self.assertEqual((resources[0].width, resources[0].height), (2048, 975))
        self.assertEqual((resources[1].width, resources[1].height), (2016, 960))
        with tempfile.TemporaryDirectory() as folder:
            result = export_images(self.catalog, resources, Path(folder))
            self.assertEqual(result['saved'], 3)
            self.assertEqual(result['failed'], 0)
            for item in resources:
                path = other_destination(Path(folder), item)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (item.width, item.height))
            self.assertEqual(export_images(self.catalog, resources, Path(folder))['skipped'], 3)
        for path in files:
            self.assertEqual(before[path], (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()))

if __name__ == '__main__':
    unittest.main(verbosity=2)
