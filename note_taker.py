import sys
import os
import json
import markdown
import bibtexparser
from bibtexparser.bwriter import BibTexWriter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QTableWidget, QTableWidgetItem, QPushButton, QComboBox,
    QLabel, QDoubleSpinBox, QSplitter, QTextEdit, QHeaderView, QMessageBox,
    QMenu, QFileDialog, QDialog, QDialogButtonBox, QFormLayout, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QAction

from pyzotero import zotero
import google.genai as genai

# ==============================================================================
#  NEW: SETTINGS MANAGEMENT
# ==============================================================================
CONFIG_FILE = 'settings.json'
DEFAULT_SETTINGS = {
    "zotero_library_id": "YOUR_LIBRARY_ID",
    "zotero_library_type": "user",
    "zotero_api_key": "YOUR_ZOTERO_API_KEY",
    "gemini_api_key": "YOUR_GEMINI_API_KEY",
    "gemini_system_prompt": """**Primary Role:** You are an expert Research Assistant...
...
*   Adhere strictly to the requested markdown format.
"""
}

def load_settings():
    """Loads settings from the JSON file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()

def save_settings(settings_dict):
    """Saves settings to the JSON file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(settings_dict, f, indent=4)

# ==============================================================================
#  NEW: SETTINGS DIALOG WINDOW
# ==============================================================================
class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)

        self.layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.library_id_edit = QLineEdit(current_settings.get("zotero_library_id"))
        self.library_type_combo = QComboBox()
        self.library_type_combo.addItems(["user", "group"])
        self.library_type_combo.setCurrentText(current_settings.get("zotero_library_type", "user"))
        self.zotero_key_edit = QLineEdit(current_settings.get("zotero_api_key"))
        self.zotero_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_edit = QLineEdit(current_settings.get("gemini_api_key"))
        self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.prompt_edit = QTextEdit(current_settings.get("gemini_system_prompt"))
        self.prompt_edit.setMinimumHeight(200)

        form_layout.addRow("Zotero Library ID:", self.library_id_edit)
        form_layout.addRow("Zotero Library Type:", self.library_type_combo)
        form_layout.addRow("Zotero API Key:", self.zotero_key_edit)
        form_layout.addRow("Gemini API Key:", self.gemini_key_edit)
        form_layout.addRow("Gemini System Prompt:", self.prompt_edit)

        self.layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.layout.addWidget(buttons)

    def get_settings(self):
        """Returns a dict of the settings from the dialog fields."""
        return {
            "zotero_library_id": self.library_id_edit.text(),
            "zotero_library_type": self.library_type_combo.currentText(),
            "zotero_api_key": self.zotero_key_edit.text(),
            "gemini_api_key": self.gemini_key_edit.text(),
            "gemini_system_prompt": self.prompt_edit.toPlainText()
        }

# ==============================================================================
#  WORKER THREADS (Unchanged)
# ==============================================================================
# ZoteroWorker, SummaryWorker, and CollectionSummaryWorker classes remain the same
# as the last provided version. They are included here for completeness.

class ZoteroWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    def __init__(self, zot_instance, task, *args):
        super().__init__()
        self.zot = zot_instance
        self.task = task
        self.args = args
    def run(self):
        try:
            if self.task == 'fetch_collections':
                data = self.zot.collections()
            elif self.task == 'fetch_items':
                collection_key = self.args[0]
                items = self.zot.collection_items_top(collection_key)
                for item in items:
                    children = self.zot.children(item['data']['key'])
                    item['data']['has_pdf'] = any(c['data'].get('filename', '').lower().endswith('.pdf') for c in children if c['data']['itemType'] == 'attachment')
                    item['data']['has_ai_note'] = any('AI-Summary' in [t.get('tag') for t in c['data'].get('tags', [])] for c in children if c['data']['itemType'] == 'note')
                data = items
            else: data = None
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(f"Zotero API Error: {e}")

