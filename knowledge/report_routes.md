# Venus ERP report routes (company rules - follow automatically, never ask the user which view to use)

## Execution rules (always)
- Before the first query on a view: read its columns and COMMENTS in the DATABASE SCHEMA section of the prompt (call describe_tables only if the view is not listed there). The comments say what each quantity / amount means. Trust comments over column names.
- Confirm: the date column, what each quantity/amount means (and its unit), the row grain, and join keys. Prevent duplicate totals from joins.
- Read-only SQL only. Never invent column names, business mappings, numbers or totals.
- Never say a query ran unless the tool actually ran it. Every number in your answer must come from a tool result in THIS conversation.
- If the data is missing, a column is unclear, or a query fails: say so plainly and show what you checked. Do not fill the gap with a guess.
- Apply the requested date filter on the view's actual date column.

## Routes
| User asks for | Use view | Supporting view | Show |
|---|---|---|---|
| Purchase / GRN (today, period) | VIEW_GRN_PBI | VIEW_ITEM_LEDGER_PBI only for ledger movement / reconciliation | GRN count; received qty/value if available; supplier-wise; plant-wise; GRN + item details. Use actual GRN date. |
| Sales orders / order booking / pending sales orders / overdue / late delivery / on-time % / LD orders / salesperson booking / SP matrix | VIEW_SALES_ORDER_PBI via the taught report /sale_order_dashboard | VIEW_LD_SALES_ORDERS_PBI only if the user names it | always run the taught report (engine). NEVER use the invoice view for order booking. |
| Purchase orders (pending, open, ordered vs received) | VIEW_PURCHASE_ORDER_ORDI_PBI (synced name of the purchase-order view) | VIEW_GRN_PBI for received-vs-ordered | open PO count; ordered qty; received qty; pending qty only if supported by verified columns; supplier-wise pending list. Validate document keys before reconciling. |
| Production (today / by plant) | VIEW_PROD_PBI | VIEW_PROD_PROC_PBI for process-level breakdown | total production; plant-wise; process-wise if available; transaction details. |
| Tubing production (MT) | VIEW_TUBING_PBI | - | inspect quantity column and unit; convert KG to MT (qty / 1000.0) ONLY when the source is confirmed KG. Taught report: /seamless_production. |
| Scrap MIS (plant-wise Welded / L-Saw / Seamless scrap %, random %, BL, final cutting, M2M) | VIEW_WELDED_SCRAP_MIS_PBI + VIEW_SEAMLESS_SCRAP_MIS_PBI + VIEW_SLITTING_MIS_PBI + VIEW_FINAL_CUTTING_SCRAP_PBI + VIEW_M2M_PBI via the taught report /scrap_mis_report | - | always run the taught report (engine). |
| Scrap by process (other scrap questions) | VIEW_WELDED_SCRAP_MIS_PBI (welded) / VIEW_SEAMLESS_SCRAP_MIS_PBI (seamless) | VIEW_FINAL_CUTTING_SCRAP_PBI (final cutting), VIEW_SLITTING_MIS_PBI (slitting), VIEW_M2M_PBI (M2M), job-card scrap VIEW_JOB_CARD_SCRAP_PBI | total scrap; process-/machine-wise; plant-wise; date-wise. For the plant-wise scrap % report run /scrap_mis_report. |
| Job card wise scrap % (buckets per job card) | VIEW_JOB_CARD_SCRAP_PBI (replaces VIEW_JOB_CARDWISE_PROD_PBI for this report) via the taught report /jobcardwise_scrap | - | always run the taught report (engine). |
| Sales turnover / invoiced sales | VIEW_SALE_INVOICE_PBI | - | actual invoice date and confirmed billed amount. NEVER substitute sales-order value for turnover. |
| Pending engineering quotations | VIEW_PENDING_QTNS_ENG_PBI | - | pending count; customer-wise list; ageing from verified quotation date; status breakdown if available. |
| Stock movement | VIEW_ITEM_LEDGER_PBI | - | item-wise in/out; plant-wise; transaction details; opening/closing balance only when the data supports it. |
| Account master (account / party list, account group, code -> name) | VIEW_ACC_MAST_PBI | - | account code, name, group/type as in the columns; use to name accounts in ledger / voucher answers (join on the verified account code). |
| Customer / party ledger | view_acc_ledger_pbi (VIEW_ACC_LEDGER_PBI) | - | customer transactions; debit/credit totals; closing balance only when ledger fields and sign convention support it. |
| Accounting transactions / vouchers / journal entries | VIEW_ACC_TRAN_ENGINE_PBI | view_acc_ledger_pbi for party balances | voucher-wise and account-wise lines; debit/credit totals. Read column comments for sign convention before totalling. |
| Cutting scrap / final cutting | VIEW_FINAL_CUTTING_SCRAP_PBI | - | final cutting prod + scrap qty; plant-/process-wise; date-wise. Not the job-card scrap % report. |
| Welded scrap | VIEW_WELDED_SCRAP_MIS_PBI | - | welded prod, RL, scrap, BL qty; plant-/machine-wise; date-wise. |
| LSAW pipe production | VIEW_LSAW_PBI | - | LSAW production qty (check unit in comments); plant/size-wise; date-wise. |
| Welded tubing production | VIEW_WELDED_TUBING_PBI | - | welded tube production qty (check unit); plant/size/grade-wise. Seamless tubing is VIEW_TUBING_PBI. |
| Slitting | VIEW_SLITTING_MIS_PBI | - | issue / received qty by item group (coil, plate, SS scrap) and godown; date-wise. |
| Welding conditions / parameters | VIEW_WELD_COND_PBI | - | weld parameters as recorded (current, voltage, speed etc. - only the columns that exist); by machine/job/date. Never invent limits. |
| Employee / staff master | VIEW_EMP_MAST_PBI - PRIVATE, NOT SYNCED at present | - | Only admins can read it (the database guard blocks everyone else). If blocked, say politely: "Employee details are private and not in your access. Please contact your admin." Never reveal salary, phone, address, ID or bank details in group chats. |
| Rejection report (plain "rejection": total, plant-wise, process-wise, trend) | VIEW_REJECTION_PBI | - | total rejection qty; plant-wise; process-wise; date-wise trend; job-card/item details if available. Use the actual date column. Never use scrap views for rejection. |
| FINAL production / FINAL rejection / "final production-rejection" / QC final inspection / REJP / yield | VIEW_REJECTION_PBI (renamed from VIEW_FINAL_PROD_PBI) via the taught report /final_production_rejection_report | - | always run the taught report (engine): PROD + REJP, U1 / U2, Rejection / Rework / A / B / C. |

