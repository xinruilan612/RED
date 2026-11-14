"""Offline OCR child process. Input: normalized image bytes; output: JSON lines."""
import json
import sys


def main():
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    result, _ = engine(sys.stdin.buffer.read(3_000_001))
    lines = [str(row[1])[:1000] for row in (result or []) if float(row[2]) >= .6][:100]
    sys.stdout.buffer.write(json.dumps(lines, ensure_ascii=True).encode('ascii'))


if __name__ == '__main__':
    main()
