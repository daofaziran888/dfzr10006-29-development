import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/metric'
const columns = [
  "序号",
  "采集器编号",
  "监控对象",
  "指标名称",
  "采集间隔",
  "聚合方式",
  "最近采集",
  "已采集窗口",
  "采集器状态"
]
const actions = [
  "启动采集",
  "暂停采集",
  "关闭采集"
]
const stats = [
  {
    "label": "指标采集器总数",
    "value": 0
  },
  {
    "label": "采集中采集器",
    "value": 0
  },
  {
    "label": "已暂停采集器",
    "value": 0
  }
]

type Collector = Record<string, string | number | null> & {
  id: number
  已采集窗口?: number[]
  最近窗口序号?: number | null
}

type Batch = {
  id: number
  批次号: string
  窗口序号: number
  采集时间: string
  聚合方式: string | null
  采样点数: number
  有效: boolean
  批次状态: string
  替换原因?: string
  数据快照: Record<string, string | number> | null
}

type Window = {
  窗口序号: number
  窗口开始: string
  窗口结束: string
  状态: string
  缺失: boolean
  批次号: string | null
  采集时间: string | null
  聚合方式: string | null
  配置聚合方式: string | null
  数据快照: Record<string, string | number> | null
  采样点数: number
  历史批次: Batch[]
  历史批次数: number
  缺失说明: string | null
}

type WindowPayload = {
  collector: Collector
  window_from: number
  window_to: number
  default_window_from: number
  default_window_to: number
  window_count: number
  windows: Window[]
  valid_windows: number[]
  missing_windows: number[]
  missing_message: string | null
}

function snapshotText(snapshot: Record<string, string | number> | null): string {
  if (!snapshot) return '—'
  return Object.entries(snapshot)
    .map(([key, value]) => `${key}: ${value}`)
    .join('，')
}

