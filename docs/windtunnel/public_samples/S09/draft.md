# S09：pathlib基础使用

来源：https://docs.python.org/3.12/library/pathlib.html#basic-use

采集时间（UTC）：2026-10-07T02:57:39.556068+00:00

来源性质：Python 3.12 官方英文文档公开章节，非用户投稿或真实创作者私稿。

许可：文档正文 PSF License Version 2；代码示例同时可按 0BSD 使用。

Copyright © 2001-2023 Python Software Foundation; All Rights Reserved.

许可全文见 ../LICENSE_PSF.txt、../LICENSE_0BSD.txt 与 ../LICENSE_SOURCE.txt。

改编说明：保留官方英文教程章节原文，未翻译、未人为植入错误、未添加真实作者反馈；仅添加来源与许可说明、删除网页段落锚点符号并整理空白。此为公开教程节选候选输入，不是 baseline 或风洞最终改稿。

## 待检查教程节选

```text
Basic use

Importing the main class:

>>> from pathlib import Path

Listing subdirectories:

>>> p = Path('.')
>>> [x for x in p.iterdir() if x.is_dir()]
[PosixPath('.hg'), PosixPath('docs'), PosixPath('dist'),
 PosixPath('__pycache__'), PosixPath('build')]

Listing Python source files in this directory tree:

>>> list(p.glob('**/*.py'))
[PosixPath('test_pathlib.py'), PosixPath('setup.py'),
 PosixPath('pathlib.py'), PosixPath('docs/conf.py'),
 PosixPath('build/lib/pathlib.py')]

Navigating inside a directory tree:

>>> p = Path('/etc')
>>> q = p / 'init.d' / 'reboot'
>>> q
PosixPath('/etc/init.d/reboot')
>>> q.resolve()
PosixPath('/etc/rc.d/init.d/halt')

Querying path properties:

>>> q.exists()
True
>>> q.is_dir()
False

Opening a file:

>>> with q.open() as f: f.readline()
...
'#!/bin/bash\n'
```
