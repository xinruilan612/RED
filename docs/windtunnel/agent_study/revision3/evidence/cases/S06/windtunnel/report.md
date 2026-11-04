# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：a4c6ac3f-031a-4f15-9139-43a1fd9624f8

条件版本：c23f4b41-7852-47fb-b551-c8aaedb9819c

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

文本文件读写

7.2. Reading and Writing Files

open() returns a file object, and is most commonly used with
two positional arguments and one keyword argument:
open(filename, mode, encoding=None)

>>> f = open('workfile', 'w', encoding="utf-8")

The first argument is a string containing the filename.  The second argument is
another string containing a few characters describing the way in which the file
will be used.  mode can be 'r' when the file will only be read, 'w'
for only writing (an existing file with the same name will be erased), and
'a' opens the file for appending; any data written to the file is
automatically added to the end.  'r+' opens the file for both reading and
writing. The mode argument is optional; 'r' will be assumed if it’s
omitted.

Normally, files are opened in text mode, that means, you read and write
strings from and to the file, which are encoded in a specific encoding.
If encoding is not specified, the default is platform dependent
(see open()).
Because UTF-8 is the modern de-facto standard, encoding="utf-8" is
recommended unless you know that you need to use a different encoding.
Appending a 'b' to the mode opens the file in binary mode.
Binary mode data is read and written as bytes objects.
You can not specify encoding when opening file in binary mode.

In text mode, the default when reading is to convert platform-specific line
endings (\n on Unix, \r\n on Windows) to just \n.  When writing in
text mode, the default is to convert occurrences of \n back to
platform-specific line endings.  This behind-the-scenes modification
to file data is fine for text files, but will corrupt binary data like that in
JPEG or EXE files.  Be very careful to use binary mode when
reading and writing such files.

It is good practice to use the with keyword when dealing
with file objects.  The advantage is that the file is properly closed
after its suite finishes, even if an exception is raised at some
point.  Using with is also much shorter than writing
equivalent try-finally blocks:

>>> with open('workfile', encoding="utf-8") as f:
...     read_data = f.read()

>>> # We can check that the file has been automatically closed.
>>> f.closed
True

If you’re not using the with keyword, then you should call
f.close() to close the file and immediately free up any system
resources used by it.

Warning

Calling f.write() without using the with keyword or calling
f.close() might result in the arguments
of f.write() not being completely written to the disk, even if the
program exits successfully.

After a file object is closed, either by a with statement
or by calling f.close(), attempts to use the file object will
automatically fail.

>>> f.close()
>>> f.read()
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
ValueError: I/O operation on closed file.

7.2.1. Methods of File Objects

The rest of the examples in this section will assume that a file object called
f has already been created.

To read a file’s contents, call f.read(size), which reads some quantity of
data and returns it as a string (in text mode) or bytes object (in binary mode).
size is an optional numeric argument.  When size is omitted or negative, the
entire contents of the file will be read and returned; it’s your problem if the
file is twice as large as your machine’s memory. Otherwise, at most size
characters (in text mode) or size bytes (in binary mode) are read and returned.
If the end of the file has been reached, f.read() will return an empty
string ('').

>>> f.read()
'This is the entire file.\n'
>>> f.read()
''

f.readline() reads a single line from the file; a newline character (\n)
is left at the end of the string, and is only omitted on the last line of the
file if the file doesn’t end in a newline.  This makes the return value
unambiguous; if f.readline() returns an empty string, the end of the file
has been reached, while a blank line is represented by '\n', a string
containing only a single newline.

>>> f.readline()
'This is the first line of the file.\n'
>>> f.readline()
'Second line of the file\n'
>>> f.readline()
''

For reading lines from a file, you can loop over the file object. This is memory
efficient, fast, and leads to simple code:

>>> for line in f:
...     print(line, end='')
...
This is the first line of the file.
Second line of the file

If you want to read all the lines of a file in a list you can also use
list(f) or f.readlines().

f.write(string) writes the contents of string to the file, returning
the number of characters written.

>>> f.write('This is a test\n')
15

Other types of objects need to be converted – either to a string (in text mode)
or a bytes object (in binary mode) – before writing them:

>>> value = ('the answer', 42)
>>> s = str(value)  # convert the tuple to string
>>> f.write(s)
18

f.tell() returns an integer giving the file object’s current position in the file
represented as number of bytes from the beginning of the file when in binary mode and
an opaque number when in text mode.

