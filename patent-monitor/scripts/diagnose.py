"""
diagnose.py —— 专利检索流程健康检查

检查项：
  1. 配置文件可加载？mode 和 API Key 是否配置？
  2. 网络连通性？（WIPO / Google Patents / USPTO）
  3. PDF 下载链路？（选一个已知专利号做下载测试）
  4. 输出目录可写？
  5. 已有 Excel/JSON 是否完好？
  6. 模块导入是否正常？
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 颜色化输出（Windows 10+ 支持 ANSI）
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# ============================================================================
# 检查项
# ============================================================================

def check_config() -> dict:
    section("1. 配置文件")
    from config_loader import load_config
    try:
        cfg = load_config()
        ok(f"配置可加载 (mode={cfg.get('mode', '?')})")
        targets = cfg.get("targets", {})
        ok(f"靶点配置: {list(targets.keys())}")
        return cfg
    except FileNotFoundError as e:
        fail(str(e))
        return {}
    except Exception as e:
        fail(f"配置加载异常: {e}")
        return {}


def check_network(cfg: dict) -> None:
    section("2. 网络连通性")
    user_agent = (
        cfg.get("web", {}).get("http", {}).get("user_agent")
        or "Mozilla/5.0 Chrome/124.0"
    )
    headers = {"User-Agent": user_agent}
    tests = [
        ("WIPO PATENTSCOPE", "https://patentscope.wipo.int/search/en/result.jsf?_afrWindowMode=0&query=ALL%3D(TSHR)+AND+DP%3A%5B20250101+TO+20250102%5D"),
        ("Google Patents", "https://patents.google.com/xhr/query?url=q%3DTSHR%26dups%3Dlanguage%26before%3Dpublication%3A20250102"),
        ("USPTO", "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/US10596168B2"),
    ]
    for name, url in tests:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(100)
                if data:
                    ok(f"{name}: HTTP {resp.status} (有数据返回)")
                else:
                    warn(f"{name}: HTTP {resp.status} 但无数据")
        except urllib.error.HTTPError as e:
            if e.code in (403, 503):
                warn(f"{name}: HTTP {e.code}（可能被反爬/限流）")
            elif e.code == 404:
                fail(f"{name}: HTTP 404")
            else:
                warn(f"{name}: HTTP {e.code}")
        except Exception as e:
            fail(f"{name}: 不可达 ({e})")


def check_api_config(cfg: dict) -> None:
    section("3. API 配置")
    mode = cfg.get("mode", "web")
    if mode != "api":
        warn(f"当前 mode={mode}，跳过 API 配置检查")
        return

    providers = ["patenthub", "zhihuia", "incoPat"]
    for p in providers:
        pcfg = cfg.get("api", {}).get(p, {})
        key = pcfg.get("api_key", "")
        if not key or key.startswith("YOUR_"):
            fail(f"{p}: api_key 未配置")
        else:
            ok(f"{p}: api_key 已配置 (auth_type={pcfg.get('auth_type', '?')})")


def check_output_dirs(cfg: dict) -> None:
    section("4. 输出目录")
    from pathlib import Path
    out_root = Path(cfg.get("output", {}).get("root", "patent_monitor")).resolve()
    print(f"  根目录: {out_root}")

    try:
        out_root.mkdir(parents=True, exist_ok=True)
        ok(f"根目录可创建/访问")
    except PermissionError:
        fail(f"根目录无写入权限")
        return

    subdirs = ["reports", "patents"]
    for sub in subdirs:
        path = out_root / sub
        try:
            path.mkdir(parents=True, exist_ok=True)
            ok(f"{sub}/ 可访问")
        except Exception:
            fail(f"{sub}/ 不可访问")

    # 状态文件
    for fname in ["task_state.json", "patent_summary.xlsx", "patent_records.json"]:
        path = out_root / fname
        if path.exists():
            size = path.stat().st_size
            ok(f"{fname}: 存在 ({size} bytes)")
            if fname.endswith(".json"):
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    ok(f"  JSON 格式完好")
                except Exception as e:
                    fail(f"  JSON 损坏: {e}")
        else:
            warn(f"{fname}: 不存在（首次运行会创建）")


def check_pdf_pipeline(cfg: dict) -> None:
    section("5. PDF 下载链路")
    # 用一个已知公开的 US 专利测试
    test_pub = "US10596168B2"  # TSHR 抑制剂抗体 (Novartis)
    url = f"https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{test_pub}"
    headers = {"User-Agent": "Mozilla/5.0 Chrome/124.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(1024)
            if data.startswith(b"%PDF"):
                ok(f"USPTO PDF 下载链路 OK（文件头有效 %PDF）")
            else:
                fail(f"返回内容非 PDF（可能是验证码/错误页）")
    except Exception as e:
        warn(f"USPTO PDF 测试失败: {e}")
        # fallback 测 Google
        google_url = f"https://patents.google.com/patent/{test_pub}/pdf"
        try:
            req2 = urllib.request.Request(google_url, headers=headers)
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                data2 = resp2.read(1024)
                if data2.startswith(b"%PDF"):
                    ok(f"Google Patents PDF 链路 OK（USPTO 不通但 Google 可用）")
                else:
                    fail(f"两个 PDF 源都不可用")
        except Exception as e2:
            fail(f"PDF 下载不可用: USPTO→{e}; Google→{e2}")


def check_imports() -> None:
    section("6. 模块导入")
    modules = [
        "models", "config_loader", "screening", "downloader", "reporter",
        "retriever", "retriever.web_retriever", "retriever.api_retriever",
    ]
    for mod in modules:
        try:
            __import__(mod)
            ok(f"{mod}")
        except Exception as e:
            fail(f"{mod}: {e}")


# ============================================================================
# 主入口
# ============================================================================

def main() -> int:
    print("=" * 50)
    print("专利检索流程 —— 健康检查")
    print("=" * 50)

    cfg = check_config()
    if cfg:
        check_network(cfg)
        check_api_config(cfg)
        check_output_dirs(cfg)
        check_pdf_pipeline(cfg)
    check_imports()

    print("\n" + "=" * 50)
    print("健康检查完成 ✓")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
