import streamlit as st
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import uuid
import datetime

# === CONFIG ===
DIMENSIONS = [
    "Originality", "Elaboration", "Clarity", "Coherence",
    "Semantic Density", "Not a Summary", "Engagement", "Overall"
]
PROMPTS_PER_ANNOTATOR = 2

# === Load JSON paragraph data ===
@st.cache_data
def load_data():
    with open("./annotations_fic.json", "r") as f:
        fic_paras = json.load(f)
    with open("./annotations_non.json", "r") as f:
        non_paras = json.load(f)
    return fic_paras, non_paras

# === Google Sheets setup ===
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
# Load credentials from Streamlit secrets
gcp_creds = st.secrets["gcp"]
# Create credentials from dict (no local file needed)
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, SCOPE)
# Authorize and open sheet
CLIENT = gspread.authorize(CREDS)
SHEET = CLIENT.open("creative_writing_annotations").sheet1


# === Deterministic prompt assignment ===
def get_assigned_prompts(annotator_id, prompt_keys):
    id_int = int(annotator_id)
    start = (id_int - 1) * PROMPTS_PER_ANNOTATOR
    return prompt_keys[start : start + PROMPTS_PER_ANNOTATOR]

# === Save annotations (overwrite if same session_id exists) ===
def save_all_annotations(annotator_id, session_id, all_data):
    serializable_data = {
        f"{k[0]}__{k[1]}": v for k, v in all_data.items()
    }
    json_data = json.dumps(serializable_data)
    timestamp = datetime.datetime.now().isoformat()

    records = SHEET.get_all_records()
    rows = SHEET.get_all_values()

    row_index = None
    for idx, row in enumerate(rows[1:], start=2):  # Skip header
        if row[0] == annotator_id and row[1] == session_id:
            row_index = idx
            break

    if row_index:
        SHEET.update(f"A{row_index}:D{row_index}", [[annotator_id, session_id, json_data, timestamp]])
    else:
        SHEET.append_row([annotator_id, session_id, json_data, timestamp])

# === Load annotations
def load_saved_annotations(annotator_id, session_id):
    records = SHEET.get_all_records()
    for rec in records:
        if rec["annotator_id"] == annotator_id and rec["session_id"] == session_id:
            try:
                loaded = json.loads(rec["full_json"])
                return {tuple(k.split("__", 1)): v for k, v in loaded.items()}
            except Exception as e:
                st.error(f"Failed to load saved annotations: {e}")
                return None
    return None

