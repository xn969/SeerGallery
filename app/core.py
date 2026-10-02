"""Read-only YooAsset indexing and paired static pet-image extraction."""
from __future__ import annotations
import csv
import gc
import io
import re
import struct
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

class ResourceError(ValueError):
    pass

class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def number(self, fmt: str):
        size = struct.calcsize('<' + fmt)
        if self.pos + size > len(self.data):
            raise ResourceError('清单被截断或格式不兼容')
        value = struct.unpack_from('<' + fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def text(self):
        size = self.number('H')
        if self.pos + size > len(self.data):
            raise ResourceError('清单字符串被截断')
        value = self.data[self.pos:self.pos + size].decode('utf-8')
        self.pos += size
        return value

    def ints(self):
        return [self.number('i') for _ in range(self.number('H'))]

    def texts(self):
        return [self.text() for _ in range(self.number('H'))]

@dataclass(frozen=True)
class Asset:
    kind: str
    path: str
    bundle: Path
    hash: str
    cached: bool
    raw: bool = False

@dataclass
class ImageResource:
    package: str
    asset: Asset
    category: str
    width: int | None = None
    height: int | None = None
    error: str = ''

    @property
    def key(self):
        return self.package + '/' + self.asset.path

    @property
    def screen_like(self):
        return bool(self.width and self.height and self.width >= 1000 and self.height >= 560
                    and 1.25 <= self.width / self.height <= 2.5)

    @property
    def name(self):
        return PurePosixPath(self.asset.path).name

@dataclass
class Pet:
    id: int
    assets: dict[str, Asset] = field(default_factory=dict)

    @property
    def category(self):
        return 'pets' if self.id < 10000 else 'skins' if self.id > 10000 else 'unknown'

    @property
    def paired(self):
        return all(k in self.assets and self.assets[k].cached for k in ('head', 'body'))

@dataclass
class Catalog:
    root: Path
    protected: Path
    version: str
    pets: list[Pet]
    ignored: int
    images: list[ImageResource] = field(default_factory=list)

def resolve_resource_root(value: str | Path) -> Path:
    folder = Path(value).expanduser().resolve()
    candidates = [folder, folder / 'yoo', folder / 'Seer_Data' / 'yoo',
                  folder.parent if folder.name == 'DefaultPackage' else folder]
    for candidate in candidates:
        if (candidate / 'DefaultPackage' / 'ManifestFiles').is_dir():
            return candidate
    raise ResourceError('未找到 DefaultPackage/ManifestFiles。请选择 NewSeer、Seer_Data 或 yoo 文件夹。')

def protected_root(root: Path) -> Path:
    if root.parent.name.lower().endswith('_data'):
        return root.parent.parent.resolve()
    return root.resolve()

def ensure_output(output: Path, protected: Path):
    output = output.expanduser().resolve()
    protected = protected.resolve()
    if output == protected or output.is_relative_to(protected):
        raise ResourceError('输出目录不能位于游戏目录中，请选择独立文件夹。')
    return output

def parse_manifest(file: Path):
    data = file.read_bytes()
    if len(data) > 100_000_000:
        raise ResourceError('资源清单过大')
    r = Reader(data)
    if r.number('I') != 0x00594F4F:
        raise ResourceError('不支持的清单标记；可能是加密清单')
    version = r.text()
    if version != '1.5.2':
        raise ResourceError(f'暂不支持清单格式 {version}，当前支持 NewSeer 1.5.2')
    flags = [r.number('B') for _ in range(3)]
    r.number('i')
    package, revision = r.text(), r.text()
    count = r.number('i')
    if not 0 <= count <= 1_000_000:
        raise ResourceError('无效的资源数量')
    assets = []
    # NewSeer compact format: no address/guid/tags when their flags are false.
    for _ in range(count):
        address = r.text() if flags[0] else ''
        path = r.text()
        guid = r.text() if flags[2] else ''
        bundle_id, dependencies = r.number('i'), r.ints()
        assets.append((path, bundle_id))
    bundles = []
    count = r.number('i')
    if not 0 <= count <= 100_000:
        raise ResourceError('无效的资源包数量')
    for _ in range(count):
        name, unity_crc = r.text(), r.number('I')
        hash_value, crc = r.text(), r.text()
        size, raw, load = r.number('q'), r.number('B'), r.number('B')
        refs = r.ints()
        if not re.fullmatch(r'[a-fA-F0-9]{32}', hash_value):
            raise ResourceError('无效的资源包哈希')
        bundles.append((hash_value, raw))
    if r.pos != len(data):
        raise ResourceError('清单格式与已支持版本不同，未执行提取')
    if any(not 0 <= i < len(bundles) for _, i in assets):
        raise ResourceError('清单中的资源包索引越界')
    return package, revision, assets, bundles

def package_manifest(root: Path, package: str):
    manifests = root / package / 'ManifestFiles'
    pointer = manifests / f'PackageManifest_{package}.version'
    if pointer.exists():
        revision = pointer.read_text(encoding='utf-8-sig').strip()
        if not re.fullmatch(r'\d{14}', revision):
            raise ResourceError('当前版本指针格式无效')
        manifest = manifests / f'PackageManifest_{package}_{revision}.bytes'
        if not manifest.exists():
            raise ResourceError(f'当前版本 {revision} 的清单不存在')
    else:
        choices = sorted(manifests.glob(f'PackageManifest_{package}_*.bytes'))
        if not choices:
            raise ResourceError('没有可用的资源清单')
        manifest = choices[-1]
    return manifest

def image_category(path: str):
    lower = path.lower()
    name = PurePosixPath(lower).stem
    if any(term in lower for term in ('/background/', '/roombg/', '/petadvback/')) or re.search(r'(?:^|[_ -])(?:bg|background)(?:[\d_ -]|$)', name):
        return 'background'
    if '/maps/' in lower:
        return 'scene'
    if any(term in lower for term in ('/mainstoryline/', '/autocard/texture/cards/', '/illustration/', '/cg/')):
        return 'illustration'
    return 'ui'

def scan(value: str | Path) -> Catalog:
    root = resolve_resource_root(value)
    package, revision, assets, bundles = parse_manifest(package_manifest(root, 'DefaultPackage'))
    if package != 'DefaultPackage':
        raise ResourceError('清单包名不匹配')
    pets: dict[int, Pet] = {}
    ignored = 0
    images = []
    def other_image(path, bundle_id, package, bundles):
        if PurePosixPath(path).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.tga', '.psd', '.bmp', '.tif', '.tiff'):
            return
        # All static pet portraits, including placeholders, belong to the pet page.
        if path.lower().startswith('assets/art/ui/assets/pet/'):
            return
        hash_value, raw = bundles[bundle_id]
        bundle = root / package / ('CacheRawFiles' if raw else 'CacheBundleFiles') / hash_value[:2] / hash_value / '__data'
        asset = Asset('image', path, bundle, hash_value, bundle.is_file(), bool(raw))
        images.append(ImageResource(package, asset, image_category(path)))
    for path, bundle_id in assets:
        match = re.fullmatch(r'Assets/Art/Ui/assets/pet/(head|body|half)/(\d+)\.(png|jpg|jpeg)', path, re.I)
        if not match:
            if path.lower().startswith('assets/art/ui/assets/pet/'):
                ignored += 1
            other_image(path, bundle_id, package, bundles)
            continue
        kind, number = match[1].lower(), int(match[2])
        if number <= 0:
            ignored += 1
            continue
        hash_value, raw = bundles[bundle_id]
        bundle = root / package / ('CacheRawFiles' if raw else 'CacheBundleFiles') / hash_value[:2] / hash_value / '__data'
        pets.setdefault(number, Pet(number)).assets[kind] = Asset(kind, path, bundle, hash_value, bundle.is_file(), bool(raw))
    if (root / 'StartupPackage' / 'ManifestFiles').is_dir():
        start_package, _, start_assets, start_bundles = parse_manifest(package_manifest(root, 'StartupPackage'))
        if start_package != 'StartupPackage':
            raise ResourceError('启动包清单包名不匹配')
        for path, bundle_id in start_assets:
            other_image(path, bundle_id, start_package, start_bundles)
    return Catalog(root, protected_root(root), revision, sorted(pets.values(), key=lambda p: p.id), ignored,
                   sorted(images, key=lambda item: item.key.lower()))

def load_images(bundle: Path):
    import UnityPy
    # Passing bytes prevents library filesystem resolution beside game files.
    data = bundle.read_bytes()
    if not data.startswith(b'UnityFS\0'):
        raise ResourceError('此文件不是可直接解析的 UnityFS 资源包')
    env = UnityPy.load(data)
    objects = {}
    for path, obj in env.container.items():
        key = path.replace('\\', '/').lower()
        if obj.type.name in ('Sprite', 'Texture2D'):
            previous = objects.get(key)
            if previous is None or obj.type.name == 'Sprite':
                objects[key] = obj
    return env, objects

def image_object(resource: ImageResource, objects):
    obj = objects.get(resource.asset.path.replace('\\', '/').lower())
    if obj is None:
        raise ResourceError('资源包中没有与清单路径匹配的图片对象')
    return obj

def image_dimensions(resource: ImageResource, objects):
    if resource.asset.raw:
        from PIL import Image
        with Image.open(io.BytesIO(resource.asset.bundle.read_bytes())) as image:
            return image.size
    obj = image_object(resource, objects)
    data = obj.read()
    if obj.type.name == 'Sprite':
        return round(data.m_Rect.width), round(data.m_Rect.height)
    return data.m_Width, data.m_Height

def preview_image(resource: ImageResource):
    if not resource.asset.cached:
        raise ResourceError('图片尚未在本地缓存')
    if resource.asset.raw:
        from PIL import Image
        image = Image.open(io.BytesIO(resource.asset.bundle.read_bytes()))
    else:
        env, objects = load_images(resource.asset.bundle)
        image = image_object(resource, objects).read().image
    width, height = image.size
    image.thumbnail((1000, 650))
    result = io.BytesIO()
    image.save(result, format='PNG')
    return dict(data=result.getvalue(), width=width, height=height)

def inspect_sizes(resources: list[ImageResource], cancel=None, progress=None):
    cancel = cancel or threading.Event()
    progress = progress or (lambda *args: None)
    groups = defaultdict(list)
    done = 0
    for resource in resources:
        if resource.width is not None:
            done += 1
        elif resource.asset.cached:
            groups[resource.asset.bundle].append(resource)
        else:
            resource.error = '尚未缓存'
            done += 1
    for bundle, items in groups.items():
        if cancel.is_set():
            break
        env = objects = None
        try:
            if not items[0].asset.raw:
                env, objects = load_images(bundle)
            for resource in items:
                if cancel.is_set():
                    break
                try:
                    resource.width, resource.height = image_dimensions(resource, objects)
                    resource.error = ''
                except Exception as error:
                    resource.error = str(error)
                done += 1
                progress(done, len(resources), f'读取尺寸 · {resource.name}')
        except Exception as error:
            for resource in items:
                resource.error = str(error)
                done += 1
                progress(done, len(resources), '资源包读取失败')
        finally:
            del env, objects
            gc.collect()
    return dict(inspected=sum(r.width is not None for r in resources),
                large=sum(r.screen_like for r in resources),
                failed=sum(bool(r.error) for r in resources), cancelled=cancel.is_set())

def other_destination(output: Path, resource: ImageResource):
    import hashlib
    def clean(segment):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', segment).rstrip(' .') or '_'
        if value.split('.')[0].upper() in ('CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))):
            value = '_' + value
        return value
    original = PurePosixPath(resource.asset.path)
    if original.is_absolute() or any(part in ('.', '..') for part in original.parts):
        raise ResourceError('资源路径不安全')
    suffix = hashlib.sha256(resource.key.encode('utf8')).hexdigest()[:16]
    return output / 'other' / clean(resource.package) / Path(*(clean(p) for p in original.parts[:-1])) / f'{clean(original.stem)}__{suffix}.png'

def export_images(catalog: Catalog, resources: list[ImageResource], output: Path,
                  skip_existing=True, cancel=None, progress=None):
    output = ensure_output(output, catalog.protected)
    output.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    progress = progress or (lambda *args: None)
    groups, rows = defaultdict(list), []
    def record(resource, status, destination='', error=''):
        rows.append(dict(package=resource.package, category=resource.category, source=resource.asset.path,
                         status=status, output=str(destination), width=resource.width or '', height=resource.height or '',
                         screen_candidate=resource.screen_like, hash=resource.asset.hash, error=error))
        progress(len(rows), len(resources), f'{resource.name} · {status}')
    for resource in resources:
        if cancel.is_set():
            break
        destination = ensure_output(other_destination(output, resource), catalog.protected)
        if not destination.is_relative_to(output):
            raise ResourceError('输出路径重定向到了输出文件夹之外')
        if not resource.asset.cached:
            record(resource, 'missing', error='资源尚未缓存')
        elif skip_existing and valid_png(destination):
            record(resource, 'skipped', destination)
        else:
            groups[resource.asset.bundle].append((resource, destination))
    for bundle, targets in groups.items():
        if cancel.is_set():
            break
        env = objects = None
        try:
            progress(len(rows), len(resources), f'读取资源包 · {len(targets)} 张图片')
            if not targets[0][0].asset.raw:
                env, objects = load_images(bundle)
        except Exception as error:
            for resource, _ in targets:
                record(resource, 'failed', error=str(error))
            continue
        for resource, destination in targets:
            if cancel.is_set():
                break
            temporary = destination.with_suffix('.png.part')
            try:
                ensure_output(temporary, catalog.protected)
                if not temporary.resolve().is_relative_to(output):
                    raise ResourceError('临时路径不在输出目录中')
                destination.parent.mkdir(parents=True, exist_ok=True)
                if resource.asset.raw:
                    from PIL import Image
                    image = Image.open(io.BytesIO(bundle.read_bytes()))
                else:
                    image = image_object(resource, objects).read().image
                resource.width, resource.height = image.size
                resource.error = ''
                image.save(temporary, format='PNG')
                temporary.replace(destination)
                record(resource, 'saved', destination)
            except Exception as error:
                if temporary.exists() and not temporary.is_symlink() and temporary.resolve().is_relative_to(output):
                    temporary.unlink()
                record(resource, 'failed', error=str(error))
        del env, objects
        gc.collect()
    completed = {(r['package'], r['source']) for r in rows}
    for resource in resources:
        if (resource.package, resource.asset.path) not in completed:
            record(resource, 'cancelled', error='已取消')
    report_dir = ensure_output(output / 'reports', catalog.protected)
    if not report_dir.is_relative_to(output):
        raise ResourceError('报告目录不在输出目录中')
    report_dir.mkdir(exist_ok=True)
    report = report_dir / f'images_{datetime.now():%Y%m%d_%H%M%S_%f}.csv'
    with report.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['package', 'category', 'source', 'status', 'output', 'width', 'height', 'screen_candidate', 'hash', 'error'])
        writer.writeheader()
        writer.writerows(rows)
    return dict(rows=rows, report=str(report), cancelled=cancel.is_set(),
                **{name: sum(row['status'] == name for row in rows) for name in ('saved', 'skipped', 'missing', 'failed')})

def preview(pet: Pet):
    for kind in ('body', 'head', 'half'):
        asset = pet.assets.get(kind)
        if asset and asset.cached:
            env, objects = load_images(asset.bundle)
            obj = objects.get(asset.path.lower())
            if obj is None:
                continue
            image = obj.read().image
            image.thumbnail((600, 600))
            output = io.BytesIO()
            image.save(output, format='PNG')
            return output.getvalue()
    raise ResourceError('这个编号没有可预览的本地静态图片')

def valid_png(path: Path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format != 'PNG':
                return False
            image.verify()
        return True
    except (OSError, ValueError):
        return False

def export(catalog: Catalog, pets: list[Pet], output: Path, include_half=False,
           skip_existing=True, cancel: threading.Event | None = None,
           progress: Callable[[int, int, str], None] | None = None):
    output = ensure_output(output, catalog.protected)
    output.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    progress = progress or (lambda *args: None)
    kinds = ('head', 'body', 'half') if include_half else ('head', 'body')
    rows, groups = [], defaultdict(list)
    total, done = len(pets) * len(kinds), 0
    def record(pet, kind, status, destination='', error=''):
        nonlocal done
        asset = pet.assets.get(kind)
        rows.append(dict(id=pet.id, category=pet.category, kind=kind, status=status,
                         output=str(destination), source=asset.path if asset else '',
                         hash=asset.hash if asset else '', error=error))
        done += 1
        progress(done, total, f'{pet.id} · {kind} · {status}')
    for pet in pets:
        for kind in kinds:
            if cancel.is_set():
                break
            asset = pet.assets.get(kind)
            destination = ensure_output(output / pet.category / str(pet.id) / f'{kind}.png', catalog.protected)
            if not destination.is_relative_to(output):
                raise ResourceError('输出子目录重定向到了输出文件夹之外')
            if asset is None:
                record(pet, kind, 'missing', error='当前清单没有此资源')
            elif not asset.cached:
                record(pet, kind, 'missing', error='资源尚未在本地缓存')
            elif skip_existing and valid_png(destination):
                record(pet, kind, 'skipped', destination)
            else:
                groups[asset.bundle].append((pet, kind, asset, destination))
    for bundle, tasks in groups.items():
        if cancel.is_set():
            break
        env = objects = None
        try:
            progress(done, total, f'读取资源包 · {len(tasks)} 张图片')
            env, objects = load_images(bundle)
        except Exception as error:
            for pet, kind, asset, destination in tasks:
                record(pet, kind, 'failed', error=str(error))
            continue
        for pet, kind, asset, destination in tasks:
            if cancel.is_set():
                break
            temporary = destination.with_suffix('.png.part')
            try:
                ensure_output(temporary, catalog.protected)
                if not temporary.resolve().is_relative_to(output):
                    raise ResourceError('临时输出文件重定向到了输出目录之外')
                destination.parent.mkdir(parents=True, exist_ok=True)
                ensure_output(destination.resolve(), catalog.protected)
                obj = objects.get(asset.path.lower())
                if obj is None:
                    raise ResourceError('资源包中没有与清单路径匹配的图片对象')
                image = obj.read().image
                image.save(temporary, format='PNG')
                temporary.replace(destination)
                record(pet, kind, 'saved', destination)
            except Exception as error:
                if temporary.exists() and not temporary.is_symlink() and temporary.resolve().is_relative_to(output):
                    temporary.unlink()
                record(pet, kind, 'failed', error=str(error))
        del objects, env
        gc.collect()
    # Mark every unfinished target explicitly; keep a useful report after cancel.
    completed = {(r['id'], r['kind']) for r in rows}
    for pet in pets:
        for kind in kinds:
            if (pet.id, kind) not in completed:
                rows.append(dict(id=pet.id, category=pet.category, kind=kind, status='cancelled', output='', source='', hash='', error='已取消'))
    report_dir = ensure_output(output / 'reports', catalog.protected)
    if not report_dir.is_relative_to(output):
        raise ResourceError('报告目录重定向到了输出文件夹之外')
    report_dir.mkdir(exist_ok=True)
    report = report_dir / f'export_{datetime.now():%Y%m%d_%H%M%S_%f}.csv'
    with report.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'category', 'kind', 'status', 'output', 'source', 'hash', 'error'])
        writer.writeheader()
        writer.writerows(rows)
    return dict(rows=rows, report=str(report), cancelled=cancel.is_set(),
                saved=sum(r['status'] == 'saved' for r in rows),
                skipped=sum(r['status'] == 'skipped' for r in rows),
                missing=sum(r['status'] == 'missing' for r in rows),
                failed=sum(r['status'] == 'failed' for r in rows))
