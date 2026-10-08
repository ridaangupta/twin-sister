# Exploratory analyses of existing dialogue logs (WS1)

**Exploratory.** These runs were already used for development or confirmation, so the results below generate hypotheses for later pre-registered sets; they confirm nothing. Produced by `scripts/explore_logs.py`.

## syn_test400_dialogue (`20261007T160631Z_syn_test400_dialogue`, 400 problems)

### 1a. Both opening posts wrong

| openings | problems | final answer correct | recovery |
|---|---|---|---|
| same wrong answer | 8 | 0 | 0% |
| different wrong answers (or none) | 48 | 26 | 54% |

### 1b. Direction of answer switches

| agent | to correct | away from correct | wrong to wrong | total |
|---|---|---|---|---|
| A | 52 | 3 | 12 | 67 |
| B | 29 | 1 | 3 | 33 |
| both | 81 | 4 | 15 | 100 |

### 1c. First numeric error per agent, by type

Claim extraction: 13471 value claims from 1482/1709 posts. An agent with no wrong claim, or whose working could not be parsed, has no row.

| error type | agents | corrected by partner | corrected by self | never corrected | final answer correct |
|---|---|---|---|---|---|
| implicit total | 66 | 23 | 8 | 35 | 47 |
| arithmetic or unexplained | 44 | 20 | 8 | 16 | 30 |
| wrong operand | 18 | 8 | 4 | 6 | 13 |
| misread relation | 15 | 5 | 1 | 9 | 10 |
| backward step | 4 | 1 | 1 | 2 | 3 |
| distractor value (harmless) | 3 | 1 | 0 | 2 | 2 |
| distractor used as operand | 2 | 1 | 0 | 1 | 2 |
| misread given value | 1 | 0 | 0 | 1 | 1 |

## syn_dev200_dialogue (`20261007T153222Z_syn_dev200_dialogue`, 200 problems)

### 1a. Both opening posts wrong

| openings | problems | final answer correct | recovery |
|---|---|---|---|
| same wrong answer | 3 | 0 | 0% |
| different wrong answers (or none) | 20 | 10 | 50% |

### 1b. Direction of answer switches

| agent | to correct | away from correct | wrong to wrong | total |
|---|---|---|---|---|
| A | 24 | 0 | 5 | 29 |
| B | 16 | 0 | 0 | 16 |
| both | 40 | 0 | 5 | 45 |

### 1c. First numeric error per agent, by type

Claim extraction: 6589 value claims from 712/838 posts. An agent with no wrong claim, or whose working could not be parsed, has no row.

| error type | agents | corrected by partner | corrected by self | never corrected | final answer correct |
|---|---|---|---|---|---|
| implicit total | 28 | 8 | 4 | 16 | 17 |
| arithmetic or unexplained | 23 | 12 | 3 | 8 | 15 |
| wrong operand | 12 | 3 | 5 | 4 | 9 |
| misread relation | 10 | 5 | 0 | 5 | 6 |
| backward step | 2 | 0 | 2 | 0 | 1 |
| distractor value (harmless) | 1 | 0 | 0 | 1 | 0 |
| misread given value | 1 | 0 | 0 | 1 | 1 |

## syn_dev200_abl_no_indep (`20261007T154220Z_syn_dev200_abl_no_indep`, 200 problems)

### 1a. Both opening posts wrong

| openings | problems | final answer correct | recovery |
|---|---|---|---|
| same wrong answer | 14 | 0 | 0% |
| different wrong answers (or none) | 22 | 8 | 36% |

### 1b. Direction of answer switches

| agent | to correct | away from correct | wrong to wrong | total |
|---|---|---|---|---|
| A | 14 | 1 | 5 | 20 |
| B | 1 | 0 | 2 | 3 |
| both | 15 | 1 | 7 | 23 |

### 1c. First numeric error per agent, by type

Claim extraction: 5072 value claims from 540/627 posts. An agent with no wrong claim, or whose working could not be parsed, has no row.

| error type | agents | corrected by partner | corrected by self | never corrected | final answer correct |
|---|---|---|---|---|---|
| implicit total | 30 | 2 | 0 | 28 | 7 |
| arithmetic or unexplained | 24 | 8 | 3 | 13 | 14 |
| wrong operand | 7 | 0 | 0 | 7 | 1 |
| misread relation | 5 | 2 | 0 | 3 | 3 |
| backward step | 4 | 1 | 0 | 3 | 2 |
| distractor value (harmless) | 1 | 0 | 0 | 1 | 0 |

## syn_dev200_abl_simplicity (`20261007T154644Z_syn_dev200_abl_simplicity`, 200 problems)

### 1a. Both opening posts wrong

| openings | problems | final answer correct | recovery |
|---|---|---|---|
| same wrong answer | 3 | 0 | 0% |
| different wrong answers (or none) | 22 | 9 | 41% |

### 1b. Direction of answer switches

| agent | to correct | away from correct | wrong to wrong | total |
|---|---|---|---|---|
| A | 22 | 1 | 3 | 26 |
| B | 22 | 1 | 5 | 28 |
| both | 44 | 2 | 8 | 54 |

### 1c. First numeric error per agent, by type

Claim extraction: 6618 value claims from 727/829 posts. An agent with no wrong claim, or whose working could not be parsed, has no row.

| error type | agents | corrected by partner | corrected by self | never corrected | final answer correct |
|---|---|---|---|---|---|
| implicit total | 37 | 9 | 7 | 21 | 19 |
| arithmetic or unexplained | 21 | 9 | 4 | 8 | 14 |
| wrong operand | 10 | 2 | 4 | 4 | 7 |
| misread relation | 9 | 4 | 2 | 3 | 6 |
| backward step | 3 | 0 | 0 | 3 | 3 |
| distractor used as operand | 1 | 0 | 0 | 1 | 0 |
| distractor value (harmless) | 1 | 1 | 0 | 0 | 1 |
| misread given value | 1 | 0 | 0 | 1 | 1 |

## Notes on method

- 1a uses the answers after the first round (turn 1). "Different wrong answers" includes an opening with no answer.
- 1b counts every change of an agent's stated answer between its own posts; gaps with no answer are skipped.
- 1c regenerates each problem's hidden graph from its seed, extracts claims of the form `label = … = value` (LaTeX and prose forms), takes each agent's first claim that differs from the true value, and classifies it: backward step (a hidden leaf), misread given value, implicit total, misread relation (matches a plausible misreading), distractor or wrong operand (matches the relation applied to another quantity), else arithmetic or unexplained. Distractor values are wrong but harmless. Corrected = a later post states the true value for that quantity.
- Validation: `analysis/results/error_validation_sample.md` holds a random 60 classified errors for hand labelling.

