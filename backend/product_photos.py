"""Small verified local product photo catalogue; never fetch untrusted URLs."""
import base64
import re
from pathlib import Path

PHOTO_PATH = Path(__file__).resolve().parent.parent / 'frontend/assets/products/logitech-m185.jpg'
PHOTO = {
    'id': 'logitech-m185-hs05', 'name': 'Logitech M185 mouse HS05',
    'author': 'Hayden Schiff', 'license': 'CC BY 4.0',
    'license_url': 'https://creativecommons.org/licenses/by/4.0/',
    'source_url': 'https://commons.wikimedia.org/wiki/File:Logitech_M185_mouse_HS05.jpg',
    'modifications': '按图卡布局等比例缩放，未生成或替换产品外观。',
}


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
    effective['cover_image'] = 'data:image/jpeg;base64,' + base64.b64encode(PHOTO_PATH.read_bytes()).decode('ascii')
    return effective, dict(PHOTO)


def attribution(photo):
    if not photo:
        return ''
    return ('产品照片：' + photo['name'] + '\n作者：' + photo['author'] +
            '\n来源：' + photo['source_url'] + '\n许可：' + photo['license'] + '（' +
            photo['license_url'] + '）\n处理说明：' + photo['modifications'] + '\n')