class SummaryWorker(QThread):
    """Worker thread for generating summaries with Gemini API."""
    progress = pyqtSignal(str)
    paper_finished = pyqtSignal(int, str) # row, status
    all_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, zot_web, zot_local, papers_to_process, model, temperature, system_prompt):
        super().__init__()
        self.zot_web, self.zot_local = zot_web, zot_local
        self.papers, self.model, self.temperature = papers_to_process, model, temperature
        self.system_prompt = system_prompt
        self.is_running = True

    def run(self):
        try:
            client = genai.Client()
        except Exception as e:
            self.error.emit(f"Failed to configure Gemini model: {e}")
            return

        for i, paper_data in enumerate(self.papers):
            if not self.is_running:
                break
            
            row, item = paper_data['row'], paper_data['item']
            item_key, item_title = item['data']['key'], item['data'].get('title', 'Untitled')

            self.progress.emit(f"Processing '{item_title}'...")
            self.paper_finished.emit(row, "Summarizing...")

            try:
                self.progress.emit("  -> Searching for local PDF via Zotero server...")
                children = self.zot_local.children(item_key)
                pdf_child = next((c for c in children if c['data']['itemType'] == 'attachment' and c['data'].get('filename', '').lower().endswith('.pdf')), None)

                if not pdf_child:
                    self.paper_finished.emit(row, "Error: PDF not found")
                    self.progress.emit(f"  -> Could not find a local PDF for '{item_title}'.")
                    continue
                
                pdf_key = pdf_child['data']['key']
                self.progress.emit(f"  -> Found local PDF. Downloading from Zotero server...")
                pdf_bytes = self.zot_local.file(pdf_key)

                response = client.models.generate_content(
                    model=self.model,
                    contents=[
                        "Please analyze the provided research paper and generate notes according to the system instructions.",
                        genai.types.Part.from_bytes(mime_type="application/pdf", data=pdf_bytes)
                    ],
                    config=genai.types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=self.temperature
                    )
                )
                
                raw_markdown_text = response.text
                html_note_content = markdown.markdown(raw_markdown_text)
                
                # --- THIS IS THE CRITICAL FIX ---
                # Instead of using item_template(), create the dictionary manually.
                # This guarantees 'itemType' is included.
                note_to_create = {
                    'itemType': 'note',
                    'note': html_note_content,
                    'tags': [{'tag': 'AI-Summary'}, {'tag': self.model}]
                }
                
                # Pass the manually created dictionary to the create_items method.
                create_response = self.zot_web.create_items([note_to_create], parentid=item_key)
                # --- END OF FIX ---

                if create_response['success']:
                    self.paper_finished.emit(row, "Done")
                    self.progress.emit(f"Successfully created note for '{item_title}'.")
                else:
                    self.paper_finished.emit(row, "Failed")
                    self.progress.emit(f"Failed to create note for '{item_title}': {create_response['failed']}")

            except Exception as e:
                self.paper_finished.emit(row, "Error")
                self.error.emit(f"An error occurred while processing '{item_title}': {e}")

            if i < len(self.papers) - 1 and self.is_running:
                self.progress.emit("Waiting 6s to respect API rate limit...")
                self.sleep(6)
        
        self.all_finished.emit()

    def stop(self):
        self.is_running = False
        self.progress.emit("Stopping summary generation...")

class CollectionSummaryWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    def __init__(self, zot_instance, collection_key):
        super().__init__()
        self.zot = zot_instance
        self.start_collection_key = collection_key
    def run(self):
        try:
            self.progress.emit("Fetching collection hierarchy...")
            collections_to_process = self.zot.all_collections(self.start_collection_key)
            self.progress.emit(f"Found {len(collections_to_process)} collections to process.")
            all_item_keys, all_items_data = [], {}
            for coll in collections_to_process:
                self.progress.emit(f"Finding items in: '{coll['data']['name']}'")
                items = self.zot.collection_items_top(coll['key'])
                for item in items:
                    if item['data']['key'] not in all_item_keys:
                        all_item_keys.append(item['data']['key'])
                        all_items_data[item['data']['key']] = item
            if not all_item_keys:
                self.progress.emit("No items found in the selected collection(s).")
                self.finished.emit("")
                return
            self.progress.emit(f"\nFound {len(all_item_keys)} total items. Fetching BibLaTeX citations in batches...")
            all_biblatex_data = {}
            chunk_size = 50
            for i in range(0, len(all_item_keys), chunk_size):
                chunk_keys = all_item_keys[i:i + chunk_size]
                self.progress.emit(f"  -> Fetching BibLaTeX batch {i//chunk_size + 1} ({len(chunk_keys)} items)...")
                key_string = ",".join(chunk_keys)
                bib_database = self.zot.items(format='biblatex', itemKey=key_string)
                if len(chunk_keys) != len(bib_database.entries):
                    self.progress.emit(f"    - Warning: Key count mismatch in batch. Requested {len(chunk_keys)}, got {len(bib_database.entries)}. Some citations may be missing.")
                writer = BibTexWriter()
                for item_key, entry in zip(chunk_keys, bib_database.entries):
                    temp_db = bibtexparser.bibdatabase.BibDatabase()
                    temp_db.entries = [entry]
                    bib_string = writer.write(temp_db)
                    all_biblatex_data[item_key] = bib_string
            self.progress.emit("\nCompiling final summary document...")
            all_summary_parts = []
            for key in all_item_keys:
                item_title = all_items_data[key]['data'].get('title', 'Untitled')
                self.progress.emit(f"  -> Processing '{item_title}'")
                bib_string = all_biblatex_data.get(key)
                if not bib_string:
                    self.progress.emit(f"    - Warning: Missing BibLaTeX for key {key}. Skipping.")
                    continue
                children = self.zot.children(key)
                ai_note_content = None
                for child in children:
                    if child['data']['itemType'] == 'note':
                        if 'AI-Summary' in [t.get('tag') for t in child['data'].get('tags', [])]:
                            ai_note_content = child['data']['note']
                            self.progress.emit("    - Found AI note.")
                            break
                if ai_note_content:
                    all_summary_parts.append(f"{bib_string.strip()}\n{ai_note_content}")
                else:
                    self.progress.emit("    - No AI note found. Using BibLaTeX only.")
                    all_summary_parts.append(bib_string.strip())
            final_text = "\n\n**\n\n".join(all_summary_parts)
            self.finished.emit(final_text)
        except Exception as e:
            self.error.emit(f"Error during collection summary: {e}")

