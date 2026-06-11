# -*- coding: utf-8 -*-
"""
Instagram 主页图片 + Reels 视频下载 - Windows 自填ID稳定最终版

这版修复“有的照片下载不了”的根因：

- /p/ 主页帖子：不再交给 yt-dlp。yt-dlp 对 Instagram 图片帖/轮播图经常报 No video formats found。
  本版用 Playwright 浏览器真实打开帖子页，从 DOM 里抓 article 中的大图，逐张保存。
- /reel/ 视频页：继续交给 yt-dlp。Reels 是视频，yt-dlp 下载更稳定，保存的是可播放成品视频。
- 链接一发现就立即写入文件。
- 媒体一发现就立即下载保存。
- 中途 Ctrl+C，已经保存的链接和文件都会保留。
- 下次重跑会跳过已成功下载的链接。

安装依赖：
    pip install --upgrade playwright yt-dlp
    python -m playwright install chromium

测试每个来源 20 条：
    python 爬取_windows_图片修复最终版.py -u kako.717 --max 20

全量：
    python 爬取_windows_图片修复最终版.py -u kako.717

只爬主页图片：
    python 爬取_windows_图片修复最终版.py -u kako.717 --source posts

只爬 Reels 视频：
    python 爬取_windows_图片修复最终版.py -u kako.717 --source reels

关闭代理临时运行：
    python 爬取_windows_自填ID_代理最终版.py --no-proxy

保存到 D 盘：
    python 爬取_windows_图片修复最终版.py -u kako.717 -s "D:\\ins_spider\\downloads"

如果 Reels 视频个别打不开：
    安装 ffmpeg 后加 --allow-merge 重跑。
"""


# ========================
# 你主要改这里
# ========================

# 博主 Instagram ID / 用户名，不要带 @。
TARGET_INSTAGRAM_ID = "iamhitomi_yade"

# 图片严格最多保存多少张。0 表示不限制。
MAX_PHOTOS_TO_SAVE = 20

# Reels 视频严格最多保存多少个。0 表示不限制。
MAX_REELS_TO_SAVE = 100

# 下载来源："all" = 图片 + 视频；"posts" = 只图片；"reels" = 只视频。
SOURCE = "all"

# 保存根目录。留空则默认保存到当前 Windows 用户桌面。
SAVE_ROOT = ""

# 浏览器登录资料目录：使用上一版能跑通的 profile，避免白屏冲突。
BROWSER_PROFILE_DIR = ".ig_browser_profile_photo_fix"

# 是否启用代理。
# 代理会同时用于：
# 1. 弹出的 Chromium 浏览器
# 2. yt-dlp 下载 Reels 视频
# 3. 浏览器上下文里的图片请求
USE_PROXY = True

# 动态代理，默认使用这个。格式支持：
# http://用户名:密码@主机:端口
# 用户名:密码@主机:端口
# 主机:端口:用户名:密码
PROXY_URL = "http://Qg8Ajet4-res-th:GlVF6XC@proxy.as.ip2up.com:10235"

# 备用代理。默认不使用；如果要用，把 PROXY_URL 改成 BACKUP_PROXY_URL。
BACKUP_PROXY_URL = "http://y8dgm3ixmk2j:zeqgco73d7bi@103.23.128.229:1337"

# 每个页面最多滚动多少次。
SCROLLS = 200

# 连续多少次滚动没有新链接就停止。
IDLE_SCROLLS = 15

# 每个帖子最多尝试点击轮播下一张多少次。
POST_CAROUSEL_ROUNDS = 12

# 图片过滤：宽高至少多少像素。
POST_MIN_SIDE = 220

# 图片过滤：文件至少多少 KB。
POST_MIN_KB = 10

# Reels 视频如果个别打不开，安装 ffmpeg 后改成 True。
ALLOW_MERGE = False

# 是否保存 Reels 的 info.json 元数据。
WRITE_INFO_JSON = False

# 是否保留远端文件时间。False 表示使用下载时间。
KEEP_MTIME = False

# True = 只保存链接，不下载媒体。
NO_DOWNLOAD = False

# ========================
# 下面一般不用改
# ========================

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import unquote, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def require_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print("缺少 yt-dlp。请先执行：")
        print("pip install --upgrade yt-dlp")
        sys.exit(1)



def normalize_proxy_url(proxy_value: str) -> str:
    """
    统一代理格式。
    支持：
    1. http://user:pass@host:port
    2. user:pass@host:port
    3. host:port:user:pass
    """
    value = str(proxy_value or "").strip()

    if not value:
        return ""

    if "://" in value:
        return value

    # user:pass@host:port
    if "@" in value:
        return "http://" + value

    # host:port:user:pass
    parts = value.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return "http://{}:{}@{}:{}".format(user, password, host, port)

    # host:port
    if len(parts) == 2:
        return "http://" + value

    return value


