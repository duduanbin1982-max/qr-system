import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/views/DashboardPage.vue'
import ReportsPage from '@/views/ReportsPage.vue'
import StatsPage from '@/views/StatsPage.vue'
import DashboardTab from '@/views/reports/DashboardTab.vue'
import MatrixTab from '@/views/reports/MatrixTab.vue'
import ModelTab from '@/views/reports/ModelTab.vue'
import OrderTab from '@/views/reports/OrderTab.vue'
import QualityTab from '@/views/reports/QualityTab.vue'
import ReworkTab from '@/views/reports/ReworkTab.vue'
import TrendTab from '@/views/reports/TrendTab.vue'
import ReportWorkerTab from '@/views/reports/WorkerTab.vue'
import CustomerTab from '@/views/stats/CustomerTab.vue'
import DailyTab from '@/views/stats/DailyTab.vue'
import MaterialTab from '@/views/stats/MaterialTab.vue'
import ModelProcessTab from '@/views/stats/ModelProcessTab.vue'
import ProductTab from '@/views/stats/ProductTab.vue'
import ProgressTab from '@/views/stats/ProgressTab.vue'
import ScrapTab from '@/views/stats/ScrapTab.vue'
import ShipmentTab from '@/views/stats/ShipmentTab.vue'
import WorkerTab from '@/views/stats/WorkerTab.vue'

const mocks = vi.hoisted(() => ({
  stats: Object.fromEntries([
    'dashboardKpi', 'productProcessMatrix', 'orderAnalysis', 'qualityAnalysis',
    'productionTrend', 'workerEfficiency', 'customerStats', 'dailyStats',
    'materialUsage', 'productProcessStats', 'productStats', 'orderProgress',
    'scrapStats', 'reportShipmentStats', 'workerStats', 'workerDetail',
  ].map(name => [name, vi.fn()])),
  dashboard: vi.fn(), listProducts: vi.fn(), listInventory: vi.fn(),
  reworkTrend: vi.fn(), reworkTopProcesses: vi.fn(), reworkWorkerStats: vi.fn(),
  showToast: vi.fn(), navigate: vi.fn(), getBoardToken: vi.fn(), can: vi.fn(),
}))
vi.mock('@/lib/api.js', () => ({ api: { domains: {
  stats: mocks.stats, dashboard: { dashboard: mocks.dashboard },
  products: { listProducts: mocks.listProducts }, inventory: { listInventory: mocks.listInventory },
  rework: { reworkTrend: mocks.reworkTrend, reworkTopProcesses: mocks.reworkTopProcesses, reworkWorkerStats: mocks.reworkWorkerStats },
} } }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ auth: { user: { nickname: '测试员' } }, can: mocks.can, getBoardToken: mocks.getBoardToken }))
vi.mock('@/lib/router.js', () => ({ navigate: mocks.navigate }))
vi.mock('chart.js', () => ({ Chart: Object.assign(vi.fn(function () { this.destroy = vi.fn() }), { register: vi.fn() }), registerables: [] }))

