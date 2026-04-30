# To run:
#   & "C:/Users/mykha/AppData/Local/Programs/Python/Python313/python.exe" -m streamlit run "C:\Users\mykha\PycharmProjects\Donation-Analytics\recurring_analysis.py"

import streamlit as st
import pandas as pd
import re
import altair as alt
import numpy as np
from datetime import date

st.set_page_config(page_title="KSE Recurring Analysis", page_icon="🔁", layout="wide")
st.title("🔁 KSE Recurring Donor Analysis — 2023–2026")
st.caption("Full recurring program breakdown: MRR, cohorts, retention, churn, LTV, designations, channels.")


# ── helpers ───────────────────────────────────────────────────────────────────

def clean_money(val) -> float:
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = re.sub(r"[^0-9\.,\-]", "", str(val).replace("\u00a0", "").replace(" ", ""))
    if s in {"", "-", ".", ","}: return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if all(len(p) == 3 for p in s.split(",")[1:]) else s.replace(",", ".")
    try: return float(s)
    except: return 0.0

def normalize_text(v) -> str:
    return "" if pd.isna(v) else str(v).strip()

def parse_recurring_flag(series):
    return series.astype(str).str.strip().str.lower().isin({"true","yes","1","y","recurring","✓","x"})

def donor_key_row(r):
    if r["email"]:        return f"email:{r['email']}"
    if r["entity_name"]:  return f"entity:{r['entity_name'].lower()}"
    if r["contact_name"]: return f"contact:{r['contact_name'].lower()}"
    return "unknown"

def donor_display_name(r):
    if r["contact_name"]: return r["contact_name"]
    if r["entity_name"]:  return r["entity_name"]
    if r["email"]:        return r["email"]
    return r["donor_key"]

def fmt(v): return f"${v:,.0f}"
def fmt2(v): return f"${v:,.2f}"

def pct_delta(curr, prev):
    if prev == 0: return "+∞%" if curr > 0 else "—"
    return f"{(curr - prev) / prev * 100:+.1f}%"


# ── loader ────────────────────────────────────────────────────────────────────

def load_and_normalise(uploaded_file):
    name   = uploaded_file.name
    is_csv = name.endswith(".csv")

    uploaded_file.seek(0)
    try:
        peek = pd.read_csv(uploaded_file, header=None, nrows=10) if is_csv \
               else pd.read_excel(uploaded_file, header=None, nrows=10)
    except Exception:
        peek = pd.DataFrame()
    header_row = next(
        (i for i, row in peek.iterrows() if any("Donation amount in USD" in str(v) for v in row.values)),
        0
    )
    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file, header=header_row) if is_csv \
             else pd.read_excel(uploaded_file, header=header_row)
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file) if is_csv else pd.read_excel(uploaded_file)

    df.columns = df.columns.astype(str).str.strip()
    if not {"Donation amount in USD", "Date of donation"}.issubset(df.columns):
        return None, "❌ Missing required columns."

    email_col    = next((c for c in ["Email","Email (Donations)"] if c in df.columns), None)
    source_col   = next((c for c in ["SOURCE (Donations)","SOURCE"] if c in df.columns), None)
    platform_col = next((c for c in ["Payment Platform","Platform"] if c in df.columns), None)
    entity_col   = next((c for c in ["Entity (Donations)","Entity Name"] if c in df.columns), None)
    contact_col  = next((c for c in ["Full Name","Contact Name","Contact Name Entity Name"] if c in df.columns), None)

    rmap = {"Donation amount in USD": "amount_raw", "Date of donation": "date"}
    if "Designations"          in df.columns: rmap["Designations"]          = "designation"
    if email_col:                              rmap[email_col]               = "email"
    if source_col:                             rmap[source_col]              = "source"
    if platform_col:                           rmap[platform_col]            = "platform"
    if entity_col:                             rmap[entity_col]              = "entity_name"
    if contact_col:                            rmap[contact_col]             = "contact_name"
    if "Is Recurring Donation" in df.columns: rmap["Is Recurring Donation"] = "is_recurring"
    if "Donor status"          in df.columns: rmap["Donor status"]          = "donor_status"

    df = df.rename(columns=rmap)
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["date"])

    for col in ["email", "contact_name", "entity_name"]:
        df[col] = df.get(col, pd.Series([""] * len(df))).astype(str).fillna("").map(normalize_text)
    df.loc[df["email"].isin(["nan","none",""]), "email"] = ""
    df["designation"] = df.get("designation", pd.Series([""] * len(df))).fillna("").astype(str).str.strip().replace("nan","")

    df["donor_key"]    = df.apply(donor_key_row, axis=1)
    df["donor_name"]   = df.apply(donor_display_name, axis=1)
    df["amount"]       = df["amount_raw"].apply(clean_money)
    df["month_key"]    = df["date"].dt.to_period("M")
    df["year"]         = df["date"].dt.year
    df["month_num"]    = df["date"].dt.month
    df["month_label"]  = df["date"].dt.strftime("%b")
    df["is_recurring"] = parse_recurring_flag(df["is_recurring"]) if "is_recurring" in df.columns else False
    df["designation_label"] = df["designation"].replace("", "(no designation)")

    # cohort = first recurring month per donor
    rec_first = df[df["is_recurring"]].groupby("donor_key")["month_key"].min().rename("cohort_month")
    df = df.join(rec_first, on="donor_key")
    df["cohort_year"] = df["cohort_month"].apply(lambda x: str(x.year) if pd.notna(x) else "unknown")

    return df.sort_values("date").reset_index(drop=True), "OK"


# ── sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.header("Upload data")
uploaded = st.sidebar.file_uploader(
    "Full KSE export 2023–2026 (csv / xlsx)",
    type=["csv", "xlsx"]
)

if not uploaded:
    st.info("📂 Upload your full donations export to get started.")
    st.stop()

@st.cache_data(show_spinner="Loading…")
def cached_load(data, name):
    import io
    f = io.BytesIO(data); f.name = name
    return load_and_normalise(f)

df_all, msg = cached_load(uploaded.read(), uploaded.name)
if df_all is None:
    st.error(msg); st.stop()

# keep only recurring
df = df_all[df_all["is_recurring"]].copy()

if df.empty:
    st.error("No recurring donations found in this file."); st.stop()

# ── sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")

years_avail = sorted(df["year"].unique())
sel_years   = st.sidebar.multiselect("Year:", years_avail, default=years_avail)

if "platform" in df.columns:
    all_platforms = sorted(df["platform"].fillna("(unknown)").unique())
    sel_platforms = st.sidebar.multiselect("Payment Platform:", all_platforms, default=all_platforms)
else:
    sel_platforms = None

if "source" in df.columns:
    all_sources = sorted(df["source"].fillna("(no source)").unique())
    sel_sources = st.sidebar.multiselect("Source:", all_sources, default=all_sources)
else:
    sel_sources = None

all_desigs  = sorted(df["designation_label"].unique())
sel_desigs  = st.sidebar.multiselect("Designation:", all_desigs, default=all_desigs)

# apply
df = df[df["year"].isin(sel_years)]
if sel_platforms:
    df = df[df["platform"].fillna("(unknown)").isin(sel_platforms)]
if sel_sources:
    df = df[df["source"].fillna("(no source)").isin(sel_sources)]
df = df[df["designation_label"].isin(sel_desigs)]

if df.empty:
    st.warning("No data after applying filters."); st.stop()

all_months  = sorted(df["month_key"].unique())
all_m_str   = [str(m) for m in all_months]

st.caption(f"🔁 {df['donor_key'].nunique():,} unique recurring donors | {len(df):,} transactions | {all_m_str[0]} → {all_m_str[-1]}")


# ── shared computation: monthly subscriber snapshots ─────────────────────────
# build full donor×month presence matrix using the UNFILTERED recurring data
# (so churn/retention is computed on true active base, not filtered slice)
df_rec_full = df_all[df_all["is_recurring"]].copy()
all_m_full  = sorted(df_rec_full["month_key"].unique())

monthly_snap = []   # {month_key, active, new, churned, reactivated, mrr, avg, median}
for i, m in enumerate(all_m_full):
    d_cur  = set(df_rec_full[df_rec_full["month_key"] == m]["donor_key"])
    d_prev = set(df_rec_full[df_rec_full["month_key"] == (m-1)]["donor_key"]) if i > 0 else set()
    new_s  = d_cur - d_prev
    churn_s= d_prev - d_cur
    react_s= set()
    if i > 1:
        d_2ago = set(df_rec_full[df_rec_full["month_key"] == (m-2)]["donor_key"])
        react_s = (d_prev - d_cur) & d_2ago   # rough: was active 2mo ago, missed last, back now
    mrr_val = df_rec_full[df_rec_full["month_key"] == m]["amount"].sum()
    avg_val = df_rec_full[df_rec_full["month_key"] == m]["amount"].mean() if d_cur else 0
    med_val = df_rec_full[df_rec_full["month_key"] == m]["amount"].median() if d_cur else 0
    ret     = len(d_cur & d_prev) / len(d_prev) * 100 if d_prev else None
    monthly_snap.append({
        "month_key":  m,
        "month_str":  str(m),
        "year":       m.year,
        "month_num":  m.month,
        "month_label":pd.Period(m, "M").strftime("%b"),
        "active":     len(d_cur),
        "new":        len(new_s),
        "churned":    len(churn_s),
        "mrr":        mrr_val,
        "avg_gift":   avg_val,
        "median_gift":med_val,
        "retention":  ret,
        "churn_rate": (len(churn_s) / len(d_prev) * 100) if d_prev else None,
    })

snap = pd.DataFrame(monthly_snap)
snap_f = snap[snap["year"].isin(sel_years)]   # year-filtered for display

