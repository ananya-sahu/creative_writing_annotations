import streamlit as st
import json
import tempfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import uuid
import datetime
import time
import os

# === CONFIG ===
DIMENSIONS = [
    "Originality", "Elaboration", "Clarity", "Coherence",
    "Semantic Density", "Not a Summary", "Engagement", "Overall"
]
PROMPTS_PER_ANNOTATOR = 2

# === LOCAL SAVE DIRECTORY ===
# LOCAL_SAVE_DIR = "./saved_sessions"
# os.makedirs(LOCAL_SAVE_DIR, exist_ok=True)
LOCAL_SAVE_DIR = os.path.join(tempfile.gettempdir(), "./saved_sessions")
os.makedirs(LOCAL_SAVE_DIR, exist_ok=True)

ADMIN_SECRET = "my_super_secret_key"# change this to something unique

def is_admin():
    try:
        return st.query_params.get("secret")[0] == ADMIN_SECRET
    except Exception:
        return False

# === Local Save/Load Helpers ===
def get_local_save_path(annotator_id, session_id):
    return f"{LOCAL_SAVE_DIR}/{annotator_id}_{session_id}.json"


def save_to_local_file(annotator_id, session_id, all_data):
    # Convert tuple keys to strings
    serializable_data = {
        (f"{k[0]}__{k[1]}" if isinstance(k, tuple) else k): v
        for k, v in all_data.items()
    }
    serializable_data["_autosave_timestamp"] = datetime.datetime.now().isoformat()

    path = get_local_save_path(annotator_id, session_id)
    with open(path, "w") as f:
        json.dump(serializable_data, f, indent=2)



def load_from_local_file(annotator_id, session_id):
    path = get_local_save_path(annotator_id, session_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            loaded = json.load(f)
        restored = {
            tuple(k.split("__", 1)): v
            for k, v in loaded.items()
            if k not in ["feedback", "_autosave_timestamp"]
        }
        if "feedback" in loaded:
            restored["feedback"] = loaded["feedback"]
        restored["_autosave_timestamp"] = loaded.get("_autosave_timestamp", "")
        return restored
    return None

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
# gcp_creds = st.secrets["gcp"]
gcp_creds = st.secrets
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET = CLIENT.open("creative_writing_annotations").sheet1


# === Deterministic prompt assignment ===
def get_assigned_prompts(annotator_id, prompt_keys):
    id_int = int(annotator_id)
    start = (id_int - 1) * PROMPTS_PER_ANNOTATOR
    return prompt_keys[start: start + PROMPTS_PER_ANNOTATOR]


# === Save annotations to Google Sheets ===
def save_all_annotations(annotator_id, session_id, all_data):
    serializable_data = {
        f"{k[0]}__{k[1]}": v for k, v in all_data.items() if isinstance(k, tuple)
    }
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
        SHEET.update(f"A{row_index}:D{row_index}",
                     [[annotator_id, session_id, json_data, timestamp]])
    else:
        SHEET.append_row([annotator_id, session_id, json_data, timestamp])


# === Main App ===
def main():
    params = st.query_params
    st.write("DEBUG - Query params:", params)

    if is_admin():
        st.title("🛠 Admin Panel – Saved Sessions")
        files = [f for f in os.listdir(LOCAL_SAVE_DIR) if f.endswith(".json")]

        if not files:
            st.info("No saved sessions found.")
        else:
            for f in files:
                path = os.path.join(LOCAL_SAVE_DIR, f)
                last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(path))

                st.markdown(f"**{f}** – Last modified: {last_modified}")
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    with open(path, "r") as fp:
                        data = fp.read()
                    st.download_button(
                        label=f"⬇️ Download {f}",
                        data=data,
                        file_name=f,
                        mime="application/json",
                        key=f"download_{f}"
                    )
                with col2:
                    if st.button(f"🗑️ Delete", key=f"delete_{f}"):
                        os.remove(path)
                        st.warning(f"Deleted {f}")
                        st.rerun()  # Refresh the admin panel after deletion
                st.markdown("---")
        return  # ✅ Stops here so annotators never see annotation UI
    
    if "page" not in st.session_state:
        st.session_state.page = 0
        # Auto-scroll if flagged (after Next/Previous rerun)
    if st.session_state.get("scroll_pending", False):
        st.session_state["scroll_pending"] = False  # Reset flag
        st.components.v1.html("""
        <script>
        const selectors = [
            '[data-testid="stVerticalBlock"]',
            '[data-testid="stAppViewContainer"]',
            'section.main',
            '.block-container'
        ];
        function scrollNow() {
            selectors.forEach(sel => {
                const el = window.parent.document.querySelector(sel);
                if (el) {
                    el.scrollTop = 0;
                    if (el.scrollTo) el.scrollTo({top:0, behavior:'instant'});
                }
            });
            window.scrollTo(0,0);
            window.parent.scrollTo(0,0);
            const header = window.parent.document.querySelector('h1');
            if (header && header.scrollIntoView) header.scrollIntoView({behavior:'instant', block:'start'});
        }
        [50,150,300].forEach(ms => setTimeout(scrollNow, ms));
        </script>
        """, height=0)

    if "instructions_expanded" not in st.session_state:
        st.session_state.instructions_expanded = True

    # Check if page changed and scroll to top BEFORE rendering content
    if "last_page" not in st.session_state:
        st.session_state.last_page = st.session_state.page
    
    page_changed = st.session_state.page != st.session_state.last_page
    if page_changed:
        st.session_state.last_page = st.session_state.page

    st.title("Paragraph Annotation Task")

    # === INSTRUCTIONS ===
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
- **Clarity** – How well the author's intentions are conveyed (clear language, no confusing phrasing).
- **Coherence** – How logically the ideas flow (smooth transitions, consistent logic).
- **Semantic Density** – Every word/phrase contributes meaningfully (no filler).
- **Not a Summary** – Whether the paragraph is a full narrative rather than a summary.
- **Engagement** – How interesting or compelling the paragraph is to read.
- **Overall Quality** – Your overall impression of the paragraph's quality and effectiveness.

