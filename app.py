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
gcp_creds = st.secrets
# gcp_creds = st.secrets["gcp"] #for local testing
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET = CLIENT.open("creative_writing_annotations").sheet1

# === Deterministic prompt assignment ===
def get_assigned_prompts(annotator_id, prompt_keys):
    id_int = int(annotator_id)
    start = (id_int - 1) * PROMPTS_PER_ANNOTATOR
    return prompt_keys[start: start + PROMPTS_PER_ANNOTATOR]

# === Save annotations (overwrite if same session_id exists) ===
def save_all_annotations(annotator_id, session_id, all_data):
    serializable_data = {
        f"{k[0]}__{k[1]}": v for k, v in all_data.items() if isinstance(k, tuple)
    }
    # Save feedback as its own key
    if "feedback" in all_data:
        serializable_data["feedback"] = all_data["feedback"]

    json_data = json.dumps(serializable_data)
    timestamp = datetime.datetime.now().isoformat()

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

# === Load annotations ===
def load_saved_annotations(annotator_id, session_id):
    records = SHEET.get_all_records()
    for rec in records:
        if rec["annotator_id"] == annotator_id and rec["session_id"] == session_id:
            try:
                loaded = json.loads(rec["full_json"])
                restored = {tuple(k.split("__", 1)): v for k, v in loaded.items() if k != "feedback"}
                if "feedback" in loaded:
                    restored["feedback"] = loaded["feedback"]
                return restored
            except Exception as e:
                st.error(f"Failed to load saved annotations: {e}")
                return None
    return None

# === Main App ===
def main():
    if "page" not in st.session_state:
        st.session_state.page = 0
    if "instructions_expanded" not in st.session_state:
        st.session_state.instructions_expanded = True
        
    st.title("Paragraph Annotation Task")

    # --- INSTRUCTIONS ---
    # with st.expander("📘 Welcome Instructions", expanded=True):
    with st.expander("📘 Welcome Instructions", expanded=st.session_state.instructions_expanded):
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
  For instance, consider the prompt: “What unique cultural and culinary experiences does Montreal offer to visitors exploring its diverse neighborhoods?” The topic (culture in Montreal) may not be inherently exciting, but your evaluation should not penalize the paragraph for that. Instead, focus on how well the writing responds to the prompt and whether it is engaging to read given the prompt’s context.

- At the **end of each task**, you will **rank the 4 paragraphs** in order of preference:  
  **1 = Best**, **4 = Worst**

- Each paragraph must receive a **unique rank** — **no duplicate ranks are allowed**.

---

