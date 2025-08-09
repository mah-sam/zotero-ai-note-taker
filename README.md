# Zotero AI Note Taker

**A desktop application to automatically generate structured, AI-powered summary notes for research papers in your Zotero library.**

This tool bridges the gap between your PDF library in Zotero and the power of large language models like Google's Gemini. It provides a user-friendly interface to select papers from your Zotero collections, send them to an AI for analysis based on a custom prompt, and save the formatted results back into Zotero as a child note.


*(Replace with a screenshot of your main application window)*

## Key Features

- **Intuitive GUI:** A clean, multi-pane interface built with PyQt6 to browse collections and papers.
- **Direct Zotero Integration:** Connects to both the Zotero Web API (for writing notes) and your local Zotero application (for fast, local PDF access).
- **AI-Powered Summarization:** Leverages Google's Gemini models (`gemini-2.5-pro` and `gemini-2.5-flash`) to analyze your papers.
- **Fully Customizable Prompt:** Edit the powerful system prompt directly in the app's settings to tailor the AI's output to your specific research project.
- **Batch Processing:** Select one or multiple papers to generate notes for in a single run.
- **Smart Status Tracking:** Automatically detects which papers already have an AI summary and which are missing a PDF, disabling them to prevent duplicate work.
- **Full Collection Summaries:** Right-click any collection to compile a single text document containing the BibLaTeX citation and AI summary for every paper within it (and its sub-collections).
- **Persistent Settings:** All your API keys, IDs, and the custom prompt are saved locally in a `settings.json` file for convenience.
- **Safe & Responsive:** All network operations run in background threads, so the user interface never freezes.

---

## Screenshots

<p align="center">
  <img src="https://i.imgur.com/your-settings-screenshot.png" width="48%" alt="Settings Dialog">
  <img src="https://i.imgur.com/your-context-menu-screenshot.png" width="48%" alt="Context Menu">
</p>
<p align="center">
  <i>(Left: The comprehensive settings dialog. Right: The right-click context menu for full collection summaries.)</i>
</p>

*(Replace with screenshots of your settings dialog and the right-click menu)*

---

## Installation & Setup

Follow these steps to get the Zotero AI Note Taker running on your local machine.

### Step 1: Prerequisites

You will need the following API keys and credentials:

1.  **Zotero API Key:**
    *   Go to your [Zotero API Settings page](https://www.zotero.org/settings/keys).
    *   Click **"Create new private key"**.
    *   Give it a description (e.g., "AI Note Taker Key").
    *   Under "Personal Library", ensure you grant **"Allow write access"**.
    *   Copy the generated key.

2.  **Zotero User/Library ID:**
    *   On the same [API Settings page](https://www.zotero.org/settings/keys), find your **User ID** under the "Your userID for use in API calls" section.

3.  **Google Gemini API Key:**
    *   Go to the [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   Click **"Create API key"** and copy the generated key.

### Step 2: Clone the Repository

Open your terminal or command prompt and clone this repository:
```bash
git clone https://github.com/mah-sam/zotero-ai-note-taker.git
cd zotero-ai-note-taker
```

### Step 3: Install Dependencies

This project uses a `requirements.txt` file to manage its dependencies. Install them using pip:
```bash
pip install -r requirements.txt
```

### Step 4: Run the Application & First-Time Setup

1.  **Ensure Zotero is Running:** The Zotero desktop application **must be running** on your computer for local PDF access to work.

2.  **Launch the App:** Run the main Python script from your terminal:
    ```bash
    python note_taker.py
    ```

3.  **Enter Settings:** On the first launch, the application will detect that it hasn't been configured and will automatically open the **Settings** dialog (if it didn't, go to File -> Settings.
    *   Paste your **Zotero Library ID**, **Zotero API Key**, and **Gemini API Key** into the appropriate fields.
    *   (Optional) Review and edit the Gemini System Prompt to fit your needs.
    *   Click **Save**.

4.  **Restart the App:** A restart is required after the initial setup. Close the application and run `python note_taker.py` again. It will now connect successfully to Zotero.

---

## How to Use

### Generating Individual Notes

1.  **Select a Collection:** Click on a collection or sub-collection in the left-hand pane. The papers within it will load in the table on the right.
2.  **Select Papers:** Use the checkboxes to select the papers you want to summarize. Papers that are grayed out either lack a PDF or already have an AI-generated summary.
3.  **Configure AI:** Choose the Gemini model and temperature you wish to use.
4.  **Generate:** Click the **"Generate Summaries for Selected"** button.
5.  **Monitor Progress:** Watch the log at the bottom for real-time updates. The status of each paper in the table will change from "Summarizing..." to "Done" upon completion. The results are saved automatically as a new child note in Zotero.

### Generating a Full Collection Summary

1.  **Right-Click a Collection:** In the left-hand pane, right-click on any collection or sub-collection.
2.  **Select "Get Full Summary":** Choose this option from the context menu.
3.  **Monitor Progress:** The log will show the application fetching data for all papers in the selected collection and its children.
4.  **Save the File:** Once complete, a "Save As..." dialog will appear. Choose a location and name for your summary text file. The file will contain the BibLaTeX citation and AI summary for every paper in the collection hierarchy.

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
