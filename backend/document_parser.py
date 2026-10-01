"""Disposable PDF parser; Unix resource limits supplement the parent timeout."""
import io
import json
import sys


def apply_resource_limits():
    """Keep Unix protections when available; Windows uses the parent timeout.

    Input, page and extracted-text limits below still apply on every platform.
    Windows does not provide resource, so CPU/address-space limits are Unix-only.
    """
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (768*1024*1024, 768*1024*1024))
    except (ValueError, OSError):
        pass  # Some macOS builds do not enforce AS.


def main():
    try:
        apply_resource_limits()
        from pypdf import PdfReader
        raw=sys.stdin.buffer.read(3_000_001)
        if len(raw)>3_000_000: raise ValueError()
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages)>50: raise ValueError()
        pages=[];total=0
        for number,page in enumerate(reader.pages,1):
            text=page.extract_text(extraction_mode='plain') or ''
            total+=len(text)
            if total>100_000: raise ValueError()
            pages.append((number,text))
        # ASCII JSON remains valid UTF-8 even with Windows' legacy pipe encoding.
        print(json.dumps({'pages':pages},ensure_ascii=True))
    except BaseException:
        print(json.dumps({'error':'无法读取 PDF，请使用未加密的文本型 PDF（最多50页 / 10万字符）；扫描件暂不支持 OCR'},ensure_ascii=True))


if __name__=='__main__': main()
