"""
@pyne

This code was compiled by PyneComp v6.0.30 — the Pine Script to Python compiler.
Run with open-source PyneCore: https://pynecore.org
Compile Pine Scripts online at PyneSys: https://pynesys.io
"""
from pynecore.core.pine_udt import udt
from pynecore.lib import (
    alertcondition, array, bar_index, barmerge, close, high, input, low,
    math, na, open, request, script, syminfo, ta, time, timeframe
)
from pynecore.types import NA, Persistent


@udt
class alerts:
    internalBullishBOS: bool = False
    internalBearishBOS: bool = False
    internalBullishCHoCH: bool = False
    internalBearishCHoCH: bool = False
    swingBullishBOS: bool = False
    swingBearishBOS: bool = False
    swingBullishCHoCH: bool = False
    swingBearishCHoCH: bool = False
    internalBullishOrderBlock: bool = False
    internalBearishOrderBlock: bool = False
    swingBullishOrderBlock: bool = False
    swingBearishOrderBlock: bool = False
    equalHighs: bool = False
    equalLows: bool = False
    bullishFairValueGap: bool = False
    bearishFairValueGap: bool = False


@udt
class trailingExtremes:
    top: float = na(float)
    bottom: float = na(float)
    barTime: int = na(int)
    barIndex: int = na(int)
    lastTopTime: int = na(int)
    lastBottomTime: int = na(int)


@udt
class fairValueGap:
    top: float = na(float)
    bottom: float = na(float)
    bias: int = na(int)


@udt
class trend:
    bias: int = na(int)


@udt
class pivot:
    currentLevel: float = na(float)
    lastLevel: float = na(float)
    crossed: bool = na(bool)
    barTime: int = time
    barIndex: int = bar_index


@udt
class orderBlock:
    barHigh: float = na(float)
    barLow: float = na(float)
    barTime: int = na(int)
    bias: int = na(int)


ATR: str = 'Atr'
RANGE: str = 'Cumulative Mean Range'
CLOSE: str = 'Close'
HIGHLOW: str = 'High/Low'