const wrappers = []
const downloads = []
async function open(Component, props = {}, full = false) {
  const wrapper = (full ? mount : shallowMount)(Component, { props })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function csvText(index = downloads.length - 1) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsText(downloads[index].blob)
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  for (const fn of Object.values(mocks.stats)) fn.mockResolvedValue({})
  for (const name of ['dashboard', 'listProducts', 'listInventory', 'reworkTrend', 'reworkTopProcesses', 'reworkWorkerStats']) mocks[name].mockResolvedValue({})
  mocks.can.mockReturnValue(true)
  downloads.length = 0
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({})
  vi.stubGlobal('Chart', vi.fn(function () { this.destroy = vi.fn() }))
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(blob => { downloads.push({ blob }); return 'blob:report-test' }),
    revokeObjectURL: vi.fn(),
  }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { downloads.at(-1).filename = this.download })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('report and statistics query contracts', () => {
  const props = { start: '2026-10-01', end: '2026-10-15', productCode: 'P+01' }
  it.each([
    ['report matrix', MatrixTab, 'productProcessMatrix', props],
    ['quality', QualityTab, 'qualityAnalysis', props],
    ['efficiency', ReportWorkerTab, 'workerEfficiency', props],
    ['material', MaterialTab, 'materialUsage', props],
    ['product', ProductTab, 'productStats', props],
    ['progress', ProgressTab, 'orderProgress', props],
    ['scrap', ScrapTab, 'scrapStats', props],
    ['shipment', ShipmentTab, 'reportShipmentStats', props],
    ['worker', WorkerTab, 'workerStats', props],
    ['customer', CustomerTab, 'customerStats', { start: props.start, end: props.end }],
    ['process', ModelProcessTab, 'productProcessStats', { start: props.start, end: props.end }],
  ])('%s sends the existing date/product filter parameters', async (_label, Component, method, input) => {
    await open(Component, input)
    const expected = { start: input.start, end: input.end }
    if (input.productCode) expected.product_code = input.productCode
    expect(mocks.stats[method]).toHaveBeenCalledExactlyOnceWith(expected)
  })

  it.each([
    [MatrixTab, 'productProcessMatrix'], [QualityTab, 'qualityAnalysis'],
    [MaterialTab, 'materialUsage'], [ProductTab, 'productStats'],
    [ProgressTab, 'orderProgress'], [ScrapTab, 'scrapStats'], [ShipmentTab, 'reportShipmentStats'],
  ])('reactive filter updates reload %s with the new query', async (Component, method) => {
    const wrapper = await open(Component, props)
    await wrapper.setProps({ end: '2026-10-16', productCode: 'P02' })
    await flushPromises()
    expect(mocks.stats[method]).toHaveBeenLastCalledWith({ start: props.start, end: '2026-10-16', product_code: 'P02' })
    expect(mocks.stats[method]).toHaveBeenCalledTimes(2)
  })

  it('daily validation blocks invalid calendar dates and reloads valid dates', async () => {
    const wrapper = await open(DailyTab, { date: '2026-02-30' })
    expect(mocks.stats.dailyStats).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('日期格式无效', 'warning')
    await wrapper.setProps({ date: '2026-10-15', productCode: 'P01' })
    await flushPromises()
    expect(mocks.stats.dailyStats).toHaveBeenCalledExactlyOnceWith({ date: '2026-10-15', per_page: 5000, product_code: 'P01' })
  })

  it('worker expansion preserves the detail query and collapse behavior', async () => {
    mocks.stats.workerStats.mockResolvedValue({ workers: [{ id: 9, name: '员工' }] })
    mocks.stats.workerDetail.mockResolvedValue({ rows: [{ product_name: '明细', output: 12 }] })
    const wrapper = await open(WorkerTab, props)
    await wrapper.vm.toggleRow(9)
    expect(mocks.stats.workerDetail).toHaveBeenCalledExactlyOnceWith({ user_id: 9, start: props.start, end: props.end })
    expect(wrapper.text()).toContain('明细')
    await wrapper.vm.toggleRow(9)
    expect(wrapper.vm.expanded).toBe(null)
    expect(wrapper.vm.detailRows).toEqual([])
    expect(mocks.stats.workerDetail).toHaveBeenCalledTimes(1)
  })

  it('failed stats query keeps the last data and displays the server error', async () => {
    mocks.stats.productStats.mockResolvedValue({ by_product: [{ product_name: '原产品', output: 5 }], summary: { total_output: 5 } })
    const wrapper = await open(ProductTab, props)
    mocks.stats.productStats.mockRejectedValueOnce(new Error('无权访问'))
    await wrapper.setProps({ end: '2026-10-16' })
    await flushPromises()
    expect(wrapper.vm.productList[0].product_name).toBe('原产品')
    expect(mocks.showToast).toHaveBeenCalledWith('无权访问', 'error')
  })
})

