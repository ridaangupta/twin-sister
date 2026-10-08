# Cost matching on the dev set (WS3)

Target: `20261007T153222Z_syn_dev200_dialogue` — **$0.00418 per problem**, 1881 generated tokens. Tolerance ±2%.

## k_plus_judge

| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |
|---|---|---|---|---|
| k=3 | 0.00214 | 0.512 | 1364 | 0 |
| k=4 | 0.00280 | 0.669 | 1775 | 0 |
| k=5 | 0.00348 | 0.831 | 2196 | 0 |
| k=6 | 0.00414 | 0.990 | 2604 | 0 |
| k=7 | 0.00485 | 1.160 | 3043 | 0 |

**Match:** mixture low = `k=6`, high = `k=7`, p_high = **0.060** → expected $0.00418 (ratio 1.000), 2630 generated tokens.

## self_consistency

| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |
|---|---|---|---|---|
| n=1 | 0.00057 | 0.136 | 385 | 0 |
| n=2 | 0.00115 | 0.275 | 778 | 0 |
| n=3 | 0.00173 | 0.414 | 1170 | 0 |
| n=4 | 0.00232 | 0.553 | 1565 | 0 |
| n=5 | 0.00291 | 0.697 | 1974 | 0 |
| n=6 | 0.00350 | 0.835 | 2367 | 0 |
| n=7 | 0.00411 | 0.983 | 2789 | 0 |
| n=8 | 0.00470 | 1.124 | 3190 | 0 |

**Match:** mixture low = `n=7`, high = `n=8`, p_high = **0.123** → expected $0.00418 (ratio 1.000), 2839 generated tokens.

## reasoning

| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |
|---|---|---|---|---|
| effort=low | 0.00098 | 0.235 | 734 | 316 |
| effort=medium | 0.00120 | 0.287 | 916 | 485 |
| effort=medium n=1 | 0.00120 | 0.287 | 916 | 485 |
| effort=high | 0.00174 | 0.415 | 1361 | 959 |
| effort=xhigh | 0.00212 | 0.508 | 1683 | 1281 |
| effort=medium n=2 | 0.00242 | 0.577 | 1841 | 994 |
| effort=medium n=3 | 0.00362 | 0.864 | 2754 | 1487 |
| effort=medium n=4 | 0.00481 | 1.148 | 3659 | 1974 |
| effort=medium n=5 | 0.00602 | 1.439 | 4585 | 2468 |

**Match:** mixture low = `effort=medium n=3`, high = `effort=medium n=4`, p_high = **0.478** → expected $0.00418 (ratio 1.000), 3187 generated tokens.

## self_refine_redraft

| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |
|---|---|---|---|---|
| calib_self_refine_redraft | 0.00355 | 0.849 | 1725 | 0 |
| calib_self_refine_redraft_mt5 | 0.00582 | 1.391 | 2348 | 0 |
| calib_self_refine_redraft_mt7 | 0.00749 | 1.791 | 3040 | 0 |

**Match:** mixture low = `calib_self_refine_redraft`, high = `calib_self_refine_redraft_mt5`, p_high = **0.278** → expected $0.00418 (ratio 1.000), 1898 generated tokens.

## self_refine

| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |
|---|---|---|---|---|
| calib_self_refine | 0.00282 | 0.675 | 1275 | 0 |

**No bracket:** every setting is cheaper than the dialogue; nearest `calib_self_refine` at ratio 0.675. Measure another setting on the other side, or report the gap.

