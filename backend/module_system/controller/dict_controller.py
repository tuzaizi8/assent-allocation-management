"""字典模块 Controller(API 路由层)。

完整路径 GET /dict/data/type/{dict_type} 与前端 fetcher 逐字一致。
消费侧查询:需登录但不挂 perms(字典是公共数据,07 七节规范 6)。
字典数据管理端点(2026-08-27):挂 CheckUserInterfaceAuth + 写操作 @ApiCacheEvict
清 dict_data 公共缓存(07 七节规范 4"管理端改字典主动清缓存"的落地)。
字典类型管理端点在 dict_type_controller.py(prefix=/dict/type)。
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.cache_annotation import ApiCache, ApiCacheEvict
from common.annotation.log_annotation import BusinessType, Log, LogMode
from common.annotation.rate_limit_annotation import ApiRateLimit
from common.response import DataResponseModel, ResponseBaseModel
from common.router import APIRouterPro
from core.context_utils import get_current_user_or_none
from core.interface_auth import CheckUserInterfaceAuth
from core.security import CurrentUser
from db.get_db import get_db
from module_system.entity.vo.dict_vo import (
    DeleteDictDataModel,
    DictDataAddModel,
    DictDataEditModel,
)
from module_system.service.dict_service import DictService
from utils.response_util import ResponseUtil

dict_controller = APIRouterPro(prefix='/dict/data', order_num=4, tags=['系统管理-字典管理'])


@dict_controller.get('/type/{dict_type}', summary='按类型获取字典数据', description='返回指定类型的字典选项列表')
@ApiCache(namespace='dict_data', expire_seconds=3600, vary_by_user=False)  # 公共缓存:全用户共享
@Log(title='字典管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_dict_data_by_type(
    request: Request,
    dict_type: Annotated[str, Path(description='字典类型,如 sys_user_sex')],
    current_user: CurrentUser,
    query_db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """获取指定类型的字典选项(前端 useDict 消费,契约见 07 4.1)。"""
    data = await DictService.get_dict_data_by_type_services(query_db, dict_type)
    return ResponseUtil.success(data=data)


@dict_controller.get(
    '/list',
    summary='获取字典数据列表接口',
    description='按类型返回全部字典数据(管理端,不过滤 status,按 dict_sort 排序)',
    response_model=DataResponseModel,
)
@ApiRateLimit(
    namespace='dict_data_list',
    limit=30,
    period=60,
    scope='user',
    algorithm='sliding_window',
    message='字典数据查询过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_dict_data_list(
    request: Request,
    dict_type: Annotated[str, Query(alias='dictType', description='字典类型,如 sys_user_sex')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:list')] = None,
) -> Response:
    """获取某类型的全部字典数据(管理端列表)。"""
    data = await DictService.get_dict_data_list_services(query_db, dict_type)
    return ResponseUtil.success(data=data)


@dict_controller.get(
    '/{dict_code}',
    summary='获取字典数据详情接口',
    description='返回字典数据信息',
    response_model=DataResponseModel,
)
@Log(title='字典管理', business_type=BusinessType.QUERY, mode=LogMode.AROUND)
async def get_dict_data_detail(
    request: Request,
    dict_code: Annotated[int, Path(description='字典编码')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:query')] = None,
) -> Response:
    """获取字典数据详情。"""
    dict_data = await DictService.get_dict_data_detail_services(query_db, dict_code)
    return ResponseUtil.success(data=dict_data)


@dict_controller.post(
    '',
    summary='新增字典数据接口',
    description='新增字典数据(所属类型必须存在;同类型内键值唯一)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_data_add',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='新增字典数据操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.INSERT, mode=LogMode.AROUND)
@ApiCacheEvict(evict_keys=['dict_data'])  # 写后清消费侧公共缓存(07 七节规范 4)
async def add_dict_data(
    request: Request,
    add_dict_data: DictDataAddModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:add')] = None,
) -> Response:
    """新增字典数据。"""
    current = get_current_user_or_none()
    add_dict_data.create_by = current.user_name if current else 'admin'
    add_dict_data.create_time = datetime.now()
    add_result = await DictService.add_dict_data_services(query_db, add_dict_data)
    return ResponseUtil.success(msg=add_result.message)


@dict_controller.put(
    '',
    summary='编辑字典数据接口',
    description='编辑字典数据(不允许修改所属类型)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_data_update',
    limit=24,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='修改字典数据操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.UPDATE, mode=LogMode.AROUND)
@ApiCacheEvict(evict_keys=['dict_data'])
async def edit_dict_data(
    request: Request,
    edit_dict_data: DictDataEditModel,
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:edit')] = None,
) -> Response:
    """编辑字典数据。"""
    current = get_current_user_or_none()
    edit_dict_data.update_by = current.user_name if current else 'admin'
    edit_dict_data.update_time = datetime.now()
    edit_result = await DictService.edit_dict_data_services(query_db, edit_dict_data)
    return ResponseUtil.success(msg=edit_result.message)


@dict_controller.delete(
    '/{dict_ids}',
    summary='删除字典数据接口',
    description='物理删除(内置字典项禁删)',
    response_model=ResponseBaseModel,
)
@ApiRateLimit(
    namespace='dict_data_delete',
    limit=6,
    period=120,
    scope='user',
    algorithm='sliding_window',
    message='删除字典数据操作过于频繁，请稍后再试',
)
@Log(title='字典管理', business_type=BusinessType.DELETE, mode=LogMode.AROUND)
@ApiCacheEvict(evict_keys=['dict_data'])
async def delete_dict_data(
    request: Request,
    dict_ids: Annotated[str, Path(description='需要删除的字典编码，多个用逗号分隔')],
    query_db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, CheckUserInterfaceAuth('system:dict:remove')] = None,
) -> Response:
    """删除字典数据(物理删除)。"""
    delete_dict_data = DeleteDictDataModel(
        dictIds=dict_ids,
        updateBy=get_current_user_or_none().user_name if get_current_user_or_none() else 'admin',
        updateTime=datetime.now(),
    )
    delete_result = await DictService.delete_dict_data_services(query_db, delete_dict_data)
    return ResponseUtil.success(msg=delete_result.message)
