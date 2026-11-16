"""操作日志后台入库服务。

@Log 注解只往内存队列塞字典(put_nowait,零阻塞),
由 lifespan 启动的后台协程逐条写库——日志写库失败不影响业务响应。
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from common.response import CrudResponseModel, PageModel
from db.database import AsyncSessionLocal
from module_system.dao.oper_log_dao import OperLogDao
from module_system.entity.do.oper_log_do import SysOperLog
from module_system.entity.vo.oper_log_vo import OperLogDeleteModel, OperLogDetailModel, OperLogQueryModel
from utils.camel_case_util import CamelCaseUtil
from utils.log import logger

# 进程内队列:上限 1000 防内存膨胀;满了丢弃并告警(日志可丢,业务不可慢)
OPER_LOG_QUEUE: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)


async def consume_oper_log_queue() -> None:
    """后台消费者:lifespan 启动时 create_task,循环取队列写库。"""
    while True:
        oper_log = await OPER_LOG_QUEUE.get()
        try:
            async with AsyncSessionLocal() as db:
                db.add(SysOperLog(**oper_log))
                await db.commit()
        except Exception as e:
            # 消费失败不重试、不中断:操作日志属可观测性数据,允许有损
            logger.error(f'[@Log] 操作日志入库失败(丢弃): {e} | title={oper_log.get("title")}')
        finally:
            OPER_LOG_QUEUE.task_done()


class OperLogService:
    """操作日志模块服务层(查询 + 删除;常规写入走队列消费,不经 service)。"""

    @classmethod
    async def get_oper_log_detail_services(
        cls, query_db: AsyncSession, oper_id: int
    ) -> OperLogDetailModel | None:
        """按 ID 查日志详情(全量含大字段,列表窄化后详情的唯一全量出口)。

        :param query_db: orm 对象
        :param oper_id: 日志主键
        :return: 详情模型(驼峰出网)或 None(不存在)
        """
        log_do = await OperLogDao.get_oper_log_by_id(query_db, oper_id)
        if log_do is None:
            return None
        return OperLogDetailModel.model_validate(
            CamelCaseUtil.transform_result(log_do)
        )

    @classmethod
    async def get_oper_log_list_services(
        cls,
        query_db: AsyncSession,
        query_object: OperLogQueryModel,
        is_page: bool = False,
    ) -> PageModel:
        """获取日志分页列表 service(category 分流操作/登录日志)。

        :param query_db: orm 对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 日志分页列表信息对象
        """
        # 查询操作无需事务控制，直接调用 DAO
        return await OperLogDao.get_oper_log_list(query_db, query_object, is_page)

    @classmethod
    async def delete_oper_log_services(cls, query_db: AsyncSession, page_object: OperLogDeleteModel) -> CrudResponseModel:
        """批量物理删除日志(操作/登录日志通用,清埋历史数据)。

        :param query_db: orm 对象
        :param page_object: 删除参数对象(逗号分隔 ID 串)
        :return: 删除结果信息对象
        """
        oper_ids = [int(x) for x in page_object.oper_ids.split(',') if x.strip()]
        try:
            await OperLogDao.delete_oper_log_dao(query_db, oper_ids)
            await query_db.commit()
            logger.info(f'[日志] 删除成功 oper_ids={page_object.oper_ids} 共{len(oper_ids)}条')
            return CrudResponseModel(is_success=True, message='删除成功')
        except Exception as e:
            await query_db.rollback()
            logger.error(f'[日志] 删除失败回滚 oper_ids={page_object.oper_ids} | {e}')
            raise e


def enqueue_oper_log(oper_log: dict) -> None:
    """@Log 注解调用:非阻塞入队。"""
    try:
        OPER_LOG_QUEUE.put_nowait(oper_log)
    except asyncio.QueueFull:
        logger.warning('[@Log] 操作日志队列已满,本条丢弃')