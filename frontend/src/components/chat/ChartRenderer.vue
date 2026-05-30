<script setup lang="ts">
import { computed, ref, onMounted, watch, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { QueryResult, ChartConfig } from '@/stores/chat'

echarts.use([BarChart, LineChart, PieChart, ScatterChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const props = defineProps<{
  result: QueryResult
  chartConfig?: ChartConfig | null
}>()

const chartContainer = ref<HTMLDivElement>()
let chartInstance: echarts.ECharts | null = null

function inferChartType(result: QueryResult): ChartConfig | null {
  const { columns, rows } = result
  if (!columns.length || !rows.length) return null

  const timeCol = columns.find(c => /time|date|时间|日期/i.test(c))
  const numericCols = columns.filter((_, i) => rows.some(r => typeof r[i] === 'number'))
  const textCols = columns.filter((_, i) => rows.some(r => typeof r[i] === 'string'))

  if (timeCol && numericCols.length >= 1) {
    return { type: 'line', x_axis: { column: timeCol, label: timeCol }, y_axis: { column: numericCols[0]!, label: numericCols[0]! } }
  }
  if (textCols.length === 1 && numericCols.length === 1) {
    return { type: 'bar', x_axis: { column: textCols[0]!, label: textCols[0]! }, y_axis: { column: numericCols[0]!, label: numericCols[0]! } }
  }
  if (textCols.length === 1 && numericCols.length >= 2 && rows.length <= 10) {
    return { type: 'pie', x_axis: { column: textCols[0]!, label: textCols[0]! }, y_axis: { column: numericCols[0]!, label: numericCols[0]! } }
  }
  return null
}

const effectiveConfig = computed<ChartConfig | null>(() => {
  if (props.chartConfig && ['bar', 'line', 'pie', 'scatter'].includes(props.chartConfig.type)) {
    return props.chartConfig
  }
  if (props.chartConfig) {
    return { ...props.chartConfig, type: 'bar' }
  }
  return inferChartType(props.result)
})

function buildEChartsOption(config: ChartConfig, result: QueryResult) {
  const { columns, rows } = result
  const xIdx = config.x_axis ? columns.indexOf(config.x_axis.column) : -1
  const yIdx = config.y_axis ? columns.indexOf(config.y_axis.column) : -1
  if (xIdx < 0 || yIdx < 0) return null

  const xData = rows.map(r => String(r[xIdx]))
  const yData = rows.map(r => Number(r[yIdx]) || 0)

  switch (config.type) {
    case 'bar':
      return {
        title: config.title ? { text: config.title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: xData, name: config.x_axis?.label },
        yAxis: { type: 'value', name: config.y_axis?.label },
        series: [{ type: 'bar', data: yData, itemStyle: { borderRadius: [4, 4, 0, 0] } }],
      }
    case 'line':
      return {
        title: config.title ? { text: config.title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: xData, name: config.x_axis?.label },
        yAxis: { type: 'value', name: config.y_axis?.label },
        series: [{ type: 'line', data: yData, smooth: true }],
      }
    case 'pie':
      return {
        title: config.title ? { text: config.title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
        tooltip: { trigger: 'item' },
        legend: { orient: 'vertical', left: 'left' },
        series: [{
          type: 'pie', radius: '60%',
          data: rows.map(r => ({ name: String(r[xIdx]), value: Number(r[yIdx]) || 0 })),
          emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } },
        }],
      }
    case 'scatter':
      return {
        title: config.title ? { text: config.title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'value', name: config.x_axis?.label },
        yAxis: { type: 'value', name: config.y_axis?.label },
        series: [{ type: 'scatter', data: rows.map(r => [Number(r[xIdx]) || 0, Number(r[yIdx]) || 0]) }],
      }
    default:
      return null
  }
}

onMounted(() => {
  if (!chartContainer.value || !effectiveConfig.value) return
  const option = buildEChartsOption(effectiveConfig.value, props.result)
  if (!option) return
  chartInstance = echarts.init(chartContainer.value)
  chartInstance.setOption(option)
})

watch(() => props.result, () => {
  if (!chartInstance || !effectiveConfig.value) return
  const option = buildEChartsOption(effectiveConfig.value, props.result)
  if (option) chartInstance.setOption(option)
}, { deep: true })

onBeforeUnmount(() => {
  chartInstance?.dispose()
})
</script>

<template>
  <div v-if="effectiveConfig" class="chart-block">
    <div ref="chartContainer" class="chart-container"></div>
  </div>
</template>

<style scoped>
.chart-block {
  margin-top: 14px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  background: var(--bg-panel);
  overflow: hidden;
}
.chart-container {
  width: 100%;
  height: 320px;
}
</style>
