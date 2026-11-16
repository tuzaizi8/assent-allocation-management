"""字典类型管理 Controller(API 路由层)。

字典管理页(2026-08-27)配套接口;契约见知识库《04-字典管理页》。
路由经 APIRouterPro 自动注册;字典数据管理端点在 dict_controller.py(prefix=/dict/data)。
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, PageResponseModel, ResponseBaseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from db.get_db import get_db
from module_system.entity.vo.dict_vo import (
    DeleteDictTypeModel,
    DictTypeAddModel,
    DictTypeEditModel,
    DictTypePageQueryModel,
)
from module_system.service.dict_service import DictService
from utils.response_util import ResponseUtil

dict_type_controller = APIRouterPro(
    prefix='/dict/type',
    order_num=4,
    tags=['系统管理-字典管理'],
)


@dict_type_controller.get(
    '/list',
    summary='获取字典类型分页列表接口',
    description='用于获取字典类型分页列表(名称/类型模糊可选)',
    response_model=PageResponseModel,
)
@ApiRateLimit(
    namespace='dict_type_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='字典类型查询过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_dict_type_list(
    request: Request,
    dict_type_page_query: Annotated[DictTypePageQueryModel, Query()],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:list')] = None,
) -> Response:
    """获取字典类型分页列表。"""
    dict_type_list_result = await DictService.get_dict_type_list_services(
        query_db, dict_type_page_query, is_page=True
    )
    return ResponseUtil.success(model_content=dict_type_list_result)


@dict_type_controller.get(
    '/{dict_id}',
    summary='获取字典类型详情接口',
    description='返回字典类型信息',
    response_model=DataResponseModel,
)
@Log(title='字典管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_dict_type_detail(
    request: Request,
    dict_id: Annotated[int, Path(description='字典主键')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:query')] = None,
) -> Response:
    """获取字典类型详情。"""
    dict_type = await DictService.get_dict_type_detail_services(query_db, dict_id)
    return ResponseUtil.success(data=dict_type)


@dict_type_controller.post(
    '',
    summary='新增字典类型接口',
    description='新增字典类型(dict_type 唯一校验)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_type_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增字典类型操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
async def add_dict_type(
    request: Request,
    add_dict_type: DictTypeAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:add')] = None,
) -> Response:
    """新增字典类型。"""
    current = get_current_user_or_none()
    add_dict_type.create_by = current.user_name if current else 'admin'
    add_dict_type.create_time = datetime.now()
    add_result = await DictService.add_dict_type_services(query_db, add_dict_type)
    return ResponseUtil.success(msg=add_result.message)


@dict_type_controller.put(
    '',
    summary='编辑字典类型接口',
    description='编辑字典类型(内置类型的标识禁改)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_type_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改字典类型操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
async def edit_dict_type(
    request: Request,
    edit_dict_type: DictTypeEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:edit')] = None,
) -> Response:
    """编辑字典类型。"""
    current = get_current_user_or_none()
    edit_dict_type.update_by = current.user_name if current else 'admin'
    edit_dict_type.update_time = datetime.now()
    edit_result = await DictService.edit_dict_type_services(query_db, edit_dict_type)
    return ResponseUtil.success(msg=edit_result.message)


@dict_type_controller.delete(
    '/{dict_ids}',
    summary='删除字典类型接口',
    description='物理删除(内置类型禁删;有字典数据禁删)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_type_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除字典类型操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
async def delete_dict_type(
    request: Request,
    dict_ids: Annotated[str, Path(description='需要删除的字典主键，多个用逗号分隔')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:remove')] = None,
) -> Response:
    """删除字典类型(物理删除)。"""
    delete_dict_type = DeleteDictTypeModel(
        dictIds=dict_ids,
        updateBy=get_current_user_or_none().user_name if get_current_user_or_none() else 'admin',
        updateTime=datetime.now(),
    )
    delete_result = await DictService.delete_dict_type_services(query_db, delete_dict_type)
    return ResponseUtil.success(msg=delete_result.message)
