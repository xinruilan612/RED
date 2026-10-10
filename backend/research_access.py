"""Collection boundary for domains whose current terms prohibit our automation.

Search-engine snippets remain discovery leads. Do not equate a public URL, a
login session or an open-source scraper license with data collection permission.
"""
from urllib.parse import urlsplit
from backend.contracts import require
from backend.sources import public_url


def require_readable_source(url):
    url = public_url(url)
    host = (urlsplit(url).hostname or '').lower()
    restricted = ('xiaohongshu.com', 'xhslink.com', 'xhslink.cn')
    require(not any(host == d or host.endswith('.' + d) for d in restricted),
            'SOURCE_PERMISSION_REQUIRED',
            '尚无获授权的小红书自动读取通道；搜索结果仅作线索。可使用有权研究的资料，不会尝试绕过平台限制。')
    return url
