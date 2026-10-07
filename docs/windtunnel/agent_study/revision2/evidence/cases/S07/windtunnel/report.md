# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：b1715cfc-bccc-4993-969a-6eee603db7eb

条件版本：47ecb7ac-a15d-473b-b724-479de5081ea3

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

材料明确说明字符串转换称为 serializing，反向重建称为 deserializing。

稿件引文：this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：给出产生JSON字符串的函数及结果

来源类型：作者设定

状态：通过

材料给出 json.dumps(x) 函数及结果示例 '[1, "simple", "list"]'。

稿件引文：>>> json.dumps(x)
'[1, "simple", "list"]'

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：>>> json.dumps(x)
'[1, "simple", "list"]'



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明已打开文本文件对象f时写入与读取分别用什么函数

来源类型：作者设定

状态：通过

材料分别给出写入函数 json.dump(x, f) 和读取函数 x = json.load(f)。

稿件引文：json.dump(x, f)

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：json.dump(x, f)

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：x = json.load(f)



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明文本JSON文件的encoding要求

来源类型：作者设定

状态：通过

材料明确要求 JSON 文件必须以 UTF-8 编码，文本文件读写时使用 encoding="utf-8"。

稿件引文：JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明为何不能随便将不可信pickle替代JSON，以及JSON对任意类实例的限制

来源类型：作者设定

状态：通过

材料说明不可信 pickle 反序列化可能执行任意代码，JSON 序列化任意类实例需要额外工作。

稿件引文：It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.

支持材料 [a6b8e2b9-d304-4610-959d-87716ce07543]：serializing arbitrary class instances in JSON requires a bit of extra effort.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。