"""Account-isolated original SKAPP inference bridge; no torch in the web process."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import threading

from backend.topic_encoder import MODEL_NAME

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / 'runtime/skapp/personal'
PYTHON = ROOT / 'runtime/skapp/venv/bin/python'
SCRIPT = ROOT / 'scripts/skapp_personal.py'
VENDOR = ROOT / 'third_party/skapp/src'
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 180
MAX_BYTES = 1_000_000
METHOD = 'upstream_skapp_personal'
_LOCK = threading.BoundedSemaphore(1)


def scope_digest(owner, account_id):
    if not all(isinstance(v, str) and v and len(v) <= 500 and '\0' not in v for v in (owner, account_id)):
        raise ValueError('scope')
    return hashlib.sha256((owner + '\0' + account_id).encode()).hexdigest()


def _state(status, message):
    return dict(available=False, status=status, method=METHOD, message=message, predictions=[])


def _read(path):
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('file')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('size')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('object')
    return data


def _context(owner, account_id, config):
    digest = scope_digest(owner, account_id)
    if not isinstance(config, dict) or config.get('metric') not in ('views', 'likes', 'saves', 'comments') or config.get('window') not in ('24h', '72h'):
        raise ValueError('config')
    return digest, BUNDLES / digest, config['metric'], int(config['window'][:-1])


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _file_digest(path):
    if path.is_symlink() or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError('artifact')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise ValueError('artifact size')
            digest.update(chunk)
    return digest.hexdigest()


def _verify_artifacts(bundle, manifest):
    files = manifest.get('files')
    upstream = manifest.get('upstream_sha256')
    if manifest.get('method') != METHOD or not isinstance(files, dict) or set(files) != {'weights.pt', 'references.json'}:
        raise ValueError('artifact manifest')
    if not isinstance(upstream, dict) or set(upstream) != {'model.py', 'teachers.py', 'teacher_graph.py'}:
        raise ValueError('architecture manifest')
    for base, entries in ((bundle, files), (VENDOR, upstream)):
        for name, digest in entries.items():
            if not _valid_digest(digest) or _file_digest(base / name) != digest:
                raise ValueError('artifact mismatch')


def availability(owner, account_id, config):
    try:
        digest, bundle, metric, window = _context(owner, account_id, config)
        if not (bundle / 'manifest.json').exists():
            return _state('not_trained', '此账号尚未训练 SKAPP 模型。需要带封面和同一观察时长数据的真实历史作品。')
        if bundle.is_symlink() or bundle.resolve().parent != BUNDLES.resolve():
            raise ValueError('scope')
        manifest = _read(bundle / 'manifest.json')
        expected = dict(schema_version=1, scope_digest=digest, encoder_id=MODEL_NAME, feature_dim=512, target_metric=metric, window_hours=window)
        if any(manifest.get(k) != v for k, v in expected.items()):
            return _state('incompatible', '模型与当前账号、图文模型或统计口径不一致，需要重新训练。')
        history_digest = config.get('_training_history_digest')
        if not _valid_digest(history_digest) or manifest.get('training_history_digest') != history_digest:
            return _state('stale_history', '历史作品或账号定位已变化，请重新导出数据并训练 SKAPP 模型。')
        if manifest.get('synthetic') or manifest.get('ready_for_prediction') is not True:
            return _state('trained_unvalidated', '账号模型已训练，但独立验证尚未通过，暂不输出热度预测。')
        if not PYTHON.is_file() or not SCRIPT.is_file():
            return _state('unavailable', '本机 SKAPP 运行环境尚未就绪。')
        _verify_artifacts(bundle, manifest)
        return dict(available=True, status='ready', method=METHOD, target_metric=metric, window_hours=window,
                    message='已安装此账号的 SKAPP 模型；预测效果请结合独立验证结果判断。')
    except (OSError, ValueError, TypeError, RecursionError):
        return _state('unavailable', 'SKAPP 模型暂不可读取，请检查训练结果。')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value):
    return isinstance(value, list) and len(value) == 512 and all(_number(v) for v in value) and .98 <= sum(v*v for v in value) <= 1.02


def _safe_validation(value):
    """Only numeric evaluation evidence crosses the subprocess boundary."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ('samples', 'train_samples', 'valid_samples', 'test_samples', 'MAE', 'MSE', 'SRC', 'mae', 'mse', 'spearman', 'baseline_mae', 'baseline_mse'):
        v = value.get(key)
        if _number(v):
            result[key] = v
    for split in ('train', 'valid', 'test'):
        source = value.get(split)
        if isinstance(source, dict):
            result[split] = {k: source[k] for k in ('count', 'log1p_mse', 'constant_log1p_mse') if _number(source.get(k))}
    return result


