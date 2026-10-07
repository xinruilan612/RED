# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：69161d1c-b31c-4b02-859e-6a21e2aeb3f0

条件版本：2086d814-8c62-4a0d-9a8a-78c0104f4143

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

状态：通过

材料支持修改规则（已有键存储时旧值被忘记、del删除、插入顺序），且示例给出从相同初始字典新增guido、删除sape、新增irv后的最终字典；结合规则可得出将jack改为5000后最终字典。

稿件引文：>>> tel = {'jack': 4098, 'sape': 4139}
>>> tel['guido'] = 4127
>>> tel
{'jack': 4098, 'sape': 4139, 'guido': 4127}
>>> tel['jack']
4098
>>> del tel['sape']
>>> tel['irv'] = 4127
>>> tel
{'jack': 4098, 'guido': 4127, 'irv': 4127}

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：The main operations on a dictionary are storing a value with some key and
extracting the value given the key.  It is also possible to delete a key:value
pair with del. If you store using a key that is already in use, the old
value associated with that key is forgotten.  It is an error to extract a value
using a non-existent key.

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：>>> tel = {'jack': 4098, 'sape': 4139}
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



### 请依据稿件给通讯录维护步骤及结果：给出list(tel)和sorted(tel)

来源类型：作者设定

状态：通过

材料说明list(d)返回所有键且按插入顺序，sorted(d)返回排序后的键，且示例给出list(tel)和sorted(tel)结果；与最终字典键一致。

稿件引文：>>> list(tel)
['jack', 'guido', 'irv']
>>> sorted(tel)
['guido', 'irv', 'jack']

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：Performing list(d) on a dictionary returns a list of all the keys
used in the dictionary, in insertion order (if you want it sorted, just use
sorted(d) instead). To check whether a single key is in the
dictionary, use the in keyword.

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：>>> tel = {'jack': 4098, 'sape': 4139}
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



### 请依据稿件给通讯录维护步骤及结果：检查guido是否存在并写表达式和结果

来源类型：作者设定

状态：通过

材料说明用in关键字检查键是否在字典中，并示例给出'guido' in tel为True；最终字典包含guido键。

稿件引文：>>> 'guido' in tel
True

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：Performing list(d) on a dictionary returns a list of all the keys
used in the dictionary, in insertion order (if you want it sorted, just use
sorted(d) instead). To check whether a single key is in the
dictionary, use the in keyword.

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：>>> tel = {'jack': 4098, 'sape': 4139}
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



### 请依据稿件给通讯录维护步骤及结果：说明再读取sape会怎样

来源类型：作者设定

状态：通过

材料明确用不存在的键提取值是错误，且示例显示sape已通过del删除；因此再读取sape会出错。

稿件引文：It is an error to extract a value
using a non-existent key.

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：The main operations on a dictionary are storing a value with some key and
extracting the value given the key.  It is also possible to delete a key:value
pair with del. If you store using a key that is already in use, the old
value associated with that key is forgotten.  It is an error to extract a value
using a non-existent key.

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：>>> tel = {'jack': 4098, 'sape': 4139}
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



### 请依据稿件给通讯录维护步骤及结果：说明用列表作键或用含列表的元组作键是否可行及原因

来源类型：作者设定

状态：通过

材料直接说明列表不可作键及原因，含可变对象的元组也不可作键；答案与材料一致。

稿件引文：Tuples can be used
as keys if they contain only strings, numbers, or tuples; if a tuple contains
any mutable object either directly or indirectly, it cannot be used as a key.
You can’t use lists as keys, since lists can be modified in place using index
assignments, slice assignments, or methods like append() and
extend().

支持材料 [61fa4075-32b5-4c5a-b7cd-8a1ed1517ab9]：Another useful data type built into Python is the dictionary (see
Mapping Types — dict). Dictionaries are sometimes found in other languages as
“associative memories” or “associative arrays”.  Unlike sequences, which are
indexed by a range of numbers, dictionaries are indexed by keys, which can be
any immutable type; strings and numbers can always be keys.  Tuples can be used
as keys if they contain only strings, numbers, or tuples; if a tuple contains
any mutable object either directly or indirectly, it cannot be used as a key.
You can’t use lists as keys, since lists can be modified in place using index
assignments, slice assignments, or methods like append() and
extend().



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。