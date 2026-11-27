# Strategy evaluation baseline — tables

Generated 2026-11-26T19:24:54+00:00 · HISTORICAL EVALUATION (simulated on MT5 history with costs; not live results)

Periods: train ['2024-10-15', '2025-10-01'], validation ['2025-10-01', '2026-04-01'], test ['2026-04-01', '2026-10-12']. spread on the correct side, IC-Markets-Raw-style commission, 0.5-spread stop slippage, overnight financing; x2-cost stress reported. Holm-Bonferroni across 33 strategies (one-sided H0: expectancy <= 0).

## 1. Ranking by statistical reliability (lower bound of the 95% CI of expectancy, all periods)

| # | Strategy | Family | Tier | Trades | Win | Avg R | 95% CI | PF | Max DD (R) | Avg R:R | Holm p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | London Session Breakout | T-034 BANK | RESEARCH | 4198 | 0.419 | +0.004 | [-0.031, +0.041] | 1.01 | 217.1 | 2.00 | 1.000 |
| 2 | Bollinger Band Mean Reversion | T-034 BANK | RESEARCH | 774 | 0.558 | +0.032 | [-0.038, +0.100] | 1.07 | 23.7 | 0.96 | 1.000 |
| 3 | Opening Range Breakout | T-034 BANK | RESEARCH | 1341 | 0.465 | +0.003 | [-0.049, +0.058] | 1.01 | 55.5 | 2.00 | 1.000 |
| 4 | Opening Range Breakout v2 | UPGRADE | RESEARCH | 525 | 0.406 | +0.052 | [-0.059, +0.161] | 1.09 | 23.4 | 2.00 | 1.000 |
| 5 | Market Structure Break | T-034 BANK | RESEARCH | 1425 | 0.357 | +0.008 | [-0.065, +0.081] | 1.01 | 64.1 | 2.00 | 1.000 |
| 6 | MACD Momentum | T-034 BANK | EXPERIMENTAL | 4318 | 0.337 | -0.033 | [-0.075, +0.010] | 0.95 | 164.7 | 2.00 | 1.000 |
| 7 | Donchian Channel Breakout | T-034 BANK | SUSPENDED | 6745 | 0.333 | -0.051 | [-0.085, -0.018] | 0.93 | 374.2 | 2.00 | 1.000 |
| 8 | ICT Silver Bullet | ICT | EXPERIMENTAL | 571 | 0.471 | -0.033 | [-0.100, +0.034] | 0.91 | 30.7 | 2.70 | 1.000 |
| 9 | Order Block Retest | T-034 BANK | EXPERIMENTAL | 717 | 0.353 | -0.002 | [-0.105, +0.107] | 1.00 | 53.5 | 2.00 | 1.000 |
| 10 | ATR Volatility Breakout | T-034 BANK | SUSPENDED | 5816 | 0.325 | -0.069 | [-0.105, -0.032] | 0.90 | 421.7 | 2.00 | 1.000 |
| 11 | ICT Liquidity Sweep Reversal | ICT | EXPERIMENTAL | 2070 | 0.363 | -0.055 | [-0.111, +0.002] | 0.91 | 170.8 | 2.71 | 1.000 |
| 12 | Ichimoku Trend Following | T-034 BANK | SUSPENDED | 5050 | 0.329 | -0.075 | [-0.114, -0.035] | 0.89 | 396.1 | 2.00 | 1.000 |
| 13 | Fair Value Gap | T-034 BANK | EXPERIMENTAL | 876 | 0.344 | -0.024 | [-0.117, +0.073] | 0.97 | 61.8 | 2.00 | 1.000 |
| 14 | Breakout Trading | T-034 BANK | EXPERIMENTAL | 1882 | 0.341 | -0.053 | [-0.117, +0.011] | 0.92 | 150.9 | 2.00 | 1.000 |
| 15 | ICT Market Structure Shift | ICT | EXPERIMENTAL | 1385 | 0.377 | -0.055 | [-0.124, +0.015] | 0.91 | 82.5 | 2.75 | 1.000 |
| 16 | Liquidity Sweep | T-034 BANK | SUSPENDED | 2873 | 0.324 | -0.078 | [-0.131, -0.025] | 0.89 | 241.9 | 2.00 | 1.000 |
| 17 | Inside Bar Breakout | T-034 BANK | SUSPENDED | 5717 | 0.320 | -0.100 | [-0.135, -0.064] | 0.86 | 598.7 | 2.00 | 1.000 |
| 18 | Liquidity Divergence v2 | UPGRADE | RESEARCH | 381 | 0.344 | +0.001 | [-0.141, +0.149] | 1.00 | 22.9 | 2.00 | 1.000 |
| 19 | EMA Pullback | T-034 BANK | SUSPENDED | 5293 | 0.320 | -0.103 | [-0.142, -0.065] | 0.86 | 587.6 | 2.00 | 1.000 |
| 20 | RSI Divergence | T-034 BANK | EXPERIMENTAL | 895 | 0.326 | -0.062 | [-0.151, +0.029] | 0.91 | 59.0 | 2.00 | 1.000 |
| 21 | Trend Pullback v2 | UPGRADE | SUSPENDED | 1758 | 0.324 | -0.085 | [-0.153, -0.017] | 0.88 | 176.2 | 2.00 | 1.000 |
| 22 | EMA Crossover | T-034 BANK | SUSPENDED | 2327 | 0.318 | -0.097 | [-0.154, -0.039] | 0.87 | 236.4 | 2.00 | 1.000 |
| 23 | Crypto Trend Breakout v2 | UPGRADE | RESEARCH | 316 | 0.269 | +0.024 | [-0.164, +0.212] | 1.03 | 24.6 | 3.00 | 1.000 |
| 24 | ICT Order Block Reversal | ICT | SUSPENDED | 1684 | 0.329 | -0.109 | [-0.175, -0.039] | 0.84 | 185.4 | 2.70 | 1.000 |
| 25 | ICT Judas Swing | ICT | RESEARCH | 126 | 0.413 | +0.027 | [-0.188, +0.248] | 1.05 | 12.7 | 2.68 | 1.000 |
| 26 | ICT Fair Value Gap Continuation | ICT | EXPERIMENTAL | 533 | 0.299 | -0.073 | [-0.203, +0.062] | 0.90 | 51.4 | 2.60 | 1.000 |
| 27 | Support & Resistance | PRODUCTION-LINKED | SUSPENDED | 697 | 0.297 | -0.130 | [-0.239, -0.019] | 0.83 | 91.7 | 2.62 | 1.000 |
| 28 | Trendline Bounce | PRODUCTION-LINKED | SUSPENDED | 8076 | 0.239 | -0.232 | [-0.272, -0.192] | 0.73 | 1875.5 | 3.53 | 1.000 |
| 29 | ICT Sweep + Displacement + FVG | ICT | EXPERIMENTAL | 48 | 0.438 | +0.080 | [-0.276, +0.451] | 1.16 | 4.1 | 2.72 | 1.000 |
| 30 | Trendline Break & Retest | PRODUCTION-LINKED | SUSPENDED | 2153 | 0.246 | -0.203 | [-0.286, -0.116] | 0.76 | 447.5 | 3.33 | 1.000 |
| 31 | ICT Premium/Discount OTE | ICT | EXPERIMENTAL | 626 | 0.227 | -0.146 | [-0.298, +0.016] | 0.83 | 116.7 | 4.05 | 1.000 |
| 32 | Trend Momentum v2 | UPGRADE | EXPERIMENTAL | 109 | 0.312 | -0.103 | [-0.355, +0.172] | 0.86 | 22.9 | 2.00 | 1.000 |
| 33 | Compression Breakout v2 | UPGRADE | EXPERIMENTAL | 138 | 0.297 | -0.175 | [-0.401, +0.052] | 0.77 | 32.4 | 2.00 | 1.000 |

