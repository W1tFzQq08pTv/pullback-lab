import {Info} from './Info';
import {strategyNames,type StrategyId} from './types';
const explanations:Record<StrategyId,string>={
 trend_pullback_v2:'沿用SMA回调首仓与中期均线清仓规则，独立保存均线参数。固定周期投入预算，支持固定比例一次买入、上涨确认加仓、回调加深加仓。分批按首次实际成交价的等距涨跌阈值触发，每日最多一批，清仓优先；收盘确认、次日尝试，预算含费用，不借款。寻优完整覆盖SMA网格与124种仓位配置，按历史累计收益排序。',
 trend_pullback:'核心思路：在上涨趋势中等回调，再等反弹确认。入场：收盘高于长期SMA、中期SMA上行，回调窗口内曾出现最低价触及短期SMA且收盘守住中期SMA，且当日收盘突破前一日最高价并站上短期SMA；开启大盘过滤时还须满足沪深300条件。退出：收盘跌破中期SMA，安排卖出。均线、回调窗口与仓位使用当前设置；信号在收盘确认，下一交易日开盘尝试成交，受停牌、涨跌停、T+1及费用约束。',
 martin_daily:'核心思路：寻找强势股回踩支撑后的重新走强。入场：21/63/126日涨幅至少一项达标、成交额达标、收盘高于上行的EMA50；当日低点贴近EMA21、锚定成交量加权均价或前高之一并收回支撑，收盘突破前日高点且高于EMA9。风控：以信号日低点为初始止损，按风险预算定仓，次日开盘重新检查止损距离。退出：收盘触及止损或跌破EMA9退出；达到3R、5R各减仓约初始仓位的1/3，R为入场价与初始止损之差。均按收盘确认、次日尝试成交；这是日线量化近似，并非原推文的盘中交易复现。',
};
export function StrategyInfo({id}:{id:StrategyId}){return <Info label={strategyNames[id]+'核心逻辑'}>{explanations[id]}</Info>;}
