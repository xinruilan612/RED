#!/usr/bin/env python3
"""Offline Chinese-CLIP feature extraction. JSON stdin/stdout, no user files."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / 'runtime/skapp/chinese-clip'
MODEL_NAME = 'OFA-Sys/chinese-clip-vit-base-patch16'
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_INPUT_BYTES = 32 * 1024 * 1024


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('请求内容无效。')
    texts, images = payload.get('texts', []), payload.get('images', [])
    if not isinstance(texts, list) or not isinstance(images, list) or len(texts) > 128 or len(images) > 64:
        raise ValueError('一次最多处理 128 段文字和 64 张图片。')
    if not texts and not images:
        raise ValueError('请添加文字或图片。')
    if any(not isinstance(t, str) or not t.strip() or len(t) > 10000 for t in texts):
        raise ValueError('文字不能为空，且每段不能超过 10000 字。')
    if any(not isinstance(i, str) or len(i) > 4 * MAX_IMAGE_BYTES // 3 + 4 for i in images):
        raise ValueError('每张图片不能超过 3 MB。')
    return texts, images


def decode_image(value):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as check:
                if check.format not in ('PNG', 'JPEG', 'WEBP') or check.width * check.height > MAX_PIXELS:
                    raise ValueError()
                if getattr(check, 'n_frames', 1) != 1:
                    raise ValueError()
                check.verify()
            with Image.open(io.BytesIO(raw)) as opened:
                rgb = ImageOps.exif_transpose(opened).convert('RGB')
                # A fresh image strips EXIF, ICC, comments and all other metadata.
                clean = Image.new('RGB', rgb.size)
                clean.paste(rgb)
                return clean
    except Exception:
        raise ValueError('图片无效。请使用不超过 3 MB、1600 万像素的静态 JPG、PNG 或 WebP。') from None


def chunk_token_ids(tokenizer, text, capacity):
    """Preserve every token; no silent truncation of long posts."""
    ids = tokenizer.encode(text, add_special_tokens=False, truncation=False)
    if not ids:
        raise ValueError('文字没有可识别的内容。')
    return [ids[start:start + capacity] for start in range(0, len(ids), capacity)]


def encode_payload(payload):
    texts, encoded_images = validate_payload(payload)
    images = [decode_image(value) for value in encoded_images]
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    import torch
    from transformers import ChineseCLIPModel, ChineseCLIPProcessor
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    processor = ChineseCLIPProcessor.from_pretrained(str(MODEL_PATH), local_files_only=True, trust_remote_code=False)
    model = ChineseCLIPModel.from_pretrained(str(MODEL_PATH), local_files_only=True, trust_remote_code=False, use_safetensors=True)
    model.eval()
    dimension = model.config.projection_dim
    capacity = model.config.text_config.max_position_embeddings - processor.tokenizer.num_special_tokens_to_add(pair=False)
    if capacity < 1:
        raise RuntimeError('invalid model configuration')
    result = {'model': MODEL_NAME, 'dimension': dimension, 'text_vectors': [], 'image_vectors': [], 'text_chunks': []}
    with torch.inference_mode():
        for text in texts:
            chunks = chunk_token_ids(processor.tokenizer, text, capacity)
            vectors = []
            weights = []
            for start in range(0, len(chunks), 8):
                group = chunks[start:start + 8]
                prepared = [processor.tokenizer.prepare_for_model(ids, add_special_tokens=True, truncation=False, return_attention_mask=True) for ids in group]
                inputs = processor.tokenizer.pad(prepared, padding=True, return_tensors='pt')
                features = model.get_text_features(**inputs)
                vectors.append(torch.nn.functional.normalize(features, dim=-1))
                weights.extend(len(ids) for ids in group)
            all_features = torch.cat(vectors)
            weight_tensor = torch.tensor(weights, dtype=all_features.dtype).unsqueeze(-1)
            pooled = (all_features * weight_tensor).sum(0) / weight_tensor.sum()
            result['text_vectors'].append(torch.nn.functional.normalize(pooled, dim=0).tolist())
            result['text_chunks'].append(len(chunks))
        for start in range(0, len(images), 8):
            inputs = processor(images=images[start:start + 8], return_tensors='pt')
            features = model.get_image_features(**inputs)
            result['image_vectors'].extend(torch.nn.functional.normalize(features, dim=-1).tolist())
    return result


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('本次图片总量过大，请减少图片。')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('请求内容无效。') from None
        validate_payload(payload)
        result = encode_payload(payload)
    except ValueError as exc:
        # Only validation messages defined here may be shown, never library errors.
        known = ('请求内容无效。', '一次最多处理 128 段文字和 64 张图片。', '请添加文字或图片。', '文字不能为空，且每段不能超过 10000 字。', '每张图片不能超过 3 MB。', '图片无效。请使用不超过 3 MB、1600 万像素的静态 JPG、PNG 或 WebP。', '文字没有可识别的内容。', '本次图片总量过大，请减少图片。')
        message = str(exc) if str(exc) in known else '图文模型暂时不可用，请检查本机模型配置。'
        print(json.dumps({'error': message}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({'error': '图文模型暂时不可用，请检查本机模型配置。'}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