month_order = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
    "📊 1. MRR & Metrics",
    "🔄 2. Retention & Churn",
    "➕ 3. New vs. Churned",
    "🧱 4. Cohort Table",
    "💰 5. LTV",
    "📦 6. Gift Distribution",
    "🎯 7. Designations & Channels",
    "🏆 8. Top Donors by Cohort",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MRR & KEY METRICS
# ══════════════════════════════════════════════════════════════════════════════
with t1:
    st.subheader("MRR & Key Metrics")

    latest_m   = snap_f.iloc[-1]
    prev_m_row = snap_f.iloc[-2] if len(snap_f) > 1 else None

    total_mrr     = latest_m["mrr"]
    total_active  = latest_m["active"]
    avg_g         = latest_m["avg_gift"]
    med_g         = latest_m["median_gift"]
    cum_mrr       = snap_f["mrr"].sum()
    avg_active    = snap_f["active"].mean()

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Latest MRR",        fmt(total_mrr),
              delta=pct_delta(total_mrr, prev_m_row["mrr"]) if prev_m_row is not None else None)
    c2.metric("Active Subscribers", f"{int(total_active):,}",
              delta=pct_delta(total_active, prev_m_row["active"]) if prev_m_row is not None else None)
    c3.metric("Avg Monthly Gift",   fmt(avg_g))
    c4.metric("Median Monthly Gift",fmt(med_g))
    c5.metric("Cumulative MRR",     fmt(cum_mrr))
    c6.metric("Avg Active / Month", f"{avg_active:.0f}")

    st.divider()
    st.subheader("MRR Over Time")

    mrr_bar = alt.Chart(snap_f).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("mrr:Q", title="USD", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("year:O", scale=alt.Scale(scheme="tableau10"), title="Year"),
        tooltip=["month_str:O", alt.Tooltip("mrr:Q", format="$,.0f", title="MRR"),
                 alt.Tooltip("active:Q", title="Active")]
    ).properties(height=300)
    st.altair_chart(mrr_bar, use_container_width=True)

    st.divider()
    st.subheader("MRR — Year-over-Year by Month")
    yoy_mrr = alt.Chart(snap).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_label:O", sort=month_order, title="", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("mrr:Q", title="USD", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("year:O", scale=alt.Scale(scheme="tableau10"), title="Year"),
        tooltip=["year:O","month_label:O", alt.Tooltip("mrr:Q", format="$,.0f")]
    ).properties(height=300)
    st.altair_chart(yoy_mrr, use_container_width=True)

    st.divider()
    st.subheader("Active Subscribers Over Time")
    sub_line = alt.Chart(snap_f).mark_line(point=True, strokeWidth=2, color="#6366f1").encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("active:Q", title="Active Subscribers"),
        tooltip=["month_str:O", "active:Q"]
    ).properties(height=260)
    st.altair_chart(sub_line, use_container_width=True)

    st.divider()
    st.subheader("Avg & Median Gift Over Time")
    gift_m = snap_f.melt(id_vars="month_str", value_vars=["avg_gift","median_gift"],
                         var_name="Metric", value_name="USD")
    gift_m["Metric"] = gift_m["Metric"].map({"avg_gift":"Average","median_gift":"Median"})
    gift_line = alt.Chart(gift_m).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("USD:Q", title="USD", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Metric:N", scale=alt.Scale(range=["#6366f1","#f59e0b"])),
        tooltip=["month_str:O","Metric:N", alt.Tooltip("USD:Q", format="$,.2f")]
    ).properties(height=260)
    st.altair_chart(gift_line, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RETENTION & CHURN RATE
# ══════════════════════════════════════════════════════════════════════════════
with t2:
    st.subheader("Retention & Churn Rate")

    snap_ret = snap_f.dropna(subset=["retention"])
    avg_ret   = snap_ret["retention"].mean()
    avg_churn = snap_ret["churn_rate"].mean()
    best_ret  = snap_ret.loc[snap_ret["retention"].idxmax()]
    worst_ret = snap_ret.loc[snap_ret["retention"].idxmin()]

    r1,r2,r3,r4 = st.columns(4)
    r1.metric("Avg Monthly Retention", f"{avg_ret:.1f}%")
    r2.metric("Avg Monthly Churn",     f"{avg_churn:.1f}%")
    r3.metric("Best Month",  f"{best_ret['month_str']}",  help=f"{best_ret['retention']:.1f}% retention")
    r4.metric("Worst Month", f"{worst_ret['month_str']}", help=f"{worst_ret['retention']:.1f}% retention")

    st.divider()
    st.subheader("Monthly Retention Rate")
    ret_line = alt.Chart(snap_ret).mark_line(point=True, strokeWidth=2, color="#22c55e").encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("retention:Q", title="Retention %", scale=alt.Scale(domain=[0,100])),
        tooltip=["month_str:O", alt.Tooltip("retention:Q", format=".1f", title="Retention %")]
    ).properties(height=280)
    ref_line = alt.Chart(pd.DataFrame({"y":[80]})).mark_rule(
        color="#ef4444", strokeDash=[6,3], strokeWidth=1.5
    ).encode(y="y:Q")
    st.altair_chart(ret_line + ref_line, use_container_width=True)
    st.caption("Red dashed line = 80% retention benchmark.")

    st.divider()
    st.subheader("Monthly Churn Rate")
    churn_bar = alt.Chart(snap_ret).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("churn_rate:Q", title="Churn %"),
        color=alt.condition(
            alt.datum.churn_rate > 20,
            alt.value("#ef4444"),
            alt.value("#f59e0b")
        ),
        tooltip=["month_str:O", alt.Tooltip("churn_rate:Q", format=".1f", title="Churn %"),
                 alt.Tooltip("churned:Q", title="Donors churned")]
    ).properties(height=260)
    st.altair_chart(churn_bar, use_container_width=True)
    st.caption("Red = churn > 20%.")

    st.divider()
    st.subheader("Retention — Year-over-Year by Month")
    snap_ret2 = snap.dropna(subset=["retention"])
    yoy_ret = alt.Chart(snap_ret2).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_label:O", sort=month_order, title="", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("retention:Q", title="Retention %", scale=alt.Scale(domain=[0,100])),
        color=alt.Color("year:O", scale=alt.Scale(scheme="tableau10"), title="Year"),
        tooltip=["year:O","month_label:O", alt.Tooltip("retention:Q", format=".1f")]
    ).properties(height=280)
    st.altair_chart(yoy_ret, use_container_width=True)

    st.divider()
    st.subheader("Monthly Detail Table")
    tbl = snap_ret[["month_str","active","new","churned","retention","churn_rate","mrr"]].copy()
    tbl["retention"]  = tbl["retention"].apply(lambda x: f"{x:.1f}%")
    tbl["churn_rate"] = tbl["churn_rate"].apply(lambda x: f"{x:.1f}%")
    tbl["mrr"]        = tbl["mrr"].apply(fmt)
    tbl.columns       = ["Month","Active","New","Churned","Retention","Churn Rate","MRR"]
    st.dataframe(tbl, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — NEW vs. CHURNED SUBSCRIBERS
# ══════════════════════════════════════════════════════════════════════════════
with t3:
    st.subheader("New vs. Churned Subscribers per Month")

    # stacked bar: new (green) above x-axis, churned (red) below
    snap_nc = snap_f.copy()
    snap_nc["churned_neg"] = -snap_nc["churned"]

    pos = snap_nc[["month_str","new"]].rename(columns={"new":"count"})
    pos["Type"] = "New"
    neg = snap_nc[["month_str","churned_neg"]].rename(columns={"churned_neg":"count"})
    neg["Type"] = "Churned"
    nc_long = pd.concat([pos, neg])

    nc_bar = alt.Chart(nc_long).mark_bar().encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("count:Q", title="Subscribers",
                axis=alt.Axis(labelExpr="abs(datum.value)")),
        color=alt.Color("Type:N", scale=alt.Scale(
            domain=["New","Churned"], range=["#22c55e","#ef4444"])),
        tooltip=["month_str:O","Type:N",
                 alt.Tooltip("count:Q", title="Count")]
    ).properties(height=300)
    zero_line = alt.Chart(pd.DataFrame({"y":[0]})).mark_rule(
        color="#6b7280", strokeWidth=1
    ).encode(y="y:Q")
    st.altair_chart(nc_bar + zero_line, use_container_width=True)
    st.caption("Green bars above zero = new subscribers. Red bars below = churned. Net growth = green − red.")

    st.divider()
    st.subheader("Net Subscriber Growth per Month")
    snap_nc["net"] = snap_nc["new"] - snap_nc["churned"]
    net_bar = alt.Chart(snap_nc).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("month_str:O", sort=list(snap_f["month_str"]), title="",
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("net:Q", title="Net change"),
        color=alt.condition(alt.datum.net >= 0, alt.value("#22c55e"), alt.value("#ef4444")),
        tooltip=["month_str:O", alt.Tooltip("net:Q", title="Net growth"),
                 "new:Q","churned:Q"]
    ).properties(height=240)
    st.altair_chart(net_bar, use_container_width=True)

    st.divider()
    st.subheader("New Subscribers — Year-over-Year by Month")
    yoy_new = alt.Chart(snap).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_label:O", sort=month_order, title="", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("new:Q", title="New Subscribers"),
        color=alt.Color("year:O", scale=alt.Scale(scheme="tableau10"), title="Year"),
        tooltip=["year:O","month_label:O","new:Q"]
    ).properties(height=260)
    st.altair_chart(yoy_new, use_container_width=True)

    st.divider()
    new_total  = snap_f["new"].sum()
    churn_total= snap_f["churned"].sum()
    net_total  = new_total - churn_total
    n1,n2,n3   = st.columns(3)
    n1.metric("Total New Subscribers",    f"{int(new_total):,}")
    n2.metric("Total Churned",            f"{int(churn_total):,}")
    n3.metric("Net Subscriber Growth",    f"{int(net_total):+,}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — COHORT RETENTION TABLE
# ══════════════════════════════════════════════════════════════════════════════
with t4:
    st.subheader("Cohort Retention Table")
    st.caption("Each row = a cohort (month donors first subscribed). Each column = months since start (0,1,2…). Value = % of original cohort still active.")

    # build cohort table using full recurring data so cohorts aren't cut off
    df_cohort = df_all[df_all["is_recurring"]].copy()
    df_cohort["cohort_month"] = df_cohort.groupby("donor_key")["month_key"].transform("min")

    cohort_sizes = df_cohort.groupby("cohort_month")["donor_key"].nunique().rename("cohort_size")
    df_cohort = df_cohort.join(cohort_sizes, on="cohort_month")
    df_cohort["period_num"] = (
        df_cohort["month_key"].apply(lambda x: x.ordinal) -
        df_cohort["cohort_month"].apply(lambda x: x.ordinal)
    )

    cohort_pivot = (
        df_cohort.groupby(["cohort_month","period_num"])["donor_key"]
        .nunique()
        .reset_index()
    )
    cohort_pivot = cohort_pivot.join(cohort_sizes, on="cohort_month")
    cohort_pivot["pct"] = cohort_pivot["donor_key"] / cohort_pivot["cohort_size"] * 100

    cohort_table = cohort_pivot.pivot(
        index="cohort_month", columns="period_num", values="pct"
    )
    cohort_table.index = cohort_table.index.astype(str)

    # Limit to max 24 periods for readability
    max_cols = min(24, cohort_table.shape[1])
    cohort_table = cohort_table.iloc[:, :max_cols]
    cohort_table.columns = [f"M+{c}" for c in cohort_table.columns]

    # filter to selected years only
    cohort_table = cohort_table[
        cohort_table.index.str[:4].astype(int).isin(sel_years)
    ]

    # style: colour by retention %
    def style_cohort(val):
        if pd.isna(val): return "background-color: #1f2937; color: #374151;"
        if val >= 90:    return "background-color: #14532d; color: #bbf7d0;"
        if val >= 75:    return "background-color: #166534; color: #dcfce7;"
        if val >= 60:    return "background-color: #854d0e; color: #fef9c3;"
        if val >= 40:    return "background-color: #7c2d12; color: #ffedd5;"
        return                  "background-color: #450a0a; color: #fecaca;"

    styled = cohort_table.style.map(style_cohort).format(
        lambda v: f"{v:.0f}%" if not pd.isna(v) else ""
    )
    st.dataframe(styled, use_container_width=True)
    st.caption("🟢 ≥90%  🟡 75–90%  🟠 60–75%  🔴 <60%  ⬛ no data")

    st.divider()
    st.subheader("Cohort Size at Start")
    cs = cohort_sizes.reset_index()
    cs["cohort_str"] = cs["cohort_month"].astype(str)
    cs = cs[cs["cohort_str"].str[:4].astype(int).isin(sel_years)]
    cs_bar = alt.Chart(cs).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("cohort_str:O", title="Cohort Month", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("cohort_size:Q", title="Donors in Cohort"),
        tooltip=["cohort_str:O","cohort_size:Q"]
    ).properties(height=240)
    st.altair_chart(cs_bar, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — LTV ESTIMATES
# ══════════════════════════════════════════════════════════════════════════════
with t5:
    st.subheader("Lifetime Value (LTV) Estimates")
    st.caption("LTV = total amount donated by each recurring donor across all time. Avg LTV uses avg monthly gift × estimated avg lifespan.")

    # Per-donor LTV (total paid since first recurring donation)
    ltv_df = df.groupby(["donor_key","donor_name","cohort_month","cohort_year"]).agg(
        total_paid   = ("amount","sum"),
        months_active= ("month_key","nunique"),
        avg_gift     = ("amount","mean"),
        first_month  = ("month_key","min"),
        last_month   = ("month_key","max"),
    ).reset_index()
    ltv_df["est_lifespan_mo"] = ltv_df["months_active"]  # actual observed lifespan

    overall_avg_ltv    = ltv_df["total_paid"].mean()
    overall_med_ltv    = ltv_df["total_paid"].median()
    overall_avg_life   = ltv_df["months_active"].mean()
    top10_ltv          = ltv_df.nlargest(10, "total_paid")

    l1,l2,l3,l4 = st.columns(4)
    l1.metric("Avg LTV per Donor",    fmt(overall_avg_ltv))
    l2.metric("Median LTV per Donor", fmt(overall_med_ltv))
    l3.metric("Avg Active Lifespan",  f"{overall_avg_life:.1f} months")
    l4.metric("Total Unique Donors",  f"{len(ltv_df):,}")

    st.divider()
    st.subheader("LTV Distribution")
    BRACKETS = [0,100,250,500,1000,2500,5000,float("inf")]
    LABELS   = ["$0–100","$100–250","$250–500","$500–1k","$1k–2.5k","$2.5k–5k","$5k+"]
    ltv_df["ltv_bracket"] = pd.cut(ltv_df["total_paid"], bins=BRACKETS, labels=LABELS, right=False)
    ltv_dist = ltv_df.groupby("ltv_bracket", observed=True).size().reset_index(name="Donors")
    ltv_bar = alt.Chart(ltv_dist).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("ltv_bracket:O", sort=LABELS, title="LTV Bracket", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("Donors:Q"),
        tooltip=["ltv_bracket:O","Donors:Q"]
    ).properties(height=260)
    st.altair_chart(
        ltv_bar + ltv_bar.mark_text(dy=-8, fontSize=10).encode(text="Donors:Q"),
        use_container_width=True
    )

    st.divider()
    st.subheader("Avg LTV by Cohort Year")
    ltv_by_year = ltv_df.groupby("cohort_year").agg(
        avg_ltv    = ("total_paid","mean"),
        median_ltv = ("total_paid","median"),
        donors     = ("donor_key","nunique"),
    ).reset_index().sort_values("cohort_year")
    ly_bar = alt.Chart(ltv_by_year).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("cohort_year:O", title="Cohort Year"),
        y=alt.Y("avg_ltv:Q", title="Avg LTV (USD)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("cohort_year:O", scale=alt.Scale(scheme="tableau10"), legend=None),
        tooltip=["cohort_year:O",
                 alt.Tooltip("avg_ltv:Q", format="$,.0f", title="Avg LTV"),
                 alt.Tooltip("median_ltv:Q", format="$,.0f", title="Median LTV"),
                 "donors:Q"]
    ).properties(height=260)
    st.altair_chart(
        ly_bar + ly_bar.mark_text(dy=-8, fontSize=10).encode(text=alt.Text("avg_ltv:Q", format="$,.0f")),
        use_container_width=True
    )

    st.divider()
    st.subheader("Avg LTV by Cohort Month")
    ltv_by_cohort = ltv_df.groupby("cohort_month").agg(
        avg_ltv=("total_paid","mean"),
        donors =("donor_key","nunique"),
    ).reset_index()
    ltv_by_cohort["cohort_str"] = ltv_by_cohort["cohort_month"].astype(str)
    lc_line = alt.Chart(ltv_by_cohort).mark_line(point=True, strokeWidth=2, color="#6366f1").encode(
        x=alt.X("cohort_str:O", title="Cohort Month", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("avg_ltv:Q", title="Avg LTV (USD)", axis=alt.Axis(format="$,.0f")),
        tooltip=["cohort_str:O", alt.Tooltip("avg_ltv:Q", format="$,.0f"), "donors:Q"]
    ).properties(height=260)
    st.altair_chart(lc_line, use_container_width=True)

    st.divider()
    st.subheader("Top 10 Donors by LTV")
    top10_display = top10_ltv[["donor_name","cohort_year","total_paid","months_active","avg_gift"]].copy()
    top10_display["total_paid"] = top10_display["total_paid"].apply(fmt)
    top10_display["avg_gift"]   = top10_display["avg_gift"].apply(fmt)
    top10_display.columns = ["Donor","Cohort Year","Total Paid","Months Active","Avg Gift"]
    st.dataframe(top10_display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — GIFT SIZE DISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════════
with t6:
    st.subheader("Gift Size Distribution")

    BRACKETS = [0,25,50,100,250,500,1000,float("inf")]
    LABELS   = ["$0–25","$25–50","$50–100","$100–250","$250–500","$500–1k","$1k+"]
    df["bracket"] = pd.cut(df["amount"], bins=BRACKETS, labels=LABELS, right=False)

    g1,g2 = st.columns(2)

    with g1:
        st.caption("By number of transactions")
        dist_txn = df.groupby("bracket", observed=True).size().reset_index(name="Transactions")
        b_txn = alt.Chart(dist_txn).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("bracket:O", sort=LABELS, title="", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("Transactions:Q"),
            tooltip=["bracket:O","Transactions:Q"]
        ).properties(height=280)
        st.altair_chart(b_txn + b_txn.mark_text(dy=-8, fontSize=9).encode(text="Transactions:Q"),
                        use_container_width=True)

    with g2:
        st.caption("By unique donors")
        dist_don = df.groupby("bracket", observed=True)["donor_key"].nunique().reset_index(name="Donors")
        b_don = alt.Chart(dist_don).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("bracket:O", sort=LABELS, title="", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("Donors:Q"),
            tooltip=["bracket:O","Donors:Q"]
        ).properties(height=280)
        st.altair_chart(b_don + b_don.mark_text(dy=-8, fontSize=9).encode(text="Donors:Q"),
                        use_container_width=True)

    st.divider()
    st.subheader("Gift Size — Year-over-Year Distribution")
    dist_yoy = df.groupby(["year","bracket"], observed=True).size().reset_index(name="Transactions")
    dist_yoy["year"] = dist_yoy["year"].astype(str)
    dist_yoy_bar = alt.Chart(dist_yoy).mark_bar().encode(
        x=alt.X("bracket:O", sort=LABELS, title="", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("Transactions:Q"),
        color=alt.Color("year:N", scale=alt.Scale(scheme="tableau10"), title="Year"),
        xOffset="year:N",
        tooltip=["year:N","bracket:O","Transactions:Q"]
    ).properties(height=280)
    st.altair_chart(dist_yoy_bar, use_container_width=True)

    st.divider()
    st.subheader("Avg Gift Over Time — Year-over-Year")
    yoy_avg = snap.copy()
    yoy_avg_chart = alt.Chart(yoy_avg).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_label:O", sort=month_order, title="", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("avg_gift:Q", title="Avg Gift (USD)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("year:O", scale=alt.Scale(scheme="tableau10"), title="Year"),
        tooltip=["year:O","month_label:O", alt.Tooltip("avg_gift:Q", format="$,.2f")]
    ).properties(height=260)
    st.altair_chart(yoy_avg_chart, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — DESIGNATIONS & CHANNELS
# ══════════════════════════════════════════════════════════════════════════════
with t7:
    st.subheader("Revenue by Designation")

    desig = df.groupby("designation_label").agg(
        revenue    = ("amount","sum"),
        donors     = ("donor_key","nunique"),
        txns       = ("amount","count"),
        avg_gift   = ("amount","mean"),
    ).sort_values("revenue", ascending=False).reset_index()
    total_rev = desig["revenue"].sum()
    desig["% Rev"] = (desig["revenue"] / total_rev * 100).apply(lambda x: f"{x:.1f}%")

    if len(desig):
        top3_pct = desig.head(3)["revenue"].sum() / total_rev * 100
        st.info(f"📌 Top: **{desig.iloc[0]['designation_label']}** ({desig.iloc[0]['% Rev']}). Top 3 = {top3_pct:.0f}% of recurring revenue.")

    desig_display = desig.copy()
    desig_display["revenue"] = desig_display["revenue"].apply(fmt)
    desig_display["avg_gift"]= desig_display["avg_gift"].apply(fmt)
    st.dataframe(
        desig_display[["designation_label","revenue","% Rev","donors","txns","avg_gift"]].rename(columns={
            "designation_label":"Designation","revenue":"Revenue",
            "donors":"Donors","txns":"Txns","avg_gift":"Avg Gift"
        }),
        use_container_width=True, hide_index=True
    )

    st.subheader("Designation Revenue — Year-over-Year by Month")
    top5_d = desig.head(5)["designation_label"].tolist()
    desig_time = df[df["designation_label"].isin(top5_d)].copy()
    desig_time = desig_time.groupby(["month_num","month_label","year","designation_label"])["amount"].sum().reset_index()
    desig_time["year"] = desig_time["year"].astype(str)
    desig_yoy = alt.Chart(desig_time).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("month_label:O", sort=month_order, title="", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("amount:Q", title="USD", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("year:N", scale=alt.Scale(scheme="tableau10"), title="Year"),
        strokeDash=alt.StrokeDash("designation_label:N", title="Designation"),
        tooltip=["year:N","month_label:O","designation_label:N", alt.Tooltip("amount:Q", format="$,.0f")]
    ).properties(height=300)
    st.altair_chart(desig_yoy, use_container_width=True)
    st.caption("Top 5 designations. Line style = designation, colour = year.")

    st.divider()
    st.subheader("Revenue by Payment Platform")
    if "platform" in df.columns:
        plat = df.groupby(df["platform"].fillna("(unknown)")).agg(
            revenue=("amount","sum"),
            donors =("donor_key","nunique"),
            txns   =("amount","count"),
        ).sort_values("revenue", ascending=False).reset_index()
        plat["% Rev"]   = (plat["revenue"] / plat["revenue"].sum() * 100).apply(lambda x: f"{x:.1f}%")
        plat["revenue"] = plat["revenue"].apply(fmt)
        st.dataframe(
            plat[["platform","revenue","% Rev","donors","txns"]].rename(columns={
                "platform":"Platform","revenue":"Revenue","donors":"Donors","txns":"Txns"
            }),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("No payment platform column found.")

    st.divider()
    st.subheader("Revenue by Source / Channel")
    if "source" in df.columns:
        ch = df.groupby(df["source"].fillna("(no source)")).agg(
            revenue=("amount","sum"),
            donors =("donor_key","nunique"),
            txns   =("amount","count"),
        ).sort_values("revenue", ascending=False).reset_index()
        ch["% Rev"]   = (ch["revenue"] / ch["revenue"].sum() * 100).apply(lambda x: f"{x:.1f}%")
        ch["revenue"] = ch["revenue"].apply(fmt)
        st.dataframe(
            ch[["source","revenue","% Rev","donors","txns"]].rename(columns={
                "source":"Channel","revenue":"Revenue","donors":"Donors","txns":"Txns"
            }),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("No source column found.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — TOP DONORS BY COHORT
# ══════════════════════════════════════════════════════════════════════════════
with t8:
    st.subheader("Top Donors by Cohort")
    st.caption("Select a cohort (month of first recurring donation) to see its top contributors by total recurring revenue.")

    # cohort picker
    cohort_months_avail = sorted(df["cohort_month"].dropna().unique())
    cohort_labels = [str(c) for c in cohort_months_avail]

    col_a, col_b = st.columns([2,1])
    with col_a:
        sel_cohort_label = st.selectbox("Select cohort:", cohort_labels, index=len(cohort_labels)-1)
    with col_b:
        top_n = st.number_input("Show top N donors:", min_value=5, max_value=50, value=10, step=5)

    sel_cohort = cohort_months_avail[cohort_labels.index(sel_cohort_label)]

    cohort_donors = df[df["cohort_month"] == sel_cohort].groupby(
        ["donor_key","donor_name"]
    ).agg(
        total_paid    = ("amount","sum"),
        months_active = ("month_key","nunique"),
        avg_gift      = ("amount","mean"),
        first_txn     = ("date","min"),
        last_txn      = ("date","max"),
        designation   = ("designation_label", lambda x: x.mode()[0] if len(x) else "—"),
        platform      = ("platform", lambda x: x.mode()[0] if "platform" in df.columns and len(x) else "—"),
    ).reset_index().sort_values("total_paid", ascending=False).head(top_n)

    cohort_size = df[df["cohort_month"] == sel_cohort]["donor_key"].nunique()
    cohort_mrr  = df[df["cohort_month"] == sel_cohort]["amount"].sum()
    cohort_avg_ltv = cohort_donors["total_paid"].mean()

    ca, cb, cc = st.columns(3)
    ca.metric("Cohort Size",     f"{cohort_size:,} donors")
    cb.metric("Total Revenue",   fmt(cohort_mrr))
    cc.metric("Avg LTV in Cohort", fmt(cohort_avg_ltv))

    # bar chart
    bar_top = alt.Chart(cohort_donors).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("total_paid:Q", title="Total Paid (USD)", axis=alt.Axis(format="$,.0f")),
        y=alt.Y("donor_name:O", sort="-x", title=""),
        color=alt.Color("designation:N", scale=alt.Scale(scheme="tableau10"), title="Designation"),
        tooltip=["donor_name:O", alt.Tooltip("total_paid:Q", format="$,.0f", title="Total Paid"),
                 "months_active:Q", alt.Tooltip("avg_gift:Q", format="$,.0f")]
    ).properties(height=max(250, top_n * 28))
    st.altair_chart(bar_top, use_container_width=True)

    # detail table
    cohort_display = cohort_donors.copy()
    cohort_display["total_paid"] = cohort_display["total_paid"].apply(fmt)
    cohort_display["avg_gift"]   = cohort_display["avg_gift"].apply(fmt)
    cohort_display["first_txn"]  = cohort_display["first_txn"].dt.strftime("%Y-%m-%d")
    cohort_display["last_txn"]   = cohort_display["last_txn"].dt.strftime("%Y-%m-%d")
    cohort_display = cohort_display[[
        "donor_name","total_paid","months_active","avg_gift",
        "first_txn","last_txn","designation","platform"
    ]].rename(columns={
        "donor_name":"Donor","total_paid":"Total Paid",
        "months_active":"Months Active","avg_gift":"Avg Gift",
        "first_txn":"First Txn","last_txn":"Last Txn",
        "designation":"Top Designation","platform":"Platform"
    })
    st.dataframe(cohort_display, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("All Cohorts — Top Donor Summary")
    st.caption("Best donor (by total paid) per cohort across all cohorts.")

    top_per_cohort = df.groupby(["cohort_month","donor_key","donor_name"]).agg(
        total_paid=("amount","sum"),
        months_active=("month_key","nunique"),
    ).reset_index()
    top_per_cohort = top_per_cohort.sort_values("total_paid", ascending=False)\
                                   .groupby("cohort_month").first().reset_index()
    top_per_cohort["cohort_str"] = top_per_cohort["cohort_month"].astype(str)
    top_per_cohort["total_paid_fmt"] = top_per_cohort["total_paid"].apply(fmt)
    top_per_cohort = top_per_cohort.sort_values("cohort_month")

    st.dataframe(
        top_per_cohort[["cohort_str","donor_name","total_paid_fmt","months_active"]].rename(columns={
            "cohort_str":"Cohort","donor_name":"Top Donor",
            "total_paid_fmt":"Total Paid","months_active":"Months Active"
        }),
        use_container_width=True, hide_index=True
    )