describe('report calculations and exports', () => {
  it('order analysis retains weighted totals and completion rate', async () => {
    mocks.stats.orderAnalysis.mockResolvedValue({ status_distribution: [{ status: 'completed', qty: 10, done: 10 }, { status: 'producing', qty: 30, done: 5 }] })
    const wrapper = await open(OrderTab)
    expect(wrapper.vm.totalQty).toBe(40)
    expect(wrapper.vm.totalDone).toBe(15)
    expect(wrapper.vm.completionRate).toBe(37.5)
    expect(mocks.stats.orderAnalysis).toHaveBeenCalledExactlyOnceWith()
  })
  it('model aggregation merges identical trimmed model/spec pairs', async () => {
    mocks.listInventory.mockResolvedValue({ items: [{ product_model: ' M ', specification: ' S ', quantity: '5' }, { product_model: 'M', specification: 'S', quantity: 3 }, { product_model: 'M', specification: 'T', quantity: 2 }] })
    const wrapper = await open(ModelTab)
    expect(mocks.listInventory).toHaveBeenCalledExactlyOnceWith({ limit: 500 })
    expect(wrapper.vm.modelGroups.map(g => [g.model, g.spec, g.count, g.pct])).toEqual([['M', 'S', 8, 80], ['M', 'T', 2, 20]])
    expect(wrapper.vm.totalQty).toBe(10)
  })
  it('efficiency keeps total count while displaying the existing top fifteen', async () => {
    mocks.stats.workerEfficiency.mockResolvedValue({ workers: Array.from({ length: 18 }, (_, id) => ({ id, name: '员工' + id, output: id })) })
    const wrapper = await open(ReportWorkerTab)
    expect(wrapper.vm.totalWorkers).toBe(18)
    expect(wrapper.vm.workers).toHaveLength(15)
  })
  it('process statistics preserves process ordering, zero fill and all process totals in CSV', async () => {
    mocks.stats.productProcessStats.mockResolvedValue({ processes: ['焊接', '下料'], products: [{ product_code: '=P01', data: { 焊接: 3, 其他: 2 } }] })
    const wrapper = await open(ModelProcessTab, { start: '2026-10-01', end: '2026-10-15' })
    wrapper.vm.exportData()
    expect(wrapper.vm.productList[0]).toEqual({ product_code: '=P01', data: [3, 0], total: 5 })
    expect(await csvText()).toBe("序号,产品编码,焊接,下料,合计\n1,'=P01,3,0,5")
    expect(downloads[0].filename).toBe('工序统计_2026-10-01_2026-10-15.csv')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:report-test')
  })
  it('product CSV keeps all columns, decimals and computed output value', async () => {
    mocks.stats.productStats.mockResolvedValue({ by_product: [{ product_name: '产品,"A"', product_code: 'P1', output: 2.5, price: 4, scrap: 1, rework: 2, order_count: 3, upper_opening: 8 }] })
    const wrapper = await open(ProductTab)
    wrapper.vm.exportProduct()
    const csv = await csvText()
    expect(csv).toContain('产品名称,产品编码,型号,规格,分类,规格参数,订单数量,产量,报废,返工,产值,涉及订单数')
    expect(csv).toContain('"产品,""A""",P1,,,,上口8,0,2.5,1,2,10,3')
  })
  it('shipment exports keep the three distinct aggregations and status labels', async () => {
    mocks.stats.reportShipmentStats.mockResolvedValue({ by_status: [{ status: 'completed', count: 2, total_qty: 8 }], by_customer: [{ customer: '客户', shipment_count: 2, total_qty: 8 }], monthly_trend: [{ month: '2026-10', count: 2, total_qty: 8 }] })
    const wrapper = await open(ShipmentTab, { start: '2026-10-01', end: '2026-10-15' })
    for (const type of ['status', 'customer', 'monthly']) wrapper.vm.exportCsv(type)
    expect(await csvText(0)).toBe('状态,发货数,总数量\n已出库,2,8')
    expect(await csvText(1)).toBe('客户,发货批次,总数量\n客户,2,8')
    expect(await csvText(2)).toBe('月份,发货批次,总数量\n2026-10,2,8')
    expect(downloads.map(d => d.filename)).toEqual(['发货统计_状态_2026-10-01_2026-10-15.csv', '发货统计_客户_2026-10-01_2026-10-15.csv', '发货统计_月度_2026-10-01_2026-10-15.csv'])
  })
  it('empty exports keep the original warning and create no download', async () => {
    const wrapper = await open(MaterialTab)
    wrapper.vm.exportMaterial()
    expect(downloads).toEqual([])
    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('没有数据可导出', 'warning')
  })
  it('KPI maps weekly output and monthly summary without changing the response', async () => {
    mocks.stats.dashboardKpi.mockResolvedValue({ weekly_trend: [{ date: '2026-10-15', output: 8 }], monthly_summary: { output: 19 } })
    const wrapper = await open(DashboardTab)
    expect(wrapper.vm.trendDates).toEqual(['2026-10-15'])
    expect(wrapper.vm.trendOutputs).toEqual([8])
    expect(wrapper.vm.monthly).toEqual({ output: 19 })
    expect(wrapper.vm.loading).toBe(false)
  })
  it('trend sends the same days and corresponding local date range', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 15, 12))
    const wrapper = await open(TrendTab)
    expect(mocks.stats.productionTrend).toHaveBeenCalledExactlyOnceWith({ days: 30 })
    expect(mocks.stats.qualityAnalysis).toHaveBeenCalledExactlyOnceWith({ start: '2026-09-16', end: '2026-10-15' })
    expect(wrapper.vm.loading).toBe(false)
  })
  it('rework refresh reloads all three independent queries', async () => {
    const wrapper = await open(ReworkTab)
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(mocks.reworkTrend).toHaveBeenLastCalledWith({ period: 'week', months: 6 })
    expect(mocks.reworkTopProcesses).toHaveBeenLastCalledWith({ n: 6 })
    for (const name of ['reworkTrend', 'reworkTopProcesses', 'reworkWorkerStats']) expect(mocks[name]).toHaveBeenCalledTimes(2)
  })
})