# ==============================================================================
#  MAIN GUI WINDOW (Updated with Settings Logic)
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Zotero Paper Summarizer")
        self.setGeometry(100, 100, 1200, 800)
        self.zot_web, self.zot_local = None, None
        self.summary_worker, self.collection_summary_worker = None, None
        self.is_task_running = False

        self.settings = load_settings()

        self.init_ui()

        if self.check_initial_settings():
            self.connect_to_zotero()

    def init_ui(self):
        # --- Create Menu Bar ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        settings_action = QAction("&Settings...", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)

        # ... (Rest of UI setup is unchanged) ...
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setSizes([300, 900])
        left_layout.addWidget(QLabel("Zotero Collections"))
        self.collection_tree = QTreeView()
        self.collection_tree.setHeaderHidden(True)
        self.collection_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.collection_tree.customContextMenuRequested.connect(self.show_collection_context_menu)
        self.collection_model = QStandardItemModel()
        self.collection_tree.setModel(self.collection_model)
        self.collection_tree.clicked.connect(self.on_collection_selected)
        left_layout.addWidget(self.collection_tree)
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["gemini-2.5-pro", "gemini-2.5-flash"])
        controls_layout.addWidget(self.model_combo)
        controls_layout.addWidget(QLabel("Temperature:"))
        self.temp_spinbox = QDoubleSpinBox()
        self.temp_spinbox.setRange(0.0, 1.0)
        self.temp_spinbox.setSingleStep(0.1)
        self.temp_spinbox.setValue(0.7)
        controls_layout.addWidget(self.temp_spinbox)
        controls_layout.addStretch()
        self.generate_button = QPushButton("Generate Summaries for Selected")
        self.generate_button.clicked.connect(self.start_summary_generation)
        controls_layout.addWidget(self.generate_button)
        right_layout.addLayout(controls_layout)
        paper_selection_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(lambda: self.toggle_all_selection(True))
        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.clicked.connect(lambda: self.toggle_all_selection(False))
        paper_selection_layout.addWidget(self.select_all_button)
        paper_selection_layout.addWidget(self.deselect_all_button)
        paper_selection_layout.addStretch()
        right_layout.addLayout(paper_selection_layout)
        self.paper_table = QTableWidget()
        self.paper_table.setColumnCount(4)
        self.paper_table.setHorizontalHeaderLabels(["", "Title", "Authors", "Status"])
        self.paper_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.paper_table.setColumnWidth(0, 30)
        self.paper_table.setColumnWidth(2, 250)
        self.paper_table.setColumnWidth(3, 100)
        self.paper_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.paper_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.paper_table)
        right_layout.addWidget(QLabel("Log"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        right_layout.addWidget(self.log_view)

    def open_settings_dialog(self):
        """Opens the settings dialog and handles the result."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            save_settings(self.settings)
            self.log("Settings saved. Please restart the application to apply changes.")
            QMessageBox.information(self, "Settings Saved", "Settings have been saved. Please restart the application to connect with the new credentials.")

    def check_initial_settings(self):
        """Checks if settings are valid on startup. Forces settings dialog if not."""
        for key, value in self.settings.items():
            if "YOUR_" in value:
                QMessageBox.warning(self, "First-Time Setup", "Please enter your API keys and Zotero information in the settings dialog.")
                self.open_settings_dialog()
                # Re-check after user interaction
                if any("YOUR_" in v for v in self.settings.values()):
                    self.log("Setup cancelled. Exiting.")
                    QApplication.instance().quit()
                    return False
                break
        return True

    def connect_to_zotero(self):
        self.log("Connecting to Zotero...")
        try:
            # Use loaded settings
            lib_id = self.settings['zotero_library_id']
            lib_type = self.settings['zotero_library_type']
            zot_key = self.settings['zotero_api_key']

            self.zot_web = zotero.Zotero(lib_id, lib_type, zot_key)
            self.zot_local = zotero.Zotero(lib_id, lib_type, local=True)
            
            self.zot_local.collections(limit=1) # Test connection
            self.log("-> Successfully connected to Zotero Web API and Local Server.")
            self.fetch_collections()
        except Exception as e:
            error_msg = f"Failed to connect to Zotero. Please check your credentials in Settings, and make sure the Zotero application is running. Error: {e}"
            self.log(error_msg)
            QMessageBox.critical(self, "Zotero Connection Error", error_msg)

    def start_summary_generation(self):
        papers_to_process = []
        for row in range(self.paper_table.rowCount()):
            if self.paper_table.item(row, 0).checkState() == Qt.CheckState.Checked:
                paper_item = self.paper_table.item(row, 1)
                papers_to_process.append({'row': row, 'item': paper_item.data(Qt.ItemDataRole.UserRole)})
        if not papers_to_process:
            QMessageBox.warning(self, "No Selection", "Please select at least one paper with a PDF to summarize.")
            return

        self.log(f"Starting summary generation for {len(papers_to_process)} paper(s)...")
        
        # Set Gemini API key for this worker's environment
        os.environ['GEMINI_API_KEY'] = self.settings['gemini_api_key']
        
        self.set_task_running(True)
        self.generate_button.setText("Stop Generation")
        self.generate_button.clicked.disconnect()
        self.generate_button.clicked.connect(self.stop_summary_generation)
        
        self.summary_worker = SummaryWorker(
            self.zot_web, self.zot_local, papers_to_process, 
            self.model_combo.currentText(), self.temp_spinbox.value(),
            self.settings['gemini_system_prompt']
        )
        self.summary_worker.progress.connect(self.log)
        self.summary_worker.paper_finished.connect(self.update_paper_status)
        self.summary_worker.all_finished.connect(self.on_all_summaries_finished)
        self.summary_worker.error.connect(self.handle_error)
        self.summary_worker.start()

    # ... (All other methods like on_all_summaries_finished, handle_error, etc., remain the same)
    def set_task_running(self, is_running):
        self.is_task_running = is_running
        self.generate_button.setEnabled(not is_running)
        self.collection_tree.setEnabled(not is_running)
    def show_collection_context_menu(self, point):
        if self.is_task_running: return
        index = self.collection_tree.indexAt(point)
        if not index.isValid(): return
        item = self.collection_model.itemFromIndex(index)
        collection_key = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        summary_action = QAction("Get Full Summary", self)
        summary_action.triggered.connect(lambda: self.start_collection_summary(collection_key, item.text()))
        menu.addAction(summary_action)
        menu.exec(self.collection_tree.viewport().mapToGlobal(point))
    def fetch_collections(self):
        self.worker = ZoteroWorker(self.zot_web, 'fetch_collections')
        self.worker.finished.connect(self.populate_collection_tree)
        self.worker.error.connect(self.handle_error)
        self.worker.start()
    def populate_collection_tree(self, collections):
        self.collection_model.clear()
        root_node = self.collection_model.invisibleRootItem()
        collection_nodes = {}
        for coll in collections:
            key, name = coll['key'], coll['data']['name']
            item = QStandardItem(name)
            item.setData(key, Qt.ItemDataRole.UserRole)
            collection_nodes[key] = item
        for coll in collections:
            key, parent_key = coll['key'], coll['data'].get('parentCollection', False)
            if parent_key and parent_key in collection_nodes:
                collection_nodes[parent_key].appendRow(collection_nodes[key])
            else:
                root_node.appendRow(collection_nodes[key])
        self.log("Collections loaded.")
    def on_collection_selected(self, index):
        item = self.collection_model.itemFromIndex(index)
        collection_key = item.data(Qt.ItemDataRole.UserRole)
        self.log(f"Fetching papers for collection: '{item.text()}'...")
        self.paper_table.setRowCount(0)
        self.worker = ZoteroWorker(self.zot_web, 'fetch_items', collection_key)
        self.worker.finished.connect(self.populate_paper_table)
        self.worker.error.connect(self.handle_error)
        self.worker.start()
    def populate_paper_table(self, papers):
        self.paper_table.setRowCount(len(papers))
        for row, paper in enumerate(papers):
            data = paper['data']
            title, authors = data.get('title', 'No Title'), ", ".join([f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() for c in data.get('creators', [])])
            has_pdf, has_ai_note = data.get('has_pdf', False), data.get('has_ai_note', False)
            check_item, title_item, authors_item = QTableWidgetItem(), QTableWidgetItem(title), QTableWidgetItem(authors)
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            if has_ai_note:
                status_item = QTableWidgetItem("Done")
                check_item.setFlags(Qt.ItemFlag.NoItemFlags)
                done_color = QColor(20, 110, 50)
                title_item.setForeground(done_color)
                authors_item.setForeground(done_color)
                status_item.setForeground(done_color)
            elif not has_pdf:
                status_item = QTableWidgetItem("No PDF")
                check_item.setFlags(Qt.ItemFlag.NoItemFlags)
                gray_color = QColor(150, 150, 150)
                title_item.setForeground(gray_color)
                authors_item.setForeground(gray_color)
                status_item.setForeground(gray_color)
            else: status_item = QTableWidgetItem("Pending")
            title_item.setData(Qt.ItemDataRole.UserRole, paper)
            self.paper_table.setItem(row, 0, check_item)
            self.paper_table.setItem(row, 1, title_item)
            self.paper_table.setItem(row, 2, authors_item)
            self.paper_table.setItem(row, 3, status_item)
        self.log(f"Loaded {len(papers)} papers.")
    def toggle_all_selection(self, check_state):
        state = Qt.CheckState.Checked if check_state else Qt.CheckState.Unchecked
        for row in range(self.paper_table.rowCount()):
            item = self.paper_table.item(row, 0)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)
    def stop_summary_generation(self):
        if self.summary_worker: self.summary_worker.stop()
        self.on_all_summaries_finished()
    def on_all_summaries_finished(self):
        self.log("Summary generation finished or was stopped.")
        self.generate_button.setText("Generate Summaries for Selected")
        try: self.generate_button.clicked.disconnect()
        except TypeError: pass
        self.generate_button.clicked.connect(self.start_summary_generation)
        self.set_task_running(False)
    def update_paper_status(self, row, status):
        self.paper_table.item(row, 3).setText(status)
    def log(self, message):
        """Appends a message to the log view on the GUI."""
        self.log_view.append(message)
    def start_collection_summary(self, collection_key, collection_name):
        self.log(f"Starting full summary compilation for collection: '{collection_name}'...")
        self.set_task_running(True)
        self.collection_summary_worker = CollectionSummaryWorker(self.zot_web, collection_key)
        self.collection_summary_worker.progress.connect(self.log)
        self.collection_summary_worker.finished.connect(self.save_collection_summary)
        self.collection_summary_worker.error.connect(self.handle_error)
        self.collection_summary_worker.start()
    def save_collection_summary(self, summary_text):
        self.log("Full summary compilation finished.")
        self.set_task_running(False)
        if not summary_text:
            QMessageBox.information(self, "No Summaries Found", "No items with an 'AI-Summary' note were found in the selected collection(s).")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Full Summary", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(summary_text)
                self.log(f"Successfully saved full summary to {file_path}")
                QMessageBox.information(self, "Success", f"Full summary saved to:\n{file_path}")
            except Exception as e:
                self.handle_error(f"Failed to save file: {e}")
        else: self.log("Save operation cancelled by user.")
    def handle_error(self, error_message):
        self.log(f"ERROR: {error_message}")
        QMessageBox.critical(self, "An Error Occurred", error_message)
        if self.is_task_running:
            self.set_task_running(False)
            if self.summary_worker and self.summary_worker.isRunning():
                self.on_all_summaries_finished()
    def closeEvent(self, event):
        if self.summary_worker and self.summary_worker.isRunning(): self.summary_worker.stop()
        if self.collection_summary_worker and self.collection_summary_worker.isRunning(): self.collection_summary_worker.terminate()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())