# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：7fa3738d-ff97-4179-b2bb-896b5052d872

条件版本：e486719a-4bae-4ee8-9d62-1724a942826b

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

处理异常

8.3. Handling Exceptions

It is possible to write programs that handle selected exceptions. Look at the
following example, which asks the user for input until a valid integer has been
entered, but allows the user to interrupt the program (using Control-C or
whatever the operating system supports); note that a user-generated interruption
is signalled by raising the KeyboardInterrupt exception.

>>> while True:
...     try:
...         x = int(input("Please enter a number: "))
...         break
...     except ValueError:
...         print("Oops!  That was no valid number.  Try again...")
...

The try statement works as follows.

First, the try clause (the statement(s) between the try and
except keywords) is executed.

If no exception occurs, the except clause is skipped and execution of the
try statement is finished.

If an exception occurs during execution of the try clause, the rest of the
clause is skipped.  Then, if its type matches the exception named after the
except keyword, the except clause is executed, and then execution
continues after the try/except block.

If an exception occurs which does not match the exception named in the except
clause, it is passed on to outer try statements; if no handler is
found, it is an unhandled exception and execution stops with an error message.

A try statement may have more than one except clause, to specify
handlers for different exceptions.  At most one handler will be executed.
Handlers only handle exceptions that occur in the corresponding try clause,
not in other handlers of the same try statement.  An except clause
may name multiple exceptions as a parenthesized tuple, for example:

... except (RuntimeError, TypeError, NameError):
...     pass

A class in an except clause matches exceptions which are instances of the
class itself or one of its derived classes (but not the other way around — an
except clause listing a derived class does not match instances of its base classes).
For example, the following code will print B, C, D in that order:

class B(Exception):
    pass

class C(B):
    pass

class D(C):
    pass

for cls in [B, C, D]:
    try:
        raise cls()
    except D:
        print("D")
    except C:
        print("C")
    except B:
        print("B")

Note that if the except clauses were reversed (with except B first), it
would have printed B, B, B — the first matching except clause is triggered.

When an exception occurs, it may have associated values, also known as the
exception’s arguments. The presence and types of the arguments depend on the
exception type.

The except clause may specify a variable after the exception name.  The
variable is bound to the exception instance which typically has an args
attribute that stores the arguments. For convenience, builtin exception
types define __str__() to print all the arguments without explicitly
accessing .args.

>>> try:
...     raise Exception('spam', 'eggs')
... except Exception as inst:
...     print(type(inst))    # the exception type
...     print(inst.args)     # arguments stored in .args
...     print(inst)          # __str__ allows args to be printed directly,
...                          # but may be overridden in exception subclasses
...     x, y = inst.args     # unpack args
...     print('x =', x)
...     print('y =', y)
...
<class 'Exception'>
('spam', 'eggs')
('spam', 'eggs')
x = spam
y = eggs

The exception’s __str__() output is printed as the last part (‘detail’)
of the message for unhandled exceptions.

BaseException is the common base class of all exceptions. One of its
subclasses, Exception, is the base class of all the non-fatal exceptions.
Exceptions which are not subclasses of Exception are not typically
handled, because they are used to indicate that the program should terminate.
They include SystemExit which is raised by sys.exit() and
KeyboardInterrupt which is raised when a user wishes to interrupt
the program.

Exception can be used as a wildcard that catches (almost) everything.
However, it is good practice to be as specific as possible with the types
of exceptions that we intend to handle, and to allow any unexpected
exceptions to propagate on.

The most common pattern for handling Exception is to print or log
the exception and then re-raise it (allowing a caller to handle the
exception as well):

import sys

try:
    f = open('myfile.txt')
    s = f.readline()
    i = int(s.strip())
except OSError as err:
    print("OS error:", err)
except ValueError:
    print("Could not convert data to an integer.")
except Exception as err:
    print(f"Unexpected {err=}, {type(err)=}")
    raise

The try … except statement has an optional else
clause, which, when present, must follow all except clauses.  It is useful
for code that must be executed if the try clause does not raise an exception.
For example:

for arg in sys.argv[1:]:
    try:
        f = open(arg, 'r')
    except OSError:
        print('cannot open', arg)
    else:
        print(arg, 'has', len(f.readlines()), 'lines')
        f.close()

The use of the else clause is better than adding additional code to
the try clause because it avoids accidentally catching an exception
that wasn’t raised by the code being protected by the try …
except statement.

Exception handlers do not handle only exceptions that occur immediately in the
try clause, but also those that occur inside functions that are called (even
indirectly) in the try clause. For example:

>>> def this_fails():
...     x = 1/0
...
>>> try:
...     this_fails()
... except ZeroDivisionError as err:
...     print('Handling run-time error:', err)
...
Handling run-time error: division by zero



## 条件与结果



### 依据稿件给异常处理代码审查建议：输入整数的重试循环应处理哪类异常，Ctrl-C为何不会被该处理器吃掉

