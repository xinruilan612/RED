# S02：列表基础

来源：https://docs.python.org/3.12/tutorial/introduction.html#lists

采集时间（UTC）：2026-10-07T02:57:33.826982+00:00

来源性质：Python 3.12 官方英文文档公开章节，非用户投稿或真实创作者私稿。

许可：文档正文 PSF License Version 2；代码示例同时可按 0BSD 使用。

Copyright © 2001-2023 Python Software Foundation; All Rights Reserved.

许可全文见 ../LICENSE_PSF.txt、../LICENSE_0BSD.txt 与 ../LICENSE_SOURCE.txt。

## 官方章节全文

```text
3.1.3. Lists

Python knows a number of compound data types, used to group together other
values.  The most versatile is the list, which can be written as a list of
comma-separated values (items) between square brackets.  Lists might contain
items of different types, but usually the items all have the same type.

>>> squares = [1, 4, 9, 16, 25]
>>> squares
[1, 4, 9, 16, 25]

Like strings (and all other built-in sequence types), lists can be
indexed and sliced:

>>> squares[0]  # indexing returns the item
1
>>> squares[-1]
25
>>> squares[-3:]  # slicing returns a new list
[9, 16, 25]

Lists also support operations like concatenation:

>>> squares + [36, 49, 64, 81, 100]
[1, 4, 9, 16, 25, 36, 49, 64, 81, 100]

Unlike strings, which are immutable, lists are a mutable
type, i.e. it is possible to change their content:

>>> cubes = [1, 8, 27, 65, 125]  # something's wrong here
>>> 4 ** 3  # the cube of 4 is 64, not 65!
64
>>> cubes[3] = 64  # replace the wrong value
>>> cubes
[1, 8, 27, 64, 125]

You can also add new items at the end of the list, by using
the list.append() method (we will see more about methods later):

>>> cubes.append(216)  # add the cube of 6
>>> cubes.append(7 ** 3)  # and the cube of 7
>>> cubes
[1, 8, 27, 64, 125, 216, 343]

Simple assignment in Python never copies data. When you assign a list
to a variable, the variable refers to the existing list.
Any changes you make to the list through one variable will be seen
through all other variables that refer to it.:

>>> rgb = ["Red", "Green", "Blue"]
>>> rgba = rgb
>>> id(rgb) == id(rgba)  # they reference the same object
True
>>> rgba.append("Alph")
>>> rgb
["Red", "Green", "Blue", "Alph"]

All slice operations return a new list containing the requested elements.  This
means that the following slice returns a
shallow copy of the list:

>>> correct_rgba = rgba[:]
>>> correct_rgba[-1] = "Alpha"
>>> correct_rgba
["Red", "Green", "Blue", "Alpha"]
>>> rgba
["Red", "Green", "Blue", "Alph"]

Assignment to slices is also possible, and this can even change the size of the
list or clear it entirely:

>>> letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
>>> letters
['a', 'b', 'c', 'd', 'e', 'f', 'g']
>>> # replace some values
>>> letters[2:5] = ['C', 'D', 'E']
>>> letters
['a', 'b', 'C', 'D', 'E', 'f', 'g']
>>> # now remove them
>>> letters[2:5] = []
>>> letters
['a', 'b', 'f', 'g']
>>> # clear the list by replacing all the elements with an empty list
>>> letters[:] = []
>>> letters
[]

The built-in function len() also applies to lists:

>>> letters = ['a', 'b', 'c', 'd']
>>> len(letters)
4

It is possible to nest lists (create lists containing other lists), for
example:

>>> a = ['a', 'b', 'c']
>>> n = [1, 2, 3]
>>> x = [a, n]
>>> x
[['a', 'b', 'c'], [1, 2, 3]]
>>> x[0]
['a', 'b', 'c']
>>> x[0][1]
'b'
```
