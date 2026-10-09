# Charts: round 1 (2026-10-09)

Siddhant: "Let it be a charting tool only. I can type a stock name or add many from Deals, Sector, Screener etc. Peers together. Stocks from the star watchlist. More tools in charts. One global chart window: candle or line, a different candle colour per event, 10/20/200 EMA, Darvas box from the Pine references, a second pane with RSI and RSI divergence lines, volume, and volume-weighted candles like TradingView. See the main app for reference. Like TradingView."

## 1. What exists today (main @ 56a58b8)
| Piece | Today |
|---|---|
| Engine | `lightweight-charts` v5 (`frontend/src/ui/Chart.tsx`) |
| Charts tab | A grid of tiles from one source (`?src=`): setup queue, screener preset, group, deals buy/sell, research pre-move, watchlist, explicit list. Per-tile candle/line, Darvas toggle, expand, big chart (F), J/K through the list, remove |
| Big chart (Stock 360) | Candles, Darvas (Pine SUCCESS step lines + dotted 5-bar projection), EMA10 projection, setup trigger/stop on the axis, volume/delivery pane, RS pane, sizer rail |
| Indicators | `lib/indicators.ts`: EMA, D/W/M resample. **No RSI, no divergence, no volume candles, no drawing tools** |
| Stock 360 | Single-stock page: setups, strength, trend, Minervini 8-point, footprint, delivery, peers (copy to TV), events, deals, notes |

## 2. Decision: Charts becomes a charting tool
- One tab, one chart engine and one settings model, used everywhere a chart appears (tiles, big chart, drawers in other tabs).
- **Stock 360 is no longer a tab.** It becomes a side panel you open from any chart (the `i` key or a click on the symbol). It keeps the profile, peers, events, deals and notes. Proposed; confirm.

## 3. Proposed layout
```
[ symbol search ⌘K ] [ + Add list ▾ ] [ layout 1 · 2 · 4 · 6 · 9 ] [ D W M ] [ Candle · Line · Volume candles ] [ Indicators ▾ ] [ Draw ▾ ] [ Copy to TV ]
┌──────────── main chart (or grid) ────────────┬─ list rail ─┐
│ price + EMAs + Darvas + event candles          │ ★ Watchlist │
│────────────────────────────────────────────────│ Deals today │
│ volume (or delivery)                           │ Group: …    │
│────────────────────────────────────────────────│ Screener: … │
│ RSI 14 + divergence lines                      │ Peers of X  │
└────────────────────────────────────────────────┴─────────────┘
```
- **Symbol search**: type a name or symbol and press Enter to open it. Shift+Enter adds it to the current list.
- **Add list from**: ★ watchlist, Deals (any view: Today, Watch, History, a house's buys, a group), Sector Intel (any group at any level), Screener/Setups (any preset or queue), **Peers of the current stock** (same industry, sorted by RS), Pulse lists, or pasted text (`NSE:A,NSE:B` or one per line, so a TradingView export goes straight in).
- **List rail**: lists stay open as tabs. J/K moves through the list; the chart keeps its zoom and indicators. Star a stock with S. Copy the list to TradingView.
- **Layouts**: 1, 2, 4, 6 or 9 charts. In a grid, the crosshair and timeframe sync across tiles. "Peers together" is a grid of the stock + its 5 strongest peers.

## 4. Global chart settings (one place, stored, apply to every chart in the app)
| Setting | Default | Notes |
|---|---|---|
| Price style | Candles | Candles, line (close), **volume candles** (candle width ∝ volume vs its 20-bar average, as TradingView's volume candles do). On a phone, volume candles fall back to colour intensity |
| EMAs | 10, 20, 200 on; 50 off | Colours fixed app-wide. Each can be turned on or off |
| Darvas box | On | The existing Pine-faithful lines (`/stock/{sym}/darvas`) + projection |
| Event candles | On | See §5 |
| Pane 2 | Volume | Volume bars coloured up/down. A 20-bar average line. Option: delivery qty |
| Pane 3 | RSI 14 | 70/30 + 50 lines. **Divergence lines** (§6) |
| RS line | Off | RS vs Nifty MidSmallcap 400 as an optional pane. It's already in the big chart |
| Timeframe | D | W and M resample (exists) |

## 5. Event candles: one colour each
The whole candle takes the event's colour (as agreed for Deals). Each event has a letter above or below the candle. When two events land on one day, the priority order is:
| Priority | Event | Colour | Letter |
|---|---|---|---|
| 1 | Results day | purple | R |
| 2 | Deal: net buy / placement / net sell / churn / transfer | teal / blue / orange / grey / grey | B P S C T |
| 3 | Breakout from Darvas box top on volume ≥ 1.5× | bright green outline + fill | ↑ |
| 4 | Box-bottom break on volume | red-orange | ↓ |
| 5 | Gap ≥ 4% (up/down) | gold | G |
| 6 | Volume ≥ 3× the 20-bar avg (no other event) | white body | V |
| 7 | Ex-date / ASM / GSM entry | small chip only, no colour change | E / A |
Every event can be turned on or off. The legend sits under the chart. Hover shows what happened ("Net buy ₹57.8 Cr by …, deal price ₹1,174.9").

## 6. RSI divergence (proposed rule; to be tested in round 2)
- Pivots: swing high/low with 5 bars on each side (confirmed 5 bars late, so the chart never repaints).
- Regular bearish: price makes a higher high, RSI a lower high, and the first RSI high was > 60. Regular bullish: price makes a lower low, RSI a higher low, and the first RSI low was < 40.
- The two pivots are 5–60 bars apart. A line is drawn on both the price and RSI panes between the pivots.
- Hidden divergences off by default.
- Round 2 will report how often a bearish divergence near a 52W high preceded a 10% fall vs the base rate (D and W), so the line comes with its record.

## 7. More tools ("this will have more tools")
Proposed in order of value for a Darvas/VCP trader:
1. **Drawing**: horizontal line (price alert), trend line, rectangle (manual box), measure (% and bars). Saved per symbol.
2. **Position tool**: entry, stop, target → R-multiple, qty from the sizer (account and risk % in settings). It uses the sizer that exists.
3. **Anchored VWAP**: anchor on a deal date, results day, or any click. The deal-price lines from the Deals tab show as anchored levels.
4. **Base measure**: auto-measure the current base (length in weeks, depth %, contractions T1/T2/T3). The VCP draft already defines the rule.
5. **52W high / pivot line**, prior swing highs.
6. **Compare**: overlay a second symbol or index (% scale).
7. **Replay** (later): step bar by bar from a past date to practise reading setups.
8. **Alerts** on lines → Telegram (later; needs the alert plumbing from Deals).

## 8. Open questions for Siddhant
1. Fold Stock 360 into a side panel of Charts (and drop it as a tab)?
2. Event priority order in §5: is results day above deals right?
3. Which of the §7 tools matter most to you? I'd build 1, 2, 3 and 4 first.
4. Volume candles: width scaled (TradingView style) or colour intensity?
