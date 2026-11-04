# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：9bd2f29d-4b78-4b88-9da0-e4fcb2bd54e6

条件版本：500417b1-b7f4-4da9-92cc-e6317199c6b3

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

列表推导式

5.1.3. List Comprehensions

List comprehensions provide a concise way to create lists.
Common applications are to make new lists where each element is the result of
some operations applied to each member of another sequence or iterable, or to
create a subsequence of those elements that satisfy a certain condition.

For example, assume we want to create a list of squares, like:

>>> squares = []
>>> for x in range(10):
...     squares.append(x**2)
...
>>> squares
[0, 1, 4, 9, 16, 25, 36, 49, 64, 81]

Note that this creates (or overwrites) a variable named x that still exists
after the loop completes.  We can calculate the list of squares without any
side effects using:

squares = list(map(lambda x: x**2, range(10)))

or, equivalently:

squares = [x**2 for x in range(10)]

which is more concise and readable.

A list comprehension consists of brackets containing an expression followed
by a for clause, then zero or more for or if
clauses.  The result will be a new list resulting from evaluating the expression
in the context of the for and if clauses which follow it.
For example, this listcomp combines the elements of two lists if they are not
equal:

>>> [(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

and it’s equivalent to:

>>> combs = []
>>> for x in [1,2,3]:
...     for y in [3,1,4]:
...         if x != y:
...             combs.append((x, y))
...
>>> combs
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

Note how the order of the for and if statements is the
same in both these snippets.

If the expression is a tuple (e.g. the (x, y) in the previous example),
it must be parenthesized.

>>> vec = [-4, -2, 0, 2, 4]
>>> # create a new list with the values doubled
>>> [x*2 for x in vec]
[-8, -4, 0, 4, 8]
>>> # filter the list to exclude negative numbers
>>> [x for x in vec if x >= 0]
[0, 2, 4]
>>> # apply a function to all the elements
>>> [abs(x) for x in vec]
[4, 2, 0, 2, 4]
>>> # call a method on each element
>>> freshfruit = ['  banana', '  loganberry ', 'passion fruit  ']
>>> [weapon.strip() for weapon in freshfruit]
['banana', 'loganberry', 'passion fruit']
>>> # create a list of 2-tuples like (number, square)
>>> [(x, x**2) for x in range(6)]
[(0, 0), (1, 1), (2, 4), (3, 9), (4, 16), (5, 25)]
>>> # the tuple must be parenthesized, otherwise an error is raised
>>> [x, x**2 for x in range(6)]
  File "<stdin>", line 1
    [x, x**2 for x in range(6)]
     ^^^^^^^
SyntaxError: did you forget parentheses around the comprehension target?
>>> # flatten a list using a listcomp with two 'for'
>>> vec = [[1,2,3], [4,5,6], [7,8,9]]
>>> [num for elem in vec for num in elem]
[1, 2, 3, 4, 5, 6, 7, 8, 9]

List comprehensions can contain complex expressions and nested functions:

>>> from math import pi
>>> [str(round(pi, i)) for i in range(1, 6)]
['3.1', '3.14', '3.142', '3.1416', '3.14159']



## 条件与结果



### 请依据稿件写一份列表推导式小抄：将vec=[-4,-2,0,2,4]筛去负数后将剩余值翻倍并给出结果

来源类型：作者设定

状态：通过

材料明确给出对vec筛负数及翻倍的相关表达式，阅读答案与材料一致。

稿件引文：[x*2 for x in vec]
[-8, -4, 0, 4, 8]
>>> # filter the list to exclude negative numbers
>>> [x for x in vec if x >= 0]
[0, 2, 4]

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> # filter the list to exclude negative numbers
>>> [x for x in vec if x >= 0]
[0, 2, 4]

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> # create a new list with the values doubled
>>> [x*2 for x in vec]
[-8, -4, 0, 4, 8]



### 请依据稿件写一份列表推导式小抄：将[[1,2],[3,4]]按原顺序展平成列表并给出表达式和结果

来源类型：作者设定

状态：通过

材料给出展平嵌套列表的两个for模式，阅读答案与材料中的规则一致。

稿件引文：>>> [num for elem in vec for num in elem]
[1, 2, 3, 4, 5, 6, 7, 8, 9]

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> # flatten a list using a listcomp with two 'for'
>>> vec = [[1,2,3], [4,5,6], [7,8,9]]
>>> [num for elem in vec for num in elem]
[1, 2, 3, 4, 5, 6, 7, 8, 9]



### 请依据稿件写一份列表推导式小抄：说明生成(number,square)对时元组表达式的括号要求

来源类型：作者设定

状态：通过

材料直接说明元组表达式必须加括号，阅读答案与材料一致。

稿件引文：If the expression is a tuple (e.g. the (x, y) in the previous example),
it must be parenthesized.

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：If the expression is a tuple (e.g. the (x, y) in the previous example),
it must be parenthesized.

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> # the tuple must be parenthesized, otherwise an error is raised
>>> [x, x**2 for x in range(6)]
  File "<stdin>", line 1
    [x, x**2 for x in range(6)]
     ^^^^^^^
SyntaxError: did you forget parentheses around the comprehension target?



### 请依据稿件写一份列表推导式小抄：说明两个for加一个if如何与普通嵌套循环对应

来源类型：作者设定

状态：通过

材料展示列表推导式与普通嵌套循环对应，并说明for和if顺序相同，阅读答案与材料一致。

稿件引文：Note how the order of the for and if statements is the
same in both these snippets.

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> [(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：>>> combs = []
>>> for x in [1,2,3]:
...     for y in [3,1,4]:
...         if x != y:
...             combs.append((x, y))

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：Note how the order of the for and if statements is the
same in both these snippets.



### 请依据稿件写一份列表推导式小抄：说明普通for循环变量与稿内推导式例子的变量副作用区别

来源类型：作者设定

状态：通过

材料对比普通for循环变量x在循环后仍存在，并称列表推导式方式无副作用，阅读答案与材料一致。

稿件引文：Note that this creates (or overwrites) a variable named x that still exists
after the loop completes.  We can calculate the list of squares without any
side effects using:

支持材料 [bd1628dd-85c5-4f28-b8ea-51f632b51131]：Note that this creates (or overwrites) a variable named x that still exists
after the loop completes.  We can calculate the list of squares without any
side effects using:



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。