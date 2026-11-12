"""
统一配置加载器

支持：
  - config.yaml (真实配置)
  - config.example.yaml (模板)
  - 命令行 --config 指定路径
  - 环境变量覆盖（PATENT_MODE, PATENT_API_KEY 等）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


# ============================================================================
# 单例加载
# ============================================================================

_config: dict[str, Any] | None = None
_config_path: Path | None = None


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """
    加载配置文件，支持环境变量覆盖。
    
    优先级：命令行 path > 环境变量 PATENT_CONFIG > 自动查找
    """
    global _config, _config_path

    if _config is not None and path is None:
        return _config

    # 定位配置文件
    if path:
        cfg_path = Path(path)
    elif os.environ.get("PATENT_CONFIG"):
        cfg_path = Path(os.environ["PATENT_CONFIG"])
    else:
        # 自动查找：当前目录 config.yaml → config.example.yaml
        here = Path(__file__).resolve().parent
        cfg_path = here / "config.yaml"
        if not cfg_path.exists():
            cfg_path = here / "config.example.yaml"

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在：{cfg_path}\n"
            f"请复制 config.example.yaml 为 config.yaml 后修改，或通过 --config 指定路径。"
        )

    # 加载
    if yaml is None:
        # 退化为简单 JSON/YAML 文本解析（不完整，仅用于无 PyYAML 环境的基本字段）
        _config = _load_minimal(cfg_path)
    else:
        with cfg_path.open("r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}

    _config_path = cfg_path

    # 环境变量覆盖
    _apply_env_overrides(_config)

    return _config


def _load_minimal(path: Path) -> dict[str, Any]:
    """无 PyYAML 时的极简加载 —— 仅抽取 mode 和 output.root"""
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("mode:"):
            result["mode"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        if stripped.startswith("root:") and "output" in text.splitline_before_block(line) if False else True:
            # 简化处理
            result.setdefault("output", {})
            result["output"]["root"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return result


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    """允许环境变量覆盖关键配置（用于定时任务/CI）"""
    env_map = {
        "PATENT_MODE": ("mode",),
        "PATENT_ROOT": ("output", "root"),
        "PATENT_FULL_REBUILD": ("execution", "full_rebuild"),
    }
    for env_key, path in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            d = cfg
            for key in path[:-1]:
                d = d.setdefault(key, {})
            val_path = path[-1]
            if val_path == "execution.full_rebuild":
                d[val_path] = value.lower() in ("1", "true", "yes", "on")
            else:
                d[val_path] = value

    # API Key 单独支持环境变量
    providers = ["patenthub", "zhihuia", "incoPat"]
    for p in providers:
        env_key = f"PATENT_{p.upper()}_API_KEY"
        if env_key in os.environ:
            cfg.setdefault("api", {}).setdefault(p, {})["api_key"] = os.environ[env_key]


# ============================================================================
# 便捷访问
# ============================================================================

def get_mode() -> str:
    return load_config().get("mode", "web")


def get_targets() -> dict[str, Any]:
    return load_config().get("targets", {})


def get_output_root() -> Path:
    cfg = load_config()
    return Path(cfg.get("output", {}).get("root", "patent_monitor"))


def get_web_sources() -> list[str]:
    cfg = load_config()
    return cfg.get("web", {}).get("sources", ["wipo", "google"])


def get_audit_config() -> dict[str, Any]:
    return load_config().get("audit", {})


def get_api_config(provider: str | None = None) -> dict[str, Any]:
    cfg = load_config().get("api", {})
    if provider is None:
        provider = cfg.get("provider", "patenthub")
    return cfg.get(provider, {})