def mask_proxy_url(proxy_url: str) -> str:
    """打印代理时隐藏账号密码。"""
    proxy_url = normalize_proxy_url(proxy_url)

    if not proxy_url:
        return "未启用"

    parsed = urlparse(proxy_url)

    if not parsed.hostname:
        return "已启用，但格式无法解析"

    port = ":{}".format(parsed.port) if parsed.port else ""
    return "{}://***:***@{}{}".format(parsed.scheme or "http", parsed.hostname, port)


def proxy_url_to_playwright(proxy_url: str) -> Optional[Dict[str, str]]:
    """把代理 URL 转成 Playwright 的 proxy 配置。"""
    proxy_url = normalize_proxy_url(proxy_url)

    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)

    if not parsed.hostname or not parsed.port:
        raise ValueError("代理格式错误，请使用 http://用户名:密码@主机:端口")

    scheme = parsed.scheme or "http"
    config: Dict[str, str] = {
        "server": "{}://{}:{}".format(scheme, parsed.hostname, parsed.port)
    }

    if parsed.username:
        config["username"] = unquote(parsed.username)

    if parsed.password:
        config["password"] = unquote(parsed.password)

    return config


def extract_username(value: str) -> str:
    value = str(value).strip()

    if not value:
        return ""

    match = re.search(r"instagram\.com/([^/?#]+)/?", value, re.I)
    if match:
        username = match.group(1).strip()
    else:
        username = value.strip().lstrip("@").strip("/")

    blocked = {
        "p",
        "reel",
        "reels",
        "stories",
        "explore",
        "accounts",
        "direct",
    }

    if username.lower() in blocked:
        return ""

    return username


def safe_name(name: str) -> str:
    name = str(name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = name.strip(". ")
    return name or "instagram_download"


def clean_url(url: str) -> str:
    url = str(url or "").strip().strip('"').strip("'")
    url = url.replace("\\u0026", "&")
    url = url.replace("\\/", "/")
    url = url.replace("&amp;", "&")
    return unquote(url)


def is_instagram_media_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False

    return (
        "cdninstagram" in host
        or "fbcdn.net" in host
        or "scontent" in host
        or "instagram.f" in host
    )


def read_lines(path: Path) -> Set[str]:
    if not path.exists():
        return set()

    result: Set[str] = set()

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                result.add(line)
    except Exception:
        pass

    return result


def append_line(path: Path, line: str):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line.strip() + "\n")
        f.flush()


def append_jsonl(path: Path, data: Dict):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
        f.flush()


def count_existing_files(directory: Path, patterns: Iterable[str]) -> int:
    if not directory.exists():
        return 0

    total = 0
    for pattern in patterns:
        total += len(list(directory.glob(pattern)))
    return total


def goto_page(page, url: str, wait_ms: int = 3000):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeoutError:
        print("打开页面超时，但继续尝试：{}".format(url))
    except Exception as e:
        print("打开页面提示：{}，继续尝试。".format(e))

    page.wait_for_timeout(wait_ms)


def try_dismiss_instagram_popups(page):
    texts = [
        "Not now",
        "Not Now",
        "Maybe Later",
        "以后再说",
        "暂时不要",
        "稍后再说",
        "取消",
        "关闭",
    ]

    for text in texts:
        try:
            locator = page.get_by_text(text, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=1200)
                page.wait_for_timeout(500)
        except Exception:
            pass


def wait_for_login(page, username: str):
    print("\n浏览器已打开。")
    print("请在浏览器里登录 Instagram。")
    print("如果已经登录，确认能正常打开 Instagram 首页或目标账号页面即可。")
    print("登录/验证完成后，不要关闭浏览器，回到 PowerShell 按回车。")

    goto_page(page, "https://www.instagram.com/", wait_ms=4000)
    try_dismiss_instagram_popups(page)

    input("\n确认浏览器里已经登录 Instagram 后，按回车继续：")

    target_url = "https://www.instagram.com/{}/".format(username)
    goto_page(page, target_url, wait_ms=5000)
    try_dismiss_instagram_popups(page)


def export_cookies_netscape(context, cookie_path: Path) -> bool:
    cookies = context.cookies("https://www.instagram.com")

    if not cookies:
        print("没有读取到浏览器 Cookie。")
        return False

    has_sessionid = any(cookie.get("name") == "sessionid" for cookie in cookies)

    if not has_sessionid:
        print("没有读取到 sessionid，说明浏览器里可能没有真正登录 Instagram。")
        return False

    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by 爬取_windows_图片修复最终版.py",
        "# Keep this file private.",
    ]

    count = 0

    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain") or ".instagram.com"
        path = cookie.get("path") or "/"
        expires = cookie.get("expires")
        secure = cookie.get("secure", False)

        if not name or value is None:
            continue

        if "instagram.com" not in domain:
            continue

        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure_text = "TRUE" if secure else "FALSE"

        try:
            expires_int = int(expires) if expires and expires > 0 else 0
        except Exception:
            expires_int = 0

        lines.append(
            "\t".join([
                domain,
                include_subdomains,
                path,
                secure_text,
                str(expires_int),
                name,
                value,
            ])
        )
        count += 1

    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("已导出 Cookie：{}，字段数：{}".format(cookie_path, count))
    return count > 0


