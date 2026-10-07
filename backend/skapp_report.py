"""Read a bounded, local SKAPP public-benchmark report; never run model code."""
import json
import math
import re
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parents[1] / 'runtime' / 'skapp' / 'result.json'
MAX_BYTES = 4_000_000


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _metrics(value, allow_undefined_rank=False):
    if not isinstance(value, dict):
        raise ValueError('metrics')
    result = {}
    for key in ('MSE', 'MAE', 'SRC'):
        x = value.get(key)
        if key == 'SRC' and x is None and allow_undefined_rank:
            result[key] = None
            continue
        if not _number(x) or (key != 'SRC' and x < 0) or (key == 'SRC' and not -1 <= x <= 1):
            raise ValueError('metric')
        result[key] = x
    n = value.get('samples')
    if type(n) is not int or not 0 < n <= 100_000_000:
        raise ValueError('samples')
    result['samples'] = n
    return result


def read_report():
    """Return only public benchmark fields, never local paths or exception text."""
    try:
        if not REPORT_PATH.exists():
            return {'status': 'not_trained', 'message': '尚未完成本机训练与评估。完成后，这里会显示真实实验结果。'}
        if REPORT_PATH.is_symlink() or REPORT_PATH.stat().st_size > MAX_BYTES:
            raise ValueError('file')
        with REPORT_PATH.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('size')
        data = json.loads(raw)
        if data.get('status') != 'ready' or data.get('scope') != 'public_benchmark':
            raise ValueError('scope')
        commit = data.get('upstream_commit', '')
        if not isinstance(commit, str) or not re.fullmatch(r'[a-f0-9]{7,40}', commit):
            raise ValueError('provenance')
        if data.get('dataset') not in ('icip', 'smpd', 'instagram'):
            raise ValueError('dataset')
        metrics = _metrics(data.get('metrics'))
        baseline = None
        if data.get('baseline'):
            source = data['baseline']
            baseline = _metrics({**source, 'samples': source.get('samples', metrics['samples'])}, allow_undefined_rank=True)
            if baseline['samples'] != metrics['samples']:
                raise ValueError('baseline samples')
            baseline['name'] = str(source.get('name', '对照模型'))[:120]
        rows = data.get('predictions', [])
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError('predictions')
        predictions = []
        for row in rows:
            if not isinstance(row, dict) or not _number(row.get('actual')) or not _number(row.get('predicted')):
                raise ValueError('prediction')
            identifier = row.get('id')
            if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
                raise ValueError('id')
            predictions.append({'id': str(identifier)[:200], 'actual': row['actual'], 'predicted': row['predicted']})
        if len(predictions) > metrics['samples']:
            raise ValueError('prediction count')
        training = {}
        source = data.get('training', {})
        if not isinstance(source, dict):
            raise ValueError('training')
        for key in ('seed', 'epochs', 'train_samples', 'valid_samples', 'test_samples', 'duration_seconds', 'device', 'method', 'limitations'):
            value = source.get(key)
            if isinstance(value, str):
                training[key] = value[:2000]
            elif _number(value):
                training[key] = value
            elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                training[key] = [v[:1000] for v in value[:20]]
        return {'status': 'ready', 'scope': 'public_benchmark', 'dataset': data['dataset'],
                'upstream_commit': commit, 'metrics': metrics, 'baseline': baseline,
                'predictions': predictions, 'training': training}
    except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        return {'status': 'unavailable', 'message': '实验报告暂不可读取，请重新完成本机评估。你的创作和资料不受影响。'}