def predict(owner, account_id, config, candidates, encoder):
    state = availability(owner, account_id, config)
    if not state['available']:
        return state
    if encoder != MODEL_NAME:
        return _state('incompatible', '当前图文编码模型与 SKAPP 训练模型不一致，请重新训练。')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
        return _state('invalid_input', '每次预测 1 至 5 个选题。')
    rows = []
    for row in candidates:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not 1 <= len(row['id']) <= 100:
            return _state('invalid_input', '选题标识无效，请重新填写。')
        if row.get('image_vector') is None:
            return _state('missing_cover', 'SKAPP 图文预测需要每个选题的封面，请先补充封面。')
        if not _vector(row.get('text_vector')) or not _vector(row.get('image_vector')):
            return _state('invalid_input', '选题图文特征无效，请重新比较。')
        rows.append(dict(id=row['id'], textual=row['text_vector'], visual=row['image_vector']))
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids):
        return _state('invalid_input', '选题标识不能重复。')
    if not _LOCK.acquire(blocking=False):
        return _state('busy', '正在进行另一批 SKAPP 预测，请稍后重试。')
    try:
        digest, bundle, metric, window = _context(owner, account_id, config)
        payload = dict(schema_version=1, scope_digest=digest, encoder_id=encoder, target_metric=metric, window_hours=window, training_history_digest=config['_training_history_digest'], candidates=rows)
        with tempfile.TemporaryDirectory(prefix='youji-skapp-') as directory:
            input_path, output_path = Path(directory) / 'input.json', Path(directory) / 'output.json'
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if len(raw.encode()) > MAX_BYTES:
                raise ValueError('input size')
            input_path.write_text(raw, encoding='utf-8')
            completed = subprocess.run([str(PYTHON), str(SCRIPT), 'predict', '--bundle', str(bundle), '--input', str(input_path), '--output', str(output_path)],
                                       cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS, check=False)
            if completed.returncode:
                raise ValueError('process')
            result = _read(output_path)
        if result.get('schema_version') != 1 or result.get('status') != 'predicted' or result.get('method') != METHOD or result.get('target_metric') != metric or result.get('window_hours') != window:
            raise ValueError('contract')
        predictions = result.get('candidates')
        if not isinstance(predictions, list) or len(predictions) != len(ids) or any(not isinstance(r, dict) for r in predictions):
            raise ValueError('predictions')
        if [r.get('id') for r in predictions] != ids:
            raise ValueError('ids')
        clean = []
        for row in predictions:
            value = row.get('predicted_value')
            if not _number(value) or value < 0 or value > 1e15:
                raise ValueError('prediction')
            refs = row.get('reference_ids', [])
            if not isinstance(refs, list) or len(refs) > 100 or any(not isinstance(v, str) or len(v) > 200 for v in refs):
                raise ValueError('refs')
            item = dict(id=row['id'], predicted_value=value, reference_ids=refs)
            for key in ('rrcp', 'attention'):
                values = row.get(key, [])
                if not isinstance(values, list) or len(values) != len(refs) or len(values) > 100 or any(not _number(v) or abs(v) > 1e10 for v in values):
                    raise ValueError('weights')
                item[key] = values
            if not refs or any(v < 0 for v in item['attention']) or abs(sum(item['attention']) - 1.) > .001:
                raise ValueError('attention')
            clean.append(item)
        return dict(available=True, status='ready', method=METHOD, predictions=clean, target_metric=metric, window_hours=window, metric=metric, window=f'{window}h',
                    validation=_safe_validation(result.get('validation')), message='SKAPP 模型预测，仅供选题比较，不保证实际流量。')
    except subprocess.TimeoutExpired:
        return _state('timeout', 'SKAPP 预测耗时较长，请稍后重试。')
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return _state('unavailable', 'SKAPP 预测未完成，请检查模型或重新训练。')
    finally:
        _LOCK.release()