export default function MetricView() {
  const [rows, setRows] = useState<Collector[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({ metric_name: '' })
  const [selected, setSelected] = useState<WindowPayload | null>(null)
  const [windowFrom, setWindowFrom] = useState('1')
  const [windowTo, setWindowTo] = useState('2')
  const [locateForm, setLocateForm] = useState<Record<string, string>>({})
  const [batchForm, setBatchForm] = useState<Record<string, string>>({
    窗口序号: '2',
    采集时间: '',
    聚合方式: '',
    采样点数: '',
    数据快照: '{"失败率": 0.12, "下单量": 1000}',
  })
  const [expandedWindow, setExpandedWindow] = useState<number | null>(null)

  const query = () => {
    const params: Record<string, string> = {}
    if (filters.metric_name?.trim()) params.metric_name = filters.metric_name.trim()
    return params
  }

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}?${new URLSearchParams(query()).toString()}`)
      if (!response.ok) {
        throw new Error('指标采集器列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务指标采集列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  const loadWindows = useCallback(async (collectorId: number, from?: number, to?: number) => {
    setErrorMessage('')
    try {
      const params = new URLSearchParams()
      if (from !== undefined && to !== undefined) {
        params.set('window_from', String(from))
        params.set('window_to', String(to))
      }
      const suffix = params.toString() ? `?${params.toString()}` : ''
      const response = await request(`${ENDPOINT}/${collectorId}/windows${suffix}`)
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}))
        throw new Error(detail.detail ?? '采集窗口读取失败')
      }
      const payload: WindowPayload = await response.json()
      setSelected(payload)
      setWindowFrom(String(payload.window_from))
      setWindowTo(String(payload.window_to))
      setBatchForm((prev) => ({
        ...prev,
        聚合方式: prev.聚合方式 || String(payload.collector.聚合方式 ?? ''),
      }))
    } catch (error) {
      setSelected(null)
      setErrorMessage(error instanceof Error ? error.message : '采集窗口读取失败')
    }
  }, [])

  async function locateCollector() {
    setErrorMessage('')
    const params = new URLSearchParams()
    if (locateForm.monitor_object?.trim()) params.set('monitor_object', locateForm.monitor_object.trim())
    if (locateForm.metric_name?.trim()) params.set('metric_name', locateForm.metric_name.trim())
    if (locateForm.interval?.trim()) params.set('interval', locateForm.interval.trim())
    if (![...params.keys()].length) {
      setErrorMessage('请提供监控对象、指标名称与采集间隔以定位指标采集器')
      return
    }
    try {
      const response = await request(`${ENDPOINT}/locate?${params.toString()}`)
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail ?? '未找到匹配的指标采集器')
      }
      const collector = payload as Collector
      setFilters({ metric_name: String(collector.指标名称 ?? '') })
      await loadWindows(collector.id)
    } catch (error) {
      setSelected(null)
      setErrorMessage(error instanceof Error ? error.message : '指标采集器定位失败')
    }
  }

  function focusWindow(windowNo: number) {
    void loadWindows(Number(selected?.collector.id), windowNo, windowNo)
  }

  function clearWindowFocus() {
    void loadWindows(Number(selected?.collector.id))
  }

  async function submitBatch() {
    if (!selected) {
      setErrorMessage('请先定位指标采集器')
      return
    }
    setErrorMessage('')
    let snapshot: unknown
    try {
      snapshot = JSON.parse(batchForm.数据快照)
    } catch {
      setErrorMessage('数据快照必须是合法的 JSON 对象')
      return
    }
    try {
      const response = await request(`${ENDPOINT}/${selected.collector.id}/batches`, {
        method: 'POST',
        body: JSON.stringify({
          values: {
            窗口序号: Number(batchForm.窗口序号),
            采集时间: batchForm.采集时间 || undefined,
            聚合方式: batchForm.聚合方式 || undefined,
            采样点数: Number(batchForm.采样点数) || 0,
            数据快照: snapshot,
          },
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message ?? '采集批次登记失败')
      }
      await loadWindows(Number(selected.collector.id), Number(windowFrom), Number(windowTo))
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '采集批次登记失败')
    }
  }

  async function runAction(action: string, row: Collector) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('服务指标采集动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务指标采集操作失败')
    }
  }

  const selectedCollector = selected?.collector

  return (
    <section className="page" data-module="metric">
      <header className="page-head">
        <div>
          <h2>服务指标采集管理</h2>
          <p className="page-desc">按监控对象、指标名称与采集间隔定位指标采集器，按窗口序号查看采集快照与聚合方式；缺失窗口保留序号并明确标出。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('指标采集器登记入口尚未接入审批流')}>
            登记指标采集器
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出服务指标采集清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item, index) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">
              {index === 0 ? total : rows.filter((row) => row.status === (index === 1 ? '采集中' : '已暂停')).length}
            </strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>指标名称</span>
          <input
            value={filters.metric_name ?? ''}
            placeholder="按指标名称过滤"
            onChange={(event) => setFilters({ metric_name: event.target.value })}
          />
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({ metric_name: '' })}>重置条件</button>
      </form>

      <form className="filter-bar locate-bar" onSubmit={(event) => { event.preventDefault(); void locateCollector() }}>
        <label className="filter-item">
          <span>监控对象</span>
          <input
            value={locateForm.monitor_object ?? ''}
            placeholder="如：订单服务集群"
            onChange={(event) => setLocateForm((prev) => ({ ...prev, monitor_object: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>指标名称</span>
          <input
            value={locateForm.metric_name ?? ''}
            placeholder="如：订单创建失败率"
            onChange={(event) => setLocateForm((prev) => ({ ...prev, metric_name: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>采集间隔</span>
          <input
            value={locateForm.interval ?? ''}
            placeholder="如：1m"
            onChange={(event) => setLocateForm((prev) => ({ ...prev, interval: event.target.value }))}
          />
        </label>
        <button className="btn" type="submit">组合定位采集器</button>
        {selectedCollector && (
          <span className="locate-current">当前采集器：{selectedCollector.采集器编号}</span>
        )}
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id)} className={selectedCollector?.id === row.id ? 'row-active' : undefined}>
              <td>{index + 1}</td>
              <td>{row.采集器编号 ?? '—'}</td>
              <td>{row.监控对象 ?? '—'}</td>
              <td>{row.指标名称 ?? '—'}</td>
              <td>{row.采集间隔 ?? '—'}</td>
              <td>{row.聚合方式 ?? '—'}</td>
              <td>{row.最近采集 ?? '—'}</td>
              <td>{(row.已采集窗口 ?? []).join('、') || '无有效窗口'}</td>
              <td>{row.采集器状态 ?? '—'}</td>
              <td className="row-actions">
                <button className="link" type="button" onClick={() => void loadWindows(row.id)}>
                  查看采集窗口
                </button>
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无服务指标采集数据，可先按指标名称过滤或登记指标采集器</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条服务指标采集记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {selectedCollector && (
        <section className="window-panel" data-testid="metric-window-panel">
          <header className="panel-head">
            <div>
              <h3>采集窗口 · {selectedCollector.采集器编号}</h3>
              <p className="page-desc">
                {selectedCollector.监控对象} / {selectedCollector.指标名称} / 间隔 {selectedCollector.采集间隔} /
                聚合方式 {selectedCollector.聚合方式}
              </p>
            </div>
            <div className="window-controls">
              <label className="filter-item">
                <span>起始窗口</span>
                <input value={windowFrom} onChange={(event) => setWindowFrom(event.target.value)} />
              </label>
              <label className="filter-item">
                <span>截止窗口</span>
                <input value={windowTo} onChange={(event) => setWindowTo(event.target.value)} />
              </label>
              <button
                className="btn"
                type="button"
                onClick={() => void loadWindows(Number(selectedCollector.id), Number(windowFrom) || 1, Number(windowTo) || 1)}
              >
                定位窗口
              </button>
              <button className="btn ghost" type="button" onClick={clearWindowFocus}>
                查看全部已采集窗口
              </button>
            </div>
          </header>

          <p className="window-hint">
            采集窗口 {selected.window_from}–{selected.window_to}，有效窗口：
            {selected.valid_windows.join('、') || '无'}；缺失窗口：
            {selected.missing_windows.join('、') || '无'}。窗口按序号排列，跨窗口数据不合并。
          </p>
          {selected.missing_message && <p className="error-text">{selected.missing_message}</p>}

          <table className="data-table window-table">
            <thead>
              <tr>
                <th>窗口序号</th>
                <th>窗口区间</th>
                <th>采集状态</th>
                <th>有效批次</th>
                <th>采集时间</th>
                <th>数据快照</th>
                <th>聚合方式</th>
                <th>采样点数</th>
                <th>历史批次</th>
              </tr>
            </thead>
            <tbody>
              {selected.windows.map((window) => (
                <tr key={window.窗口序号} className={window.缺失 ? 'row-missing' : undefined}>
                  <td>{window.窗口序号}</td>
                  <td>{window.窗口开始} ~ {window.窗口结束}</td>
                  <td>
                    <span className={window.缺失 ? 'badge badge-missing' : 'badge badge-ok'}>{window.状态}</span>
                    {window.缺失 && <div className="cell-note">{window.缺失说明}</div>}
                  </td>
                  <td>{window.批次号 ?? '—'}</td>
                  <td>{window.采集时间 ?? '—'}</td>
                  <td>{snapshotText(window.数据快照)}</td>
                  <td>{window.聚合方式 ?? window.配置聚合方式 ?? '—'}</td>
                  <td>{window.缺失 ? '—' : window.采样点数}</td>
                  <td>
                    {window.历史批次数 === 0 ? (
                      '—'
                    ) : (
                      <button
                        className="link"
                        type="button"
                        onClick={() => setExpandedWindow(expandedWindow === window.窗口序号 ? null : window.窗口序号)}
                      >
                        {window.历史批次数} 个历史批次
                      </button>
                    )}
                    {expandedWindow === window.窗口序号 && (
                      <ul className="history-list">
                        {window.历史批次.map((batch) => (
                          <li key={batch.id}>
                            {batch.批次号} · {batch.采集时间} · {batch.聚合方式} · {snapshotText(batch.数据快照)}
                            {batch.替换原因 ? `（${batch.替换原因}）` : ''}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
              {selected.windows.length === 0 && (
                <tr>
                  <td className="empty-state" colSpan={9}>当前窗口范围内没有采集记录</td>
                </tr>
              )}
            </tbody>
          </table>

          <p className="window-hint">
            {selected.missing_windows.length > 0
              ? `窗口 ${selected.missing_windows.join('、')} 无有效批次：这些行不展示数据快照，不使用最近一次采集填充。`
              : '当前范围内每个窗口都有有效批次；同一窗口仅保留一个有效批次，历史批次可展开追溯。'}
            {' '}
            单窗口定位：
            {selected.windows.map((window) => (
              <button key={window.窗口序号} className="link" type="button" onClick={() => focusWindow(window.窗口序号)}>
                {window.窗口序号}
              </button>
            ))}
          </p>

          <form className="batch-form" onSubmit={(event) => { event.preventDefault(); void submitBatch() }}>
            <h4>登记采集批次</h4>
            <div className="filter-bar">
              <label className="filter-item">
                <span>窗口序号</span>
                <input value={batchForm.窗口序号} onChange={(event) => setBatchForm((prev) => ({ ...prev, 窗口序号: event.target.value }))} />
              </label>
              <label className="filter-item">
                <span>采集时间</span>
                <input
                  value={batchForm.采集时间}
                  placeholder="留空取当前时间"
                  onChange={(event) => setBatchForm((prev) => ({ ...prev, 采集时间: event.target.value }))}
                />
              </label>
              <label className="filter-item">
                <span>聚合方式</span>
                <input value={batchForm.聚合方式} onChange={(event) => setBatchForm((prev) => ({ ...prev, 聚合方式: event.target.value }))} />
              </label>
              <label className="filter-item">
                <span>采样点数</span>
                <input value={batchForm.采样点数} onChange={(event) => setBatchForm((prev) => ({ ...prev, 采样点数: event.target.value }))} />
              </label>
              <label className="filter-item snapshot-item">
                <span>数据快照（JSON）</span>
                <input value={batchForm.数据快照} onChange={(event) => setBatchForm((prev) => ({ ...prev, 数据快照: event.target.value }))} />
              </label>
              <button className="btn primary" type="submit">提交批次</button>
            </div>
            <p className="page-desc">同一窗口重复提交时，新批次生效，原有效批次转为历史批次，可在历史批次中追溯。</p>
          </form>
        </section>
      )}
    </section>
  )
}
