# Recipe: Sales Order MIS dashboard (prompt + how it is wired into VERONICA)

Use this when someone gives a similar prompt and says "use this view" - build the HTML generator from the
prompt, then wire it into VERONICA the same way as /sale_order_dashboard.

## A. The build prompt (as given by IT, 26-Oct-2026)

I am attaching the Venus Pipes ERP export "SALES ORDER REPORTS - LD ORDER DETAILS REPORT" (CSV, windows-1252, 4 title rows above the header, "Printed On" date in row 2).

Build ONE self-contained offline HTML file (Sales_Order_MIS_Generator.html) where I drop this raw CSV/XLSX and a full Sales Order MIS dashboard builds in the browser. Inline all libraries (Chart.js 4.4, SheetJS for reading, ExcelJS for writing). Dark + Light + Auto theme switch.

DATA RULES
- Find the header row by "Sales Order No". Use "Printed On" as the status as-of date (allow override).
- Grade = "Parent Grade" (not the "Grade" column). Unit = "Div". Order status = "Closed Flag" (blank = Open).
- Qty in MT for UM=KG lines; fittings with UM=NO kept in Nos and shown separately.
- Value = "Material Value (INR)" (net of cancellation), shown in ₹ Cr or ₹ Lakh.
  - Rate per line = Material Value ÷ Net qty.
  - Executed / pending / cancelled value = qty × that rate.
  - Never total "Basic Value" (has corrupt rows).
  - Ignore cancelled value on lines with rate > ₹20,000/kg.
- Delay days = max number after ":" in "Delay Duration". Late qty = min(Delay Delivery Qty, Disp qty).
- Overdue = pending > 0 and delivery date before the as-of date.
- Market: Export / Domestic / Other from Tran Type.
- LD Yes/No from "LD Applicable".
- Inspection grouped as Venus / Third Party / Client.
- OD size bands: ≤60.3, 60.3–168.3, 168.3–323.9, >323.9.
- Approval lag = approval date − order date.

DASHBOARD
- Header switch Qty MT / ₹ Cr / ₹ Lakh that changes every chart and table.
- Multi-select slicers: FY, item group, salesperson, segment, market, grade, LD, country, line status, unit, order status, inspection, finish, OD size, quotation, customer.
- Order-date range with presets, plus search. Clicking a chart bar filters.
- Like-for-like = this FY to date vs same months last FY (or same dates last year when a date range is set).
- Tabs:
  - Overview: KPIs, trend, insights.
  - Sales Team: salesperson profile vs team, 12-month tracker with Rising/Falling, scorecard, heatmap.
  - SP Matrix: see below.
  - Customers: Pareto, status New/Growing/At risk/Dormant.
  - Value & Pricing: values, ₹/kg trend, ₹/kg by grade and by salesperson, unit, order status, size, approval lag.
  - Grades: grade scorecard and trends.
  - Products.
  - Delivery & Pending: on-time %, ageing, overdue lines with LD filter.
  - Alerts & Insights: auto alerts.
  - Data.
- SP MATRIX in my management layout:
  - As-on date control.
  - Periods: Today, Yesterday, This Week (Sun–Sat, week to date), Last Week, This Month (MTD), Last Month, FY to Date, plus MTD vs last-month-same-days %.
  - Rows: salesperson → division (SMLS / WELDED / LSAW / FITTING / OTHER) → person Total → Grand Total, plus Division Summary.
  - Qty (KG/MT, order or net) and Value (Mat. value or order value, ₹ Cr / ₹ Lakh) per period.

BUTTONS
- "Download Excel": formatted workbook, one sheet per tab, copying dashboard colours.
  - KPI tiles, table header and total-row colours, heatmaps, ▲▼ growth colours.
  - Indian number format, merged matrix headers, frozen panes.
  - Charts as images with legends.
  - Data sheet with filtered rows.
- "Download HTML": same page with data embedded, opens without upload.
- "Load new file".

Before giving it to me, test in a headless browser:
- Upload my file and confirm there are no errors.
- Check KPIs and the matrix for one as-on date against pandas totals.
- Test both downloads.
- Screenshot all tabs in light and dark mode.
Then send me the file and a short list of findings.

## B. How a generator like this becomes a VERONICA report (pattern used for /sale_order_dashboard)

1. Template: the generator HTML is stored unchanged in `app/templates/dashboards/` (here `sales_order_mis.html`).
2. Engine (`app/engines/<name>.py`): reads the view, ports the generator's parsing/cleaning function
   line by line (here `MIS_buildD` -> `build_d`), and
   - fills the generator's own data slot (`<script id="mis-data">`) = its "Download HTML" snapshot, or
     feeds the rows to its upload box (jobcard / scrap MIS pattern);
   - computes the chat KPI cards and tables from the same data.
3. Skill JSON (`examples/skills/<name>.json`): `sql_template` = {"engine", "source": view, "formats", "template"}; rules = the data rules above.
4. Register the engine in `app/agent.py` and `app/dash.py` (live dashboard link).
5. Route the questions to it in `knowledge/report_routes.md`; add the view to `oracle_mysql_sync.py` and to the department roles.
6. Verify in headless Chromium: the generator's own JS function on the same rows must give exactly the Python
   result (here 6,000 lines, every field identical), KPIs and SP Matrix equal, both downloads work, all tabs in light + dark.
