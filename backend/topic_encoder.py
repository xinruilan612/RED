"""Bounded offline subprocess bridge; the website never imports torch."""
import json
import math
from pathlib import Path
import subprocess
import threading

from backend.python_runtime import venv_python

ROOT = Path(__file__).resolve().parents[1]
PYTHON = venv_python(ROOT / 'runtime/skapp/venv')
SCRIPT = ROOT / 'scripts/topic_encode.py'
MODEL_PATH = ROOT / 'runtime/skapp/chinese-clip'
MODEL_NAME = 'OFA-Sys/chinese-clip-vit-base-patch16'
_LOCK = threading.BoundedSemaphore(1)
TIMEOUT_SECONDS = 180
MAX_INPUT_BYTES = 32 * 1024 * 1024


class TopicEncoderError(ValueError):
    """Safe message suitable for a noncritical user notice."""


def availability():
    ready = PYTHON.is_file() and (MODEL_PATH / 'config.json').is_file() and (MODEL_PATH / 'model.safetensors').is_file()
    return {'ready': ready, 'model': MODEL_NAME, 'message': '本机中文图文模型已安装。' if ready else '请先安装本机中文图文模型，安装后即可分析。'}


def encode(texts, images=None):
    from scripts.topic_encode import validate_payload
    payload = {'texts': texts, 'images': images if images is not None else []}
    try:
        validate_payload(payload)
    except ValueError as exc:
        raise TopicEncoderError(str(exc)) from None
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw.encode('utf-8')) > MAX_INPUT_BYTES:
        raise TopicEncoderError('本次图片总量过大，请减少图片。')
    if not availability()['ready']:
        raise TopicEncoderError('请先安装本机中文图文模型，安装后即可分析。')
    if not _LOCK.acquire(blocking=False):
        raise TopicEncoderError('正在分析另一批图文，请稍后再试。')
    try:
        try:
            completed = subprocess.run([str(PYTHON), str(SCRIPT)], input=raw, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=str(ROOT), check=False)
        except subprocess.TimeoutExpired:
            raise TopicEncoderError('图文分析耗时较长，请减少候选内容后重试。') from None
        except OSError:
            raise TopicEncoderError('图文模型暂时不可用，请稍后重试。') from None
        try:
            result = json.loads(completed.stdout)
            if not isinstance(result, dict) or completed.returncode:
                raise ValueError()
            if result.get('model') != MODEL_NAME or result.get('dimension') != 512:
                raise ValueError()
            for key, count in (('text_vectors', len(texts)), ('image_vectors', len(payload['images']))):
                vectors = result.get(key)
                if not isinstance(vectors, list) or len(vectors) != count:
                    raise ValueError()
                for vector in vectors:
                    if not isinstance(vector, list) or len(vector) != 512 or any(type(x) not in (float, int) or not math.isfinite(x) for x in vector):
                        raise ValueError()
                    if not 0.99 <= sum(x*x for x in vector) <= 1.01:
                        raise ValueError()
        except (ValueError, TypeError):
            if completed.returncode and isinstance(locals().get('result'), dict) and str(result.get('error', '')).startswith('图片无效。'):
                raise TopicEncoderError('图片无效，请使用不超过 3 MB、1600 万像素的静态 JPG、PNG 或 WebP。') from None
            raise TopicEncoderError('图文分析未完成，请检查模型或换一张图片重试。') from None
        return {key: result[key] for key in ('model', 'dimension', 'text_vectors', 'image_vectors')}
    finally:
        _LOCK.release()