@script.indicator('SMC Compute Only', 'SMC-CO', overlay=True)
def main(
    internalFilterConfluenceInput=input(False, 'Confluence Filter'),
    swingsLengthInput=input.int(50, 'Swings Length', minval=10),
    internalOrderBlocksSizeInput=input.int(5, 'Internal OB Size', minval=1, maxval=20),
    swingOrderBlocksSizeInput=input.int(5, 'Swing OB Size', minval=1, maxval=20),
    orderBlockFilterInput=input.string('Atr', 'OB Filter', options=(ATR, RANGE)),
    orderBlockMitigationInput=input.string(HIGHLOW, 'OB Mitigation', options=(CLOSE, HIGHLOW)),
    equalHighsLowsLengthInput=input.int(3, 'EQH/EQL Bars', minval=1),
    equalHighsLowsThresholdInput=input.float(0.1, 'EQH/EQL Threshold', minval=0, maxval=0.5),
    fairValueGapsThresholdInput=input(True, 'FVG Auto Threshold'),
    fairValueGapsTimeframeInput=input.timeframe('', 'FVG Timeframe')
):
    BULLISH_LEG: int = 1
    BEARISH_LEG: int = 0
    BULLISH: int = 1
    BEARISH = -1





    swingHigh: Persistent[pivot] = pivot(na, na, False)
    swingLow: Persistent[pivot] = pivot(na, na, False)
    internalHigh: Persistent[pivot] = pivot(na, na, False)
    internalLow: Persistent[pivot] = pivot(na, na, False)
    equalHigh: Persistent[pivot] = pivot(na, na, False)
    equalLow: Persistent[pivot] = pivot(na, na, False)
    swingTrend: Persistent[trend] = trend(0)
    internalTrend: Persistent[trend] = trend(0)
    fairValueGaps__global__: Persistent[list[fairValueGap]] = array.new(0, NA(fairValueGap))
    parsedHighs__global__: Persistent[list[float]] = array.new_float()
    parsedLows__global__: Persistent[list[float]] = array.new_float()
    highs__global__: Persistent[list[float]] = array.new_float()
    lows__global__: Persistent[list[float]] = array.new_float()
    times__global__: Persistent[list[int]] = array.new_int()
    trailing: Persistent[trailingExtremes] = trailingExtremes()
    swingOrderBlocks: Persistent[list[orderBlock]] = array.new(0, NA(orderBlock))
    internalOrderBlocks: Persistent[list[orderBlock]] = array.new(0, NA(orderBlock))
    currentAlerts: alerts = alerts()

    bearishOrderBlockMitigationSource = close if orderBlockMitigationInput == CLOSE else high
    bullishOrderBlockMitigationSource = close if orderBlockMitigationInput == CLOSE else low
    atrMeasure = ta.atr(200)
    volatilityMeasure = atrMeasure if orderBlockFilterInput == ATR else ta.cum(ta.tr) / bar_index
    highVolatilityBar = high - low >= 2 * volatilityMeasure
    parsedHigh = low if highVolatilityBar else high
    parsedLow = high if highVolatilityBar else low

    array.push(parsedHighs__global__, parsedHigh)
    array.push(parsedLows__global__, parsedLow)
    array.push(highs__global__, high)
    array.push(lows__global__, low)
    array.push(times__global__, time)

    def leg(size__: int):
        leg__7610ab14__: Persistent[int] = 0
        newLegHigh = high[size__] > ta.highest(size__)
        newLegLow = low[size__] < ta.lowest(size__)
        if newLegHigh:
            leg__7610ab14__ = BEARISH_LEG
        elif newLegLow:
            leg__7610ab14__ = BULLISH_LEG
        return leg__7610ab14__

    def startOfNewLeg(leg__7610b56b__: int):
        return ta.change(leg__7610b56b__) != 0

    def startOfBearishLeg(leg__7610c0d6__: int):
        return ta.change(leg__7610c0d6__) == -1

    def startOfBullishLeg(leg__7610cafb__: int):
        return ta.change(leg__7610cafb__) == 1

    def getCurrentStructure(size__: int, equalHighLow: bool = False, internal: bool = False):
        currentLeg = leg(size__)
        newPivot = startOfNewLeg(currentLeg)
        pivotLow = startOfBullishLeg(currentLeg)
        pivotHigh = startOfBearishLeg(currentLeg)
        __block_result__ = na
        if newPivot:
            __block_result_1__ = na
            if pivotLow:
                p_ivot: pivot = equalLow if equalHighLow else internalLow if internal else swingLow
                if equalHighLow and math.abs(p_ivot.currentLevel - low[size__]) < equalHighsLowsThresholdInput * atrMeasure:
                    currentAlerts.equalLows = True
                p_ivot.lastLevel = p_ivot.currentLevel
                p_ivot.currentLevel = low[size__]
                p_ivot.crossed = False
                p_ivot.barTime = time[size__]
                p_ivot.barIndex = bar_index[size__]
                __block_result_2__ = na
                if not equalHighLow and (not internal):
                    trailing.bottom = p_ivot.currentLevel
                    trailing.barTime = p_ivot.barTime
                    trailing.barIndex = p_ivot.barIndex
                    trailing.lastBottomTime = p_ivot.barTime
                    __block_result_2__ = trailing.lastBottomTime
                __block_result_1__ = __block_result_2__
            else:
                p_ivot: pivot = equalHigh if equalHighLow else internalHigh if internal else swingHigh
                if equalHighLow and math.abs(p_ivot.currentLevel - high[size__]) < equalHighsLowsThresholdInput * atrMeasure:
                    currentAlerts.equalHighs = True
                p_ivot.lastLevel = p_ivot.currentLevel
                p_ivot.currentLevel = high[size__]
                p_ivot.crossed = False
                p_ivot.barTime = time[size__]
                p_ivot.barIndex = bar_index[size__]
                __block_result_2__ = na
                if not equalHighLow and (not internal):
                    trailing.top = p_ivot.currentLevel
                    trailing.barTime = p_ivot.barTime
                    trailing.barIndex = p_ivot.barIndex
                    trailing.lastTopTime = p_ivot.barTime
                    __block_result_2__ = trailing.lastTopTime
                __block_result_1__ = __block_result_2__
            __block_result__ = __block_result_1__
        return __block_result__

    def deleteOrderBlocks(internal: bool = False):
        orderBlocks__7611ce27__: list[orderBlock] = internalOrderBlocks if internal else swingOrderBlocks
        __block_result__ = na
        for index, eachOrderBlock in enumerate(orderBlocks__7611ce27__):
            crossedOderBlock: bool = False
            if bearishOrderBlockMitigationSource > eachOrderBlock.barHigh and eachOrderBlock.bias == BEARISH:
                crossedOderBlock = True
                if internal:
                    currentAlerts.internalBearishOrderBlock = True
                else:
                    currentAlerts.swingBearishOrderBlock = True
            elif bullishOrderBlockMitigationSource < eachOrderBlock.barLow and eachOrderBlock.bias == BULLISH:
                crossedOderBlock = True
                if internal:
                    currentAlerts.internalBullishOrderBlock = True
                else:
                    currentAlerts.swingBullishOrderBlock = True
            __block_result_1__ = na
            if crossedOderBlock:
                __block_result_1__ = array.remove(orderBlocks__7611ce27__, index)
            __block_result__ = __block_result_1__
        return __block_result__

    def storeOrdeBlock(p_ivot: pivot, internal: bool = False, bias: int = na):
        a_rray__76128579__: list[float] = na(list[float])
        parsedIndex: int = na(int)
        if bias == BEARISH:
            a_rray__76128579__ = array.slice(parsedHighs__global__, p_ivot.barIndex, bar_index)
            parsedIndex = p_ivot.barIndex + array.indexof(a_rray__76128579__, array.max(a_rray__76128579__))
        else:
            a_rray__76128579__ = array.slice(parsedLows__global__, p_ivot.barIndex, bar_index)
            parsedIndex = p_ivot.barIndex + array.indexof(a_rray__76128579__, array.min(a_rray__76128579__))
        o_rderBlock: orderBlock = orderBlock(array.get(parsedHighs__global__, parsedIndex), array.get(parsedLows__global__, parsedIndex), array.get(times__global__, parsedIndex), bias)
        orderBlocks__76128579__: list[orderBlock] = internalOrderBlocks if internal else swingOrderBlocks
        if array.size(orderBlocks__76128579__) >= 100:
            array.pop(orderBlocks__76128579__)
        return array.unshift(orderBlocks__76128579__, o_rderBlock)

    def displayStructure(internal: bool = False):
        bullishBar: Persistent[bool] = True
        bearishBar: Persistent[bool] = True
        if internalFilterConfluenceInput:
            bullishBar = high - math.max(close, open) > math.min(close, open - low)
            bearishBar = high - math.max(close, open) < math.min(close, open - low)
        p_ivot: pivot = internalHigh if internal else swingHigh
        t_rend: trend = internalTrend if internal else swingTrend
        extraCondition = internalHigh.currentLevel != swingHigh.currentLevel and bullishBar if internal else True
        if ta.crossover(close, p_ivot.currentLevel) and (not p_ivot.crossed) and extraCondition:
            tag: str = 'CHoCH' if t_rend.bias == BEARISH else 'BOS'
            if internal:
                currentAlerts.internalBullishCHoCH = tag == 'CHoCH'
                currentAlerts.internalBullishBOS = tag == 'BOS'
            else:
                currentAlerts.swingBullishCHoCH = tag == 'CHoCH'
                currentAlerts.swingBullishBOS = tag == 'BOS'
            p_ivot.crossed = True
            t_rend.bias = BULLISH
            storeOrdeBlock(p_ivot, internal, BULLISH)
        p_ivot = internalLow if internal else swingLow
        extraCondition = internalLow.currentLevel != swingLow.currentLevel and bearishBar if internal else True
        __block_result__ = na
        if ta.crossunder(close, p_ivot.currentLevel) and (not p_ivot.crossed) and extraCondition:
            tag: str = 'CHoCH' if t_rend.bias == BULLISH else 'BOS'
            if internal:
                currentAlerts.internalBearishCHoCH = tag == 'CHoCH'
                currentAlerts.internalBearishBOS = tag == 'BOS'
            else:
                currentAlerts.swingBearishCHoCH = tag == 'CHoCH'
                currentAlerts.swingBearishBOS = tag == 'BOS'
            p_ivot.crossed = True
            t_rend.bias = BEARISH
            __block_result__ = storeOrdeBlock(p_ivot, internal, BEARISH)
        return __block_result__

    def deleteFairValueGaps():
        __block_result__ = na
        for index, eachFairValueGap in enumerate(fairValueGaps__global__):
            __block_result_1__ = na
            if low < eachFairValueGap.bottom and eachFairValueGap.bias == BULLISH or (high > eachFairValueGap.top and eachFairValueGap.bias == BEARISH):
                __block_result_1__ = array.remove(fairValueGaps__global__, index)
            __block_result__ = __block_result_1__
        return __block_result__

    def drawFairValueGaps():
        lastClose, lastOpen, lastTime, currentHigh, currentLow, currentTime, last2High, last2Low = request.security(syminfo.tickerid, fairValueGapsTimeframeInput, (close[1], open[1], time[1], high, low, time, high[2], low[2]), lookahead=barmerge.lookahead_on)
        barDeltaPercent = (lastClose - lastOpen) / (lastOpen * 100)
        newTimeframe = timeframe.change(fairValueGapsTimeframeInput)
        threshold = ta.cum(math.abs(barDeltaPercent if newTimeframe else 0)) / bar_index * 2 if fairValueGapsThresholdInput else 0
        bullishFairValueGap = currentLow > last2High and lastClose > last2High and (barDeltaPercent > threshold) and newTimeframe
        bearishFairValueGap = currentHigh < last2Low and lastClose < last2Low and (-barDeltaPercent > threshold) and newTimeframe
        if bullishFairValueGap:
            currentAlerts.bullishFairValueGap = True
            array.unshift(fairValueGaps__global__, fairValueGap(currentLow, last2High, BULLISH))
        __block_result__ = na
        if bearishFairValueGap:
            currentAlerts.bearishFairValueGap = True
            __block_result__ = array.unshift(fairValueGaps__global__, fairValueGap(currentHigh, last2Low, BEARISH))
        return __block_result__

    def updateTrailingExtremes():
        trailing.top = math.max(high, trailing.top)
        trailing.lastTopTime = time if trailing.top == high else trailing.lastTopTime
        trailing.bottom = math.min(low, trailing.bottom)
        trailing.lastBottomTime = time if trailing.bottom == low else trailing.lastBottomTime
        return trailing.lastBottomTime

    updateTrailingExtremes()
    deleteFairValueGaps()

    getCurrentStructure(swingsLengthInput, False)
    getCurrentStructure(5, False, True)
    getCurrentStructure(equalHighsLowsLengthInput, True)

    displayStructure(True)
    displayStructure()

    deleteOrderBlocks(True)
    deleteOrderBlocks()

    drawFairValueGaps()

    alertcondition(currentAlerts.internalBullishBOS, 'Internal Bullish BOS', 'Internal Bullish BOS formed')
    alertcondition(currentAlerts.internalBullishCHoCH, 'Internal Bullish CHoCH', 'Internal Bullish CHoCH formed')
    alertcondition(currentAlerts.internalBearishBOS, 'Internal Bearish BOS', 'Internal Bearish BOS formed')
    alertcondition(currentAlerts.internalBearishCHoCH, 'Internal Bearish CHoCH', 'Internal Bearish CHoCH formed')
    alertcondition(currentAlerts.swingBullishBOS, 'Bullish BOS', 'Bullish BOS formed')
    alertcondition(currentAlerts.swingBullishCHoCH, 'Bullish CHoCH', 'Bullish CHoCH formed')
    alertcondition(currentAlerts.swingBearishBOS, 'Bearish BOS', 'Bearish BOS formed')
    alertcondition(currentAlerts.swingBearishCHoCH, 'Bearish CHoCH', 'Bearish CHoCH formed')
    alertcondition(currentAlerts.internalBullishOrderBlock, 'Bullish Internal OB Breakout', 'Price broke bullish internal OB')
    alertcondition(currentAlerts.internalBearishOrderBlock, 'Bearish Internal OB Breakout', 'Price broke bearish internal OB')
    alertcondition(currentAlerts.swingBullishOrderBlock, 'Bullish Swing OB Breakout', 'Price broke bullish swing OB')
    alertcondition(currentAlerts.swingBearishOrderBlock, 'Bearish Swing OB Breakout', 'Price broke bearish swing OB')
    alertcondition(currentAlerts.equalHighs, 'Equal Highs', 'Equal highs detected')
    alertcondition(currentAlerts.equalLows, 'Equal Lows', 'Equal lows detected')
    alertcondition(currentAlerts.bullishFairValueGap, 'Bullish FVG', 'Bullish FVG formed')
    alertcondition(currentAlerts.bearishFairValueGap, 'Bearish FVG', 'Bearish FVG formed')


if __name__ == "__main__":
    from pynecore.standalone import run
    run(__file__)