Not evaluable: vwap_reversion.

## 2. Out-of-sample, walk-forward and 2x-cost stress

| Strategy | Dev E | Test E | Test n | Test CI | All E | x2-cost E | Survives x2 | WF folds + | Validation checks failed |
|---|---|---|---|---|---|---|---|---|---|
| London Session Breakout | -0.024 | +0.083 | 1122 | [+0.01, +0.15] | +0.004 | -0.031 | no | 4/7 | out_of_sample, significance, costs, walk_forward |
| Bollinger Band Mean Reversion | +0.016 | +0.077 | 204 | [-0.06, +0.21] | +0.032 | -0.024 | no | 5/7 | significance, costs |
| Opening Range Breakout | +0.056 | -0.132 | 379 | [-0.23, -0.04] | +0.003 | -0.011 | no | 5/7 | out_of_sample, significance, costs |
| Opening Range Breakout v2 | +0.053 | +0.048 | 166 | [-0.14, +0.24] | +0.052 | +0.020 | yes | 6/7 | significance |
| Market Structure Break | -0.007 | +0.050 | 375 | [-0.09, +0.19] | +0.008 | -0.052 | no | 4/7 | out_of_sample, significance, costs, walk_forward |
| MACD Momentum | -0.035 | -0.029 | 1091 | [-0.11, +0.05] | -0.033 | -0.097 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| Donchian Channel Breakout | -0.037 | -0.094 | 1755 | [-0.16, -0.03] | -0.051 | -0.111 | no | 0/7 | out_of_sample, significance, costs, walk_forward |
| ICT Silver Bullet | -0.026 | -0.056 | 145 | [-0.20, +0.09] | -0.033 | -0.081 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| Order Block Retest | -0.010 | +0.025 | 177 | [-0.18, +0.24] | -0.002 | -0.086 | no | 5/7 | out_of_sample, significance, costs |
| ATR Volatility Breakout | -0.029 | -0.180 | 1540 | [-0.25, -0.11] | -0.069 | -0.135 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| ICT Liquidity Sweep Reversal | -0.028 | -0.134 | 528 | [-0.25, -0.02] | -0.055 | -0.132 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| Ichimoku Trend Following | -0.067 | -0.097 | 1388 | [-0.17, -0.02] | -0.075 | -0.149 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| Fair Value Gap | +0.035 | -0.222 | 198 | [-0.40, -0.03] | -0.024 | -0.074 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| Breakout Trading | -0.025 | -0.132 | 516 | [-0.25, -0.01] | -0.053 | -0.126 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| ICT Market Structure Shift | -0.025 | -0.144 | 344 | [-0.28, -0.01] | -0.055 | -0.128 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| Liquidity Sweep | -0.070 | -0.099 | 790 | [-0.20, +0.01] | -0.078 | -0.153 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| Inside Bar Breakout | -0.080 | -0.155 | 1523 | [-0.22, -0.08] | -0.100 | -0.183 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| Liquidity Divergence v2 | +0.004 | -0.009 | 91 | [-0.30, +0.29] | +0.001 | -0.078 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| EMA Pullback | -0.080 | -0.168 | 1393 | [-0.24, -0.10] | -0.103 | -0.178 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| RSI Divergence | -0.026 | -0.174 | 218 | [-0.35, +0.01] | -0.062 | -0.132 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| Trend Pullback v2 | -0.032 | -0.232 | 471 | [-0.36, -0.11] | -0.085 | -0.154 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| EMA Crossover | -0.104 | -0.079 | 640 | [-0.19, +0.03] | -0.097 | -0.183 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| Crypto Trend Breakout v2 | +0.049 | -0.058 | 75 | [-0.42, +0.33] | +0.024 | -0.067 | no | 3/7 | out_of_sample, significance, costs, walk_forward |
| ICT Order Block Reversal | -0.099 | -0.139 | 433 | [-0.27, -0.01] | -0.109 | -0.199 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| ICT Judas Swing | +0.078 | -0.110 | 34 | [-0.52, +0.36] | +0.027 | -0.014 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| ICT Fair Value Gap Continuation | -0.052 | -0.141 | 127 | [-0.42, +0.15] | -0.073 | -0.163 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| Support & Resistance | -0.160 | -0.042 | 175 | [-0.26, +0.18] | -0.130 | -0.253 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| Trendline Bounce | -0.201 | -0.314 | 2221 | [-0.39, -0.24] | -0.232 | -0.435 | no | 0/7 | out_of_sample, significance, costs, walk_forward |
| ICT Sweep + Displacement + FVG | +0.104 | +0.007 | 12 | [-0.58, +0.65] | +0.080 | +0.029 | yes | 3/7 | sample, significance, walk_forward |
| Trendline Break & Retest | -0.188 | -0.244 | 575 | [-0.38, -0.10] | -0.203 | -0.371 | no | 1/7 | out_of_sample, significance, costs, walk_forward |
| ICT Premium/Discount OTE | -0.172 | -0.069 | 160 | [-0.34, +0.22] | -0.146 | -0.262 | no | 2/7 | out_of_sample, significance, costs, walk_forward |
| Trend Momentum v2 | -0.214 | +0.204 | 29 | [-0.32, +0.73] | -0.103 | -0.209 | no | 2/7 | sample, out_of_sample, significance, costs, walk_forward |
| Compression Breakout v2 | -0.013 | -0.442 | 52 | [-0.74, -0.10] | -0.175 | -0.249 | no | 3/7 | out_of_sample, significance, costs, walk_forward |