---

#### **Important Guidelines**
- Always evaluate the paragraph **in relation to the prompt**.  
  If the prompt itself seems uninteresting, focus on **how well the paragraph responds to it** rather than the topic's inherent appeal.
  For instance, consider the prompt: "What unique cultural and culinary experiences does Montreal offer to visitors exploring its diverse neighborhoods?" The topic (culture in Montreal) may not be inherently exciting, but your evaluation should not penalize the paragraph for that. Instead, focus on how well the writing responds to the prompt and whether it is engaging to read given the prompt's context.

- At the **end of each task**, you will **rank the 4 paragraphs** in order of preference:  
  **1 = Best**, **4 = Worst**

- Each paragraph must receive a **unique rank** — **no duplicate ranks are allowed**.

- After ranking you will be asked to respond to 2 open ended questions on the reasoning behind why you chose the overall rankings. Please explain your answers in detail (2-3 sentences) 

---

Once all tasks are complete, you will be asked to submit a feedback form about your annotation process. Please answer attentively and explain your answers thoroughly. 

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
    st.markdown(f"**Session ID:** {session_id} (auto-saved locally)")

    # Store in session_state for easy access
    st.session_state.annotator_id = annotator_id
    st.session_state.session_id = session_id

    fic_paras, non_paras = load_data()
    fiction_keys = list(fic_paras.keys())
    nonfiction_keys = list(non_paras.keys())
    assigned_fic = get_assigned_prompts(annotator_id, fiction_keys)
    assigned_nonfic = get_assigned_prompts(annotator_id, nonfiction_keys)
    all_prompts = [("fiction", p) for p in assigned_fic] + [("nonfiction", p) for p in assigned_nonfic]

    total_pages = len(all_prompts) + 1  # +1 for feedback page
    current_page = st.session_state.page

    # === Load saved progress if not loaded yet ===
    if "all_annotations" not in st.session_state:
        previous = load_from_local_file(annotator_id, session_id)
        if previous:
            st.session_state["all_annotations"] = previous
            st.info(f"✅ Resumed from last auto-save at {previous.get('_autosave_timestamp', 'unknown')}")
        else:
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
                new_rating = st.radio(
                    dim,
                    [1, 2, 3, 4],
                    index=stored_rating - 1,
                    horizontal=True,
                    key=f"rating_{key[0]}_{key[1]}_{para_id}_{dim}"
                )
                if new_rating != ratings[para_id][dim]:
                    ratings[para_id][dim] = new_rating
                    save_to_local_file(annotator_id, session_id, st.session_state["all_annotations"])
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
            new_rank = st.selectbox(
                f"Rank for {para}:",
                [1, 2, 3, 4],
                index=(stored_rank - 1) if stored_rank in [1, 2, 3, 4] else 0,
                key=f"rank_{key[0]}_{key[1]}_{para}"
            )
            if new_rank != rankings[para]:
                rankings[para] = new_rank
                save_to_local_file(annotator_id, session_id, st.session_state["all_annotations"])
        
        # --- Feedback questions at end of each task ---
        task_data = st.session_state["all_annotations"][key]

        if "feedback" not in task_data:
            task_data["feedback"] = {
                "reasoning_features": "",
                "other_factors": ""
            }

        fb = task_data["feedback"]

        st.markdown("### Task Feedback")

        new_reasoning = st.text_area(
            "1. Which of the quality dimensions (if any) were most helpful or reliable when deciding your overall rankings?",
            fb["reasoning_features"],
            key=f"reasoning_{key[0]}_{key[1]}"
        )
        if new_reasoning != fb["reasoning_features"]:
            fb["reasoning_features"] = new_reasoning
            save_to_local_file(annotator_id, session_id, st.session_state["all_annotations"])

        new_factors = st.text_area(
            "2. Were there any other factors, beyond the listed dimensions, that influenced your ranking decisions? If so please list them and explain how.",
            fb["other_factors"],
            key=f"factors_{key[0]}_{key[1]}"
        )
        if new_factors != fb["other_factors"]:
            fb["other_factors"] = new_factors
            save_to_local_file(annotator_id, session_id, st.session_state["all_annotations"])

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Previous") and current_page > 0:
                st.session_state.page -= 1
                # Force page refresh with query parameter to reset scroll
                st.session_state["scroll_pending"] = True
                st.query_params.update(
                    annotator=annotator_id, 
                    session=session_id,
                    _scroll_reset=str(datetime.datetime.now().timestamp())
                )
                
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
                    # Force page refresh with query parameter to reset scroll
                    st.session_state["scroll_pending"] = True
                    st.query_params.update(
                        annotator=annotator_id, 
                        session=session_id,
                        _scroll_reset=str(datetime.datetime.now().timestamp())
                    )
                    st.rerun()
                    st.components.v1.html("""
                <script>
                const selectors = [
                    '[data-testid="stVerticalBlock"]',
                    '[data-testid="stAppViewContainer"]',
                    'section.main',
                    '.block-container'
                ];
                selectors.forEach(sel => {
                    const el = window.parent.document.querySelector(sel);
                    if (el) {
                        el.scrollTop = 0;
                        if (el.scrollTo) el.scrollTo({top:0, behavior:'instant'});
                    }
                });
                window.scrollTo(0,0);
                window.parent.scrollTo(0,0);
                const header = window.parent.document.querySelector('h1');
                if (header && header.scrollIntoView) header.scrollIntoView({behavior:'instant', block:'start'});
                </script>
                """, height=0)
        
        # Back to Top button (appears below navigation)
            if st.button("⬆️ Back to Top"):
                st.components.v1.html("""
                <script>
                const selectors = [
                    '[data-testid="stVerticalBlock"]',
                    '[data-testid="stAppViewContainer"]',
                    'section.main',
                    '.block-container'
                ];
                selectors.forEach(sel => {
                    const el = window.parent.document.querySelector(sel);
                    if (el) {
                        el.scrollTop = 0;
                        if (el.scrollTo) el.scrollTo({top:0, behavior:'instant'});
                    }
                });
                window.scrollTo(0,0);
                window.parent.scrollTo(0,0);
                const header = window.parent.document.querySelector('h1');
                if (header && header.scrollIntoView) header.scrollIntoView({behavior:'instant', block:'start'});
                </script>
                """, height=0)


   # === FINAL FEEDBACK PAGE ===
    else:
        st.header("Final Feedback")

        # Store final workflow as its own key, not inside "feedback"
        if "annotator_workflow" not in st.session_state["all_annotations"]:
            st.session_state["all_annotations"]["annotator_workflow"] = ""

        st.markdown("### 3. Briefly describe your workflow")

        st.markdown("""
        *Some questions to consider (you do not need to answer each individually):*  
        - In Task 2, how did you approach ranking the paragraphs?  
        - Did you read all the paragraphs first before ranking, or evaluate them one by one?  
        - Did you compare paragraphs side by side, or decide based on an overall impression?  
        - Did you revisit and change any rankings after reading others?  
        - What cues or reasoning were most important in helping you decide which paragraph was better?
        """)

        new_workflow = st.text_area(
            "Your response:",
            st.session_state["all_annotations"]["annotator_workflow"]
        )
        if new_workflow != st.session_state["all_annotations"]["annotator_workflow"]:
            st.session_state["all_annotations"]["annotator_workflow"] = new_workflow
            save_to_local_file(annotator_id, session_id, st.session_state["all_annotations"])

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
                st.success("✅ All annotations saved to Google Sheets!")
                try:
                    os.remove(get_local_save_path(annotator_id, session_id))
                    st.caption("🗑️ Local backup deleted after submission.")
                except FileNotFoundError:
                    pass


        # Navigation for feedback page
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Back to Last Task", key="feedback_back") and current_page > 0:
                st.session_state.page = len(all_prompts) - 1
                st.rerun()

    # Show autosave timestamp
    ts = st.session_state["all_annotations"].get("_autosave_timestamp", "")
    if ts:
        st.caption(f"💾 Auto-saved locally at: {ts}")


if __name__ == "__main__":
    main()










