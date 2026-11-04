# S08：处理异常

来源：https://docs.python.org/3.12/tutorial/errors.html#handling-exceptions

采集时间（UTC）：2026-10-07T02:57:37.835265+00:00

来源性质：Python 3.12 官方英文文档公开章节，非用户投稿或真实创作者私稿。

许可：文档正文 PSF License Version 2；代码示例同时可按 0BSD 使用。

Copyright © 2001-2023 Python Software Foundation; All Rights Reserved.

许可全文见 ../LICENSE_PSF.txt、../LICENSE_0BSD.txt 与 ../LICENSE_SOURCE.txt。

改编说明：保留官方英文教程章节原文，未翻译、未人为植入错误、未添加真实作者反馈；仅添加来源与许可说明、删除网页段落锚点符号并整理空白。此为公开教程节选候选输入，不是 baseline 或风洞最终改稿。

## 待检查教程节选

```text
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
```
