"""客户端 IP 提取工具。

从 Request 中提取客户端真实 IP，处理反向代理场景（Nginx / CDN / API 网关）。
"""


from fastapi import Request


class ClientIPUtil:
    """客户端 IP 提取工具。"""

    @classmethod
    def get_client_ip(cls, request: Request) -> str:
        """从 Request 中提取客户端真实 IP。

        优先级：
        1. X-Forwarded-For 请求头（反向代理场景，取第一个 IP）
        2. X-Real-IP 请求头（部分代理只设置这个头）
        3. request.client.host（直连场景）
        4. 'unknown'（极端情况兜底）

        :param request: FastAPI Request 对象
        :return: 客户端真实 IP 字符串
        """
        # 1. X-Forwarded-For：可能有多个 IP（client, proxy1, proxy2），取第一个
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            return forwarded.split(',')[0].strip()
        # 2. X-Real-IP：部分反向代理只设置这个头
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        # 3. request.client.host：直连场景
        if request.client:
            return request.client.host
        # 4. 兜底
        return 'unknown'