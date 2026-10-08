"""Small verified local product photo catalogue; never fetch untrusted URLs."""
import base64
import hashlib
import re
from pathlib import Path

PHOTO_PATH = Path(__file__).resolve().parent.parent / 'frontend/assets/products/logitech-m185.jpg'
PHOTO = {
    'id': 'logitech-m185-hs05', 'view_label': '侧前方外观', 'name': 'Logitech M185 mouse HS05',
    'author': 'Hayden Schiff', 'license': 'CC BY 4.0',
    'license_url': 'https://creativecommons.org/licenses/by/4.0/',
    'source_url': 'https://commons.wikimedia.org/wiki/File:Logitech_M185_mouse_HS05.jpg',
    'modifications': '按图卡布局等比例缩放，未生成或替换产品外观。',
}


# Order is intentional: side view, top view, underside.
CATALOG = [(PHOTO_PATH, PHOTO)] + [
    (PHOTO_PATH.with_name('logitech-m185-' + filename + '.jpg'), {
        **PHOTO, 'id': 'logitech-m185-' + suffix.lower(),
        'name': 'Logitech M185 mouse ' + suffix,
        'view_label': '俯视外观' if suffix == 'HS01' else '底部细节',
        'source_url': 'https://commons.wikimedia.org/wiki/File:Logitech_M185_mouse_' + suffix + '.jpg',
    }) for suffix, filename in (('HS01', 'top'), ('HS06', 'bottom'))]


def catalog_images(photo):
    """Resolve only server-owned catalogue IDs, never client paths or URLs."""
    from backend.card_layout import normalize_options
    images = []
    for item in (photo or {}).get('photos', []):
        entry = next(((path, info) for path, info in CATALOG if info['id'] == item['id']), None)
        if entry:
            raw = entry[0].read_bytes()
            options = {'cover_image': 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')}
            _, image = normalize_options(options)
            images.append(image)
    return images


def photo_identity(normalized, photo):
    if photo:
        normalized['photos'] = [{k: item[k] for k in ('id', 'sha256')} for item in photo.get('photos', [])]
    return normalized


def resolve_options(snapshot, options=None):
    """Use a catalogue photo only for explicit adjacent brand/model mentions."""
    if not isinstance(options, (dict, type(None))):
        return options, None  # The shared option validator supplies the domain error.
    effective = dict(options or {})
    if effective.get('cover_image') is not None or effective.get('product_photo') == 'none':
        return effective, None
    content = snapshot['content']
    text = '\n'.join(str(content.get(k, '')) for k in ('selected_title', 'body'))
    # Do not match M1850, M185S or a different brand's M185; do not infer a
    # product from tags, research context or a merely similar model number.
    match = re.search(r'(?:罗技|(?<![A-Za-z])Logitech)\s*[·：:]?\s*M185(?![A-Za-z0-9_-])', text, re.I)
    if not match or not PHOTO_PATH.is_file():
        return effective, None
    photos, seen = [], set()
    for path, info in CATALOG:
        if not path.is_file(): continue
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha in seen: continue
        seen.add(sha)
        photos.append({**info, 'sha256': sha})
    effective['cover_image'] = 'data:image/jpeg;base64,' + base64.b64encode(PHOTO_PATH.read_bytes()).decode('ascii')
    return effective, {**PHOTO, 'photos': photos}


def attribution(photo):
    if not photo:
        return ''
    if photo.get('photos'):
        return '\n'.join(attribution(item) for item in photo['photos'])
    return ('产品照片：' + photo['name'] + '\n作者：' + photo['author'] +
            '\n来源：' + photo['source_url'] + '\n许可：' + photo['license'] + '（' +
            photo['license_url'] + '）\n处理说明：' + photo['modifications'] + '\n')
