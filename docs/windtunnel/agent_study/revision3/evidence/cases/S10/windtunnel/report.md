# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：d95910b9-ed27-4a91-8f1b-522910492db6

条件版本：45a176b8-11fe-435d-ad18-1fd18b43d629

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

材料明确说明未使用可选参数时 args.verbosity 为 None，因此条件真值测试失败，程序不输出。

稿件引文：Note that by default, if an optional argument isn’t
used, the relevant variable, in this case args.verbosity, is
given None as a value, which is the reason it fails the truth
test of the if statement.

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：Note that by default, if an optional argument isn’t
used, the relevant variable, in this case args.verbosity, is
given None as a value, which is the reason it fails the truth
test of the if statement.



### 依据稿件为命令行工具设计verbose开关：解释仅写--verbosity为什么报错

来源类型：作者设定

状态：通过

材料显示仅写 --verbosity 时报错 expected one argument，并说明使用时必须指定某个值。

稿件引文：$ python prog.py --verbosity
usage: prog.py [-h] [--verbosity VERBOSITY]
prog.py: error: argument --verbosity: expected one argument

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：When using the --verbosity option, one must also specify some value,
any value.

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：python prog.py --verbosity
usage: prog.py [-h] [--verbosity VERBOSITY]
prog.py: error: argument --verbosity: expected one argument



### 依据稿件为命令行工具设计verbose开关：改成无需值的--verbose时给出add_argument及启用/缺省值

来源类型：作者设定

状态：通过

材料给出修改后的 add_argument，并说明 store_true 在指定时赋予 True，未指定时隐含 False。

稿件引文：parser.add_argument("--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：parser.add_argument("--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：This means that, if the option is specified,
assign the value True to args.verbose.
Not specifying it implies False.



### 依据稿件为命令行工具设计verbose开关：说明--verbose 1为何报错

来源类型：作者设定

状态：通过

材料显示 --verbose 1 报错 unrecognized arguments: 1，并说明指定值时会报错。

稿件引文：$ python prog.py --verbose 1
usage: prog.py [-h] [--verbose]
prog.py: error: unrecognized arguments: 1

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：python prog.py --verbose 1
usage: prog.py [-h] [--verbose]
prog.py: error: unrecognized arguments: 1

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：It complains when you specify a value, in true spirit of what flags
actually are.



### 依据稿件为命令行工具设计verbose开关：增加-v别名并给出add_argument，说明-v的输出及help反映什么

来源类型：作者设定

状态：通过

材料给出 -v 别名的 add_argument，显示 -v 输出，并说明 help 反映新能力。

稿件引文：parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：python prog.py -v
verbosity turned on

支持材料 [b3d2d032-91a6-44b5-ae14-bb0c7d497b9d]：Note that the new ability is also reflected in the help text.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。