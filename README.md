# ins_spider

Instagram 主页图片和 Reels 视频下载脚本。

本项目包含两个版本：

- 爬取_windows_自填ID_稳定最终版.py
- 爬取_windows_自填ID_代理最终版.py

---

## 1. 功能说明

用于下载 Instagram 指定账号主页内容：

- 主页图片 posts
- Reels 视频
- 自动保存发现的链接
- 自动跳过已下载内容
- 支持断点续跑
- 支持限制图片数量
- 支持限制 Reels 数量
- 支持自定义保存目录
- 支持浏览器登录资料目录，避免每次重复登录

---

## 2. 依赖环境

建议使用 Python 3.10 或以上版本。

依赖文件：

requirements.txt

当前依赖：

- playwright
- yt-dlp

---

## 3. 安装方式

进入项目目录：

cd "D:\编程\ins_spider"

创建虚拟环境：

python -m venv .venv

激活虚拟环境：

.\.venv\Scripts\Activate.ps1

安装 Python 依赖：

pip install -r requirements.txt

安装 Playwright Chromium 浏览器：

python -m playwright install chromium

---

## 4. 运行方式

稳定版测试运行：

python 爬取_windows_自填ID_稳定最终版.py -u kako.717 --max-photos 20 --max-reels 20

代理版测试运行：

python 爬取_windows_自填ID_代理最终版.py -u kako.717 --max-photos 20 --max-reels 20

只下载主页图片：

python 爬取_windows_自填ID_稳定最终版.py -u kako.717 --source posts

只下载 Reels 视频：

python 爬取_windows_自填ID_稳定最终版.py -u kako.717 --source reels

指定保存目录：

python 爬取_windows_自填ID_稳定最终版.py -u kako.717 -s "D:\ins_spider\downloads"

---

## 5. 参数说明

-u 或 --user

指定 Instagram 用户名，不要带 @。

示例：

python 爬取_windows_自填ID_稳定最终版.py -u kako.717

--source

指定下载来源。

可选值：

- all：图片和 Reels 都下载
- posts：只下载主页图片
- reels：只下载 Reels 视频

--max-photos

限制最多保存多少张图片。

--max-reels

限制最多保存多少个 Reels 视频。

-s 或 --save-root

指定保存根目录。

--no-download

只保存链接，不下载媒体文件。

---

## 6. 两个版本区别

稳定最终版：

适合普通网络环境，优先使用这个版本。

代理最终版：

适合需要代理环境时使用。

---

## 7. 重要安全说明

不要上传以下内容到 GitHub：

- .venv/
- .ig_browser_profile*/
- browser_profile*/
- User Data/
- Cookies
- Login Data
- Local State
- *_cookies.txt
- cookies.txt
- *.session
- *.db
- *.sqlite
- *.sqlite3
- *.jsonl
- downloads/
- output/
- outputs/
- temp/
- logs/
- *.log
- 图片文件
- 视频文件
- 压缩包

这些文件可能包含：

- 登录状态
- Cookie
- 账号信息
- 下载结果
- 本地缓存
- 临时数据

---

## 8. GitHub 提交说明

推荐只提交这些文件：

- .gitignore
- .gitattributes
- requirements.txt
- README.md
- 爬取_windows_自填ID_稳定最终版.py
- 爬取_windows_自填ID_代理最终版.py

提交命令：

git add .gitignore
git add .gitattributes
git add requirements.txt
git add README.md
git add "爬取_windows_自填ID_稳定最终版.py"
git add "爬取_windows_自填ID_代理最终版.py"

git commit -m "Update README"
git push

---

## 9. 常见问题

如果提示缺少 playwright：

pip install playwright

如果提示缺少 yt-dlp：

pip install yt-dlp

如果 Playwright 浏览器打不开：

python -m playwright install chromium

如果 Reels 视频个别打不开，可以安装 ffmpeg 后再重试。

---

## 10. 项目状态

当前仓库用于保存 Instagram 下载脚本源码。

浏览器登录数据、下载结果、缓存文件不纳入 GitHub 管理。
