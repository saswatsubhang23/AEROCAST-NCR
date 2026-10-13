"use client";

import { useEffect, useEffectEvent, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([
  LineChart, BarChart, ScatterChart,
  GridComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, TooltipComponent,
  CanvasRenderer,
]);

/**
 * Thin ECharts wrapper. `onSelectIndex` fires with the category index under a click inside the plot area,
 * which is how charts drive the shared timeline.
 */
export function EChart({
  option,
  ariaLabel,
  height = 260,
  onSelectIndex,
}: {
  option: EChartsCoreOption;
  ariaLabel: string;
  height?: number;
  onSelectIndex?: (index: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const select = useEffectEvent((i: number) => onSelectIndex?.(i));

  // The chart is created only once its container has a size. A chart inside a hidden tab or a collapsed panel has width 0, and initialising
  // there logs "Can't get DOM width or height" and renders nothing until a later resize; waiting for the first real size avoids both.
  const optionRef = useRef(option);
  useEffect(() => {
    optionRef.current = option;
  });
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let c: echarts.ECharts | null = null;
    const make = () => {
      if (c || node.clientWidth === 0 || node.clientHeight === 0) return;
      c = echarts.init(node);
      chart.current = c;
      c.setOption(optionRef.current, { notMerge: true });
      c.getZr().on("click", (e: { offsetX: number; offsetY: number }) => {
        const pt: [number, number] = [e.offsetX, e.offsetY];
        if (!c || !c.containPixel("grid", pt)) return;
        const idx = c.convertFromPixel({ gridIndex: 0 }, pt)[0];
        if (Number.isFinite(idx)) select(Math.round(idx));
      });
    };
    make();
    const ro = new ResizeObserver(() => {
      if (c) c.resize();
      else make();
    });
    ro.observe(node);
    return () => {
      ro.disconnect();
      c?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={el} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />;
}
