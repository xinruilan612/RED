# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：f280309a-cf9a-44c2-b677-cc83e932ebcb

条件版本：5e044875-43c7-437f-bf3e-5a0b91077edf

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

JSON保存结构化数据

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



## 条件与结果



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明字符串转换及反向重建的名称

来源类型：作者设定

状态：通过

材料明确说明将 Python 数据层次转换为字符串表示称为 serializing，从字符串表示重建数据称为 deserializing。

稿件引文：Rather than having users constantly writing and debugging code to save
complicated data types to files, Python allows you to use the popular data
interchange format called JSON (JavaScript Object Notation).  The standard module called json can take Python
data hierarchies, and convert them to string representations; this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.  Between serializing and deserializing, the
string representing the object may have been stored in a file or data, or
sent over a network connection to some distant machine.

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：Rather than having users constantly writing and debugging code to save
complicated data types to files, Python allows you to use the popular data
interchange format called JSON (JavaScript Object Notation).  The standard module called json can take Python
data hierarchies, and convert them to string representations; this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.  Between serializing and deserializing, the
string representing the object may have been stored in a file or data, or
sent over a network connection to some distant machine.



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：给出产生JSON字符串的函数及结果

来源类型：作者设定

状态：通过

材料示例直接给出 import json、x = [1, 'simple', 'list']、json.dumps(x) 及结果 '[1, "simple", "list"]'。

稿件引文：>>> import json
>>> x = [1, 'simple', 'list']
>>> json.dumps(x)
'[1, "simple", "list"]'

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：>>> import json
>>> x = [1, 'simple', 'list']
>>> json.dumps(x)
'[1, "simple", "list"]'



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明已打开文本文件对象f时写入与读取分别用什么函数

来源类型：作者设定

状态：通过

材料分别给出写入用 json.dump(x, f)，读取用 x = json.load(f)。

稿件引文：json.dump(x, f)

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：json.dump(x, f)

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：x = json.load(f)



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明文本JSON文件的encoding要求

来源类型：作者设定

状态：通过

材料明确说明 JSON 文件必须以 UTF-8 编码，作为文本文件读写时使用 encoding="utf-8"。

稿件引文：JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明为何不能随便将不可信pickle替代JSON，以及JSON对任意类实例的限制

来源类型：作者设定

状态：通过

材料说明 pickle 默认不安全，反序列化来自不可信来源的 pickle 数据可能执行任意代码；同时说明该简单 JSON 序列化技术能处理列表和字典，但序列化任意类实例需要额外努力。

稿件引文：Contrary to JSON, pickle is a protocol which allows
the serialization of arbitrarily complex Python objects.  As such, it is
specific to Python and cannot be used to communicate with applications
written in other languages.  It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：Contrary to JSON, pickle is a protocol which allows
the serialization of arbitrarily complex Python objects.  As such, it is
specific to Python and cannot be used to communicate with applications
written in other languages.  It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.

支持材料 [96fce853-99f0-4bbc-9774-0a82c8ecde54]：This simple serialization technique can handle lists and dictionaries, but
serializing arbitrary class instances in JSON requires a bit of extra effort.
The reference for the json module contains an explanation of this.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。