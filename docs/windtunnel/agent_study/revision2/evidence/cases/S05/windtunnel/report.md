# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：3fee0d89-ef51-451b-a057-dc63c7452023

条件版本：b33d10b3-dad4-4c0f-b212-4fea0006095e

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

字典

5.5. Dictionaries

Another useful data type built into Python is the dictionary (see
Mapping Types — dict). Dictionaries are sometimes found in other languages as
“associative memories” or “associative arrays”.  Unlike sequences, which are
indexed by a range of numbers, dictionaries are indexed by keys, which can be
any immutable type; strings and numbers can always be keys.  Tuples can be used
as keys if they contain only strings, numbers, or tuples; if a tuple contains
any mutable object either directly or indirectly, it cannot be used as a key.
You can’t use lists as keys, since lists can be modified in place using index
assignments, slice assignments, or methods like append() and
extend().

It is best to think of a dictionary as a set of key: value pairs,
with the requirement that the keys are unique (within one dictionary). A pair of
braces creates an empty dictionary: {}. Placing a comma-separated list of
key:value pairs within the braces adds initial key:value pairs to the
dictionary; this is also the way dictionaries are written on output.

The main operations on a dictionary are storing a value with some key and
extracting the value given the key.  It is also possible to delete a key:value
pair with del. If you store using a key that is already in use, the old
value associated with that key is forgotten.  It is an error to extract a value
using a non-existent key.

Performing list(d) on a dictionary returns a list of all the keys
used in the dictionary, in insertion order (if you want it sorted, just use
sorted(d) instead). To check whether a single key is in the
dictionary, use the in keyword.

Here is a small example using a dictionary:

>>> tel = {'jack': 4098, 'sape': 4139}
>>> tel['guido'] = 4127
>>> tel
{'jack': 4098, 'sape': 4139, 'guido': 4127}
>>> tel['jack']
4098
>>> del tel['sape']
>>> tel['irv'] = 4127
>>> tel
{'jack': 4098, 'guido': 4127, 'irv': 4127}
>>> list(tel)
['jack', 'guido', 'irv']
>>> sorted(tel)
['guido', 'irv', 'jack']
>>> 'guido' in tel
True
>>> 'jack' not in tel
False

The dict() constructor builds dictionaries directly from sequences of
key-value pairs:

>>> dict([('sape', 4139), ('guido', 4127), ('jack', 4098)])
{'sape': 4139, 'guido': 4127, 'jack': 4098}

In addition, dict comprehensions can be used to create dictionaries from
arbitrary key and value expressions:

>>> {x: x**2 for x in (2, 4, 6)}
{2: 4, 4: 16, 6: 36}

When the keys are simple strings, it is sometimes easier to specify pairs using
keyword arguments:

>>> dict(sape=4139, guido=4127, jack=4098)
{'sape': 4139, 'guido': 4127, 'jack': 4098}



## 条件与结果



### 请依据稿件给通讯录维护步骤及结果：从tel={'jack':4098,'sape':4139}开始，新增guido:4127、将jack改为5000、删除sape、再新增irv:4127。写出最终字典

来源类型：作者设定

状态：稿件未讲清

根据指令，reading.status为unclear，必须输出unclear。

稿件引文：>>> tel
{'jack': 4098, 'guido': 4127, 'irv': 4127}



### 请依据稿件给通讯录维护步骤及结果：给出list(tel)和sorted(tel)

来源类型：作者设定

状态：通过

材料直接给出list(tel)和sorted(tel)的结果。

稿件引文：>>> list(tel)
['jack', 'guido', 'irv']
>>> sorted(tel)
['guido', 'irv', 'jack']

支持材料 [086db89a-8f91-4604-9b2f-8d030a774a57]：>>> list(tel)
['jack', 'guido', 'irv']
>>> sorted(tel)
['guido', 'irv', 'jack']



### 请依据稿件给通讯录维护步骤及结果：检查guido是否存在并写表达式和结果

来源类型：作者设定

状态：通过

材料直接给出表达式和结果。

稿件引文：>>> 'guido' in tel
True

支持材料 [086db89a-8f91-4604-9b2f-8d030a774a57]：>>> 'guido' in tel
True



### 请依据稿件给通讯录维护步骤及结果：说明再读取sape会怎样

来源类型：作者设定

状态：通过

材料说明用不存在的键提取值是错误，sape已被删除。

稿件引文：It is an error to extract a value
using a non-existent key.

支持材料 [086db89a-8f91-4604-9b2f-8d030a774a57]：It is an error to extract a value
using a non-existent key.



### 请依据稿件给通讯录维护步骤及结果：说明用列表作键或用含列表的元组作键是否可行及原因

来源类型：作者设定

状态：通过

材料直接说明元组作键条件及列表不能作键的原因。

稿件引文：Tuples can be used
as keys if they contain only strings, numbers, or tuples; if a tuple contains
any mutable object either directly or indirectly, it cannot be used as a key.
You can’t use lists as keys, since lists can be modified in place using index
assignments, slice assignments, or methods like append() and
extend().

支持材料 [086db89a-8f91-4604-9b2f-8d030a774a57]：Tuples can be used
as keys if they contain only strings, numbers, or tuples; if a tuple contains
any mutable object either directly or indirectly, it cannot be used as a key.
You can’t use lists as keys, since lists can be modified in place using index
assignments, slice assignments, or methods like append() and
extend().



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。