## Views currently synced to the replica
VIEW_WELDED_SCRAP_MIS_PBI, VIEW_SEAMLESS_SCRAP_MIS_PBI, VIEW_SLITTING_MIS_PBI, VIEW_FINAL_CUTTING_SCRAP_PBI, VIEW_M2M_PBI, VIEW_JOB_CARD_SCRAP_PBI, VIEW_TUBING_PBI, VIEW_LSAW_PBI, VIEW_WELD_COND_PBI, VIEW_WELDED_TUBING_PBI, VIEW_LD_SALES_ORDERS_PBI, VIEW_PURCHASE_ORDER_ORDI_PBI, VIEW_GRN_PBI, VIEW_SALE_INVOICE_PBI, VIEW_ITEM_LEDGER_PBI, VIEW_ACC_TRAN_ENGINE_PBI, view_acc_ledger_pbi, VIEW_REJECTION_PBI, VIEW_ACC_MAST_PBI, VIEW_SALES_ORDER_PBI.
VIEW_JOB_CARD_SCRAP_PBI = job card scrap % source; VIEW_REJECTION_PBI = final production + rejection (old name VIEW_FINAL_PROD_PBI); VIEW_SALES_ORDER_PBI = sales-order lines for /sale_order_dashboard; VIEW_LD_SALES_ORDERS_PBI = older sales-order view (old name VIEW_LD_ORDERS_PBI); VIEW_ACC_MAST_PBI = account master (account / party code, name, group).
Views not in the replica now (VIEW_PROD_PBI, VIEW_PROD_PROC_PBI, VIEW_EMP_MAST_PBI, VIEW_PENDING_QTNS_ENG_PBI, VIEW_JOB_CARDWISE_PROD_PBI and other old names): check with list_tables; if missing, say "<view> is not synced yet - ask IT to add it to the sync" and stop.

## Never mix
- Scrap MIS (/scrap_mis_report) is not the job-card scrap % report (/jobcardwise_scrap).
- Scrap is not rejection: do not use scrap views for a rejection request unless the user explicitly asks for scrap.
- Orders (VIEW_LD_SALES_ORDERS_PBI) are not invoices (VIEW_SALE_INVOICE_PBI).
- If a view in this table is not in the database, say "<view> is not available in the replica yet" - do not switch to another view silently.
