# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：e3dfe416-b713-4aca-b83a-34a7f439b5eb

条件版本：bc53818e-b94b-4be7-9d1f-f2b987b11fb5

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
Cheat Sheet Additions

Filter and then transform vec = [-4, -2, 0, 2, 4]:
Put the if clause after the for clause so that only values satisfying the condition are used:

>>> vec = [-4, -2, 0, 2, 4]
>>> [x*2 for x in vec if x >= 0]
[0, 4, 8]

Flatten [[1, 2], [3, 4]] in the original order:
A list comprehension may use more than one for clause.  The clauses run left to right, from the outer loop to the inner loop, so [num for elem in vec for num in elem] flattens one level:

>>> vec = [[1, 2], [3, 4]]
>>> [num for elem in vec for num in elem]
[1, 2, 3, 4]

Tuple expressions as the output must be parenthesized:
If the expression is a tuple, write it in parentheses.  Otherwise Python raises a SyntaxError:

>>> [(x, x**2) for x in range(6)]
[(0, 0), (1, 1), (2, 4), (3, 9), (4, 16), (5, 25)]
>>> [x, x**2 for x in range(6)]
SyntaxError: did you forget parentheses around the comprehension target?

Two for clauses and one if clause match nested loops:
The for and if clauses are written in the same order as the equivalent nested loop statements.  Read them as ordinary loops from left to right, with the if filtering before the expression is evaluated:

>>> [(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

Variable scope differs from a normal for loop:
A normal for loop assigns the loop variable in the surrounding environment, so x remains after the loop completes.  A list comprehension evaluates its own expression and for/if clauses and produces a new list; the examples create the result directly without creating or overwriting an outer variable named x:

>>> squares = []
>>> for x in range(10):
...     squares.append(x**2)
...
>>> squares
[0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
>>> squares = [x**2 for x in range(10)]




## 条件与结果



### 请依据稿件写一份列表推导式小抄：将vec=[-4,-2,0,2,4]筛去负数后将剩余值翻倍并给出结果

来源类型：作者设定

状态：通过

阅读状态为 pass，稿件 Cheat Sheet Additions 明确给出表达式 [x*2 for x in vec if x >= 0] 和结果 [0, 4, 8]，与答案一致。

稿件引文：>>> vec = [-4, -2, 0, 2, 4]
>>> [x*2 for x in vec if x >= 0]
[0, 4, 8]

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：>>> vec = [-4, -2, 0, 2, 4]
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



### 请依据稿件写一份列表推导式小抄：将[[1,2],[3,4]]按原顺序展平成列表并给出表达式和结果

来源类型：作者设定

状态：通过

阅读状态为 pass，稿件 Cheat Sheet Additions 明确给出向量设置、展平表达式和结果 [1, 2, 3, 4]，与答案一致。

稿件引文：>>> vec = [[1, 2], [3, 4]]
>>> [num for elem in vec for num in elem]
[1, 2, 3, 4]

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：>>> vec = [-4, -2, 0, 2, 4]
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



### 请依据稿件写一份列表推导式小抄：说明生成(number,square)对时元组表达式的括号要求

来源类型：作者设定

状态：通过

阅读状态为 pass，稿件有规则说明元组表达式必须加括号，并有对应示例及缺少括号时的 SyntaxError。

稿件引文：Tuple expressions as the output must be parenthesized:
If the expression is a tuple, write it in parentheses.  Otherwise Python raises a SyntaxError:

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：If the expression is a tuple (e.g. the (x, y) in the previous example),
it must be parenthesized.

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：>>> vec = [-4, -2, 0, 2, 4]
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



### 请依据稿件写一份列表推导式小抄：说明两个for加一个if如何与普通嵌套循环对应

来源类型：作者设定

状态：通过

阅读状态为 pass，稿件说明 for 和 if 子句顺序与等价嵌套循环相同，并给出列表推导式与嵌套循环的对应示例。

稿件引文：Two for clauses and one if clause match nested loops:
The for and if clauses are written in the same order as the equivalent nested loop statements.  Read them as ordinary loops from left to right, with the if filtering before the expression is evaluated:

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：>>> [(x, y) for x in [1,2,3] for y in [3,1,4] if x != y]
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：>>> combs = []
>>> for x in [1,2,3]:
...     for y in [3,1,4]:
...         if x != y:
...             combs.append((x, y))
...
>>> combs
[(1, 3), (1, 4), (2, 3), (2, 1), (2, 4), (3, 1), (3, 4)]

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：Note how the order of the for and if statements is the
same in both these snippets.



### 请依据稿件写一份列表推导式小抄：说明普通for循环变量与稿内推导式例子的变量副作用区别

来源类型：作者设定

状态：通过

阅读状态为 pass，稿件明确说明普通 for 循环会创建或覆盖外层变量 x，而列表推导式示例直接创建结果、不会创建或覆盖外层变量 x。

稿件引文：Variable scope differs from a normal for loop:
A normal for loop assigns the loop variable in the surrounding environment, so x remains after the loop completes.  A list comprehension evaluates its own expression and for/if clauses and produces a new list; the examples create the result directly without creating or overwriting an outer variable named x:

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：Note that this creates (or overwrites) a variable named x that still exists
after the loop completes.  We can calculate the list of squares without any
side effects using:

支持材料 [6db470bb-aac1-4a96-962c-b2419b9201f2]：squares = [x**2 for x in range(10)]



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。