import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import (Asset, Catalog, Pet, ResourceError, ensure_output,
                  export, parse_manifest, resolve_resource_root, scan, valid_png)

GAME = Path(r'D:\seer\unity\SeerLauncher\games\NewSeer\Seer_Data\yoo')

class SafetyTests(unittest.TestCase):
    def test_number_boundary(self):
        self.assertEqual(Pet(9999).category, 'pets')
        self.assertEqual(Pet(10000).category, 'unknown')
        self.assertEqual(Pet(10001).category, 'skins')

    def test_output_game_guard(self):
        game = GAME.parent.parent
        for folder in (game, game / 'output', GAME / 'output'):
            with self.assertRaises(ResourceError):
                ensure_output(folder, game)
        self.assertEqual(ensure_output(Path('output'), game), Path('output').resolve())

    def test_manifest_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.bytes'
            path.write_bytes(b'OOY\0\5\0')
            with self.assertRaises(ResourceError):
                parse_manifest(path)

    def test_missing_pair_and_cancel_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = Catalog(root / 'source', root / 'source', 'test', [], 0)
            pet = Pet(1)
            result = export(catalog, [pet], root / 'output')
            self.assertEqual(result['missing'], 2)
            self.assertTrue(Path(result['report']).is_file())
            event = threading.Event()
            event.set()
            result = export(catalog, [pet], root / 'cancelled', cancel=event)
            self.assertTrue(result['cancelled'])
            self.assertEqual([r['status'] for r in result['rows']], ['cancelled'] * 2)

@unittest.skipUnless(GAME.exists(), '需要本地游戏资源')
class GameIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = scan(GAME)

    def test_install_directory_resolution(self):
        for folder in (GAME, GAME.parent, GAME.parent.parent, GAME / 'DefaultPackage'):
            self.assertEqual(resolve_resource_root(folder), GAME)

    def test_actual_pairs_and_skin(self):
        import hashlib
        from PIL import Image
        lookup = {pet.id: pet for pet in self.catalog.pets}
        pets = [lookup[i] for i in (1, 4, 1400001, 1400834)]
        files = {asset.bundle for pet in pets for asset in pet.assets.values()}
        before = {p: (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
        output = Path(__file__).resolve().parents[1] / 'output'
        result = export(self.catalog, pets, output, include_half=True, skip_existing=False)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['missing'], 2)  # 1 and 4 do not have half portraits.
        self.assertEqual(result['saved'], 10)
        for pet in pets:
            for kind in ('head', 'body'):
                path = output / pet.category / str(pet.id) / f'{kind}.png'
                self.assertTrue(valid_png(path))
                with Image.open(path) as image:
                    self.assertGreater(image.width, 0)
                    if kind == 'head':
                        self.assertEqual(image.size, (200, 200))
        resumed = export(self.catalog, pets, output, include_half=True)
        self.assertEqual(resumed['skipped'], 10)
        self.assertEqual(resumed['saved'], 0)
        for path, original in before.items():
            self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()), original)

    def test_corrupt_bundle_reports_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            bad = source / 'bad.bundle'
            bad.write_bytes(b'not a unity bundle')
            pet = Pet(1, {k: Asset(k, f'{k}.png', bad, '0'*32, True) for k in ('head', 'body')})
            catalog = Catalog(source, source, 'test', [pet], 0)
            result = export(catalog, [pet], root / 'output')
            self.assertEqual(result['failed'], 2)
            self.assertEqual(result['saved'], 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
