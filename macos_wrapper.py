import os
import sys
import threading
import time
import logging
import socket
import http.server
import socketserver
import webview


# =================================================================
# 0. Architectural & Environment Initialization
# =================================================================

# Performance tuning for Apple Silicon
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_ENABLE_METAL_ACCELERATOR"] = "1"

# GRADIO SECURITY & FILE ACCESS
os.environ["GRADIO_ALLOWED_PATHS"] = "/,/,/private/var/folders,/var/folders,/tmp,/private/tmp"
os.environ["GRADIO_TEMP_DIR"] = os.path.expanduser("~/Library/Caches/Applio/gradio")
os.makedirs(os.environ["GRADIO_TEMP_DIR"], exist_ok=True)

# Redirect Cache Directories to User Library
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/Applio")
os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
os.environ["HF_HOME"] = os.path.join(APP_SUPPORT_DIR, "huggingface")
os.environ["HF_DATASETS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "datasets")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(APP_SUPPORT_DIR, "huggingface", "models")
os.environ["MPLCONFIGDIR"] = os.path.join(APP_SUPPORT_DIR, "matplotlib")
os.environ["TORCH_HOME"] = os.path.join(APP_SUPPORT_DIR, "torch")

# Path Hygiene for PyInstaller
if getattr(sys, "frozen", False):
    BASE_PATH = sys._MEIPASS
    os.chdir(BASE_PATH)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# =================================================================
# 1. Logging Configuration
# =================================================================

def setup_logging():
    log_dir = os.path.expanduser("~/Library/Logs/Applio")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "applio_wrapper.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Redirect stdout/stderr to log for frozen builds
    if getattr(sys, "frozen", False):
        sys.stdout = open(log_file, 'a')
        sys.stderr = open(log_file, 'a')
    
    logging.info("--- Applio macOS Native Session Start ---")
    logging.info(f"Version: 1.7.4 (Simplified Local)")
    logging.info(f"CWD: {os.getcwd()}")
    logging.info(f"Base Path: {BASE_PATH}")

setup_logging()

# =================================================================
# 2. UI Support & Native Menu
# =================================================================

def get_native_menu():
    from webview.menu import Menu, MenuAction, MenuSeparator
    return [
        Menu("Applio", [
            MenuAction("About Applio", lambda: logging.info("About clicked")),
            MenuSeparator(),
            MenuAction("Services", lambda: None),
            MenuSeparator(),
            MenuAction("Hide Applio", lambda: None),
            MenuAction("Hide Others", lambda: None),
            MenuSeparator(),
            MenuAction("Quit Applio", lambda: os._exit(0))
        ]),
        Menu("Edit", [
            MenuAction("Undo", lambda: None),
            MenuAction("Redo", lambda: None),
            MenuSeparator(),
            MenuAction("Cut", lambda: None),
            MenuAction("Copy", lambda: None),
            MenuAction("Paste", lambda: None),
            MenuAction("Select All", lambda: None)
        ]),
        Menu("Window", [
            MenuAction("Minimize", lambda: None),
            MenuAction("Zoom", lambda: None),
        ])
    ]

# =================================================================
# 3. App Core Class
# =================================================================

class ApplioApp:
    def __init__(self):
        self.server_host = "127.0.0.1"
        self.server_port = 6969
        self.loading_port = 5678
        self.window = None
        self.is_ready = False
        self.heading = "System Calibration"
        self.sub_heading = "Initializing environment..."
        self.technical_detail = "Allocating memory..."
        self.progress = 0
        self.stage = "1/4"
        self.log_file = os.path.expanduser("~/Library/Logs/Applio/applio_wrapper.log")

    def start_loading_server(self):
        """Serves the high-fidelity loading screen and status API."""
        parent = self
        class LoadingHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    import json
                    data = {
                        "heading": parent.heading,
                        "sub_heading": parent.sub_heading,
                        "progress": round(parent.progress, 1),
                        "stage": parent.stage,
                        "detail": parent.technical_detail
                    }
                    self.wfile.write(json.dumps(data).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                try:
                    path = os.path.join(BASE_PATH, "assets", "loading.html")
                    with open(path, 'r') as f:
                        self.wfile.write(f.read().encode("utf-8"))
                except Exception as e:
                    self.wfile.write(f"<h1>Loading Applio...</h1><p>{e}</p>".encode("utf-8"))
            def log_message(self, format, *args): pass

        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer((self.server_host, self.loading_port), LoadingHandler) as httpd:
                logging.info(f"Loading UI server active on port {self.loading_port}")
                httpd.serve_forever()
        except Exception as e:
            logging.error(f"Loading UI server failed: {e}")

    def tail_logs(self):
        """Expert Log Observer with Real-Time Technical Feed."""
        import re
        logging.info("Starting Granular Log Observer...")
        
        # Regex patterns for real activity
        # High-level states
        p_dl_percent = re.compile(r"Downloading.* (\d+)%")
        p_dl_file = re.compile(r"Downloading (.*)\.\.\.")
        p_extract = re.compile(r"Extracting (.*)\.\.\.")
        p_req = re.compile(r"Requirement already satisfied: (.*)")
        p_pip_install = re.compile(r"Installing collected packages: (.*)")
        
        # Applio specific
        p_prereq = re.compile(r"run_prerequisites_script")
        p_init_app = re.compile(r"Initializing Gradio boot sequence")
        p_load_model = re.compile(r"Loading (.*) model")
        p_device = re.compile(r"Use (.*) acceleration")
        p_server = re.compile(r"Running on local URL:.*")
        p_responsive = re.compile(r"Gradio backend is responsive")
        
        start_time = time.time()

        while True:
            if not os.path.exists(self.log_file):
                time.sleep(0.1)
                continue
                
            try:
                with open(self.log_file, 'r') as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        
                        # ANTI-STALL CREEP: Gentle pulse, no blocking
                        if not self.is_ready and self.progress < 95:
                             creep = (100 - self.progress) / 2000
                             self.progress += creep

                        if not line:
                            time.sleep(0.05)
                            continue
                        
                        line = line.strip()
                        if not line: continue

                        # --- LOGIC MAPPING ---
                        
                        # 1. Downloads
                        if p_dl_percent.search(line):
                            self.stage = "2/4"
                            self.heading = "Synchronizing Assets"
                            match = p_dl_percent.search(line)
                            val = int(match.group(1))
                            if val > self.progress: self.progress = val
                            
                        elif p_dl_file.search(line):
                            self.stage = "2/4"
                            self.heading = "Synchronizing Assets"
                            fname = p_dl_file.search(line).group(1)
                            self.sub_heading = f"Fetching {os.path.basename(fname)}"
                            self.technical_detail = f"Network Request: {fname}"

                        # 2. Operations
                        elif p_extract.search(line):
                            self.stage = "2/4"
                            self.heading = "Decompressing Resources"
                            fname = p_extract.search(line).group(1)
                            self.sub_heading = f"Unpacking {os.path.basename(fname)}"
                            self.technical_detail = f"IO Operation: {fname}"

                        elif p_pip_install.search(line):
                             self.stage = "2/4"
                             self.heading = "Building Environment"
                             pkgs = p_pip_install.search(line).group(1)
                             if len(pkgs) > 30: pkgs = pkgs[:27] + "..."
                             self.sub_heading = f"Installing {pkgs}"
                             self.technical_detail = line

                        # 3. Initialization
                        elif p_prereq.search(line):
                            self.stage = "1/4"
                            self.heading = "System Validation"
                            self.sub_heading = "Checking Prerequisites..."
                            if self.progress < 10: self.progress = 10

                        elif p_device.search(line):
                             self.heading = "Hardware Optimization"
                             device = p_device.search(line).group(1)
                             self.sub_heading = f"Accelerating with {device}"
                             self.technical_detail = f"Device allocation: {device}"

                        # 4. Boot
                        elif p_init_app.search(line):
                            self.stage = "3/4"
                            self.heading = "Booting Inference Engine"
                            self.sub_heading = "Loading Neural Networks..."
                            self.technical_detail = "Initializing pytorch contexts..."
                            if self.progress < 80: self.progress = 80
                            
                        elif p_load_model.search(line):
                             self.heading = "Loading Models"
                             model = p_load_model.search(line).group(1)
                             self.sub_heading = f"Hydrating {model}..."
                             self.technical_detail = f"Memory mapping {model}"

                        # 5. Success
                        elif p_server.search(line) or p_responsive.search(line) or "Gradio backend is responsive" in line:
                            self.stage = "4/4"
                            self.heading = "Initialization Complete"
                            self.sub_heading = "Launching User Interface..."
                            self.progress = 100
                            self.is_ready = True
                            return
                            
                        # GENERIC FALLBACK: Show raw log activity
                        else:
                             clean = line
                             if len(clean) > 8 and "it/s]" not in clean: 
                                 if ":root:" in clean:
                                     clean = clean.split(":root:", 1)[1].strip()
                                 if len(clean) > 60: clean = clean[:57] + "..."
                                 self.technical_detail = clean
                                 if self.stage == "1/4" and self.sub_heading == "Initializing environment...":
                                     self.sub_heading = "Configuring Runtime..."
            except Exception as e:
                logging.error(f"Log observer error: {e}")
                time.sleep(1)

    def wait_for_backend(self, timeout=600):
        """Polls the Gradio backend for readiness."""
        import urllib.request
        url = f"http://{self.server_host}:{self.server_port}"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        logging.info("Gradio backend is responsive.")
                        self.is_ready = True
                        return True
            except Exception:
                time.sleep(1)
        return False

    def start_backend(self):
        """Launches the actual Applio server."""
        try:
            from app import launch_gradio
            logging.info("Initializing Gradio boot sequence...")
            launch_gradio(self.server_host, self.server_port)
        except Exception as e:
            logging.error(f"Backend launch failed: {e}")

    def monitor_transition(self):
        """Switches from loading screen to main app."""
        if self.wait_for_backend():
            # Graceful delay for UI settling
            time.sleep(1.5)
            if self.window:
                logging.info("Transitioning to main UI...")
                self.window.load_url(f"http://{self.server_host}:{self.server_port}")
        else:
            logging.error("Backend timeout period exceeded.")
            if self.window:
                self.window.load_html("<h1>Startup Error</h1><p>The server failed to respond in time.</p>")

    def run(self):
        # 0. Multiprocessing safety
        import multiprocessing
        multiprocessing.freeze_support()
        sys.argv = [sys.argv[0]] # Clean arguments

        # 1. Start Helpers
        threading.Thread(target=self.start_loading_server, daemon=True).start()
        threading.Thread(target=self.tail_logs, daemon=True).start()

        # 2. Start Backend direct
        logging.info("Launching Backend directly...")
        threading.Thread(target=self.start_backend, daemon=True).start()
        threading.Thread(target=self.monitor_transition, daemon=True).start()

        # 3. Main Window
        self.window = webview.create_window(
            "Applio",
            url=f"http://{self.server_host}:{self.loading_port}",
            width=1280,
            height=1370,
            min_size=(1024, 720),
            resizable=True,
            text_select=True,
            vibrancy=True
        )
        
        self.window.events.closed += lambda: os._exit(0)
        
        logging.info("Starting Webview GUI...")
        webview.start(menu=get_native_menu(), debug=False)

if __name__ == "__main__":
    app = ApplioApp()
    app.run()
