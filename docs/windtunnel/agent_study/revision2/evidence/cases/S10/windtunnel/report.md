# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：8b8fb6c6-8cb8-4342-8e4c-87b65d46d82a

条件版本：89ebaf30-0ca8-44ec-90df-942071f3ca45

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

argparse可选参数

Introducing Optional arguments

So far we have been playing with positional arguments. Let us
have a look on how to add optional ones:

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--verbosity", help="increase output verbosity")
args = parser.parse_args()
if args.verbosity:
    print("verbosity turned on")

And the output:

$ python prog.py --verbosity 1
verbosity turned on
$ python prog.py
$ python prog.py --help
usage: prog.py [-h] [--verbosity VERBOSITY]

options:
  -h, --help            show this help message and exit
  --verbosity VERBOSITY
                        increase output verbosity
$ python prog.py --verbosity
usage: prog.py [-h] [--verbosity VERBOSITY]
prog.py: error: argument --verbosity: expected one argument

Here is what is happening:

The program is written so as to display something when --verbosity is
specified and display nothing when not.

To show that the option is actually optional, there is no error when running
the program without it. Note that by default, if an optional argument isn’t
used, the relevant variable, in this case args.verbosity, is
given None as a value, which is the reason it fails the truth
test of the if statement.

The help message is a bit different.

When using the --verbosity option, one must also specify some value,
any value.

The above example accepts arbitrary integer values for --verbosity, but for
our simple program, only two values are actually useful, True or False.
Let’s modify the code accordingly:

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--verbose", help="increase output verbosity",
                    action="store_true")
args = parser.parse_args()
if args.verbose:
    print("verbosity turned on")

And the output:

$ python prog.py --verbose
verbosity turned on
$ python prog.py --verbose 1
usage: prog.py [-h] [--verbose]
prog.py: error: unrecognized arguments: 1
$ python prog.py --help
usage: prog.py [-h] [--verbose]

options:
  -h, --help  show this help message and exit
  --verbose   increase output verbosity

Here is what is happening:

The option is now more of a flag than something that requires a value.
We even changed the name of the option to match that idea.
Note that we now specify a new keyword, action, and give it the value
"store_true". This means that, if the option is specified,
assign the value True to args.verbose.
Not specifying it implies False.

It complains when you specify a value, in true spirit of what flags
actually are.

Notice the different help text.

Short options

If you are familiar with command line usage,
you will notice that I haven’t yet touched on the topic of short
versions of the options. It’s quite simple:

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")
args = parser.parse_args()
if args.verbose:
    print("verbosity turned on")

And here goes:

$ python prog.py -v
verbosity turned on
$ python prog.py --help
usage: prog.py [-h] [-v]

options:
  -h, --help     show this help message and exit
  -v, --verbose  increase output verbosity

Note that the new ability is also reflected in the help text.



## 条件与结果



### 依据稿件为命令行工具设计verbose开关：解释最初--verbosity缺省时的值及输出

来源类型：作者设定

状态：通过

材料明确说明缺省时 args.verbosity 为 None，导致 if 条件为假，程序不输出。

稿件引文：Note that by default, if an optional argument isn’t
used, the relevant variable, in this case args.verbosity, is
given None as a value, which is the reason it fails the truth
test of the if statement.

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：Note that by default, if an optional argument isn’t
used, the relevant variable, in this case args.verbosity, is
given None as a value, which is the reason it fails the truth
test of the if statement.



### 依据稿件为命令行工具设计verbose开关：解释仅写--verbosity为什么报错

来源类型：作者设定

状态：通过

材料直接给出仅写 --verbosity 时的错误信息，说明期待一个参数。

稿件引文：prog.py: error: argument --verbosity: expected one argument

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：prog.py: error: argument --verbosity: expected one argument



### 依据稿件为命令行工具设计verbose开关：改成无需值的--verbose时给出add_argument及启用/缺省值

来源类型：作者设定

状态：通过

材料包含使用 action="store_true" 的 add_argument 代码，并说明指定时为 True、不指定时为 False。

稿件引文：parser.add_argument("--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：parser.add_argument("--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：This means that, if the option is specified,
assign the value True to args.verbose.
Not specifying it implies False.



### 依据稿件为命令行工具设计verbose开关：说明--verbose 1为何报错

来源类型：作者设定

状态：通过

材料显示 --verbose 1 导致 unrecognized arguments 错误，并解释 flag 不接受值。

稿件引文：prog.py: error: unrecognized arguments: 1

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：prog.py: error: unrecognized arguments: 1



### 依据稿件为命令行工具设计verbose开关：增加-v别名并给出add_argument，说明-v的输出及help反映什么

来源类型：作者设定

状态：通过

材料包含 -v 别名的 add_argument、运行 -v 输出 'verbosity turned on'，以及 help 中反映 -v 的信息。

稿件引文：parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：$ python prog.py -v
verbosity turned on

支持材料 [3d001477-2069-4503-82c9-6d24f173fffa]：Note that the new ability is also reflected in the help text.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。