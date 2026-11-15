# Scrap MIS Calculation Guide (company rules)

## 1. Purpose

Explain how Scrap MIS Dashboard calculates production and scrap figures.

Use plain, simple English. Explain:
- Which source quantities are used
- Which formula is applied
- What each percentage means
- Which plants and processes are included
- How totals are built
- Which records are excluded
- What limitations can affect interpretation

Never invent formulas or business rules not defined in report logic.

## 2. Main Quantity Definitions

- **Prod Qty:** Production quantity recorded for process.
- **RL / Random:** Random-length quantity.
- **Scrap Qty:** Scrap quantity recorded for process.
- **BL:** BL quantity recorded in source data.
- **Cutting Prod Qty:** Production quantity from final cutting.
- **Cutting Scrap Qty:** Scrap quantity from final cutting.
- **M2M Received Qty:** Material received through M2M process, converted from kg to MT where required.

Use source column names when available. Do not assume two similarly named fields mean same thing without checking report logic.

## 3. Core Formulas

### Total Issue Quantity

Formula:

`Total Issue Qty = Prod Qty + Random (RL) + Scrap Qty + BL`

Meaning:

Total issue quantity combines production, random-length quantity, scrap, and BL quantity.

### Random Percentage

Formula:

`Random % = RL / Total Issue Qty * 100`

Meaning:

Shows random-length quantity as percentage of total issue quantity.

If Total Issue Qty is zero, do not divide by zero. Show blank or the report's existing zero-handling result.

### First-Process Scrap Percentage

Formula:

`First Process Scrap % = (Scrap Qty + BL) / Total Issue Qty * 100`

Meaning:

Combines scrap and BL quantities, then calculates their percentage of total issue quantity.

### Cutting Total Production

Formula:

`Cutting Total = Cutting Prod Qty + Cutting Scrap Qty`

Meaning:

Adds cutting production and cutting scrap to calculate total quantity processed through cutting.

### Cutting Scrap Percentage

Formula:

`Cutting Scrap % = Cutting Scrap Qty / (Cutting Prod Qty + Cutting Scrap Qty) * 100`

Meaning:

Shows cutting scrap as a percentage of total cutting quantity.

### Total Scrap Percentage

Formula:

`Total Scrap % = Random % + First Process Scrap % + Cutting Scrap %`

Meaning:

Adds three separately calculated percentages.

**Important limitation:** These percentages can use different denominators. Their sum is a report-defined KPI, not necessarily physical total scrap divided by total material input. Explain this whenever user asks whether Total Scrap % represents overall material loss or yield.

## 4. Kilograms to Metric Tonnes

Formula:

`MT = KG / 1000`

Rules:
- Convert kilogram quantities to metric tonnes where report requires.
- Preserve original source kg in underlying Data sheet if that is existing report behavior.
- Do not divide counts or percentage values by 1000.
- Do not convert a quantity twice.
- State units clearly in every explanation.

## 5. Plant and Process Mapping

Use following report mappings:

- `WELDE` → Welded
- `TM10` → TM10
- `CONDT` → Cond
- `L_SAW` and `PLB1` → L-Saw
- `BA` → BA
- `SMLSP`:
  - Equipment `EXP1` → SMLS Pipe (EXP1)
  - Equipment beginning `PEEL` → SMLS Pipe (PEEL)
  - Other equipment → SMLS Pipe (ALL PILGER)
- `SMLP2`:
  - Equipment beginning `PEEL` → SMLS Pipe-2 (PEEL3)
  - Other equipment → SMLS Pipe-2 (ALL PILGER)
- `SMLST` → SMLS Tube
- `PIERC` → Piercing 1
- `PIER2` → Piercing 2

Do not assign unknown plant codes to a known category. Explain that unrecognised plant records are excluded from regular mapped lines and appear in exclusions where report logic supports that.

## 6. Total Calculations

### Welded Total

`Welded Total = Welded + TM10 + Cond + Slitting`

L-Saw is separate. Do not add L-Saw into Welded Total.

### Seamless Total

Seamless Total combines report's seamless production lines. Includes M2M scrap-only line where defined by report.

### Overall KPI

Overall production-stage KPI uses:

`Overall Basis = Welded Total + Seamless Total`

L-Saw cutting can be included in combined cutting calculations, but L-Saw is not included in Welded Total.

When explaining a total, list its component lines. Do not simply say “all production added together.”

## 7. Special Process Rules

### Slitting

