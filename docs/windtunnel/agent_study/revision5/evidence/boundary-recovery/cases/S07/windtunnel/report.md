# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：b1feb702-54c7-4396-8526-4c1260abb4e8

条件版本：52c075e3-25ac-4ae7-b892-f74975836845

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

JSON保存结构化数据

JSON (JavaScript Object Notation) is a popular data interchange format for storing structured data, and Python includes a json module for working with it. The json module can take Python data hierarchies and convert them to string representations; this process is called serializing. Reconstructing the data from the string representation is called deserializing. For example, if you have x = [1, 'simple', 'list'], you can view its JSON string representation with json.dumps(x), which produces '[1, "simple", "list"]'.

To save the string representation to a file, use json.dump(). If f is a text file object opened for writing, call json.dump(x, f). To read the data back, if f is a binary file or text file object opened for reading, call x = json.load(f). JSON files must be encoded in UTF-8; use encoding="utf-8" when opening a JSON file as a text file for both reading and writing. Do not casually replace JSON with pickle for untrusted data: pickle is insecure by default, and deserializing pickle data from an untrusted source can execute arbitrary code if the data was crafted by a skilled attacker. Also, JSON can handle lists and dictionaries, but serializing arbitrary class instances in JSON requires extra effort.



## 条件与结果



### 依据稿件设计保存x=[1,'simple','list']再恢复的JSON方案：说明字符串转换及反向重建的名称；给出产生JSON字符串的函数及结果；说明已打开文本文件对象f时写入与读取分别用什么函数；说明文本JSON文件的encoding要求；说明为何不能随便将不可信pickle替代JSON，以及JSON对任意类实例的限制。每项附稿内证据，不执行代码。

来源类型：作者设定

状态：通过

阅读状态为pass；稿件与材料一致支持所要求的各项：serializing/deserializing名称、json.dumps(x)及结果、f为已打开文本文件时写入json.dump(x, f)与读取x = json.load(f)、UTF-8/encoding="utf-8"要求、pickle对不可信数据的安全风险，以及JSON序列化任意类实例需额外努力。

稿件引文：JSON (JavaScript Object Notation) is a popular data interchange format for storing structured data, and Python includes a json module for working with it. The json module can take Python data hierarchies and convert them to string representations; this process is called serializing. Reconstructing the data from the string representation is called deserializing. For example, if you have x = [1, 'simple', 'list'], you can view its JSON string representation with json.dumps(x), which produces '[1, "simple", "list"]'.

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：Rather than having users constantly writing and debugging code to save
complicated data types to files, Python allows you to use the popular data
interchange format called JSON (JavaScript Object Notation).  The standard module called json can take Python
data hierarchies, and convert them to string representations; this process is
called serializing.  Reconstructing the data from the string representation
is called deserializing.  Between serializing and deserializing, the
string representing the object may have been stored in a file or data, or
sent over a network connection to some distant machine.

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：>>> import json
>>> x = [1, 'simple', 'list']
>>> json.dumps(x)
'[1, "simple", "list"]'

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：Another variant of the dumps() function, called dump(),
simply serializes the object to a text file.  So if f is a
text file object opened for writing, we can do this:

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：json.dump(x, f)

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：To decode the object again, if f is a binary file or
text file object which has been opened for reading:

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：x = json.load(f)

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：JSON files must be encoded in UTF-8. Use encoding="utf-8" when opening
JSON file as a text file for both of reading and writing.

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：This simple serialization technique can handle lists and dictionaries, but
serializing arbitrary class instances in JSON requires a bit of extra effort.
The reference for the json module contains an explanation of this.

支持材料 [bc5d2dc4-58ea-4bf6-94f6-7396c406f09c]：Contrary to JSON, pickle is a protocol which allows
the serialization of arbitrarily complex Python objects.  As such, it is
specific to Python and cannot be used to communicate with applications
written in other languages.  It is also insecure by default:
deserializing pickle data coming from an untrusted source can execute
arbitrary code, if the data was crafted by a skilled attacker.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。