## 3. Best and worst conditions per strategy (groups with 30+ trades)

| Strategy | Best instrument | Worst instrument | Best session | Best trend regime | Best volatility regime |
|---|---|---|---|---|---|
| London Session Breakout | XAUUSD +0.06R (n=264, PF 1.12) | USDCAD -0.06R (n=330) | London +0.00R (n=4198, PF 1.01) | RANGING +0.02R (n=1773, PF 1.03) | HIGH VOL +0.06R (n=669, PF 1.13) |
| Bollinger Band Mean Reversion | USDCAD +0.42R (n=37, PF 2.65) | ETHUSD -0.36R (n=69) | Late / rollover +0.13R (n=53, PF 1.28) | TRANSITIONAL +0.05R (n=222, PF 1.11) | NORMAL VOL +0.08R (n=245, PF 1.19) |
| Opening Range Breakout | US500 +0.01R (n=477, PF 1.03) | NAS100 -0.01R (n=426) | London +0.01R (n=438, PF 1.02) | RANGING +0.05R (n=473, PF 1.13) | LOW VOL +0.08R (n=492, PF 1.19) |
| Opening Range Breakout v2 | GER40 +0.15R (n=179, PF 1.26) | NAS100 -0.08R (n=148) | London +0.15R (n=179, PF 1.26) | RANGING +0.18R (n=203, PF 1.35) | LOW VOL +0.11R (n=202, PF 1.21) |
| Market Structure Break | GBPUSD +0.43R (n=100, PF 1.80) | NZDUSD -0.26R (n=73) | Asia +0.20R (n=353, PF 1.34) | TRENDING +0.02R (n=583, PF 1.03) | NORMAL VOL +0.04R (n=502, PF 1.06) |
| MACD Momentum | XAUUSD +0.25R (n=259, PF 1.43) | USDCHF -0.20R (n=286) | Asia +0.09R (n=1040, PF 1.14) | TRANSITIONAL +0.00R (n=793, PF 1.00) | LOW VOL -0.01R (n=1386, PF 0.99) |
| Donchian Channel Breakout | USDCAD +0.13R (n=334, PF 1.21) | NZDUSD -0.23R (n=435) | Asia +0.05R (n=1440, PF 1.08) | RANGING -0.00R (n=2464, PF 0.99) | LOW VOL -0.03R (n=1648, PF 0.96) |
| ICT Silver Bullet | XAUUSD +0.21R (n=37, PF 1.87) | US500 -0.35R (n=32) | London/NY overlap +0.01R (n=199, PF 1.04) | RANGING +0.05R (n=195, PF 1.13) | LOW VOL +0.06R (n=167, PF 1.19) |
| Order Block Retest | USDCAD +0.30R (n=42, PF 1.55) | BTCUSD -0.39R (n=62) | Late / rollover +0.20R (n=84, PF 1.34) | RANGING +0.07R (n=238, PF 1.10) | LOW VOL +0.08R (n=180, PF 1.12) |
| ATR Volatility Breakout | GER40 +0.12R (n=354, PF 1.18) | AUDUSD -0.21R (n=348) | Asia +0.05R (n=1141, PF 1.08) | RANGING -0.05R (n=1682, PF 0.93) | LOW VOL -0.03R (n=1193, PF 0.96) |
| ICT Liquidity Sweep Reversal | USDJPY +0.19R (n=122, PF 1.36) | NZDUSD -0.36R (n=120) | Late / rollover +0.34R (n=70, PF 1.73) | TRANSITIONAL -0.03R (n=402, PF 0.96) | HIGH VOL -0.02R (n=477, PF 0.97) |
| Ichimoku Trend Following | USDJPY +0.17R (n=299, PF 1.27) | USDCHF -0.25R (n=327) | Asia -0.03R (n=1362, PF 0.95) | TRANSITIONAL -0.06R (n=1190, PF 0.92) | LOW VOL -0.01R (n=1404, PF 0.98) |
| Fair Value Gap | NAS100 +0.25R (n=59, PF 1.39) | AUDUSD -0.36R (n=57) | London +0.11R (n=194, PF 1.18) | TRENDING -0.01R (n=439, PF 0.99) | LOW VOL +0.03R (n=295, PF 1.05) |
| Breakout Trading | XAUUSD +0.10R (n=117, PF 1.15) | NAS100 -0.36R (n=112) | Asia +0.13R (n=295, PF 1.20) | TRENDING -0.04R (n=568, PF 0.94) | LOW VOL -0.04R (n=544, PF 0.95) |
| ICT Market Structure Shift | NAS100 +0.35R (n=75, PF 1.63) | US500 -0.42R (n=53) | Asia +0.03R (n=439, PF 1.05) | RANGING +0.00R (n=474, PF 1.00) | LOW VOL -0.00R (n=605, PF 0.99) |
| Liquidity Sweep | USDJPY +0.21R (n=159, PF 1.34) | GBPUSD -0.31R (n=168) | Late / rollover -0.02R (n=338, PF 0.97) | TRENDING +0.03R (n=1216, PF 1.05) | NORMAL VOL -0.01R (n=1018, PF 0.98) |
| Inside Bar Breakout | GER40 +0.05R (n=298, PF 1.07) | USDCHF -0.38R (n=351) | Asia -0.02R (n=1737, PF 0.97) | TRANSITIONAL -0.03R (n=1117, PF 0.95) | NORMAL VOL -0.07R (n=1915, PF 0.90) |
| Liquidity Divergence v2 | NZDUSD +0.37R (n=30, PF 1.67) | USDJPY -0.01R (n=39) | Asia +0.21R (n=113, PF 1.35) | TRENDING +0.05R (n=159, PF 1.07) | NORMAL VOL +0.06R (n=109, PF 1.09) |
| EMA Pullback | BTCUSD +0.05R (n=466, PF 1.07) | USDCHF -0.26R (n=344) | London/NY overlap -0.07R (n=1290, PF 0.90) | TRENDING -0.09R (n=2089, PF 0.88) | LOW VOL -0.06R (n=1724, PF 0.92) |
| RSI Divergence | US500 +0.28R (n=58, PF 1.47) | ETHUSD -0.41R (n=70) | Asia +0.06R (n=258, PF 1.09) | TRANSITIONAL -0.00R (n=109, PF 1.00) | LOW VOL +0.04R (n=245, PF 1.06) |
| Trend Pullback v2 | EURJPY +0.13R (n=97, PF 1.20) | USDJPY -0.36R (n=90) | Late / rollover -0.01R (n=185, PF 0.99) | TRENDING -0.05R (n=1039, PF 0.93) | LOW VOL +0.03R (n=544, PF 1.05) |
| EMA Crossover | USDCAD +0.02R (n=103, PF 1.03) | USDCHF -0.31R (n=151) | Asia -0.00R (n=562, PF 0.99) | RANGING -0.06R (n=1110, PF 0.92) | LOW VOL -0.00R (n=626, PF 1.00) |
| Crypto Trend Breakout v2 | BTCUSD +0.05R (n=159, PF 1.07) | ETHUSD -0.00R (n=157) | London +0.27R (n=43, PF 1.39) | TRENDING +0.09R (n=207, PF 1.12) | HIGH VOL +0.18R (n=168, PF 1.26) |
| ICT Order Block Reversal | GBPUSD +0.14R (n=105, PF 1.26) | USDCHF -0.47R (n=80) | London +0.03R (n=355, PF 1.05) | TRENDING -0.04R (n=682, PF 0.94) | LOW VOL -0.04R (n=550, PF 0.95) |
| ICT Judas Swing | — (no group with 30+ trades) | — | London/NY overlap +0.31R (n=34, PF 1.95) | RANGING +0.13R (n=51, PF 1.27) | LOW VOL +0.10R (n=64, PF 1.19) |
| ICT Fair Value Gap Continuation | XAUUSD +0.53R (n=38, PF 2.00) | AUDUSD -0.84R (n=32) | London/NY overlap +0.10R (n=123, PF 1.16) | TRANSITIONAL +0.01R (n=108, PF 1.02) | LOW VOL +0.02R (n=189, PF 1.02) |
| Support & Resistance | NAS100 +0.09R (n=47, PF 1.13) | EURUSD -0.48R (n=40) | London +0.01R (n=162, PF 1.01) | RANGING +0.05R (n=91, PF 1.07) | NORMAL VOL -0.06R (n=218, PF 0.92) |
| Trendline Bounce | XAUUSD +0.02R (n=562, PF 1.03) | USDCHF -0.42R (n=500) | Asia -0.14R (n=2574, PF 0.83) | TRANSITIONAL -0.20R (n=1380, PF 0.77) | HIGH VOL -0.18R (n=2677, PF 0.79) |
| ICT Sweep + Displacement + FVG | — (no group with 30+ trades) | — | — (no group with 30+ trades) | — (no group with 30+ trades) | — (no group with 30+ trades) |
| Trendline Break & Retest | XAUUSD -0.04R (n=144, PF 0.95) | XAGUSD -0.44R (n=123) | London/NY overlap -0.08R (n=313, PF 0.90) | TRENDING -0.16R (n=1341, PF 0.81) | HIGH VOL -0.05R (n=686, PF 0.94) |
| ICT Premium/Discount OTE | EURJPY +0.53R (n=33, PF 1.80) | GER40 -0.57R (n=40) | Late / rollover +0.41R (n=49, PF 1.57) | TRENDING -0.13R (n=282, PF 0.85) | LOW VOL -0.05R (n=190, PF 0.94) |
| Trend Momentum v2 | — (no group with 30+ trades) | — | London -0.13R (n=40, PF 0.82) | TRENDING -0.10R (n=109, PF 0.86) | LOW VOL +0.12R (n=41, PF 1.19) |
| Compression Breakout v2 | — (no group with 30+ trades) | — | London/NY overlap -0.02R (n=73, PF 0.97) | RANGING -0.05R (n=76, PF 0.93) | NORMAL VOL +0.01R (n=51, PF 1.01) |

