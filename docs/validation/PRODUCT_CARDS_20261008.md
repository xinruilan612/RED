# 真实产品图与文案卡片（2026-10-08）

用户取消简稿/完整稿选择，要求清晰图文、真实产品照片、逐页预览，并替换成品包中的纯文字图片。本轮保留已经确认的正文与审核历史，不进行收费模型调用。

## GitHub 参考核对

- https://github.com/vercel/satori ：将 HTML/CSS 内容渲染为 SVG，适合文字、图片组合的社交卡片。若以后需要完整 HTML 模板系统可评估引入；本轮未安装、未声称集成。
- https://github.com/joeseesun/qiaomu-info-card-designer ：杂志式信息卡设计与 HTML 截图工作流，适合参考视觉层级；本轮没有复制其实现或安装 Skill。
- https://github.com/THU-MAIC/OpenMAIC ：生成结构化页面元素，区分页面要点与完整讲述。只参考内容分区与可编辑预览思路，不宣称复刻其编辑器。

三天内优先复用现有 Pillow/FFmpeg 输出链路，实现真实图片混排、文字完整性、预览与下载一致。尚未加入自动语义提炼或任意商品联网找图。

## 操作

刷新网页并进入已确认稿件 → 图卡预览与下载 → 选择清爽杂志/重点清单 → 预览图卡 → 点缩略图检查或调整字号/强调色 → 重新预览 → 下载全部成品包。

罗技 M185 使用已核实照片；其他商品可上传 PNG/JPEG。匹配不到时明确提示没有产品图，不拿其他型号替代。图片来自 Wikimedia Commons 的 Hayden Schiff，CC BY 4.0，完整出处与处理说明随包交付。照片只表达外观，不作为连接性能、续航或亲测的证据。

图片用于封面和正文页。已下载到用户电脑的旧压缩包不会被悄悄改写；重新下载得到新排版，包内 images 与视频采用当前预览，caption 保留已确认原文。旧稿中已确认的声明不会在排版时自动删除。

## 验证

真实第四版在内存中排版，不更新任务、不新增模型调用。生成 5 张图卡及含视频的 14 文件完整包；逐张比对预览 PNG 与 ZIP 的 images/PNG 完全相同，caption 中完整保留确认正文，ZIP CRC 检查通过。实际图片已查看封面、连接说明页与末页，无文字或照片重叠。实物照片型号以来源文件描述核对，未宣称来自罗技官网。

产物：output/product-cards-20261008/youji-complete-0efe5ebe-product.zip（用户产物不提交 Git）。SHA-256：d3eca8d9f09744faecd9dae8f1f9e76d8946b268d77a6d25f65ea9faab12d560。

前端 269 项测试通过；最终图片布局/目录 21 项通过；12 份 JavaScript 语法、角色卡一致性与 git diff --check 通过。本机网页 HTTP 200，API 与 worker 已启动。浏览器正在被用户使用，本轮未夺取浏览器完成点击下载，不把脚本产物核验写成真人网页验收。

最终全量：TEST_DATABASE_URL=postgresql:///youji_operations runtime/venv/bin/python -m unittest discover -s tests -v，900 项通过，无跳过，含真实 PostgreSQL。测试日志 /tmp/red-photo-full.log。模型均为替身，不是模型质量验收。
