# S07：JSON保存结构化数据

来源：https://docs.python.org/3.12/tutorial/inputoutput.html#saving-structured-data-with-json

采集时间（UTC）：2026-10-07T02:57:36.864156+00:00

来源性质：Python 3.12 官方英文文档公开章节，非用户投稿或真实创作者私稿。

许可：文档正文 PSF License Version 2；代码示例同时可按 0BSD 使用。

Copyright © 2001-2023 Python Software Foundation; All Rights Reserved.

许可全文见 ../LICENSE_PSF.txt、../LICENSE_0BSD.txt 与 ../LICENSE_SOURCE.txt。

改编说明：保留官方英文教程章节原文，未翻译、未人为植入错误、未添加真实作者反馈；仅添加来源与许可说明、删除网页段落锚点符号并整理空白。此为公开教程节选候选输入，不是 baseline 或风洞最终改稿。

## 待检查教程节选

```text
7.2.2. Saving structured data with json

Strings can easily be written to and read from a file.  Numbers take a bit more
effort, since the read() method only returns strings, which will have to
be passed to a function like int(), which takes a string like '123'
and returns its numeric value 123.  When you want to save more complex data
types like nested lists and dictionaries, parsing and serializing by hand
becomes complicated.

Rather than having users constantly writing and debugging code to save
complicated data types to files, Python allows you to use the popular data
interchange format called JSON (JavaScript Object Notation).  The standard module called json can take Python
data hierarchies, and convert them to string representations; this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.  Between serializing and deserializing, the
string representing the object may have been stored in a file or data, or
sent over a network connection to some distant machine.

Note

The JSON format is commonly used by modern applications to allow for data
exchange.  Many programmers are already familiar with it, which makes
it a good choice for interoperability.

If you have an object x, you can view its JSON string representation with a
simple line of code:

>>> import json
>>> x = [1, 'simple', 'list']
>>> json.dumps(x)
'[1, "simple", "list"]'

Another variant of the dumps() function, called dump(),
simply serializes the object to a text file.  So if f is a
text file object opened for writing, we can do this:

json.dump(x, f)

To decode the object again, if f is a binary file or
text file object which has been opened for reading:

x = json.load(f)

Note

JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.

This simple serialization technique can handle lists and dictionaries, but
serializing arbitrary class instances in JSON requires a bit of extra effort.
The reference for the json module contains an explanation of this.

See also

pickle - the pickle module

Contrary to JSON, pickle is a protocol which allows
the serialization of arbitrarily complex Python objects.  As such, it is
specific to Python and cannot be used to communicate with applications
written in other languages.  It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.
```
