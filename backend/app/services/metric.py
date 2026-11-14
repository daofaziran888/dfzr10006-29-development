"""服务指标采集业务规则：采集器定位、采集窗口快照、批次去重与状态流转。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "metric"
REQUIRED_FIELDS = ["采集器编号", "监控对象", "指标名称"]
STATUS_ORDER = ["草稿", "采集中", "已暂停", "已关闭"]
ACTION_RULES = {"启动采集": "草稿", "暂停采集": "采集中", "关闭采集": "已暂停"}
NEGATIVE_ACTIONS = []

BATCH_VALID = "有效"
BATCH_HISTORY = "历史批次"
WINDOW_VALID = "有效"
WINDOW_MISSING = "缺失"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_BASE_TIME = "2026-11-14 10:00:00"
DEFAULT_INTERVAL_SECONDS = 60
MAX_WINDOW_SPAN = 200

INTERVAL_UNITS = {"s": 1, "秒": 1, "m": 60, "分": 60, "分钟": 60, "h": 3600, "小时": 3600}

LOCATOR_HINT = "请提供采集器编号，或同时提供监控对象、指标名称与采集间隔"


def parse_interval_seconds(value: Any) -> int | None:
    """把 30s、1m、5分钟 之类的采集间隔换算成秒；无法识别时返回 None。"""
    text = str(value or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*(s|秒|m|分|分钟|h|小时)?", text)
    if not match:
        return None
    seconds = int(match.group(1)) * INTERVAL_UNITS[match.group(2) or "s"]
    return seconds if seconds > 0 else None


def _format_time(value: datetime) -> str:
    return value.strftime(TIME_FORMAT)


def _window_bounds(entry: dict[str, Any], window_no: int) -> tuple[str, str]:
    """按采集器配置的间隔推导窗口起止时间，缺失窗口也能保留正确序号与时间。"""
    seconds = parse_interval_seconds(entry.get("采集间隔")) or DEFAULT_INTERVAL_SECONDS
    try:
        base = datetime.strptime(str(entry.get("采集起始") or DEFAULT_BASE_TIME), TIME_FORMAT)
    except ValueError:
        base = datetime.strptime(DEFAULT_BASE_TIME, TIME_FORMAT)
    start = base + timedelta(seconds=(window_no - 1) * seconds)
    return _format_time(start), _format_time(start + timedelta(seconds=seconds))


def _batch_sort_key(batch: dict[str, Any]) -> tuple[str, int]:
    return str(batch.get("采集时间") or ""), int(batch.get("id", 0))


def _copy_snapshot(snapshot: Any) -> dict[str, Any] | None:
    if isinstance(snapshot, dict):
        return {key: value for key, value in snapshot.items()}
    return None


def _copy_batch(batch: dict[str, Any]) -> dict[str, Any]:
    copied = {key: value for key, value in batch.items() if key != "数据快照"}
    copied["数据快照"] = _copy_snapshot(batch.get("数据快照"))
    copied["有效"] = bool(batch.get("有效"))
    if copied["有效"]:
        copied["批次状态"] = BATCH_VALID
    else:
        copied["批次状态"] = batch.get("批次状态") or BATCH_HISTORY
    return copied


def _collector_windows(entry: dict[str, Any]) -> list[int]:
    return sorted({
        int(batch.get("窗口序号") or 0)
        for batch in entry.get("采集批次", [])
        if int(batch.get("窗口序号") or 0) > 0 and bool(batch.get("有效"))
    })


class MetricService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        monitor_object: str | None = None,
        metric_name: str | None = None,
        interval: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("采集器编号", ""))]
        if monitor_object:
            rows = [row for row in rows if monitor_object in str(row.get("监控对象", ""))]
        if metric_name:
            rows = [row for row in rows if metric_name in str(row.get("指标名称", ""))]
        if interval:
            rows = [row for row in rows if interval in str(row.get("采集间隔", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: str(row.get("采集器编号", "")))
        total = len(rows)
        start = max(page - 1, 0) * size
        items: list[dict[str, Any]] = []
        for row in rows[start:start + size]:
            item = {key: value for key, value in row.items() if key != "采集批次"}
            item["已采集窗口"] = _collector_windows(row)
            item["最近窗口序号"] = max(item["已采集窗口"], default=None)
            items.append(item)
        return items, total

    def collector_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        view = {key: value for key, value in entry.items() if key != "采集批次"}
        view["已采集窗口"] = _collector_windows(entry)
        view["最近窗口序号"] = max(view["已采集窗口"], default=None)
        return view

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        view = self.collector_view(entry)
        view["采集批次"] = [ _copy_batch(batch) for batch in entry.get("采集批次", []) ]
        return view

    def locate_entry(
        self,
        *,
        entry_id: int | None = None,
        collector_no: str | None = None,
        monitor_object: str | None = None,
        metric_name: str | None = None,
        interval: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """用采集器编号或监控对象+指标名称+采集间隔定位唯一采集器。"""
        if entry_id is not None:
            try:
                entry = store.find(MODULE, int(entry_id))
            except (TypeError, ValueError):
                return None, f"指标采集器 {entry_id} 的编号不合法"
            if entry is None:
                return None, f"指标采集器 {entry_id} 不存在或已归档"
            return entry, ""

        conditions = {
            "采集器编号": collector_no,
            "监控对象": monitor_object,
            "指标名称": metric_name,
            "采集间隔": interval,
        }
        conditions = {field: value for field, value in conditions.items() if value not in (None, "")}
        if not conditions:
            return None, LOCATOR_HINT
        if "采集器编号" not in conditions and len(conditions) < 3:
            return None, LOCATOR_HINT

        candidates = store.rows(MODULE)
        for field, value in conditions.items():
            candidates = [row for row in candidates if str(row.get(field, "")) == str(value)]
        if not candidates:
            return None, "未找到匹配的指标采集器，请核对监控对象、指标名称与采集间隔"
        if len(candidates) > 1:
            return None, "组合条件匹配到多个指标采集器，请补充采集间隔或采集器编号"
        return candidates[0], ""

    def _window_item(self, entry: dict[str, Any], window_no: int) -> dict[str, Any]:
        batches = [
            batch for batch in entry.get("采集批次", [])
            if int(batch.get("窗口序号") or 0) == window_no
        ]
        valid = sorted(
            (batch for batch in batches if bool(batch.get("有效"))),
            key=_batch_sort_key,
        )
        # 重复采集同一窗口时写入侧已把旧批次降为历史批次，这里再兜底只取最新有效批次。
        effective = valid[-1] if valid else None
        history = sorted(
            (batch for batch in batches if not bool(batch.get("有效"))),
            key=_batch_sort_key,
            reverse=True,
        )
        start, end = _window_bounds(entry, window_no)
        if effective is None:
            return {
                "窗口序号": window_no,
                "窗口开始": start,
                "窗口结束": end,
                "状态": WINDOW_MISSING,
                "缺失": True,
                "批次号": None,
                "采集时间": None,
                "聚合方式": None,
                "配置聚合方式": entry.get("聚合方式"),
                "数据快照": None,
                "采样点数": 0,
                "历史批次": [_copy_batch(batch) for batch in history],
                "历史批次数": len(history),
                "缺失说明": f"窗口 {window_no} 无有效采集批次，不使用最近一次采集或其他窗口数据填充",
            }
        return {
            "窗口序号": window_no,
            "窗口开始": start,
            "窗口结束": end,
            "状态": WINDOW_VALID,
            "缺失": False,
            "批次号": effective.get("批次号"),
            "采集时间": effective.get("采集时间"),
            "聚合方式": effective.get("聚合方式") or entry.get("聚合方式"),
            "配置聚合方式": entry.get("聚合方式"),
            "数据快照": _copy_snapshot(effective.get("数据快照")),
            "采样点数": int(effective.get("采样点数") or 0),
            "历史批次": [_copy_batch(batch) for batch in history],
            "历史批次数": len(history),
            "缺失说明": None,
        }

    def list_windows(
        self,
        entry: dict[str, Any],
        *,
        window_no: int | None = None,
        window_from: int | None = None,
        window_to: int | None = None,
    ) -> dict[str, Any]:
        collected = _collector_windows(entry)
        try:
            configured_span = int(entry.get("窗口总数") or 0)
        except (TypeError, ValueError):
            configured_span = 0
        max_window = max([*collected, configured_span, 1])

        if window_no is not None:
            try:
                first = last = int(window_no)
            except (TypeError, ValueError):
                raise ValueError("窗口序号必须是正整数")
        else:
            try:
                first = int(window_from) if window_from is not None else 1
                last = int(window_to) if window_to is not None else max_window
            except (TypeError, ValueError):
                raise ValueError("窗口范围必须是整数")
            if last < first:
                raise ValueError("截止窗口不能小于起始窗口")
        if first < 1 or last < 1:
            raise ValueError("窗口序号从 1 开始")
        if last - first + 1 > MAX_WINDOW_SPAN:
            raise ValueError(f"单次最多查看 {MAX_WINDOW_SPAN} 个窗口")

        windows = [self._window_item(entry, number) for number in range(first, last + 1)]
        valid_windows = [item["窗口序号"] for item in windows if not item["缺失"]]
        missing_windows = [item["窗口序号"] for item in windows if item["缺失"]]
        return {
            "collector": self.collector_view(entry),
            "window_from": first,
            "window_to": last,
            "default_window_from": 1,
            "default_window_to": max_window,
            "window_count": len(windows),
            "windows": windows,
            "valid_windows": valid_windows,
            "missing_windows": missing_windows,
            "missing_message": (
                f"窗口 {missing_windows} 无有效采集批次，列表按窗口序号留空，不使用最近一次采集填充"
                if missing_windows else None
            ),
        }

    def list_batches(
        self,
        entry: dict[str, Any],
        *,
        window_no: int | None = None,
    ) -> list[dict[str, Any]]:
        batches = entry.get("采集批次", [])
        if window_no is not None:
            try:
                target = int(window_no)
            except (TypeError, ValueError):
                raise ValueError("窗口序号必须是整数")
            batches = [batch for batch in batches if int(batch.get("窗口序号") or 0) == target]
        items = [_copy_batch(batch) for batch in batches]
        items.sort(key=_batch_sort_key, reverse=True)
        items.sort(key=lambda batch: int(batch.get("窗口序号") or 0))
        return items

    def evaluate_window(
        self,
        *,
        entry: dict[str, Any] | None = None,
        collector_no: str | None = None,
        monitor_object: str | None = None,
        metric_name: str | None = None,
        interval: str | None = None,
        window_no: Any = None,
    ) -> dict[str, Any]:
        """读取某个采集窗口的有效批次并给出判定，缺失时明确不可判定。"""
        if entry is None:
            entry, locate_error = self.locate_entry(
                collector_no=collector_no,
                monitor_object=monitor_object,
                metric_name=metric_name,
                interval=interval,
            )
            if entry is None:
                return {
                    "采集器编号": collector_no,
                    "监控对象": monitor_object,
                    "指标名称": metric_name,
                    "采集间隔": interval,
                    "窗口序号": window_no,
                    "采集状态": WINDOW_MISSING,
                    "缺失": True,
                    "判定": "不可判定",
                    "判定说明": locate_error or "未找到指标采集器，采集结果不可判定",
                }
        try:
            number = int(window_no)
        except (TypeError, ValueError):
            return {
                "采集器编号": entry.get("采集器编号"),
                "监控对象": entry.get("监控对象"),
                "指标名称": entry.get("指标名称"),
                "采集间隔": entry.get("采集间隔"),
                "窗口序号": window_no,
                "采集状态": WINDOW_MISSING,
                "缺失": True,
                "判定": "不可判定",
                "判定说明": "诊断报告未关联有效的采集窗口序号",
            }
        if number < 1:
            return {
                "采集器编号": entry.get("采集器编号"),
                "监控对象": entry.get("监控对象"),
                "指标名称": entry.get("指标名称"),
                "采集间隔": entry.get("采集间隔"),
                "窗口序号": number,
                "采集状态": WINDOW_MISSING,
                "缺失": True,
                "判定": "不可判定",
                "判定说明": "窗口序号从 1 开始，采集结果不可判定",
            }

        item = self._window_item(entry, number)
        result: dict[str, Any] = {
            "采集器编号": entry.get("采集器编号"),
            "监控对象": entry.get("监控对象"),
            "指标名称": entry.get("指标名称"),
            "采集间隔": entry.get("采集间隔"),
            "窗口序号": number,
            "窗口开始": item["窗口开始"],
            "窗口结束": item["窗口结束"],
            "采集状态": item["状态"],
            "缺失": item["缺失"],
            "批次号": item["批次号"],
            "采集时间": item["采集时间"],
            "聚合方式": item["聚合方式"],
            "数据快照": item["数据快照"],
            "采样点数": item["采样点数"],
            "判定字段": entry.get("判定字段"),
            "判定阈值": entry.get("判定阈值"),
            "实际值": None,
            "判定": "不可判定",
            "判定说明": "",
        }
        if item["缺失"]:
            result["判定说明"] = (
                f"采集窗口 {number} 缺失，服务健康诊断不可判定；"
                "不允许用最近一次采集或其他窗口数据替代"
            )
            return result

        snapshot = item["数据快照"] or {}
        judge_field = entry.get("判定字段")
        actual = snapshot.get(judge_field) if judge_field else None
        result["实际值"] = actual
        if actual is None:
            result["判定说明"] = (
                f"窗口 {number} 的采集快照缺少判定字段「{judge_field or '未配置'}」，不可判定"
            )
            return result
        try:
            actual_number = float(actual)
            threshold = float(entry.get("判定阈值"))
        except (TypeError, ValueError):
            result["判定说明"] = "判定字段或判定阈值不是数值，不可判定"
            return result
        result["判定"] = "正常" if actual_number <= threshold else "异常"
        result["判定说明"] = (
            f"窗口 {number} 的 {judge_field}={actual}，阈值 ≤ {threshold:g}，判定{result['判定']}"
        )
        return result

    def record_batch(
        self,
        entry: dict[str, Any],
        window_no: Any,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """登记采集批次；同一窗口重复采集时只保留最新一个有效批次。"""
        try:
            number = int(window_no)
        except (TypeError, ValueError):
            return None, "窗口序号必须是正整数"
        if number < 1:
            return None, "窗口序号从 1 开始"

        snapshot = values.get("数据快照")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except json.JSONDecodeError:
                return None, "数据快照必须是 JSON 对象"
        if not isinstance(snapshot, dict) or not snapshot:
            return None, "缺少数据快照，无法登记采集批次"

        aggregation = str(values.get("聚合方式") or entry.get("聚合方式") or "").strip()
        if not aggregation:
            return None, "缺少聚合方式，无法登记采集批次"
        collect_time = str(values.get("采集时间") or datetime.now().strftime(TIME_FORMAT))
        try:
            sample_count = int(values.get("采样点数") or 0)
        except (TypeError, ValueError):
            sample_count = 0

        batches = entry.setdefault("采集批次", [])
        replaced: list[str] = []
        for batch in batches:
            if int(batch.get("窗口序号") or 0) == number and bool(batch.get("有效")):
                batch["有效"] = False
                batch["批次状态"] = BATCH_HISTORY
                batch["替换原因"] = "同一窗口重复采集，只保留一个有效批次"
                replaced.append(str(batch.get("批次号")))

        next_id = max((int(batch.get("id", 0)) for batch in batches), default=0) + 1
        batch = {
            "id": next_id,
            "批次号": f"BATCH-{next_id:04d}",
            "窗口序号": number,
            "采集时间": collect_time,
            "聚合方式": aggregation,
            "数据快照": _copy_snapshot(snapshot),
            "采样点数": sample_count,
            "有效": True,
            "批次状态": BATCH_VALID,
        }
        batches.append(batch)
        batches.sort(key=lambda item: (int(item.get("窗口序号") or 0), _batch_sort_key(item)))

        valid_times = [
            str(item.get("采集时间") or "")
            for item in batches
            if bool(item.get("有效"))
        ]
        if valid_times:
            entry["最近采集"] = max(valid_times)

        if replaced:
            message = (
                f"窗口 {number} 的采集批次已生效；原有效批次 {'、'.join(replaced)} 已转为历史批次"
            )
        else:
            message = f"窗口 {number} 的采集批次已生效"
        return _copy_batch(batch), message

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["采集间隔"] = values.get("采集间隔") or "60s"
        entry["采集起始"] = values.get("采集起始") or datetime.now().strftime(TIME_FORMAT)
        entry["聚合方式"] = values.get("聚合方式") or "平均值"
        entry["保留天数"] = values.get("保留天数") or "30"
        entry["最近采集"] = values.get("最近采集") or None
        entry["判定字段"] = values.get("判定字段")
        entry["判定阈值"] = values.get("判定阈值")
        entry["采集批次"] = []
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.get_entry(entry["id"]), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标采集器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于服务指标采集可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self.get_entry(entry_id), f"指标采集器已{action}"