Once all tasks are complete, you will be asked to submit a feedback form about you reasoning and annotation process. Please answer each question attentively and explain your answers thoroughly. 

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

    # Track pages including extra feedback page
    total_pages = len(all_prompts) + 1  # +1 for feedback page
    if "page" not in st.session_state:
        st.session_state.page = 0
    
    if "instructions_expanded" not in st.session_state:
        st.session_state.instructions_expanded = True

    current_page = st.session_state.page

    # Initialize annotations storage
    if "all_annotations" not in st.session_state:
        st.session_state["all_annotations"] = {}

    # === TASK PAGES ===
    if current_page < len(all_prompts):
        mode, prompt = all_prompts[current_page]
        paras_dict = fic_paras[prompt] if mode == "fiction" else non_paras[prompt]
        paras = list(paras_dict.values())

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

        ratings = st.session_state["all_annotations"][key]["ratings"]

        # Ratings
        for i, para in enumerate(paras):
            para_id = f"Paragraph {i+1}"
            st.markdown(f"### {para_id}")
            st.write(para)

            for dim in DIMENSIONS:
                stored_rating = ratings[para_id].get(dim, 1)
                ratings[para_id][dim] = st.radio(
                    dim,
                    [1, 2, 3, 4],
                    index=stored_rating - 1,
                    horizontal=True,
                    key=f"rating_{key[0]}_{key[1]}_{para_id}_{dim}"
                )
            st.markdown("---")

        st.markdown("### Need to reference the paragraphs again?")
        # Toggle for showing the prompt
        if "show_prompt" not in st.session_state:
            st.session_state.show_prompt = False
        if st.button("Show Prompt" if not st.session_state.show_prompt else "Hide Prompt"):
            st.session_state.show_prompt = not st.session_state.show_prompt
            st.rerun()
        if st.session_state.show_prompt:
            st.info(f"**Prompt:**\n\n{prompt}")

        # Toggle for showing all paragraphs
        if "show_all_paras" not in st.session_state:
            st.session_state.show_all_paras = False
        if st.button("Show All Paragraphs" if not st.session_state.show_all_paras else "Hide All Paragraphs"):
            st.session_state.show_all_paras = not st.session_state.show_all_paras
            st.rerun()

        if st.session_state.show_all_paras:
            for i, para in enumerate(paras):
                para_id = f"Paragraph {i+1}"
                st.info(f"**{para_id}**\n\n{para}")
        else:
            # Individual toggle buttons for each paragraph
            for i, para in enumerate(paras):
                para_id = f"Paragraph {i+1}"
                toggle_key = f"ref_show_{key[0]}_{key[1]}_{para_id}"
                if toggle_key not in st.session_state:
                    st.session_state[toggle_key] = False

                if st.button(f"{'Hide' if st.session_state[toggle_key] else 'Show'} {para_id}",
                            key=f"btn_{toggle_key}"):
                    st.session_state[toggle_key] = not st.session_state[toggle_key]
                    st.rerun()
                if st.session_state[toggle_key]:
                    st.info(f"**{para_id}**\n\n{para}")


        # Rankings
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

        # Navigation
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Previous") and current_page > 0:
                st.session_state.page -= 1
                st.rerun()
        with col2:
            if st.button("Next"):
                ranks = list(rankings.values())
                if None in ranks:
                    st.error("Please assign a rank to every paragraph.")
                elif len(set(ranks)) < 4:
                    st.error("Duplicate ranks detected.")
                else:
                    st.session_state.page += 1
                    st.session_state.instructions_expanded = False
                    st.rerun()

    # === FEEDBACK PAGE ===
    else:
        st.header("Final Feedback")
        st.markdown("Please answer the following questions about your reasoning and workflow:")

        if "feedback" not in st.session_state["all_annotations"]:
            st.session_state["all_annotations"]["feedback"] = {
                "reasoning_features": "",
                "other_factors": "",
                "workflow_overall": ""
            }

        fb = st.session_state["all_annotations"]["feedback"]

        # 1. Reasoning for Overall Rankings
        fb["reasoning_features"] = st.text_area(
            "1. Which of the quality dimensions (if any) were most helpful or reliable when deciding your overall rankings?",
            fb["reasoning_features"]
        )

        # 2. Other Factors
        fb["other_factors"] = st.text_area(
            "2. Were there any other factors, beyond the listed quality dimensions, that influenced your ranking decisions? If so please explain them.",
            fb["other_factors"]
        )

        # 3. Annotator Workflow (one overall answer, with guidance shown below)
        st.markdown("### 3. Please briefly describe your annotations workflow.")
        st.markdown("""
        *Some questions to consider (you do not need to answer each individually):*  
        - In Task 2, how did you approach ranking the paragraphs?  
        - Did you read all the paragraphs first before ranking, or evaluate them one by one?  
        - Did you compare paragraphs side by side, or decide based on an overall impression?  
        - Did you revisit and change any rankings after reading others?  
        - What cues or reasoning were most important in helping you decide which paragraph was better?
        """)

        fb["workflow_overall"] = st.text_area(
            "Your overall workflow description:",
            fb["workflow_overall"]
        )

        if st.button("Submit All Annotations"):
            incomplete = False
            duplicate_found = False
            for k, ann in st.session_state["all_annotations"].items():
                if isinstance(k, tuple):
                    ranks = list(ann["ranking"].values())
                    if None in ranks:
                        incomplete = True
                    elif len(set(ranks)) < 4:
                        duplicate_found = True

            if incomplete:
                st.error("Please assign ranks for all paragraphs before submitting.")
            elif duplicate_found:
                st.error("Duplicate ranks detected.")
            else:
                save_all_annotations(annotator_id, session_id, st.session_state["all_annotations"])
                st.success("✅ All annotations (including feedback) saved to Google Sheets!")


if __name__ == "__main__":
    main()









