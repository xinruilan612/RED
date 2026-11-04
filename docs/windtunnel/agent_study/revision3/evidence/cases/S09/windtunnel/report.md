# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：718541f2-f038-4940-808e-e45474ed0143

条件版本：a5316090-27e3-47be-8ad2-1df3a7dd076b

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

pathlib基础使用

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



## 条件与结果



### 仅依据稿件，给出pathlib项目浏览小抄：导入Path并代表当前目录

来源类型：作者设定

状态：通过

稿件明确给出导入Path和用Path('.')表示当前目录。

稿件引文：>>> from pathlib import Path

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> from pathlib import Path

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> p = Path('.')



### 仅依据稿件，给出pathlib项目浏览小抄：列出当前目录的子目录

来源类型：作者设定

状态：通过

稿件明确给出遍历当前目录并筛选子目录的代码。

稿件引文：>>> [x for x in p.iterdir() if x.is_dir()]

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> [x for x in p.iterdir() if x.is_dir()]



### 仅依据稿件，给出pathlib项目浏览小抄：递归收集目录树中.py文件

来源类型：作者设定

状态：通过

稿件明确给出递归收集目录树中.py文件的代码。

稿件引文：>>> list(p.glob('**/*.py'))

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> list(p.glob('**/*.py'))



### 仅依据稿件，给出pathlib项目浏览小抄：按示例拼接/etc/init.d/reboot，并区分拼接路径与resolve示例结果

来源类型：作者设定

状态：通过

稿件明确给出拼接路径及resolve示例结果。

稿件引文：>>> q.resolve()
PosixPath('/etc/rc.d/init.d/halt')

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> q = p / 'init.d' / 'reboot'

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：PosixPath('/etc/init.d/reboot')

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：PosixPath('/etc/rc.d/init.d/halt')



### 仅依据稿件，给出pathlib项目浏览小抄：解释示例q.exists()、q.is_dir()的结果，并写出用q读取首行的方式。不要把示例机器路径结果保证为所有电脑都相同

来源类型：作者设定

状态：通过

稿件明确给出q.exists()、q.is_dir()的结果及用q.open()读取首行的代码；且未将路径结果保证为所有机器相同。

稿件引文：>>> with q.open() as f: f.readline()

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> q.exists()

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：True

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> q.is_dir()

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：False

支持材料 [c587e895-50d0-4d87-afbd-7b26faac73d8]：>>> with q.open() as f: f.readline()



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。