# === Main App ===
def main():
    st.title("Paragraph Annotation Task")

    # --- INSTRUCTIONS ---
    with st.expander("📘 Welcome Instructions", expanded=True):
        st.markdown("""
### Welcome to the Annotation Task!

Please enter your assigned annotator ID to begin.

You will complete **4 tasks** today. In each task, you will read **4 paragraphs** written in response to a displayed prompt. Your job is to **rate each paragraph** on the following **8 quality dimensions** using a **4-point scale**:

**1 = Very Bad, 2 = Bad, 3 = Good, 4 = Very Good**

---

#### **Quality Dimensions**
- **Originality** – How inventive or creative the ideas are (not generic or overly predictable).
- **Elaboration** – Depth, detail, and completeness of narrative.
- **Clarity** – How well the author’s intentions are conveyed (clear language, no confusing phrasing).
- **Coherence** – How logically the ideas flow (smooth transitions, consistent logic).
- **Semantic Density** – Every word/phrase contributes meaningfully (no filler).
- **Not a Summary** – Whether the paragraph is a full narrative rather than a summary.
- **Engagement** – How interesting or compelling the paragraph is to read.
- **Overall Quality** – Your overall impression of the paragraph’s quality and effectiveness.

---

#### **Important Guidelines**
- Always evaluate the paragraph **in relation to the prompt**.  
  If the prompt itself seems uninteresting, focus on **how well the paragraph responds to it** rather than the topic’s inherent appeal.

- At the **end of each task**, you will **rank the 4 paragraphs** in order of preference:  
  **1 = Best**, **4 = Worst**

- Each paragraph must receive a **unique rank** — **no duplicate ranks are allowed**.

---

Once all tasks are complete, you can submit your responses.

**⚠️ Please try to complete the entire annotation session in one sitting to avoid data loss. Avoid refreshing or closing the browser until you have submitted all your responses.**

Thank you!
        """)

    query_params = st.query_params
    annotator_id = query_params.get("annotator", "")
    session_id = query_params.get("session", "")

    valid_ids = ["1", "2", "3", "4", "5"]
    if annotator_id not in valid_ids:
        annotator_id = st.text_input("Enter your Annotator ID (1–5)")
        if annotator_id not in valid_ids:
            st.error("Annotator ID must be 1 through 5.")
            return

    if not session_id:
        session_id = f"{annotator_id}_{uuid.uuid4().hex[:8]}"
        st.query_params.update(annotator=annotator_id, session=session_id)
        st.rerun()

    st.markdown(f"**Annotator ID:** {annotator_id}")
    st.markdown(f"**Session ID:** {session_id} (auto-saved)")

    fic_paras, non_paras = load_data()
    fiction_keys = list(fic_paras.keys())
    nonfiction_keys = list(non_paras.keys())

    assigned_fic = get_assigned_prompts(annotator_id, fiction_keys)
    assigned_nonfic = get_assigned_prompts(annotator_id, nonfiction_keys)
    all_prompts = [("fiction", p) for p in assigned_fic] + [("nonfiction", p) for p in assigned_nonfic]

    if "page" not in st.session_state:
        st.session_state.page = 0

    current_page = st.session_state.page
    mode, prompt = all_prompts[current_page]
    paras_dict = fic_paras[prompt] if mode == "fiction" else non_paras[prompt]
    paras = list(paras_dict.values())

    if "all_annotations" not in st.session_state:
        st.session_state["all_annotations"] = {}

    # Always reload from Google Sheets
    # saved_annotations = load_saved_annotations(annotator_id, session_id)
    # if saved_annotations:
    #     st.session_state["all_annotations"] = saved_annotations
    #     st.success("✅ Previous session restored from Google Sheets.")

    key = (mode, prompt)
    if key not in st.session_state["all_annotations"]:
        st.session_state["all_annotations"][key] = {
            "ranking": {f"Paragraph {i+1}": None for i in range(4)},
            "ratings": {
                f"Paragraph {i+1}": {dim: 1 for dim in DIMENSIONS} for i in range(4)
            }
        }

    st.header(f"Task {current_page + 1} of {len(all_prompts)}")
    st.subheader(f"Prompt: {prompt}")

    st.markdown("### Paragraphs with Likert Ratings")
    ratings = st.session_state["all_annotations"][key]["ratings"]

    for i, para in enumerate(paras):
        para_id = f"Paragraph {i+1}"
        st.markdown(f"**{para_id}**")
        st.write(para)

        st.markdown(f"**Rate {para_id}**")
        for dim in DIMENSIONS:
            stored_rating = ratings[para_id].get(dim, 1)
            ratings[para_id][dim] = st.radio(
                dim,
                [1, 2, 3, 4],
                index=stored_rating - 1,
                horizontal=True,
                key=f"rating_{key[0]}_{key[1]}_{para_id}_{dim}"
            )

    st.markdown("### Rank the paragraphs (1 = best, 4 = worst)")
    rankings = st.session_state["all_annotations"][key]["ranking"]
    for para in rankings:
        stored_rank = rankings[para]
        rankings[para] = st.selectbox(
            f"Rank for {para}:",
            [1, 2, 3, 4],
            index=(stored_rank - 1) if stored_rank in [1, 2, 3, 4] else 0,
            key=f"rank_{key[0]}_{key[1]}_{para}"
        )

    # # Save after every page
    # save_all_annotations(annotator_id, session_id, st.session_state["all_annotations"])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Previous") and current_page > 0:
            st.session_state.page -= 1
            st.rerun()

    with col2:
        if st.button("Next") and current_page < len(all_prompts) - 1:
            ranks = list(rankings.values())
            if None in ranks:
                st.error("Please assign a rank to every paragraph.")
            elif len(set(ranks)) < 4:
                st.error("Duplicate ranks detected.")
            else:
                st.session_state.page += 1
                st.rerun()

    if current_page == len(all_prompts) - 1:
        if st.button("Submit All Annotations"):
            incomplete = False
            duplicate_found = False
            for ann in st.session_state["all_annotations"].values():
                ranks = list(ann["ranking"].values())
                if None in ranks:
                    incomplete = True
                elif len(set(ranks)) < 4:
                    duplicate_found = True

            if incomplete:
                st.error("Please assign ranks for all paragraphs.")
            elif duplicate_found:
                st.error("Duplicate ranks detected.")
            else:
                save_all_annotations(annotator_id, session_id, st.session_state["all_annotations"])
                st.success("✅ All annotations saved to Google Sheets!")

if __name__ == "__main__":
    main()









