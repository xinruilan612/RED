"""Disposable PDF parser process: bounded CPU, address space and extracted text."""
import io
import json
import sys


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(8,8))
        try: resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        except (ValueError,OSError): pass  # Some macOS builds do not enforce AS.
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
        print(json.dumps({'pages':pages},ensure_ascii=False))
    except BaseException:
        print(json.dumps({'error':'无法读取 PDF，请使用未加密的文本型 PDF（最多50页 / 10万字符）；扫描件暂不支持 OCR'},ensure_ascii=False))


if __name__=='__main__': main()
