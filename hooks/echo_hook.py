"""echo_hook.py —— 最小调试钩子：验证事件触发与 stdin 协议

只做一件事：把收到的 stdin（Claude Code 递来的 JSON 信）追加写进 runs/hook_debug.log，exit 0。
hooks 的 stdout 没人看，调试必须写日志文件（行动方案 Phase 4 调试技巧）。
"""
import sys
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "runs" / "hook_debug.log"


def main() -> int:
    payload = sys.stdin.read()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] stdin={payload[:600]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