def collect_page_links(page, link_marker: str) -> List[str]:
    try:
        hrefs = page.evaluate(
            """
            () => Array.from(document.querySelectorAll("a[href]"))
                .map(a => a.href)
                .filter(Boolean)
            """
        )
    except Exception:
        hrefs = []

    result: List[str] = []

    for href in hrefs:
        clean = href.split("?")[0].split("#")[0].rstrip("/") + "/"

        if "instagram.com" not in clean:
            continue

        if link_marker not in clean:
            continue

        result.append(clean)

    return result


def choose_largest_src_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""

    best_url = ""
    best_width = -1

    for part in srcset.split(","):
        part = part.strip()

        if not part:
            continue

        pieces = part.split()
        url = pieces[0].strip()
        width = 0

        if len(pieces) > 1:
            size = pieces[1].strip().lower()
            if size.endswith("w"):
                try:
                    width = int(size[:-1])
                except Exception:
                    width = 0

        if width >= best_width:
            best_width = width
            best_url = url

    return best_url


def extract_large_images_from_current_post(page, min_side: int) -> List[Dict]:
    """
    从当前帖子详情页的 article 中提取大图。
    重点过滤头像、icon、表情等小图。
    """
    try:
        rows = page.evaluate(
            """
            (minSide) => {
                const result = [];

                function clean(value) {
                    if (!value) return "";
                    return String(value)
                        .replaceAll("\\\\u0026", "&")
                        .replaceAll("\\\\/", "/")
                        .replaceAll("&amp;", "&");
                }

                function largestFromSrcset(srcset) {
                    if (!srcset) return "";
                    let bestUrl = "";
                    let bestWidth = -1;
                    srcset.split(",").forEach(part => {
                        const pieces = part.trim().split(/\\s+/);
                        const url = pieces[0] || "";
                        let width = 0;

                        if (pieces.length > 1 && pieces[1].endsWith("w")) {
                            width = parseInt(pieces[1].slice(0, -1), 10) || 0;
                        }

                        if (width >= bestWidth) {
                            bestWidth = width;
                            bestUrl = url;
                        }
                    });
                    return bestUrl;
                }

                const article = document.querySelector("article") || document.querySelector("main") || document.body;
                const imgs = Array.from(article.querySelectorAll("img"));

                imgs.forEach((img, index) => {
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    const alt = img.alt || "";
                    const srcsetUrl = largestFromSrcset(img.srcset || "");
                    const src = clean(srcsetUrl || img.currentSrc || img.src || "");

                    if (!src) return;

                    // 过滤头像、icon、小尺寸资源。
                    if (w < minSide || h < minSide) return;

                    result.push({
                        url: src,
                        width: w,
                        height: h,
                        alt: alt,
                        index: index,
                    });
                });

                return result;
            }
            """,
            min_side,
        )
    except Exception as e:
        print("[posts] 提取图片失败：{}".format(e))
        return []

    result: List[Dict] = []

    for row in rows:
        url = clean_url(row.get("url", ""))

        if not url.startswith("http"):
            continue

        if not is_instagram_media_host(url):
            continue

        result.append({
            "url": url,
            "width": row.get("width", 0),
            "height": row.get("height", 0),
            "alt": row.get("alt", ""),
        })

    return result


