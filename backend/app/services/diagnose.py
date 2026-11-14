"""服务健康诊断业务规则：引用指标采集结果形成判定，采集缺失时明确不可判定。"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.metric import MetricService

MODULE = "diagnose"
REQUIRED_FIELDS = ["报告编号", "诊断对象", "健康分值"]
STATUS_ORDER = ["草稿", "诊断中", "已生成", "已处理"]
ACTION_RULES = {"开始诊断": "草稿", "处理异常": "已生成", "归档报告": "已处理"}
NEGATIVE_ACTIONS = []

UNDETERMINED = "不可判定"


class DiagnoseService:
    def __init__(self) -> None:
        self.metric_service = MetricService()

    def _with_metric(self, entry: dict[str, Any]) -> dict[str, Any]:
        """把诊断报告挂到同一指标采集器的采集窗口上，引用同一份采集结果。"""
        report = dict(entry)
        collector_no = entry.get("指标采集器")
        window_no = entry.get("采集窗口序号")
        reference = self.metric_service.evaluate_window(
            collector_no=str(collector_no) if collector_no else None,
            window_no=window_no,
        )
        report["指标采集结果"] = reference
        report["采集状态"] = reference.get("采集状态")
        report["采集缺失"] = bool(reference.get("缺失"))
        report["判定"] = reference.get("判定")
        if reference.get("缺失"):
            report["健康分值"] = UNDETERMINED
            report["判定说明"] = (
                "引用的指标采集窗口缺失，服务健康诊断不可判定；"
                "不允许使用最近一次采集或其他窗口的数据替代"
            )
        else:
            report["判定说明"] = reference.get("判定说明")
            report["采集实际值"] = reference.get("实际值")
            report["异常类型"] = (
                entry.get("异常类型") if reference.get("判定") == "异常" else "无"
            )
        return report

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        monitor_object: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("报告编号", ""))]
        if monitor_object:
            rows = [row for row in rows if monitor_object in str(row.get("诊断对象", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._with_metric(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_metric(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["指标采集器"] = values.get("指标采集器")
        entry["采集窗口序号"] = values.get("采集窗口序号")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._with_metric(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"诊断报告 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于服务健康诊断可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        evaluation = self._with_metric(entry)
        if action == "处理异常" and evaluation["采集缺失"]:
            return None, "引用的指标采集窗口缺失，服务健康诊断不可判定，不能处理异常"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_metric(entry), f"诊断报告已{action}"
