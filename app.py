import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Pallet Loading Optimizer", layout="wide")
st.title("Pallet Loading Optimizer")

# --- Constants ---
MAX_HEIGHT_MM = 1200
FIRST_LADDER_MM = 50
NESTED_ADDITION_MM = 25
max_per_stack = int((MAX_HEIGHT_MM - FIRST_LADDER_MM) / NESTED_ADDITION_MM) + 1

# Step count → color
STEP_COLORS = {
    2:  "#a8d8ea",
    3:  "#57a0d3",
    4:  "#2166ac",
    5:  "#1a6b4a",
    6:  "#4dac26",
    7:  "#f4a736",
    8:  "#d73027",
    9:  "#7b2d8b",
    10: "#404040",
}

def step_color(steps):
    return STEP_COLORS.get(steps, "#888888")

# --- File Upload ---
uploaded_file = st.file_uploader("Upload Order Excel / CSV file", type=["xlsx", "xls", "csv"])

if uploaded_file:
    try:
        # 1. Read file
        if uploaded_file.name.endswith(".csv"):
            try:
                df = pd.read_csv(uploaded_file, header=None, encoding="utf-8")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=None, encoding="cp1250")
        else:
            df = pd.read_excel(uploaded_file, header=None)

        # 2. Find "Zakázka" header row
        zakazka_row_index = -1
        for index in range(min(15, len(df))):
            row_text = df.iloc[index].tolist()
            if any("zak" in str(text).lower() for text in row_text):
                zakazka_row_index = index
                break

        if zakazka_row_index == -1:
            st.error("Could not find the order ('Zakázka') header row in the first 15 rows.")
            st.stop()

        # 3. Find steps column dynamically — look for "Poč.př." / "Počet příček"
        # in the rows around the Zakázka header. Skip totals like "Celkem příček".
        steps_col_index = None
        search_end = min(len(df), zakazka_row_index + 4)
        for r in range(zakazka_row_index, search_end):
            for col_idx in range(len(df.columns)):
                val = str(df.iloc[r, col_idx]).lower().strip()
                if val in ("nan", ""):
                    continue
                if "celk" in val:  # skip total columns like "Celkem příček"
                    continue
                if "poč" in val or "příč" in val or val.startswith("step"):
                    steps_col_index = col_idx
                    break
            if steps_col_index is not None:
                break
        # Fallback
        if steps_col_index is None:
            steps_col_index = 2

        # 4. Extract order columns (skip header/total columns and the steps column)
        order_columns = {}
        for col_idx in range(len(df.columns)):
            if col_idx == steps_col_index:
                continue
            val = str(df.iloc[zakazka_row_index, col_idx]).strip()
            if (
                val.lower() not in ["nan", "", "zakázka", "celkem", "celkem příček"]
                and "zak" not in val.lower()
                and "příč" not in val.lower()
                and "celk" not in val.lower()
            ):
                order_columns[col_idx] = val

        if not order_columns:
            st.error("No order columns found in the header row.")
            st.stop()

        # 5. Parse rows
        orders_dict = {}
        loose_ladders = []

        for row_idx in range(zakazka_row_index + 1, len(df)):
            steps_val = df.iloc[row_idx, steps_col_index]
            try:
                steps = float(steps_val)
                if pd.isna(steps):
                    continue
            except (ValueError, TypeError):
                continue

            for col_idx, order_name in order_columns.items():
                qty_val = df.iloc[row_idx, col_idx]
                try:
                    qty = int(float(qty_val))
                    if qty > 0:
                        if steps == 2:
                            loose_ladders.append({"Order": order_name, "Steps": 2, "Quantity": qty})
                        else:
                            if order_name not in orders_dict:
                                orders_dict[order_name] = []
                            while qty > 0:
                                pack_size = min(qty, 5)
                                orders_dict[order_name].append({
                                    "Order": order_name,
                                    "Steps": int(steps),
                                    "Size": pack_size,
                                })
                                qty -= pack_size
                except (ValueError, TypeError):
                    pass

        # 6. Pallet packing — iterate orders in file column order (left → right)
        pallets = []

        ordered_order_names = []
        seen = set()
        for col_idx in sorted(order_columns.keys()):
            name = order_columns[col_idx]
            if name in orders_dict and name not in seen:
                ordered_order_names.append(name)
                seen.add(name)
        # Append any orders that only appeared as loose ladders or were missed
        for name in orders_dict.keys():
            if name not in seen:
                ordered_order_names.append(name)
                seen.add(name)

        for order_name in ordered_order_names:
            pack_list = orders_dict[order_name]
            # Longest ladders (biggest step count) on the bottom
            pack_list.sort(key=lambda x: (x["Steps"], x["Size"]), reverse=True)

            state = {"L": [], "M": [], "R": []}

            def try_place(pack):
                size = pack["Size"]
                item = {"Order": pack["Order"], "Steps": pack["Steps"]}

                candidates = []
                if len(state["L"]) + size <= max_per_stack:
                    candidates.append(("L", len(state["L"])))
                if len(state["R"]) + size <= max_per_stack:
                    candidates.append(("R", len(state["R"])))
                # Middle may grow only while it stays ≤ shorter side after placement
                min_side = min(len(state["L"]), len(state["R"]))
                if (len(state["M"]) + size <= min_side
                        and len(state["M"]) + size <= max_per_stack):
                    candidates.append(("M", len(state["M"])))

                if not candidates:
                    return False

                # Place in the shortest candidate; sides preferred over middle on ties
                candidates.sort(key=lambda c: (c[1], c[0] == "M"))
                target_name = candidates[0][0]
                for _ in range(size):
                    state[target_name].append(item)
                return True

            def close_pallet():
                # Equalize L and R; push excess into M when it still fits,
                # otherwise return as carry-over for the next pallet.
                excess = []
                while len(state["L"]) != len(state["R"]):
                    if len(state["L"]) > len(state["R"]):
                        item = state["L"].pop()
                    else:
                        item = state["R"].pop()
                    new_min = min(len(state["L"]), len(state["R"]))
                    if len(state["M"]) < new_min and len(state["M"]) < max_per_stack:
                        state["M"].append(item)
                    else:
                        excess.append(item)

                if state["L"] or state["M"] or state["R"]:
                    pallets.append({
                        "L": state["L"], "M": state["M"], "R": state["R"],
                        "Order": order_name,
                    })
                state["L"], state["M"], state["R"] = [], [], []
                return excess

            pending = list(pack_list)
            while pending:
                pack = pending.pop(0)
                if not try_place(pack):
                    carry = close_pallet()
                    # Re-queue carry-over as size-1 packs at the front
                    for it in carry:
                        pending.insert(0, {"Order": it["Order"], "Steps": it["Steps"], "Size": 1})
                    if not try_place(pack):
                        # Pack too large for empty pallet (size > max) — split
                        for _ in range(pack["Size"]):
                            try_place({"Order": pack["Order"], "Steps": pack["Steps"], "Size": 1})

            # Final flush — may take multiple passes if carry-over keeps appearing
            safety = 0
            while True:
                carry = close_pallet()
                if not carry:
                    break
                for it in carry:
                    try_place({"Order": it["Order"], "Steps": it["Steps"], "Size": 1})
                safety += 1
                if safety > 20:
                    break

        # 7. Helper: group a raw stack list into packs
        def get_packs(stack):
            if not stack:
                return []
            res = []
            curr = {"Order": stack[0]["Order"], "Steps": stack[0]["Steps"], "Count": 1}
            for i in range(1, len(stack)):
                if stack[i] == stack[i - 1] and curr["Count"] < 5:
                    curr["Count"] += 1
                else:
                    res.append(curr)
                    curr = {"Order": stack[i]["Order"], "Steps": stack[i]["Steps"], "Count": 1}
            res.append(curr)
            return res

        # 8. Helper: build a plotly brick-layout figure for one pallet
        # One brick per PACK; brick HEIGHT = pack count (so 5x is 5x taller than 1x)
        def pallet_figure(p, pack_getter):
            UNIT_H  = 1.0       # height per ladder
            BLOCK_W = 0.85
            GAP     = 0.15      # gap between bricks (in ladder-units)

            stack_labels = ["LEFT", "MIDDLE", "RIGHT"]
            stack_packs  = [pack_getter(p["L"]), pack_getter(p["M"]), pack_getter(p["R"])]
            x_centers    = [0.5, 1.5, 2.5]

            shapes = []
            annotations = []
            legend_seen = set()
            legend_traces = []

            max_total_height = 0

            for x_center, packs in zip(x_centers, stack_packs):
                x0 = x_center - BLOCK_W / 2
                x1 = x_center + BLOCK_W / 2

                y_cursor = 0.0
                for pack in packs:  # bottom → top
                    h = pack["Count"] * UNIT_H
                    y0 = y_cursor
                    y1 = y0 + h
                    y_cursor = y1 + GAP

                    color = step_color(pack["Steps"])
                    shapes.append(dict(
                        type="rect",
                        x0=x0, x1=x1, y0=y0, y1=y1,
                        fillcolor=color,
                        line=dict(color="white", width=2),
                        layer="below",
                    ))
                    annotations.append(dict(
                        x=x_center, y=(y0 + y1) / 2,
                        text=f"<b>{pack['Count']}x {pack['Steps']}-step</b>",
                        showarrow=False,
                        font=dict(color="white", size=16, family="Arial"),
                        xanchor="center", yanchor="middle",
                    ))

                    if pack["Steps"] not in legend_seen:
                        legend_seen.add(pack["Steps"])
                        legend_traces.append(go.Scatter(
                            x=[None], y=[None],
                            mode="markers",
                            marker=dict(size=16, color=color, symbol="square"),
                            name=f"{pack['Steps']}-step",
                            showlegend=True,
                        ))

                max_total_height = max(max_total_height, y_cursor)

            if max_total_height == 0:
                max_total_height = 1

            fig_height = max(360, int(max_total_height * 28 + 120))

            fig = go.Figure(data=sorted(legend_traces, key=lambda t: int(t.name.split("-")[0])))
            fig.update_layout(
                shapes=shapes,
                annotations=annotations,
                height=fig_height,
                margin=dict(l=10, r=10, t=50, b=40),
                xaxis=dict(
                    tickvals=x_centers,
                    ticktext=[f"<b>{l}</b>" for l in stack_labels],
                    tickfont=dict(size=14),
                    range=[0, 3],
                    showgrid=False, zeroline=False,
                ),
                yaxis=dict(
                    showgrid=False, zeroline=False,
                    showticklabels=False,
                    range=[-0.5, max_total_height + 0.5],
                ),
                legend=dict(
                    title="Step type", orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1,
                ),
                plot_bgcolor="#fafafa",
                paper_bgcolor="#fafafa",
            )
            return fig

        # 9. Display results
        st.success(f"Packing complete — {len(pallets)} pallets generated.")

        # --- Filter bar ---
        all_orders = sorted({p["Order"] for p in pallets})
        col_search, col_select = st.columns([2, 3])
        with col_search:
            search_text = st.text_input("Search order", placeholder="Type order name…")
        with col_select:
            selected_orders = st.multiselect("Filter by order", options=all_orders, default=[])

        def pallet_visible(p):
            if search_text and search_text.lower() not in p["Order"].lower():
                return False
            if selected_orders and p["Order"] not in selected_orders:
                return False
            return True

        visible_pallets = [(i, p) for i, p in enumerate(pallets) if pallet_visible(p)]
        if not visible_pallets:
            st.warning("No pallets match the current filter.")

        for p_idx, p in visible_pallets:
            l_packs = get_packs(p["L"])
            m_packs = get_packs(p["M"])
            r_packs = get_packs(p["R"])

            with st.expander(f"Pallet #{p_idx + 1}  —  Order: {p['Order']}", expanded=False):

                # --- Visual chart ---
                st.plotly_chart(pallet_figure(p, get_packs), use_container_width=True, key=f"chart_{p_idx}")

                # --- Text table map ---
                max_d = max(len(l_packs), len(m_packs), len(r_packs), 1)
                rev_l = list(reversed(l_packs))
                rev_m = list(reversed(m_packs))
                rev_r = list(reversed(r_packs))

                def fmt(lst, i, total):
                    offset = total - len(lst)
                    if i >= offset:
                        pk = lst[i - offset]
                        return f"{pk['Count']}x {pk['Steps']}-step"
                    return ""

                visual_rows = [
                    {
                        "LEFT":   fmt(rev_l, i, max_d),
                        "MIDDLE": fmt(rev_m, i, max_d),
                        "RIGHT":  fmt(rev_r, i, max_d),
                    }
                    for i in range(max_d)
                ]
                with st.expander("Text map (top → bottom)", expanded=False):
                    st.table(pd.DataFrame(visual_rows))

                # --- Loading instructions ---
                st.markdown("**Loading Instructions** (load bottom to top)")
                cols = st.columns(3)
                for col, label, packs, stack_key in zip(
                    cols,
                    ["LEFT", "MIDDLE", "RIGHT"],
                    [l_packs, m_packs, r_packs],
                    ["L", "M", "R"],
                ):
                    with col:
                        total = len(p[stack_key])
                        st.markdown(f"**{label}** ({total} ladders)")
                        if packs:
                            for i, pk in enumerate(packs):
                                note = " ← bottom" if i == 0 else ""
                                st.write(f"{i+1}. {pk['Count']}x {pk['Steps']}-step{note}")
                        else:
                            st.write("—")

        # 10. Loose ladders
        if loose_ladders:
            st.markdown("---")
            st.markdown("### Loose Ladders (2-step) — place anywhere")
            loose_dict = {}
            for item in loose_ladders:
                loose_dict[item["Order"]] = loose_dict.get(item["Order"], 0) + item["Quantity"]
            for order_name, qty in loose_dict.items():
                st.write(f"- **{qty}x** 2-step ladders  (Order: {order_name})")

    except Exception as e:
        st.error(f"Error processing file: {e}")
