#!/usr/bin/env python3
"""Reproduce the pinned author reference implementation; never fabricate scores."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'third_party/skapp'
COMMIT = '3353b5a79bbeacf8110971b2ef035a4046c1a25c'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_vendor():
    manifest = read(VENDOR / 'PROVENANCE.json')
    if manifest['commit'] != COMMIT:
        raise ValueError('Unexpected upstream commit')
    for name, expected in manifest['files_sha256'].items():
        if digest(VENDOR / name) != expected:
            raise ValueError('Vendored source changed: ' + name)


def command(args):
    verify_vendor()
    if Path(args.python).absolute() == ROOT / 'runtime/venv/bin/python':
        raise ValueError('Use a separate SKAPP environment, not the website environment')
    cmd = [args.python, str(VENDOR / 'src' / (args.action + '.py'))]
    if args.action == 'download':
        cmd += ['--dataset', args.dataset, '--data-root', str(args.data_root)]
        if args.archive:
            cmd += ['--archive', str(args.archive)]
    else:
        if args.output_dir.exists():
            raise FileExistsError('Output exists; select a fresh output directory')
        cmd += ['--dataset-path', str(args.dataset_path), '--output-dir', str(args.output_dir), '--device', args.device]
        if args.action == 'train':
            if args.epochs < 1 or args.patience < 1 or len(set(args.seeds)) != len(args.seeds):
                raise ValueError('Positive epochs/patience and distinct seeds required')
            cmd += ['--epochs', str(args.epochs), '--patience', str(args.patience), '--seeds', *map(str, args.seeds)]
        else:
            cmd += ['--training-dir', str(args.training_dir)]
    return cmd


def constant_baseline(actual, train_labels):
    """A constant has no rank variance: Spearman correlation is undefined."""
    average = statistics.fmean(float(value) for value in train_labels)
    errors = [float(value) - average for value in actual]
    if not errors:
        raise ValueError('Cannot evaluate an empty test set')
    return {'name': '训练集均值基线', 'MSE': statistics.fmean(value ** 2 for value in errors),
            'MAE': statistics.fmean(abs(value) for value in errors), 'SRC': None, 'samples': len(errors)}


def publish(args):
    """Publish one explicitly selected seed, never an ensemble or best test seed."""
    verify_vendor()
    source = args.evaluation_dir.resolve()
    result = read(source / 'result.json')
    if result.get('status') != 'complete' or read(source / 'progress.json').get('status') != 'complete':
        raise ValueError('Evaluation is not complete')
    master = read(source / 'manifest.json')
    if len(master['seeds']) != 1:
        raise ValueError('Website publishing requires one predeclared seed; multi-seed results remain in the experiment report')
    seed = master['seeds'][0]
    run = next(x for x in master['runs'] if x['seed'] == seed)
    if digest(source / run['manifest']) != run['sha256']:
        raise ValueError('Evaluation manifest changed')
    manifest = read(source / run['manifest'])
    if manifest['selection_split'] != 'valid' or read(source / 'validation-parity.json').get(str(seed)) != 'bitwise equal':
        raise ValueError('Validation selection or parity was not verified')
    if digest(source / manifest['checkpoint']) != manifest['sha256']:
        raise ValueError('Checkpoint changed')
    import numpy as np
    from scipy.stats import spearmanr
    dataset_path = Path(manifest['dataset_path'])
    dataset = read(dataset_path / 'dataset.json')
    if digest(dataset_path / 'dataset.json') != manifest['statistics']['dataset_manifest_sha256']:
        raise ValueError('Dataset manifest changed')
    # Only pinned public releases may be presented as a public benchmark.
    catalog = read(VENDOR / 'src/datasets.json')['datasets'][dataset['dataset']]
    if digest(dataset_path / 'dataset.json') != catalog['dataset_sha256']:
        raise ValueError('Not the pinned public dataset release')
    labels, split_ids = {}, {}
    for split in ('train', 'valid', 'test'):
        entry = dataset['splits'][split]
        path = dataset_path / (split + '.npz')
        if entry['file'] != path.name or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise ValueError('Dataset split changed: ' + split)
        with np.load(path, allow_pickle=False) as data:
            labels[split] = np.asarray(data['label'], dtype=np.float32)
            split_ids[split] = data['image_id'].astype(str).tolist()
    with np.load(source / f'evaluation/seed{seed}/test-predictions.npz', allow_pickle=False) as data:
        ids = data['image_id'].astype(str).tolist()
        actual = np.asarray(data['target'], dtype=np.float32)
        predicted = np.asarray(data['prediction'], dtype=np.float32)
    if ids != split_ids['test'] or not np.array_equal(actual, labels['test']):
        raise ValueError('Predictions do not match the test split')
    if not len(ids) or len(set(ids)) != len(ids) or predicted.shape != actual.shape or not np.isfinite(predicted).all():
        raise ValueError('Invalid predictions')
    if any(set(split_ids[a]) & set(split_ids[b]) for a,b in [('train','valid'),('train','test'),('valid','test')]):
        raise ValueError('Overlapping dataset splits')
    def metrics(pred):
        correlation = float(spearmanr(actual, pred).statistic) if np.ptp(pred) and np.ptp(actual) else 0.0
        return {'MSE': float(np.mean((actual-pred)**2)), 'MAE':float(np.mean(np.abs(actual-pred))), 'SRC':correlation, 'samples':len(ids)}
    measured = metrics(predicted)
    reported = result['results']['test']['runs'][str(seed)]
    if any(not np.isclose(measured[k], reported[k], rtol=1e-5, atol=1e-7) for k in measured):
        raise ValueError('Reported metrics differ from predictions')
    training = read(source / 'attention-training.json')['runs'][0]
    baseline = constant_baseline(actual, labels['train'])
    payload = {'status':'ready', 'upstream_commit':COMMIT, 'dataset':dataset['dataset'], 'scope':'public_benchmark',
        'metrics':measured, 'baseline':baseline,
        'predictions':[{'id':i,'actual':float(y),'predicted':float(p)} for i,y,p in zip(ids,actual,predicted)],
        'training':{'seed':seed,'epochs':training['epochs'],'best_epoch':training['best_epoch'],
            'train_samples':len(labels['train']),'valid_samples':len(labels['valid']),'test_samples':len(ids),
            'device':args.device,'duration_seconds':args.duration_seconds,
            'method':'作者当前参考实现：RRCP 门控注意力；不声称逐公式复现论文双图网络',
            'limitations':['公开数据集结果，不代表小红书效果或爆款概率','没有新稿图文编码与邻居构建流程，不能对用户新稿推理','ICIP mean_views 的采集时点未验证，不能据此证明严格发布前预测','单随机种子实验，不等于论文多次实验结果']},
        'evidence':{'evaluation_result_sha256':digest(source/'result.json'),'dataset_manifest_sha256':digest(dataset_path/'dataset.json'),
            'checkpoint_sha256':manifest['sha256'],'evaluation_path':str(source)}}
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents silently replacing a previously accepted result.
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(raw)
    return payload


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    for action in ('download','train','evaluate'):
        s = sub.add_parser(action)
        s.add_argument('--python', required=True, help='Python executable in a separate SKAPP environment')
        if action == 'download':
            s.add_argument('--dataset', choices=['icip','smpd','instagram'], default='icip')
            s.add_argument('--data-root', type=Path, default=ROOT/'runtime/skapp/data')
            s.add_argument('--archive', type=Path)
        else:
            s.add_argument('--dataset-path', type=Path, required=True)
            s.add_argument('--output-dir', type=Path, required=True)
            s.add_argument('--device', default='cpu')
            if action == 'train':
                s.add_argument('--epochs',type=int,default=60)
                s.add_argument('--patience',type=int,default=8)
                s.add_argument('--seeds',type=int,nargs='+',default=[12])
            else:
                s.add_argument('--training-dir',type=Path,required=True)
    s = sub.add_parser('publish')
    s.add_argument('--evaluation-dir',type=Path,required=True)
    s.add_argument('--output',type=Path,default=ROOT/'runtime/skapp/result.json')
    s.add_argument('--device',default='cpu',help='Device used during the recorded training run')
    s.add_argument('--duration-seconds',type=float,default=None)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.action == 'publish':
        publish(args)
        print('Verified benchmark result saved to ' + str(args.output))
    else:
        subprocess.run(command(args), check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
