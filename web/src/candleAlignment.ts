import {registerLayout} from 'echarts/core';

// ECharts snaps body edges and wicks independently. Keep an even body span
// around the snapped wick so both edges remain crisp and exactly symmetric.
registerLayout(1001, {
 seriesType: 'candlestick',
 reset(seriesModel) {
  if (seriesModel.pipelineContext.large) return;
  const data = seriesModel.getData();
  const axis = 0; // This application's candles use a horizontal category axis.
  const halfWidth = Math.max(0, Math.floor(Number(data.getLayout('candleWidth')) / 2));
  return {dataEach(_data, index) {
   const layout = data.getItemLayout(index) as {ends?: number[][]} | undefined;
   const points = layout?.ends;
   if (!points || points.length < 8) return;
   const center = points[4][axis];
   points[0][axis] = points[3][axis] = center - halfWidth;
   points[1][axis] = points[2][axis] = center + halfWidth;
  }};
 }
});