To change the file object’s position, use f.seek(offset, whence).  The position is computed
from adding offset to a reference point; the reference point is selected by
the whence argument.  A whence value of 0 measures from the beginning
of the file, 1 uses the current file position, and 2 uses the end of the file as
the reference point.  whence can be omitted and defaults to 0, using the
beginning of the file as the reference point.

>>> f = open('workfile', 'rb+')
>>> f.write(b'0123456789abcdef')
16
>>> f.seek(5)      # Go to the 6th byte in the file
5
>>> f.read(1)
b'5'
>>> f.seek(-3, 2)  # Go to the 3rd byte before the end
13
>>> f.read(1)
b'd'

In text files (those opened without a b in the mode string), only seeks
relative to the beginning of the file are allowed (the exception being seeking
to the very file end with seek(0, 2)) and the only valid offset values are
those returned from the f.tell(), or zero. Any other offset value produces
undefined behaviour.

File objects have some additional methods, such as isatty() and
truncate() which are less frequently used; consult the Library
Reference for a complete guide to file objects.

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



### 依据稿件为同事制定日志文件读写方案：选择可保留原内容并在末尾追加的模式及UTF-8写法，说明与w模式的差异

来源类型：作者设定

状态：通过

稿件明确说明 'a' 模式用于追加，写入数据自动加到末尾以保留原内容；并推荐 encoding="utf-8" 作为现代事实标准。同时材料指出 'w' 只用于写入，会擦除同名已有文件，可支持与 'a' 的差异说明。

稿件引文：'a' opens the file for appending; any data written to the file is
automatically added to the end.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：'a' opens the file for appending; any data written to the file is
automatically added to the end.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：'w'
for only writing (an existing file with the same name will be erased)

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：Because UTF-8 is the modern de-facto standard, encoding="utf-8" is
recommended unless you know that you need to use a different encoding.



### 依据稿件为同事制定日志文件读写方案：说明为何使用with

来源类型：作者设定

状态：通过

稿件直接说明使用 with 的优势是文件在套件结束后正确关闭，即使抛出异常；并指出 with 比等价的 try-finally 更简短。

稿件引文：It is good practice to use the with keyword when dealing
with file objects.  The advantage is that the file is properly closed
after its suite finishes, even if an exception is raised at some
point.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：It is good practice to use the with keyword when dealing
with file objects.  The advantage is that the file is properly closed
after its suite finishes, even if an exception is raised at some
point.



### 依据稿件为同事制定日志文件读写方案：区分readline返回空串和仅换行的含义

来源类型：作者设定

状态：通过

稿件明确区分空串与仅换行的含义：返回空字符串表示到达文件末尾，而空行由只含单个换行符的字符串 '\n' 表示。

稿件引文：if f.readline() returns an empty string, the end of the file
has been reached, while a blank line is represented by '\n', a string
containing only a single newline.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：if f.readline() returns an empty string, the end of the file
has been reached, while a blank line is represented by '\n', a string
containing only a single newline.



### 依据稿件为同事制定日志文件读写方案：写出逐行读取的大文件方案并说明与read()无size的差别

来源类型：作者设定

状态：通过

稿件给出逐行读取方式：直接迭代文件对象 for line in f，并说明其内存高效、快速且代码简单；同时说明无 size 的 f.read() 会读取并返回整个文件，并提示文件若为机器内存两倍则是使用者的问题，可支持与逐行读取的差别。

稿件引文：For reading lines from a file, you can loop over the file object. This is memory
efficient, fast, and leads to simple code:

支持材料 [e0fdd542-f597-49d9-b50d-8c48f3b740a6]：For reading lines from a file, you can loop over the file object. This is memory
efficient, fast, and leads to simple code:

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：When size is omitted or negative, the
entire contents of the file will be read and returned; it’s your problem if the
file is twice as large as your machine’s memory.



### 依据稿件为同事制定日志文件读写方案：说明复制JPEG时模式、读写对象类型及encoding参数限制

来源类型：作者设定

状态：通过

稿件说明附加 'b' 打开二进制模式，二进制模式数据读写为 bytes 对象，且不能在二进制模式下指定 encoding；同时警告 JPEG 等二进制数据需谨慎使用二进制模式。

稿件引文：Appending a 'b' to the mode opens the file in binary mode.
Binary mode data is read and written as bytes objects.
You can not specify encoding when opening file in binary mode.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：Appending a 'b' to the mode opens the file in binary mode.
Binary mode data is read and written as bytes objects.
You can not specify encoding when opening file in binary mode.

支持材料 [121bce55-d3c1-4935-82a5-b30af34bff9b]：will corrupt binary data like that in
JPEG or EXE files.  Be very careful to use binary mode when
reading and writing such files.



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。