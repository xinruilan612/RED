"""Offline integrity/attribution check; no model quality claim."""
from pathlib import Path
from hashlib import sha256
import json

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text())
assert len(manifest['samples']) == 10
assert len({s['sample_id'] for s in manifest['samples']}) == 10
assert sum(s['cohort_candidate'] == 'exploratory' for s in manifest['samples']) == 3
assert sum(s['cohort_candidate'] == 'holdout_candidate' for s in manifest['samples']) == 7
for sample in manifest['samples']:
    assert not sample['strict_hidden'] and not sample['frozen']
    for kind in ('draft', 'support'):
        path = root / sample[kind + '_path']
        data = path.read_bytes()
        assert sha256(data).hexdigest() == sample[kind + '_sha256'], str(path)
        content = data.decode()
        assert sample['source_url'] in content
        assert 'Python Software Foundation' in content
        assert sample['fetched_at_utc'] in content
        section = content.split('```text\n', 1)[1].rsplit('```', 1)[0]
        assert sha256(section.encode()).hexdigest() == sample['section_text_sha256']
    data = (root / sample['source_html']).read_bytes()
    assert sha256(data).hexdigest() == sample['source_html_sha256']
    assert ('id="' + sample['source_section'] + '"') in data.decode()
    assert (root / sample['license_ref']).is_file()
    assert sample['human_results'] is None and sample['author_feedback'] is None
    assert sample['baseline_result'] is None and sample['windtunnel_result'] is None
assert sha256((root / 'license.html').read_bytes()).hexdigest() == manifest['license_html_sha256']
psf = (root / 'LICENSE_PSF.txt').read_text()
assert all(f'{n}.' in psf for n in range(1, 9))
assert 'Permission to use, copy, modify' in (root / 'LICENSE_0BSD.txt').read_text()
print('PASS: 10 public samples, 3 exploration + 7 candidate holdout; hashes, source anchors, attribution, license files, no fabricated results.')
