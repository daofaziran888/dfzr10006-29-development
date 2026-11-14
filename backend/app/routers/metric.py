"""服务指标采集接口：采集器定位、采集窗口快照、批次追溯与动作流转。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.metric import MetricService

router = APIRouter(prefix="/api/metric", tags=["服务指标采集"])

service = MetricService()

LIST_FIELDS = ["采集器编号", "监控对象", "指标名称", "采集间隔", "聚合方式", "保留天数", "最近采集", "采集器状态"]
STATUSES = ["草稿", "采集中", "已暂停", "已关闭"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按采集器编号检索"),
    monitor_object: str | None = Query(default=None, description="按监控对象检索"),
    metric_name: str | None = Query(default=None, description="按指标名称检索"),
    interval: str | None = Query(default=None, description="按采集间隔检索"),
    status: str | None = Query(default=None, description="草稿、采集中、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按采集器编号、监控对象、指标名称、采集间隔与状态过滤；列表按采集器编号排序。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        monitor_object=monitor_object,
        metric_name=metric_name,
        interval=interval,
        status=status,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/locate", response_model=dict)
def locate_entry(
    entry_id: int | None = Query(default=None, description="采集器编号（内部 ID）"),
    collector_no: str | None = Query(default=None, description="采集器编号，如 METR-0002"),
    monitor_object: str | None = Query(default=None, description="监控对象"),
    metric_name: str | None = Query(default=None, description="指标名称"),
    interval: str | None = Query(default=None, description="采集间隔"),
) -> dict:
    """按采集器编号，或监控对象+指标名称+采集间隔定位唯一采集器；定位失败给出可读原因。"""
    entry, message = service.locate_entry(
        entry_id=entry_id,
        collector_no=collector_no,
        monitor_object=monitor_object,
        metric_name=metric_name,
        interval=interval,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    return service.collector_view(entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出服务指标采集清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "metric", "total": total, "items": items}


@router.get("/{entry_id}/windows", response_model=dict)
def list_windows(
    entry_id: int,
    window_no: int | None = Query(default=None, gt=0, description="只查看某个窗口"),
    window_from: int | None = Query(default=None, ge=1, description="起始窗口序号"),
    window_to: int | None = Query(default=None, ge=1, description="截止窗口序号"),
) -> dict:
    """按窗口序号查看采集快照与聚合方式；缺失窗口保留序号并明确标出，不拼接其他窗口的数据。"""
    entry, message = service.locate_entry(entry_id=entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    try:
        return service.list_windows(entry, window_no=window_no, window_from=window_from, window_to=window_to)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{entry_id}/batches", response_model=list[dict])
def list_batches(
    entry_id: int,
    window_no: int | None = Query(default=None, gt=0, description="只查看某个窗口的批次"),
) -> list[dict]:
    """查看采集批次；同一窗口仅一个有效批次，历史批次仍可追溯。"""
    entry, message = service.locate_entry(entry_id=entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    try:
        return service.list_batches(entry, window_no=window_no)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{entry_id}/batches", response_model=ActionResult)
def record_batch(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记采集批次：重复采集同一窗口时只保留最新有效批次，旧批次转为历史批次。"""
    entry, message = service.locate_entry(entry_id=entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    window_no = payload.values.get("窗口序号")
    if window_no in (None, ""):
        return ActionResult(ok=False, message="缺少窗口序号，无法登记采集批次")
    batch, message = service.record_batch(entry, window_no, payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/{entry_id}/window", response_model=dict)
def evaluate_window(
    entry_id: int,
    window_no: int = Query(..., gt=0, description="窗口序号"),
) -> dict:
    """读取单个窗口的有效采集批次并给出判定；窗口缺失时明确不可判定。"""
    entry, message = service.locate_entry(entry_id=entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    return service.evaluate_window(entry=entry, window_no=window_no)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条指标采集器明细，含采集批次与已采集窗口序号。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"指标采集器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条指标采集器，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="指标采集器已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条指标采集器执行启动采集、暂停采集、关闭采集；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
