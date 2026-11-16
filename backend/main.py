"""uvicorn 启动入口。

开发模式：uv run python main.py（自动 reload）
生产模式：uv run uvicorn main:app --workers 4
"""
import errno
import os
import socket
import subprocess
import sys

import uvicorn

from app import create_app
from config.settings import AppConfig

# 创建应用实例（供 uvicorn main:app 引用）
app = create_app()


def _describe_port_holder(port: int) -> str:
    """查端口占用者(PID + 完整命令);lsof/ps 不可用或没查到时返回空串,不影响启动。"""
    try:
        listed = subprocess.run(  # -t 只输出 PID,省得去解析 lsof 的列(COMMAND 含空格会错列)
            ['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'], capture_output=True, text=True, timeout=3
        )
        pids = [pid for pid in dict.fromkeys(listed.stdout.split()) if pid.isdigit()]
        if not pids:
            return ''
        detail = subprocess.run(
            ['ps', '-o', 'pid=,command=', '-p', ','.join(pids)], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):  # 没有 lsof / 超时:静默降级,别让提示功能拖垮启动
        return ''
    return '；'.join(line.strip() for line in detail.stdout.splitlines() if line.strip())


def _assert_port_available(host: str, port: int) -> None:
    """启动前探一次端口:被占就打印占用者与处置建议后退出,别把裸 [Errno 48] 丢给使用者。

    探测方式与 uvicorn 建监听 sock 一致(SO_REUSEADDR + bind),避免把 TIME_WAIT 误判成"被占"。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:  # 其它错误(如无权限)不拦,交给 uvicorn 自己报
            return
        holder = _describe_port_holder(port)
        print(f'[启动失败] 端口 {port} 已被占用：{holder or "占用者未知"}', file=sys.stderr)
        print('  处置：kill 上面那个进程，或改 .env.dev 的 APP_PORT 换个端口', file=sys.stderr)
        print('        （也可临时覆盖：APP_PORT=8123 python main.py）', file=sys.stderr)
        sys.stderr.flush()
        # 用 os._exit 而非 sys.exit:module_fund 为防 V8 崩溃刻意模块级保活 py_mini_racer 实例,
        # 它在解释器收尾时 __del__ 会 join 线程卡死,进程就成了"报了错却不退出"的幽灵,端着端口不放
        os._exit(1)
    finally:
        probe.close()


if __name__ == '__main__':
    # 开发模式：通过 python main.py 启动，支持热重载
    _assert_port_available(AppConfig.app_host, AppConfig.app_port)
    try:
        uvicorn.run(
            app='main:app',  # 指定 app 路径（字符串形式，reload 时需要）
            host=AppConfig.app_host,  # 监听地址
            port=AppConfig.app_port,  # 监听端口
            reload=AppConfig.app_reload,  # 是否热重载（开发模式 True）
            workers=AppConfig.app_workers,  # worker 数量（生产模式 >1）
            log_config=None,  # 禁用 uvicorn 默认日志配置，使用项目自定义日志
        )
    except SystemExit as exc:  # uvicorn 自己启动失败(如 bind 被抢)也会抛 SystemExit,同样别留幽灵
        os._exit(exc.code if isinstance(exc.code, int) else 1)
    # 正常停止(Ctrl+C / SIGTERM)后也直接 os._exit 收尾:走解释器收尾会被 py_mini_racer 的
    # __del__ 卡住,进程留在后台不放端口,下次启动就撞 [Errno 48]
    os._exit(0)