## 4. Families pooled (all periods, after costs)

| Family | Strategies | Trades | Pooled avg R | Pooled total R | Test-period avg R |
|---|---|---|---|---|---|
| ICT | 8 | 7043 | -0.073 | -515.3 | -0.124 |
| PRODUCTION-LINKED | 3 | 10926 | -0.220 | -2401.5 | -0.284 |
| T-034 BANK | 16 | 50247 | -0.059 | -2950.8 | -0.096 |
| UPGRADE | 6 | 3227 | -0.047 | -150.3 | -0.140 |

## 5. Technical funnels of the new strategies (historical decisions -> accepted signals)

- **Opening Range Breakout v2**: 525 decisions, 525 accepted
- **ICT Silver Bullet**: 589 decisions, 573 accepted; rejected: {'rejected: reward/risk x below the x minimum': 11, 'rejected: spread above x% of the risk': 3, 'rejected: entry moved more than x ATR from the confirming close': 2}
- **ICT Liquidity Sweep Reversal**: 2247 decisions, 2140 accepted; rejected: {'rejected: reward/risk x below the x minimum': 52, 'rejected: spread above x% of the risk': 20, 'rejected: entry moved more than x ATR from the confirming close': 35}
- **ICT Market Structure Shift**: 1672 decisions, 1601 accepted; rejected: {'rejected: spread above x% of the risk': 26, 'rejected: entry moved more than x ATR from the confirming close': 18, 'rejected: reward/risk x below the x minimum': 27}
- **Liquidity Divergence v2**: 497 decisions, 482 accepted; rejected: {'rejected: spread above x% of the risk': 5, 'rejected: entry moved more than x ATR from the confirming close': 8, 'rejected: stop distance outside xx ATR': 2}
- **Trend Pullback v2**: 4296 decisions, 4264 accepted; rejected: {'rejected: spread above x% of the risk': 12, 'rejected: entry moved more than x ATR from the confirming close': 19, 'rejected: no next bar': 1}
- **Crypto Trend Breakout v2**: 552 decisions, 549 accepted; rejected: {'rejected: entry moved more than x ATR from the confirming close': 3}
- **ICT Order Block Reversal**: 1855 decisions, 1758 accepted; rejected: {'rejected: reward/risk x below the x minimum': 45, 'rejected: entry moved more than x ATR from the confirming close': 24, 'rejected: spread above x% of the risk': 28}
- **ICT Judas Swing**: 187 decisions, 182 accepted; rejected: {'rejected: reward/risk x below the x minimum': 1, 'rejected: entry moved more than x ATR from the confirming close': 3, 'rejected: spread above x% of the risk': 1}
- **ICT Fair Value Gap Continuation**: 587 decisions, 562 accepted; rejected: {'rejected: entry moved more than x ATR from the confirming close': 4, 'rejected: reward/risk x below the x minimum': 13, 'rejected: spread above x% of the risk': 8}
- **ICT Sweep + Displacement + FVG**: 50 decisions, 48 accepted; rejected: {'rejected: reward/risk x below the x minimum': 2}
- **ICT Premium/Discount OTE**: 996 decisions, 626 accepted; rejected: {'rejected: reward/risk x below the x minimum': 322, 'rejected: spread above x% of the risk': 26, 'rejected: entry moved more than x ATR from the confirming close': 22}
- **Trend Momentum v2**: 114 decisions, 114 accepted
- **Compression Breakout v2**: 140 decisions, 140 accepted
