import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/diagnose'
const columns = [
  "序号",
  "报告编号",
  "诊断对象",
  "指标采集窗口",
  "健康分值",
  "采集状态",
  "判定",
  "判定说明",
  "异常类型",
  "诊断时间"
]
const actions = [
  "开始诊断",
  "处理异常",
  "归档报告"
]
const stats = [
  {
    "label": "诊断报告总数",
    "value": 0
  },
  {
    "label": "采集缺失报告",
    "value": 0
  },
  {
    "label": "不可判定报告",
    "value": 0
  }
]

type MetricReference = {
  采集器编号: string | null
  监控对象: string | null
  指标名称: string | null
  采集间隔: string | null
  窗口序号: number | null
  窗口开始?: string | null
  窗口结束?: string | null
  采集状态: string
  缺失: boolean
  批次号?: string | null
  采集时间?: string | null
  聚合方式?: string | null
  数据快照?: Record<string, string | number> | null
  实际值?: number | null
  判定: string
  判定说明: string
}

type Row = Record<string, string | number | boolean | null> & {
  id: number
  指标采集结果?: MetricReference
}

function snapshotText(snapshot: Record<string, string | number> | null | undefined): string {
  if (!snapshot) return '—'
  return Object.entries(snapshot)
    .map(([key, value]) => `${key}: ${value}`)
    .join('，')
}

export default function DiagnoseView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('诊断报告列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务健康诊断列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? '服务健康诊断动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务健康诊断操作失败')
    }
  }

  const missingCount = rows.filter((row) => row.采集缺失).length
  const undeterminedCount = rows.filter((row) => row.判定 === '不可判定').length

  return (
    <section className="page" data-module="diagnose">
      <header className="page-head">
        <div>
          <h2>服务健康诊断管理</h2>
          <p className="page-desc">诊断报告引用服务指标采集的同一份窗口结果；引用的采集窗口缺失时明确标注不可判定，不用最近一次采集替代。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('诊断报告登记入口尚未接入审批流')}>
            登记诊断报告
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出服务健康诊断清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">{stats[0].label}</span>
          <strong className="stat-value">{total}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">{stats[1].label}</span>
          <strong className="stat-value">{missingCount}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">{stats[2].label}</span>
          <strong className="stat-value">{undeterminedCount}</strong>
        </article>
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>报告编号</span>
          <input
            value={filters.keyword ?? ''}
            placeholder="按报告编号检索"
            onChange={(event) => setFilters((prev) => ({ ...prev, keyword: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>诊断对象</span>
          <input
            value={filters.monitor_object ?? ''}
            placeholder="按诊断对象检索"
            onChange={(event) => setFilters((prev) => ({ ...prev, monitor_object: event.target.value }))}
          />
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>引用采集结果</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const reference = row.指标采集结果
            const missing = Boolean(row.采集缺失)
            return (
              <tr key={String(row.id)} className={missing ? 'row-missing' : undefined}>
                <td>{index + 1}</td>
                <td>{row.报告编号 ?? '—'}</td>
                <td>{row.诊断对象 ?? '—'}</td>
                <td>{reference ? `${reference.采集器编号 ?? '—'} · 窗口 ${reference.窗口序号 ?? '—'}` : '—'}</td>
                <td>{row.健康分值 ?? '—'}</td>
                <td>
                  <span className={missing ? 'badge badge-missing' : 'badge badge-ok'}>{row.采集状态 ?? '—'}</span>
                </td>
                <td>
                  <span className={row.判定 === '不可判定' ? 'badge badge-missing' : 'badge badge-ok'}>{row.判定 ?? '—'}</span>
                </td>
                <td>{row.判定说明 ?? '—'}</td>
                <td>{row.异常类型 ?? '—'}</td>
                <td>{row.诊断时间 ?? '—'}</td>
                <td>
                  {reference ? (
                    <div className="reference-cell">
                      <div>
                        {reference.指标名称} / {reference.采集间隔} / 聚合 {reference.聚合方式 ?? '—'}
                      </div>
                      <div className="cell-note">
                        {reference.缺失
                          ? `窗口 ${reference.窗口序号} 无有效批次，快照留空`
                          : `${reference.窗口开始} ~ ${reference.窗口结束} · 批次 ${reference.批次号} · ${snapshotText(reference.数据快照)}`}
                      </div>
                    </div>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="row-actions">
                  {actions.map((action) => (
                    <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                      {action}
                    </button>
                  ))}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无服务健康诊断数据，可先登记诊断报告</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条服务健康诊断记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
