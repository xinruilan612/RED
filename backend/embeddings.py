"""Optional real local semantic embeddings; never download or call paid APIs.

A local sentence-transformers installation and model directory are explicit
operator prerequisites. Without them retrieval remains honestly labelled BM25.
"""
import hashlib
import json
import math
from collections import OrderedDict
import os
from functools import lru_cache
from pathlib import Path
from threading import RLock


class EmbeddingUnavailable(Exception):
    pass


@lru_cache(maxsize=2)
def _load_model(path):
    try:
        os.environ.setdefault('HF_HOME',str(Path(__file__).resolve().parents[1]/'runtime/huggingface'))
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(path, local_files_only=True, trust_remote_code=False, device='cpu', model_kwargs={'use_safetensors':True})
    except Exception:
        raise EmbeddingUnavailable('本地向量模型或依赖不可用；请配置已下载并核验的模型') from None


class LocalEmbeddings:
    """Compute bounded, normalized vectors using a preinstalled local model."""
    name = 'sentence-transformers-local'
    max_chunks = 256
    minimum_similarity = 0.40
    _lock = RLock()
    _cache = OrderedDict()

    def __init__(self, model_path):
        path = Path(model_path).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise EmbeddingUnavailable('本地向量模型路径不存在；当前使用 BM25')
        self.path = str(path.resolve())
        self.model_id = path.name
        manifest=path/'youji-model-manifest.json'
        self.revision=hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else 'operator-local-model'
        self.cache_key=(self.path,self.revision)

    def encode(self, texts):
        if not isinstance(texts, list) or not texts or len(texts) > self.max_chunks + 1:
            raise EmbeddingUnavailable('向量候选数量超过本地处理上限')
        if not all(isinstance(t, str) and len(t) <= 1000 for t in texts):
            raise EmbeddingUnavailable('向量输入长度超限')
        with self._lock:
            keys=[(*self.cache_key,hashlib.sha256(text.encode()).hexdigest()) for text in texts]
            missing=list(dict.fromkeys(key for key in keys if key not in self._cache))
            by_key=dict(zip(keys,texts))
            if missing:
                try:
                    vectors=_load_model(self.path).encode([by_key[key] for key in missing], batch_size=16,
                        normalize_embeddings=True, show_progress_bar=False).tolist()
                    vectors=validated_vectors(vectors,len(missing))
                except EmbeddingUnavailable:
                    raise
                except Exception:
                    raise EmbeddingUnavailable('本地向量计算失败；当前使用 BM25') from None
                for key,vector in zip(missing,vectors):
                    self._cache[key]=vector
            result=[self._cache[key] for key in keys]
            for key in keys:
                self._cache.move_to_end(key)
            while len(self._cache)>1024:
                self._cache.popitem(last=False)
            return result



def configured_embeddings():
    path = os.environ.get('YOUJI_EMBEDDING_MODEL_PATH', '').strip()
    if path.lower() in ('off','disabled','none'):
        return None, '本地语义检索已关闭，使用 BM25'
    if not path:
        candidate=Path(__file__).resolve().parents[1]/'runtime/models/bge-small-zh-v1.5'
        if (candidate/'youji-model-manifest.json').is_file():
            path=str(candidate)
    if not path:
        return None, '未配置本地语义模型，使用 BM25 关键词检索'
    try:
        return LocalEmbeddings(path), ''
    except EmbeddingUnavailable as error:
        return None, str(error)
    except OSError:
        return None, '本地模型目录不可读取，使用 BM25'


def validated_vectors(vectors, count):
    if not isinstance(vectors, (list, tuple)) or len(vectors) != count:
        raise EmbeddingUnavailable('向量模型返回数量不匹配')
    result = []
    dimension = None
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not vector or len(vector) > 8192:
            raise EmbeddingUnavailable('向量维度无效')
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise EmbeddingUnavailable('向量数值或维度无效')
        norm = math.sqrt(sum(x*x for x in vector))
        if not math.isfinite(norm) or norm == 0:
            raise EmbeddingUnavailable('向量归一化失败')
        result.append([x/norm for x in vector])
    return result


def semantic_ranks(provider, query, rows):
    """rows must already be authorized and restricted to active versions."""
    if len(rows) > provider.max_chunks:
        raise EmbeddingUnavailable('当前资料块超过本地语义上限；缩小资料范围后重试，当前使用 BM25')
    if not rows:
        return [], {}
    vectors = validated_vectors(provider.encode([query] + [row[5] for row in rows]), len(rows)+1)
    scores = {row[0]: sum(a*b for a,b in zip(vectors[0], vector))
              for row,vector in zip(rows,vectors[1:])}
    order = sorted((key for key,value in scores.items() if value >= provider.minimum_similarity),
                   key=lambda key: (-scores[key],key))
    return order, scores
