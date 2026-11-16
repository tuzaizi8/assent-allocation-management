"""路由自动注册模块。

提供 APIRouterPro（带 order_num / auto_register 的扩展路由器）
与 RouterRegister（自动扫描注册器）。
"""

from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any

from fastapi import FastAPI, params
from fastapi.datastructures import Default
from fastapi.routing import APIRoute, APIRouter
from fastapi.utils import generate_unique_id
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Lifespan

import glob
import importlib
import os
import sys
from typing import Literal

class APIRouterPro(APIRouter):
    """扩展的 APIRouter，新增 order_num 与 auto_register 两个参数。

    - order_num：注册顺序，数值越小越靠前，默认 100
    - auto_register：是否参与自动注册，默认 True
    其他参数与 FastAPI 官方 APIRouter 完全一致。
    """

    def __init__(
        self,
        *,
        prefix: str = '',
        order_num: int = 100,
        auto_register: bool = True,
        tags: list[str | Enum] | None = None,
        dependencies: Sequence[params.Depends] | None = None,
        default_response_class: type[Response] = Default(JSONResponse),
        responses: dict[int | str, dict[str, Any]] | None = None,
        callbacks: list[BaseRoute] | None = None,
        routes: list[BaseRoute] | None = None,
        redirect_slashes: bool = True,
        default: ASGIApp | None = None,
        dependency_overrides_provider: Any | None = None,
        route_class: type[APIRoute] = APIRoute,
        on_startup: Sequence[Callable[[], Any]] | None = None,
        on_shutdown: Sequence[Callable[[], Any]] | None = None,
        lifespan: Lifespan[Any] | None = None,
        deprecated: bool | None = None,
        include_in_schema: bool = True,
        generate_unique_id_function: Callable[[APIRoute], str] = Default(generate_unique_id),
    ) -> None:
        # 保存新增的两个参数，供 RouterRegister 读取
        self.order_num = order_num
        self.auto_register = auto_register
        # 其余参数透传给父类 APIRouter
        super().__init__(
            prefix=prefix,
            tags=tags,
            dependencies=dependencies,
            default_response_class=default_response_class,
            responses=responses,
            callbacks=callbacks,
            routes=routes,
            redirect_slashes=redirect_slashes,
            default=default,
            dependency_overrides_provider=dependency_overrides_provider,
            route_class=route_class,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            lifespan=lifespan,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            generate_unique_id_function=generate_unique_id_function,
        )

class RouterRegister:
    """路由注册器：自动扫描所有 controller 目录下的 py 文件并注册路由。"""

    def __init__(self, app: FastAPI) -> None:
        """初始化路由注册器。

        :param app: FastAPI 应用对象
        """
        self.app = app
        # common/router.py 的上级目录即为项目根目录
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        # 将项目根目录加入 sys.path，确保 importlib 能按模块名导入
        sys.path.insert(0, self.project_root)

    def _find_controller_files(self) -> list[str]:
        """查找所有 controller 目录下的 py 文件（排除以 _ 开头的文件）。

        :return: 排序后的 py 文件绝对路径列表
        """
        # 关键 glob 模式：*/controller/[!_]*.py
        pattern = os.path.join(self.project_root, '*', 'controller', '[!_]*.py')
        # sorted 保证不同操作系统下的扫描顺序稳定
        return sorted(glob.glob(pattern))

    def _import_module_and_get_routers(self, controller_files: list[str]) -> list[tuple[str, APIRouter]]:
        """动态导入模块并收集其中的路由实例。

        :param controller_files: controller 目录下的 py 文件路径列表
        :return: (变量名, 路由实例) 二元组列表
        """
        routers: list[tuple[str, APIRouter]] = []
        for file_path in controller_files:
            # 将文件相对路径转换为模块名
            # 例：module_admin/controller/user_controller.py -> module_admin.controller.user_controller
            relative_path = os.path.relpath(file_path, self.project_root)
            module_name = relative_path.replace(os.sep, '.')[:-3]  # 去掉 .py 后缀

            # 动态导入模块
            module = importlib.import_module(module_name)

            # 遍历模块 __dict__，只收集模块自身定义的路由实例
            for attr_name, attr in module.__dict__.items():
                # APIRouterPro 实例：受 auto_register 控制
                if isinstance(attr, APIRouterPro):
                    if attr.auto_register:
                        routers.append((attr_name, attr))
                # 普通 APIRouter 实例：直接收集（保持向后兼容）
                elif isinstance(attr, APIRouter):
                    routers.append((attr_name, attr))
        return routers

    def _sort_routers(
        self, routers: list[tuple[str, APIRouter]]
    ) -> list[tuple[str, APIRouter]]:
        """按规则排序路由实例。

        排序规则：
        - APIRouterPro 实例优先，按 (0, order_num, attr_name) 排序
        - 普通 APIRouter 实例在后，按 (1, attr_name) 排序
        - 同组内 order_num 越小越靠前；order_num 相同则按变量名字典序

        :param routers: 路由实例列表
        :return: 排序后的路由实例列表
        """

        def sort_key(
            item: tuple[str, APIRouter],
        ) -> tuple[Literal[0], int, str] | tuple[Literal[1], str]:
            attr_name, router = item
            # APIRouterPro：组 0，按 order_num 升序，再按变量名
            if isinstance(router, APIRouterPro):
                return (0, router.order_num, attr_name)
            # 普通 APIRouter：组 1，仅按变量名
            return (1, attr_name)

        return sorted(routers, key=sort_key)

    def _register_routers_to_app(self, routers: list[tuple[str, APIRouter]]) -> None:
        """将排序后的路由实例注册到 FastAPI 应用。

        :param routers: 排序后的路由实例列表
        """
        for _attr_name, router in routers:
            self.app.include_router(router=router)

    def register_routers(self) -> None:
        """完整注册流程：扫描 -> 导入 -> 排序 -> 注册。"""
        # 1. 扫描 controller 文件
        controller_files = self._find_controller_files()
        # 2. 动态导入并收集路由实例
        routers = self._import_module_and_get_routers(controller_files)
        # 3. 按规则排序
        sorted_routers = self._sort_routers(routers)
        # 4. 注册到 FastAPI 应用
        self._register_routers_to_app(sorted_routers)

def auto_register_routers(app: FastAPI) -> None:
    """自动注册所有 controller 目录下的路由。

    使用方法：在 create_app 中调用 auto_register_routers(app)。

    :param app: FastAPI 应用对象
    :return: None
    """
    # 实例化注册器并执行完整注册流程
    router_register = RouterRegister(app)
    router_register.register_routers()