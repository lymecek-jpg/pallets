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

        # 3. Find steps column dynamically — look for "příč" in the header row
        steps_col_index = None
        for col_idx in range(len(df.columns)):
            val = str(df.iloc[zakazka_row_index, col_idx]).lower()
            if "příč" in val or "step" in val or "pricel" in val or "pric" in val:
                steps_col_index = col_idx
                break
        # Fallback to column 2 if not found
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

        # 6. Pallet packing
        pallets = []

        for order_name, pack_list in orders_dict.items():
            pack_list.sort(key=lambda x: (x["Steps"], x["Size"]), reverse=True)
            current_left, current_mid, current_right = [], [], []

            for pack in pack_list:
                stacks = [("L", current_left), ("R", current_right), ("M", current_mid)]
                stacks.sort(key=lambda x: (len(x[1]), x[0] == "M"))

                placed = False
                for name, stack in stacks:
                    if len(stack) + pack["Size"] <= max_per_stack:
                        for _ in range(pack["Size"]):
                            stack.append({"Order": pack["Order"], "Steps": pack["Steps"]})
                        placed = True
                        break

                if not placed:
                    pallets.append({"L": current_left, "M": current_mid, "R": current_right, "Order": order_name})
                    current_left, current_mid, current_right = [], [], []
                    for _ in range(pack["Size"]):
                        current_left.append({"Order": pack["Order"], "Steps": pack["Steps"]})

            if current_left or current_mid or current_right:
                pallets.append({"L": current_left, "M": current_mid, "R": current_right, "Order": order_name})

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

        # 8. Helper: build a plotly figure for one pallet
        def pallet_figure(p):
            stack_labels = ["LEFT", "MIDDLE", "RIGHT"]
            stack_data   = [p["L"], p["M"], p["R"]]

            # Collect all unique step counts across this pallet for legend
            all_steps = sorted({item["Steps"] for stack in stack_data for item in stack}, reverse=True)

            # For each step count, build one bar trace (one segment per stack)
            traces = {}
            for steps in all_steps:
                traces[steps] = {"x": [], "y": [], "text": []}

            for label, stack in zip(stack_labels, stack_data):
                # Count ladders per step type in this stack (bottom → top order)
                step_counts = {}
                for item in stack:
                    step_counts[item["Steps"]] = step_counts.get(item["Steps"], 0) + 1
                for steps in all_steps:
                    count = step_counts.get(steps, 0)
                    traces[steps]["x"].append(label)
                    traces[steps]["y"].append(count)
                    traces[steps]["text"].append(f"{count}x {steps}-step" if count else "")

            fig = go.Figure()
            for steps in all_steps:
                t = traces[steps]
                fig.add_trace(go.Bar(
                    name=f"{steps}-step",
                    x=t["x"],
                    y=t["y"],
                    text=t["text"],
                    textposition="inside",
                    insidetextanchor="middle",
                    marker_color=step_color(steps),
                    marker_line_color="white",
                    marker_line_width=1.5,
                    hovertemplate="%{text}<extra></extra>",
                ))

            fig.update_layout(
                barmode="stack",
                height=380,
                margin=dict(l=20, r=20, t=30, b=20),
                legend=dict(title="Step count", orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="Ladders", dtick=5),
                xaxis=dict(title="Stack position"),
                plot_bgcolor="#fafafa",
                paper_bgcolor="#fafafa",
            )
            # Draw max capacity line
            fig.add_hline(
                y=max_per_stack,
                line_dash="dash",
                line_color="red",
                annotation_text=f"Max ({max_per_stack})",
                annotation_position="top right",
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

            with st.expander(f"Pallet #{p_idx + 1}  —  Order: {p['Order']}", expanded=True):

                # --- Visual chart ---
                st.plotly_chart(pallet_figure(p), use_container_width=True, key=f"chart_{p_idx}")

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