来源类型：作者设定

状态：通过

材料支持：样例重试循环只捕获 ValueError，用于处理非整数输入；用户中断由 KeyboardInterrupt 表示，且材料说明 KeyboardInterrupt 不是 Exception 的子类，因此针对 ValueError 的处理器不会捕获它。

稿件引文：It is possible to write programs that handle selected exceptions. Look at the
following example, which asks the user for input until a valid integer has been
entered, but allows the user to interrupt the program (using Control-C or
whatever the operating system supports); note that a user-generated interruption
is signalled by raising the KeyboardInterrupt exception.

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：It is possible to write programs that handle selected exceptions. Look at the
following example, which asks the user for input until a valid integer has been
entered, but allows the user to interrupt the program (using Control-C or
whatever the operating system supports); note that a user-generated interruption
is signalled by raising the KeyboardInterrupt exception.

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：>>> while True:
...     try:
...         x = int(input("Please enter a number: "))
...         break
...     except ValueError:
...         print("Oops!  That was no valid number.  Try again...")
...

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：BaseException is the common base class of all exceptions. One of its
subclasses, Exception, is the base class of all the non-fatal exceptions.
Exceptions which are not subclasses of Exception are not typically
handled, because they are used to indicate that the program should terminate.
They include SystemExit which is raised by sys.exit() and
KeyboardInterrupt which is raised when a user wishes to interrupt
the program.



### 依据稿件给异常处理代码审查建议：try出现匹配异常后剩余语句和处理器怎样执行

来源类型：作者设定

状态：通过

材料直接说明 try 子句执行期间发生异常时，剩余子句被跳过；若类型匹配，则执行 except 子句，然后继续执行 try/except 块之后的代码。

稿件引文：If an exception occurs during execution of the try clause, the rest of the
clause is skipped.  Then, if its type matches the exception named after the
except keyword, the except clause is executed, and then execution
continues after the try/except block.

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：If an exception occurs during execution of the try clause, the rest of the
clause is skipped.  Then, if its type matches the exception named after the
except keyword, the except clause is executed, and then execution
continues after the try/except block.



### 依据稿件给异常处理代码审查建议：父类与子类异常处理器顺序如何影响稿内B/C/D示例

来源类型：作者设定

状态：通过

材料说明 except 子句中的类匹配其实例及其派生类实例，并给出 B/C/D 输出顺序；还说明若反转子句顺序（except B 在前）则输出 B, B, B，因为第一个匹配的 except 子句被触发。

稿件引文：Note that if the except clauses were reversed (with except B first), it
would have printed B, B, B — the first matching except clause is triggered.

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：A class in an except clause matches exceptions which are instances of the
class itself or one of its derived classes (but not the other way around — an
except clause listing a derived class does not match instances of its base classes).
For example, the following code will print B, C, D in that order:

支持材料 [d78785ba-26a6-4504-98df-3f4e3a5f575d]：Note that if the except clauses were reversed (with except B first), it
would have printed B, B, B — the first matching except clause is triggered.



### 依据稿件给异常处理代码审查建议：else应何时执行及为何比塞进try更合适

来源类型：作者设定

状态：通过

材料说明 else 子句在 try 子句不引发异常时执行，并说明使用 else 比把额外代码加入 try 子句更好，因为它避免意外捕获并非由受保护代码引发的异常。

稿件引文：The use of the else clause is better than adding additional code to
the try clause because it avoids accidentally catching an exception
that wasn’t raised by the code being protected by the try …
except statement.

支持材料 [10d7b4b6-1b0e-4695-8b08-558f79cd4fa1]：The try … except statement has an optional else
clause, which, when present, must follow all except clauses.  It is useful
for code that must be executed if the try clause does not raise an exception.
For example:

支持材料 [10d7b4b6-1b0e-4695-8b08-558f79cd4fa1]：The use of the else clause is better than adding additional code to
the try clause because it avoids accidentally catching an exception
that wasn’t raised by the code being protected by the try …
except statement.



### 依据稿件给异常处理代码审查建议：意外Exception被记录后建议如何处理，以及try调用的函数内部异常是否能被捕获

来源类型：作者设定

状态：通过

材料说明处理 Exception 的常见模式是打印或记录异常后重新引发，并说明异常处理器也会处理 try 子句中调用（甚至间接调用）的函数内部发生的异常。

稿件引文：The most common pattern for handling Exception is to print or log
the exception and then re-raise it (allowing a caller to handle the
exception as well):

支持材料 [10d7b4b6-1b0e-4695-8b08-558f79cd4fa1]：The most common pattern for handling Exception is to print or log
the exception and then re-raise it (allowing a caller to handle the
exception as well):

支持材料 [10d7b4b6-1b0e-4695-8b08-558f79cd4fa1]：Exception handlers do not handle only exceptions that occur immediately in the
try clause, but also those that occur inside functions that are called (even
indirectly) in the try clause. For example:



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。