def try_click_next_in_post(page) -> bool:
    """
    尝试点击轮播下一张。
    成功返回 True；没找到按钮则 False。
    """
    selectors = [
        'button[aria-label="Next"]',
        'button[aria-label="下一步"]',
        'button[aria-label="下一张"]',
        'button[aria-label="下一页"]',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.last.click(timeout=1500)
                page.wait_for_timeout(1400)
                return True
        except Exception:
            pass

    # 键盘右箭头兜底，但不能无限按。调用方会做去重和轮数限制。
    try:
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


def get_ext_from_response_or_url(headers: Dict, url: str) -> str:
    content_type = (headers.get("content-type") or "").lower()
    lower_url = url.lower()

    if "png" in content_type or ".png" in lower_url:
        return "png"

    if "webp" in content_type or ".webp" in lower_url:
        return "webp"

    if "avif" in content_type or ".avif" in lower_url:
        return "avif"

    return "jpg"


def download_image_url(
    context,
    url: str,
    referer: str,
    output_dir: Path,
    source_name: str,
    link_index: int,
    image_index: int,
    saved_hashes: Set[str],
    min_kb: int,
) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        response = context.request.get(
            url,
            timeout=120000,
            headers={
                "referer": referer,
                "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )

        if not response.ok:
            print("[posts] 图片请求失败 HTTP {}：{}".format(response.status, url))
            return False

        body = response.body()

        if min_kb > 0 and len(body) < min_kb * 1024:
            print("[posts] 图片体积过小，跳过：{} KB".format(round(len(body) / 1024, 1)))
            return False

        body_hash = hashlib.sha1(body).hexdigest()

        if body_hash in saved_hashes:
            return True

        saved_hashes.add(body_hash)

        ext = get_ext_from_response_or_url(response.headers, url)
        filename = "{}_{:05d}_{:02d}_{}.{}".format(
            source_name,
            link_index,
            image_index,
            body_hash[:12],
            ext,
        )

        file_path = output_dir / filename
        file_path.write_bytes(body)

        print("[posts] 已保存图片：{}".format(file_path.name))
        return True

    except KeyboardInterrupt:
        raise

    except Exception as e:
        print("[posts] 图片下载失败：{}，原因：{}".format(url, e))
        return False


def download_post_images_with_browser(
    page,
    context,
    post_url: str,
    output_dir: Path,
    source_name: str,
    link_index: int,
    carousel_rounds: int,
    min_side: int,
    min_kb: int,
    saved_hashes: Set[str],
    remaining_images: Optional[int] = None,
) -> int:
    """
    用浏览器打开 /p/ 帖子，直接下载 article 中的大图。
    轮播帖会尝试点下一张。
    """
    goto_page(page, post_url, wait_ms=4500)
    try_dismiss_instagram_popups(page)

    found_urls: List[str] = []
    seen_urls: Set[str] = set()

    def collect_current():
        rows = extract_large_images_from_current_post(page, min_side=min_side)

        for row in rows:
            url = row["url"]

            if url not in seen_urls:
                seen_urls.add(url)
                found_urls.append(url)
                print("[posts] 发现图片 URL {}：{}x{}".format(
                    len(found_urls),
                    row.get("width", 0),
                    row.get("height", 0),
                ))

    collect_current()

    idle_rounds = 0

    for _ in range(carousel_rounds):
        before = len(found_urls)
        clicked = try_click_next_in_post(page)

        if not clicked:
            break

        collect_current()

        if len(found_urls) == before:
            idle_rounds += 1
        else:
            idle_rounds = 0

        # 连续两次没新图，基本就是没有更多轮播图了。
        if idle_rounds >= 2:
            break

    saved = 0

    for image_index, url in enumerate(found_urls, start=1):
        if remaining_images is not None and saved >= remaining_images:
            print("[posts] 本次图片保存数量已达到剩余额度 {}，停止当前帖子保存。".format(remaining_images))
            break

        ok = download_image_url(
            context=context,
            url=url,
            referer=post_url,
            output_dir=output_dir,
            source_name=source_name,
            link_index=link_index,
            image_index=image_index,
            saved_hashes=saved_hashes,
            min_kb=min_kb,
        )

        if ok:
            saved += 1

        time.sleep(0.25)

    print("[posts] 当前帖子保存图片 {} 张。".format(saved))
    return saved


def build_ydl_options(
    output_dir: Path,
    cookie_path: Path,
    user_agent: str,
    source_name: str,
    link_index: int,
    allow_merge: bool,
    write_info_json: bool,
    keep_mtime: bool,
    proxy_url: str = "",
) -> Dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    if allow_merge and shutil.which("ffmpeg") is None:
        print("提示：你启用了 --allow-merge，但没有检测到 ffmpeg。需要安装 ffmpeg 并加入 PATH。")

    fmt = "bestvideo*+bestaudio/best" if allow_merge else "best[ext=mp4]/best"

    ydl_opts = {
        "cookiefile": str(cookie_path),
        "paths": {
            "home": str(output_dir),
        },
        "outtmpl": {
            "default": "{source}_{index:05d}_%(extractor_key)s_%(id)s_%(title).100B.%(ext)s".format(
                source=source_name,
                index=link_index,
            ),
            "thumbnail": "{source}_{index:05d}_%(extractor_key)s_%(id)s_%(title).100B_thumbnail.%(ext)s".format(
                source=source_name,
                index=link_index,
            ),
        },
        "format": fmt,
        "merge_output_format": "mp4",
        "noplaylist": False,
        "ignoreerrors": True,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 5,
        "sleep_interval_requests": 1,
        "sleep_interval": 1,
        "max_sleep_interval": 3,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": False,
        "nooverwrites": True,
        "writeinfojson": write_info_json,
        "no_mtime": not keep_mtime,
        "quiet": False,
        "no_warnings": False,
        "http_headers": {
            "User-Agent": user_agent,
            "Referer": "https://www.instagram.com/",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    }

    if proxy_url:
        ydl_opts["proxy"] = proxy_url

    return ydl_opts


def download_reel_with_ytdlp(
    yt_dlp,
    url: str,
    output_dir: Path,
    cookie_path: Path,
    user_agent: str,
    source_name: str,
    link_index: int,
    allow_merge: bool,
    write_info_json: bool,
    keep_mtime: bool,
    proxy_url: str = "",
) -> bool:
    opts = build_ydl_options(
        output_dir=output_dir,
        cookie_path=cookie_path,
        user_agent=user_agent,
        source_name=source_name,
        link_index=link_index,
        allow_merge=allow_merge,
        write_info_json=write_info_json,
        keep_mtime=keep_mtime,
        proxy_url=proxy_url,
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            code = ydl.download([url])

        return code == 0

    except KeyboardInterrupt:
        raise

    except Exception as e:
        print("[reels] 下载失败：{}，原因：{}".format(url, e))
        return False


class SourceRunner:
    def __init__(
        self,
        *,
        page,
        context,
        yt_dlp,
        username: str,
        source_name: str,
        start_url: str,
        link_marker: str,
        output_dir: Path,
        links_dir: Path,
        cookie_path: Path,
        user_agent: str,
        proxy_url: str,
        max_count: int,
        scrolls: int,
        idle_limit: int,
        allow_merge: bool,
        write_info_json: bool,
        keep_mtime: bool,
        no_download: bool,
        global_all_links_path: Path,
        progress_path: Path,
        post_carousel_rounds: int,
        post_min_side: int,
        post_min_kb: int,
        post_saved_hashes: Set[str],
        media_limit: int = 0,
        media_saved_total: int = 0,
    ):
        self.page = page
        self.context = context
        self.yt_dlp = yt_dlp
        self.username = username
        self.source_name = source_name
        self.start_url = start_url
        self.link_marker = link_marker
        self.output_dir = output_dir
        self.links_dir = links_dir
        self.cookie_path = cookie_path
        self.user_agent = user_agent
        self.proxy_url = proxy_url
        self.max_count = max_count
        self.scrolls = scrolls
        self.idle_limit = idle_limit
        self.allow_merge = allow_merge
        self.write_info_json = write_info_json
        self.keep_mtime = keep_mtime
        self.no_download = no_download
        self.global_all_links_path = global_all_links_path
        self.progress_path = progress_path
        self.post_carousel_rounds = post_carousel_rounds
        self.post_min_side = post_min_side
        self.post_min_kb = post_min_kb
        self.post_saved_hashes = post_saved_hashes
        self.media_limit = media_limit
        self.media_saved_total = media_saved_total

        self.links_path = self.links_dir / "{}_links.txt".format(self.source_name)
        self.success_path = self.links_dir / "{}_downloaded_success.txt".format(self.source_name)
        self.failed_path = self.links_dir / "{}_download_failed.txt".format(self.source_name)

        self.known_links = read_lines(self.links_path)
        self.success_links = read_lines(self.success_path)
        self.global_known_links = read_lines(self.global_all_links_path)

        self.found_count_this_run = 0
        self.new_links_this_run = 0
        self.downloaded_this_run = 0
        self.failed_this_run = 0
        self.skipped_success_this_run = 0

    def write_link_immediately(self, link: str):
        if link not in self.known_links:
            append_line(self.links_path, link)
            self.known_links.add(link)
            self.new_links_this_run += 1
            print("[{}] 已写入链接：{}".format(self.source_name, link))

        if link not in self.global_known_links:
            append_line(self.global_all_links_path, link)
            self.global_known_links.add(link)

        append_jsonl(
            self.progress_path,
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "event": "link_found",
                "source": self.source_name,
                "url": link,
            },
        )

    def media_limit_reached(self) -> bool:
        return self.media_limit > 0 and self.media_saved_total >= self.media_limit

    def download_if_needed(self, link: str, link_index: int):
        if self.no_download:
            return

        if self.media_limit_reached():
            print("[{}] 已达到保存上限 {}，跳过后续下载。".format(self.source_name, self.media_limit))
            return

        if link in self.success_links:
            self.skipped_success_this_run += 1
            print("[{}] 已下载过，跳过：{}".format(self.source_name, link))
            return

        print("[{}] 开始下载：{}".format(self.source_name, link))

        if self.source_name == "posts":
            saved_count = download_post_images_with_browser(
                page=self.page,
                context=self.context,
                post_url=link,
                output_dir=self.output_dir,
                source_name=self.source_name,
                link_index=link_index,
                carousel_rounds=self.post_carousel_rounds,
                min_side=self.post_min_side,
                min_kb=self.post_min_kb,
                saved_hashes=self.post_saved_hashes,
                remaining_images=(self.media_limit - self.media_saved_total) if self.media_limit > 0 else None,
            )
            self.media_saved_total += saved_count
            ok = saved_count > 0
        else:
            ok = download_reel_with_ytdlp(
                yt_dlp=self.yt_dlp,
                url=link,
                output_dir=self.output_dir,
                cookie_path=self.cookie_path,
                user_agent=self.user_agent,
                source_name=self.source_name,
                link_index=link_index,
                allow_merge=self.allow_merge,
                write_info_json=self.write_info_json,
                keep_mtime=self.keep_mtime,
                proxy_url=self.proxy_url,
            )

        if ok:
            if self.source_name == "reels":
                self.media_saved_total += 1
            append_line(self.success_path, link)
            self.success_links.add(link)
            self.downloaded_this_run += 1
            append_jsonl(
                self.progress_path,
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "event": "download_success",
                    "source": self.source_name,
                    "url": link,
                },
            )
            print("[{}] 下载完成：{}".format(self.source_name, link))
        else:
            append_line(self.failed_path, link)
            self.failed_this_run += 1
            append_jsonl(
                self.progress_path,
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "event": "download_failed",
                    "source": self.source_name,
                    "url": link,
                },
            )
            print("[{}] 下载失败，已记录：{}".format(self.source_name, link))

    def handle_link(self, link: str):
        self.found_count_this_run += 1
        self.write_link_immediately(link)
        self.download_if_needed(link, self.found_count_this_run)

    def run(self):
        print("\n==============================")
        print("开始处理来源：{}".format(self.source_name))
        print("页面：{}".format(self.start_url))
        print("链接文件：{}".format(self.links_path))
        print("下载目录：{}".format(self.output_dir))
        print("==============================")

        goto_page(self.page, self.start_url, wait_ms=6000)
        try_dismiss_instagram_popups(self.page)

        seen_this_page: Set[str] = set()
        idle_rounds = 0

        for step in range(1, self.scrolls + 1):
            if self.media_limit_reached():
                print("[{}] 已达到保存上限 {}，停止当前来源。".format(self.source_name, self.media_limit))
                break

            links = collect_page_links(self.page, self.link_marker)
            before = len(seen_this_page)

            for link in links:
                if self.media_limit_reached():
                    break

                if link in seen_this_page:
                    continue

                seen_this_page.add(link)

                print("[{}] 发现链接 {}：{}".format(self.source_name, len(seen_this_page), link))
                self.handle_link(link)

                # 如果下载 posts 时打开了详情页，处理完要回列表页继续滚动。
                if self.source_name == "posts":
                    goto_page(self.page, self.start_url, wait_ms=2500)

                if self.max_count > 0 and len(seen_this_page) >= self.max_count:
                    print("[{}] 已达到 --max {}。".format(self.source_name, self.max_count))
                    self.print_summary()
                    return

            if len(seen_this_page) == before:
                idle_rounds += 1
            else:
                idle_rounds = 0

            if idle_rounds >= self.idle_limit:
                print("[{}] 连续 {} 次滚动没有新链接，停止。".format(self.source_name, self.idle_limit))
                break

            print("[{}] 第 {}/{} 次滚动，当前本页链接数：{}".format(
                self.source_name,
                step,
                self.scrolls,
                len(seen_this_page),
            ))

            try:
                self.page.mouse.wheel(0, 2600)
                self.page.wait_for_timeout(2500)
            except Exception:
                try:
                    self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    self.page.wait_for_timeout(2500)
                except Exception:
                    pass

        self.print_summary()

    def print_summary(self):
        print("\n[{}] 本轮完成。".format(self.source_name))
        print("[{}] 本轮发现链接：{} 个".format(self.source_name, self.found_count_this_run))
        print("[{}] 本轮新增写入：{} 个".format(self.source_name, self.new_links_this_run))
        print("[{}] 本轮下载成功：{} 个".format(self.source_name, self.downloaded_this_run))
        print("[{}] 本轮已下载跳过：{} 个".format(self.source_name, self.skipped_success_this_run))
        print("[{}] 本轮下载失败：{} 个".format(self.source_name, self.failed_this_run))
        if self.media_limit > 0:
            print("[{}] 当前累计保存：{} / {}".format(self.source_name, self.media_saved_total, self.media_limit))
        else:
            print("[{}] 当前累计保存：{}".format(self.source_name, self.media_saved_total))
        print("[{}] 链接文件：{}".format(self.source_name, self.links_path))
        print("[{}] 下载目录：{}".format(self.source_name, self.output_dir))


def write_run_summary(summary_path: Path, data: Dict):
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存运行摘要：{}".format(summary_path))


def parse_args():
    parser = argparse.ArgumentParser(description="Instagram 主页图片 + Reels 视频下载 - Windows 自填ID稳定最终版")

    parser.add_argument("-u", "--user", help="临时覆盖文件顶部 TARGET_INSTAGRAM_ID")
    parser.add_argument("-s", "--save-root", help="临时覆盖文件顶部 SAVE_ROOT")
    parser.add_argument("--source", choices=["all", "posts", "reels"], help="临时覆盖文件顶部 SOURCE")
    parser.add_argument("--max-photos", type=int, help="临时覆盖文件顶部 MAX_PHOTOS_TO_SAVE")
    parser.add_argument("--max-reels", type=int, help="临时覆盖文件顶部 MAX_REELS_TO_SAVE")
    parser.add_argument("--no-download", action="store_true", help="只保存链接，不下载媒体")
    parser.add_argument("--no-proxy", action="store_true", help="临时关闭文件顶部的代理配置")

    return parser.parse_args()

def main():
    args = parse_args()
    yt_dlp = require_yt_dlp()

    raw_user = args.user or TARGET_INSTAGRAM_ID
    username = extract_username(raw_user)

    if not username:
        print("无法识别 Instagram 用户名。请输入类似 kako.717 或 https://www.instagram.com/kako.717/reels/")
        return

    target = safe_name(username)

    if args.save_root:
        save_root = Path(args.save_root).expanduser()
    elif SAVE_ROOT:
        save_root = Path(SAVE_ROOT).expanduser()
    else:
        save_root = Path.home() / "Desktop"

    root_output_dir = save_root / target
    posts_output_dir = root_output_dir / "posts_photos"
    reels_output_dir = root_output_dir / "reels_videos"
    links_dir = root_output_dir / "_links"

    root_output_dir.mkdir(parents=True, exist_ok=True)
    posts_output_dir.mkdir(parents=True, exist_ok=True)
    reels_output_dir.mkdir(parents=True, exist_ok=True)
    links_dir.mkdir(parents=True, exist_ok=True)

    script_dir = Path(__file__).resolve().parent
    browser_profile_dir = Path(BROWSER_PROFILE_DIR)

    if not browser_profile_dir.is_absolute():
        browser_profile_dir = script_dir / browser_profile_dir

    cookie_path = root_output_dir / "_cookies.txt"
    all_links_path = links_dir / "all_links.txt"
    progress_path = links_dir / "progress.jsonl"
    summary_path = root_output_dir / "_run_summary.json"

    source = args.source or SOURCE
    max_photos = MAX_PHOTOS_TO_SAVE if args.max_photos is None else args.max_photos
    max_reels = MAX_REELS_TO_SAVE if args.max_reels is None else args.max_reels
    no_download = NO_DOWNLOAD or args.no_download
    proxy_url = normalize_proxy_url(PROXY_URL) if USE_PROXY and not args.no_proxy else ""

    if source not in ("all", "posts", "reels"):
        print('SOURCE 只能是 "all"、"posts" 或 "reels"')
        return

    existing_photo_count = count_existing_files(posts_output_dir, ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif"])
    existing_reel_count = len(read_lines(links_dir / "reels_downloaded_success.txt"))
    if existing_reel_count == 0:
        existing_reel_count = count_existing_files(reels_output_dir, ["*.mp4", "*.mkv", "*.webm", "*.mov"])

    print("\n目标账号：{}".format(username))
    print("下载来源：{}".format(source))
    print("图片上限：{}，0 表示不限制".format(max_photos))
    print("视频上限：{}，0 表示不限制".format(max_reels))
    print("当前已有图片文件：{}".format(existing_photo_count))
    print("当前已有视频记录：{}".format(existing_reel_count))
    print("根保存目录：{}".format(root_output_dir))
    print("主页图片保存：{}".format(posts_output_dir))
    print("Reels 视频保存：{}".format(reels_output_dir))
    print("链接保存目录：{}".format(links_dir))
    print("浏览器登录资料目录：{}".format(browser_profile_dir))
    print("代理状态：{}".format(mask_proxy_url(proxy_url)))
    print("说明：本版 /p/ 用浏览器抓图片，/reel/ 用 yt-dlp 抓视频。")

    started_at = datetime.now().isoformat(timespec="seconds")
    post_saved_hashes: Set[str] = set()

    with sync_playwright() as p:
        launch_kwargs = {
            "user_data_dir": str(browser_profile_dir),
            "headless": False,
            "viewport": {"width": 1280, "height": 900},
            "locale": "zh-CN",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        }

        if proxy_url:
            try:
                launch_kwargs["proxy"] = proxy_url_to_playwright(proxy_url)
            except Exception as e:
                print("代理配置错误：{}".format(e))
                return

        context = p.chromium.launch_persistent_context(**launch_kwargs)

        try:
            page = context.pages[0] if context.pages else context.new_page()

            wait_for_login(page, username)

            user_agent = page.evaluate("() => navigator.userAgent")

            if not export_cookies_netscape(context, cookie_path):
                print("Cookie 导出失败，停止。")
                return

            runners: List[SourceRunner] = []

            if source in ("all", "posts"):
                runners.append(
                    SourceRunner(
                        page=page,
                        context=context,
                        yt_dlp=yt_dlp,
                        username=username,
                        source_name="posts",
                        start_url="https://www.instagram.com/{}/".format(username),
                        link_marker="/p/",
                        output_dir=posts_output_dir,
                        links_dir=links_dir,
                        cookie_path=cookie_path,
                        user_agent=user_agent,
                        proxy_url=proxy_url,
                        max_count=0,
                        scrolls=SCROLLS,
                        idle_limit=IDLE_SCROLLS,
                        allow_merge=ALLOW_MERGE,
                        write_info_json=WRITE_INFO_JSON,
                        keep_mtime=KEEP_MTIME,
                        no_download=no_download,
                        global_all_links_path=all_links_path,
                        progress_path=progress_path,
                        post_carousel_rounds=POST_CAROUSEL_ROUNDS,
                        post_min_side=POST_MIN_SIDE,
                        post_min_kb=POST_MIN_KB,
                        post_saved_hashes=post_saved_hashes,
                        media_limit=max_photos,
                        media_saved_total=existing_photo_count,
                    )
                )

            if source in ("all", "reels"):
                runners.append(
                    SourceRunner(
                        page=page,
                        context=context,
                        yt_dlp=yt_dlp,
                        username=username,
                        source_name="reels",
                        start_url="https://www.instagram.com/{}/reels/".format(username),
                        link_marker="/reel/",
                        output_dir=reels_output_dir,
                        links_dir=links_dir,
                        cookie_path=cookie_path,
                        user_agent=user_agent,
                        proxy_url=proxy_url,
                        max_count=0,
                        scrolls=SCROLLS,
                        idle_limit=IDLE_SCROLLS,
                        allow_merge=ALLOW_MERGE,
                        write_info_json=WRITE_INFO_JSON,
                        keep_mtime=KEEP_MTIME,
                        no_download=no_download,
                        global_all_links_path=all_links_path,
                        progress_path=progress_path,
                        post_carousel_rounds=POST_CAROUSEL_ROUNDS,
                        post_min_side=POST_MIN_SIDE,
                        post_min_kb=POST_MIN_KB,
                        post_saved_hashes=post_saved_hashes,
                        media_limit=max_reels,
                        media_saved_total=existing_reel_count,
                    )
                )

            for runner in runners:
                runner.run()

            finished_at = datetime.now().isoformat(timespec="seconds")

            write_run_summary(
                summary_path,
                {
                    "username": username,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "source": source,
                    "max_photos": max_photos,
                    "max_reels": max_reels,
                    "scrolls": SCROLLS,
                    "root_output_dir": str(root_output_dir),
                    "posts_output_dir": str(posts_output_dir),
                    "reels_output_dir": str(reels_output_dir),
                    "links_dir": str(links_dir),
                    "posts_links_file": str(links_dir / "posts_links.txt"),
                    "reels_links_file": str(links_dir / "reels_links.txt"),
                    "all_links_file": str(all_links_path),
                    "progress_file": str(progress_path),
                    "download_enabled": not no_download,
                    "proxy_enabled": bool(proxy_url),
                    "proxy_masked": mask_proxy_url(proxy_url),
                    "allow_merge": ALLOW_MERGE,
                    "post_min_side": POST_MIN_SIDE,
                    "post_min_kb": POST_MIN_KB,
                },
            )

            print("\n全部处理完成。")
            print("主页链接文件：{}".format(links_dir / "posts_links.txt"))
            print("Reels 链接文件：{}".format(links_dir / "reels_links.txt"))
            print("全部链接文件：{}".format(all_links_path))
            print("主页图片目录：{}".format(posts_output_dir))
            print("Reels 视频目录：{}".format(reels_output_dir))

            if not ALLOW_MERGE:
                print("\n如果 Reels 仍有个别视频打不开，安装 ffmpeg 后用 --allow-merge 重跑。")

        except KeyboardInterrupt:
            print("\n用户中断。")
            print("已发现的链接已经实时保存到：{}".format(links_dir))
            print("已下载的文件已经保存在：{}".format(root_output_dir))

        finally:
            context.close()


if __name__ == "__main__":
    main()