describe('report workspaces and home lifecycle', () => {
  it('reports query remounts only the selected tab and preserves product options', async () => {
    mocks.listProducts.mockResolvedValue({ products: [{ product_code: 'P1', product_name: '产品', model: 'M' }] })
    const wrapper = await open(ReportsPage)
    expect(mocks.listProducts).toHaveBeenCalledExactlyOnceWith({ limit: 500 })
    expect(wrapper.vm.productOptions).toEqual([{ code: 'P1', label: '产品 M' }])
    wrapper.vm.switchTab('worker')
    wrapper.vm.loadCurrent()
    expect(wrapper.vm.workerKey).toBe(1)
    expect(wrapper.vm.qualityKey).toBe(0)
    wrapper.vm.switchTab('matrix')
    wrapper.vm.loadCurrent()
    expect(wrapper.vm.matrixKey).toBe(1)
  })
  it('statistics uses the previous reporting date before 07:00 and preserves PDF query', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 15, 6, 59))
    const popup = vi.spyOn(window, 'open').mockImplementation(() => {})
    const wrapper = await open(StatsPage)
    expect(mocks.listProducts).toHaveBeenCalledExactlyOnceWith({})
    expect(wrapper.vm.reportEnd).toBe('2026-10-14')
    wrapper.vm.switchTab('product')
    wrapper.vm.filterProduct = 'P+01'
    wrapper.vm.setQuickDate('today')
    wrapper.vm.exportPdf()
    expect(wrapper.vm.reportStart).toBe('2026-10-14')
    expect(wrapper.vm.queryKey).toBe(1)
    expect(popup).toHaveBeenCalledWith('/api/stats/export-pdf?tab=product&start=2026-10-14&end=2026-10-14&product_code=P%2B01', '_blank')
  })
  it('statistics switches date/product filter visibility with the selected tab', async () => {
    const wrapper = await open(StatsPage)
    expect(wrapper.vm.showFilter).toBe(true)
    expect(wrapper.vm.showProductFilter).toBe(false)
    wrapper.vm.switchTab('product')
    expect(wrapper.vm.showProductFilter).toBe(true)
    wrapper.vm.switchTab('progress')
    expect(wrapper.vm.showFilter).toBe(false)
  })
  it('home maps server actions, retries errors and cleans up refresh timers and visibility listener', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    const remove = vi.spyOn(document, 'removeEventListener')
    mocks.dashboard.mockRejectedValueOnce(new Error('首页暂不可用'))
    const wrapper = await open(DashboardPage)
    expect(wrapper.text()).toContain('首页暂不可用')
    mocks.dashboard.mockResolvedValue({ stats: { total_orders: 9 }, quick_actions: [{ page: ' orders ', label: '订单' }, { page: ' ' }, null] })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('测试员')
    expect(wrapper.vm.quickActions).toEqual([{ page: 'orders', icon: '📋', text: '订单', desc: '', external: null }])
    await wrapper.vm.goAction(wrapper.vm.quickActions[0])
    expect(mocks.navigate).toHaveBeenCalledWith('orders')
    await vi.advanceTimersByTimeAsync(30000)
    expect(mocks.dashboard).toHaveBeenCalledTimes(3)
    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    await vi.advanceTimersByTimeAsync(60000)
    expect(mocks.dashboard).toHaveBeenCalledTimes(3)
  })
  it('home external action obtains the board token before opening the board', async () => {
    const popup = vi.spyOn(window, 'open').mockImplementation(() => {})
    const wrapper = await open(DashboardPage)
    await wrapper.vm.goAction({ external: 'https://board.example.test/' })
    expect(mocks.getBoardToken).toHaveBeenCalledOnce()
    expect(popup).toHaveBeenCalledWith('https://board.example.test/', '_blank')
    expect(mocks.navigate).not.toHaveBeenCalled()
    expect(mocks.getBoardToken.mock.invocationCallOrder[0]).toBeLessThan(popup.mock.invocationCallOrder[0])
  })
})
