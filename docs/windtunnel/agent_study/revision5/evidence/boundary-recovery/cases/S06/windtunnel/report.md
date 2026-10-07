# 有迹 · 内容预演报告



模式：AI 辅助检查；需要人工核实

稿件版本：22db1207-c6f1-483e-8887-30f357fbe019

条件版本：663e9bf0-1027-4ce4-b297-1926b578cc45

局限：引文存在不证明事实真实；检查通过不代表读者满意或传播效果。



## 稿件

文本文件读写

Python programs can open files to read or write data. `open()` returns a file object and is most commonly used as `open(filename, mode, encoding=None)`. The filename is a string. The mode is a string of a few characters: `'r'` reads only, `'w'` writes only and erases an existing file with the same name, `'a'` opens for appending and automatically adds any written data to the end, and `'r+'` opens for both reading and writing. Mode is optional; if omitted, `'r'` is assumed.

Files are normally opened in text mode, so you read and write strings using a specific encoding. If `encoding` is not specified, the default is platform dependent. Because UTF-8 is the modern de-facto standard, `encoding="utf-8"` is recommended unless you know you need another encoding. For log files that should keep existing content and add new records at the end, use append mode with UTF-8, for example `open('app.log', 'a', encoding='utf-8')`. The difference from `'w'` is important: `'w'` is for only writing, and an existing file with the same name will be erased; `'a'` preserves the existing content and appends to the end.

It is good practice to use the `with` keyword when dealing with file objects, because the file is properly closed after the suite finishes, even if an exception is raised. For example, `with open('app.log', 'a', encoding='utf-8') as f:` lets you write inside the block, and the file is closed automatically afterward. If you are not using `with`, you should call `f.close()` to close the file and immediately free up any system resources used by it. Calling `f.write()` without using `with` or calling `f.close()` might result in the arguments of `f.write()` not being completely written to the disk, even if the program exits successfully.

To read a file's contents, call `f.read(size)`, which returns a string in text mode or a bytes object in binary mode. `size` is optional. When `size` is omitted or negative, the entire contents of the file will be read and returned; it is your problem if the file is twice as large as your machine's memory. Otherwise, at most `size` characters in text mode or `size` bytes in binary mode are read and returned. If the end of the file has been reached, `f.read()` will return an empty string (`''`).

`f.readline()` reads a single line from the file. A newline character (`\n`) is left at the end of the string, and it is only omitted on the last line of the file if the file doesn't end in a newline. This makes the return value unambiguous: if `f.readline()` returns an empty string, the end of the file has been reached, while a blank line is represented by `'\n'`, a string containing only a single newline. For reading lines from a file, you can loop over the file object. This is memory efficient, fast, and leads to simple code, for example `for line in f: print(line, end='')`. If you want to read all the lines of a file in a list, you can also use `list(f)` or `f.readlines()`.

To copy a JPEG, you must be very careful to use binary mode. Appending a `'b'` to the mode opens the file in binary mode, and binary mode data is read and written as bytes objects. In text mode, the default when reading is to convert platform-specific line endings to just `\n`, and when writing in text mode, the default is to convert occurrences of `\n` back to platform-specific line endings. This behind-the-scenes modification to file data is fine for text files, but will corrupt binary data like that in JPEG or EXE files. Also, you cannot specify `encoding` when opening a file in binary mode.



## 条件与结果



### 依据稿件为同事制定日志文件读写方案：选择可保留原内容并在末尾追加的模式及UTF-8写法，说明与w模式的差异；说明为何使用with；区分readline返回空串和仅换行的含义；写出逐行读取的大文件方案并说明与read()无size的差别；说明复制JPEG时模式、读写对象类型及encoding参数限制。每项附稿内证据，不执行代码。

来源类型：作者设定

状态：通过

稿内材料分别支持日志追加模式与UTF-8写法、与w模式差异、with用法、readline空串与仅换行含义、逐行读取大文件方案及其与read()无size的差别、复制JPEG时的二进制模式、读写对象类型与encoding限制。

稿件引文：Files are normally opened in text mode, so you read and write strings using a specific encoding. If `encoding` is not specified, the default is platform dependent. Because UTF-8 is the modern de-facto standard, `encoding="utf-8"` is recommended unless you know you need another encoding. For log files that should keep existing content and add new records at the end, use append mode with UTF-8, for example `open('app.log', 'a', encoding='utf-8')`. The difference from `'w'` is important: `'w'` is for only writing, and an existing file with the same name will be erased; `'a'` preserves the existing content and appends to the end.

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：The first argument is a string containing the filename.  The second argument is
another string containing a few characters describing the way in which the file
will be used.  mode can be 'r' when the file will only be read, 'w'
for only writing (an existing file with the same name will be erased), and
'a' opens the file for appending; any data written to the file is
automatically added to the end.  'r+' opens the file for both reading and
writing. The mode argument is optional; 'r' will be assumed if it’s
omitted.

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：Normally, files are opened in text mode, that means, you read and write
strings from and to the file, which are encoded in a specific encoding.
If encoding is not specified, the default is platform dependent
(see open()).
Because UTF-8 is the modern de-facto standard, encoding="utf-8" is
recommended unless you know that you need to use a different encoding.
Appending a 'b' to the mode opens the file in binary mode.
Binary mode data is read and written as bytes objects.
You can not specify encoding when opening file in binary mode.

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：It is good practice to use the with keyword when dealing
with file objects.  The advantage is that the file is properly closed
after its suite finishes, even if an exception is raised at some
point.  Using with is also much shorter than writing
equivalent try-finally blocks:

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：If you’re not using the with keyword, then you should call
f.close() to close the file and immediately free up any system
resources used by it.

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：Calling f.write() without using the with keyword or calling
f.close() might result in the arguments
of f.write() not being completely written to the disk, even if the
program exits successfully.

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：To read a file’s contents, call f.read(size), which reads some quantity of
data and returns it as a string (in text mode) or bytes object (in binary mode).
size is an optional numeric argument.  When size is omitted or negative, the
entire contents of the file will be read and returned; it’s your problem if the
file is twice as large as your machine’s memory. Otherwise, at most size
characters (in text mode) or size bytes (in binary mode) are read and returned.
If the end of the file has been reached, f.read() will return an empty
string ('').

支持材料 [0ef822ba-0a19-48b3-92b9-48dac1834679]：f.readline() reads a single line from the file; a newline character (\n)
is left at the end of the string, and is only omitted on the last line of the
file if the file doesn’t end in a newline.  This makes the return value
unambiguous; if f.readline() returns an empty string, the end of the file
has been reached, while a blank line is represented by '\n', a string
containing only a single newline.

支持材料 [ec401377-46c2-4631-a356-b3cbcae8c07c]：For reading lines from a file, you can loop over the file object. This is memory
efficient, fast, and leads to simple code:

支持材料 [ec401377-46c2-4631-a356-b3cbcae8c07c]：>>> for line in f:
...     print(line, end='')
...
This is the first line of the file.
Second line of the file

支持材料 [ec401377-46c2-4631-a356-b3cbcae8c07c]：If you want to read all the lines of a file in a list you can also use
list(f) or f.readlines().



## 修改新增问题

本次没有报告新增问题；模拟模式或模型未发现均不保证没有错误。