- Production = Coil Received Qty + Plate Received Qty.
- Scrap = SS Scrap / Outside Scrap Received Qty, according to report field mapping.
- RL = 0.
- BL = 0.
- Final cutting is not applied to Slitting.

Do not apply normal production-process formulas to Slitting without explaining these special rules.

### Final Cutting

- Use final cutting production and scrap fields as defined by report.
- `Cutting WO Process-MH` is always excluded.
- `Cutting WO Process` is excluded unless its inclusion checkbox is selected.
- Explain checkbox effect when discussing cutting totals.

### M2M

- M2M received kg is used as cutting scrap only.
- M2M production is zero.
- M2M must not overwrite seamless production quantity.

Explain this distinction whenever M2M changes scrap totals.

## 8. Date Filters and Monthly Comparison

- Apply selected date range to records before summarising.
- Explain selected start and end dates.
- Monthly comparisons must use same report metrics and comparable periods.
- For percentage metrics, report change in percentage points where appropriate.
- For production quantities, percentage change can be calculated against previous period.
- Do not calculate percentage change against a zero previous value without explaining the result.
- If current month is incomplete, daily-average insight may be used by report logic. Clearly label it as an estimate based on elapsed days, not a final full-month result.

## 9. Data Validation and Exclusions

Explain these known behaviors:

- Invalid dates may be skipped.
- Duplicate records may be ignored when generated record keys identify them as duplicates.
- Duplicate detection is not guaranteed for every possible duplicate.
- Unmapped plant records may appear in exclusions rather than regular totals.
- Final cutting `Prod Qty with Scrap` can be compared with `Prod Qty + Scrap Qty` as a validation check.
- Validation checks do not automatically mean a record was corrected.

Never claim all duplicates are detected or all excluded records are invalid.

## 10. Required Answer Format

When user asks how a calculation works, answer in this order:

1. **What report calculates**
2. **Source fields used**
3. **Exact formula**
4. **Simple example with numbers**
5. **Meaning of result**
6. **Included processes and plant mappings**
7. **Exclusions and special rules**
8. **Important limitations**

Use this example format:

**Example: Cutting Scrap %**

- Cutting Prod Qty = 900 MT
- Cutting Scrap Qty = 100 MT
- Cutting Total = 900 + 100 = 1,000 MT
- Cutting Scrap % = 100 / 1,000 × 100 = 10%

Meaning: 10% of total quantity processed through cutting is recorded as cutting scrap.

Examples must be mathematically correct and clearly marked as illustrative. Do not present example values as actual company data.

## 11. Rules for Answering Questions

- If user asks “Why is this total high?”, identify contributing quantities and formulas before giving possible explanations.
- If user asks “How is this percentage calculated?”, show numerator, denominator, formula, and result.
- If user asks “Why does total not match?”, check filters, process mappings, excluded records, duplicate handling, units, and separate totals.
- If user asks “Is this total scrap?”, distinguish report's combined percentage KPI from physical scrap quantity or material-loss percentage.
- If source logic does not define an answer, state: “Report logic does not define this clearly.”
- Do not silently change formulas, mappings, exclusions, or field meanings.
- Do not assume report logic is the correct business definition. Explain what code calculates separately from whether business should use that KPI.
- Keep explanations simple, but preserve exact formulas, field names, units, and exceptions.

## 12. How VERONICA applies this guide (engine notes)
- /scrap_mis_report runs the engine that is an exact port of Scrap_MIS_Dashboard_Generator_v10_NoCharts.html; every figure comes from it. Use this guide to EXPLAIN those figures, in the order of section 10.
- Sources: Welded = VIEW_WELDED_SCRAP_MIS_PBI, Seamless = VIEW_SEAMLESS_SCRAP_MIS_PBI, Slitting = VIEW_SLITTING_MIS_PBI, Final cutting = VIEW_FINAL_CUTTING_SCRAP_PBI, M2M = VIEW_M2M_PBI. Quantities are kg in the views and shown in MT (kg / 1000).
- Cutting WO Process: in the v10 tool both "Cutting WO Process" and "Cutting WO Process-MH" are always left out (matched in Machine, Process or Plant name) - the include checkbox has no effect in v10. Say this if asked about the checkbox.
- Duplicates: the tool only drops duplicates between two files loaded into the same box; VERONICA loads one file per box, so no rows are dropped as duplicates.
- Left-out records are listed in the report's "Left out and data checks" table (summary.left_out); per-view row counts are in summary.views and the checks.
