import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import soundfile as sf
import numpy as np
import scipy.signal

def get_resource_path(relative_path):
    """
    Get the absolute path to a resource.
    Handles paths for both development environment and PyInstaller frozen exe.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Constant: Path to the external encoder binary
PSX_TOOL_PATH = get_resource_path(os.path.join("bin", "psxavenc.exe"))
# Constant: Standard PSX sample rate
TARGET_SAMPLE_RATE = 22050
# Constant: PSX SPU block size alignment (28 samples)
SPU_BLOCK_ALIGNMENT = 28

class PSXConverterApp:
    def __init__(self, root):
        """Initialize the GUI application."""
        self.root = root
        self.root.title("PSX Sample Forge")
        self.root.geometry("520x380")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e1e")

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        """Configure ttk styles for a dark theme."""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", background="#1e1e1e", foreground="#ffffff", font=("Segoe UI", 10))
        style.configure("TButton", background="#3e3e42", foreground="#ffffff", borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#007acc")])
        style.configure("TCheckbutton", background="#1e1e1e", foreground="#ffffff", font=("Segoe UI", 10))

    def _build_ui(self):
        """Construct the user interface widgets."""
        # Header
        header_frame = tk.Frame(self.root, bg="#1e1e1e")
        header_frame.pack(pady=20)
        
        tk.Label(header_frame, text="PSX SAMPLE FORGE", bg="#1e1e1e", fg="#007acc", 
                font=("Impact", 24)).pack()
        tk.Label(header_frame, text="Automated .VAG Converter", bg="#1e1e1e", fg="#888888", 
                font=("Segoe UI", 9)).pack()

        # File Selection Area
        self.file_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.file_frame.pack(pady=15, fill="x", padx=25)
        
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(self.file_frame, textvariable=self.path_var, 
                                bg="#2d2d30", fg="white", bd=0, insertbackground="white")
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 10))
        
        btn_browse = ttk.Button(self.file_frame, text="Browse...", command=self.select_file)
        btn_browse.pack(side="right")

        # Options Area
        options_frame = tk.Frame(self.root, bg="#1e1e1e")
        options_frame.pack(pady=10)

        self.loop_var = tk.BooleanVar()
        self.chk_loop = ttk.Checkbutton(options_frame, text="Loop Mode (Pad/Texture)", 
                                        variable=self.loop_var, command=self.update_info_label)
        self.chk_loop.pack()

        self.info_label = tk.Label(self.root, text="One-Shot: Standard conversion for SFX/Drums.", 
                                bg="#1e1e1e", fg="#666666", font=("Segoe UI", 9))
        self.info_label.pack(pady=5)

        # Action Area
        self.btn_convert = tk.Button(self.root, text="CONVERT", command=self.process_audio, 
                                    bg="#007acc", fg="white", font=("Segoe UI", 12, "bold"), 
                                    bd=0, activebackground="#005a9e", activeforeground="white", cursor="hand2")
        self.btn_convert.pack(pady=25, ipadx=40, ipady=8)

        # Status Bar
        self.status_label = tk.Label(self.root, text="Ready", bg="#1e1e1e", fg="#4caf50", font=("Segoe UI", 9))
        self.status_label.pack(side="bottom", pady=15)

    def update_info_label(self):
        """Update the description text based on the selected mode."""
        if self.loop_var.get():
            self.info_label.config(text="Loop Mode: Trims length to multiple of 28 samples.\nEnables seamless playback flag.")
        else:
            self.info_label.config(text="One-Shot: Standard conversion for SFX/Drums.")

    def select_file(self):
        """Open file dialog to select source audio."""
        file_path = filedialog.askopenfilename(filetypes=[("Audio Files", "*.wav *.flac *.ogg *.aiff *.mp3")])
        if file_path:
            self.path_var.set(file_path)

    def process_audio(self):
        """
        Main processing logic:
        1. Read audio file.
        2. Convert to Mono.
        3. Resample to 22050Hz.
        4. Align sample length to SPU block size (if looping).
        5. Encode to VAG using external tool.
        """
        input_path = self.path_var.get()
        
        # Validation
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("Input Error", "Please select a valid source file.")
            return

        if not os.path.exists(PSX_TOOL_PATH):
            messagebox.showerror("Configuration Error", f"Encoder binary not found at:\n{PSX_TOOL_PATH}")
            return

        try:
            self.status_label.config(text="Processing audio data...", fg="yellow")
            self.root.update()

            # 1. Read Audio
            # 'data' is a numpy array, 'samplerate' is an integer
            data, samplerate = sf.read(input_path)

            # 2. Downmix to Mono
            # If audio has more than 1 channel, calculate the mean across channels
            if data.ndim > 1:
                data = np.mean(data, axis=1)

            # 3. Resample
            # Calculate new number of samples to match TARGET_SAMPLE_RATE (22050Hz)
            if samplerate != TARGET_SAMPLE_RATE:
                number_of_samples = round(len(data) * float(TARGET_SAMPLE_RATE) / samplerate)
                data = scipy.signal.resample(data, number_of_samples)
            
            # 4. SPU Block Alignment (Loop Mode Only)
            # The PSX SPU processes audio in blocks of 28 samples.
            # For a seamless loop, the total sample count must be divisible by 28.
            if self.loop_var.get():
                total_samples = len(data)
                remainder = total_samples % SPU_BLOCK_ALIGNMENT
                if remainder != 0:
                    # Trim the end of the file to align with block size
                    data = data[:-remainder]
                    print(f"Loop Alignment: Trimmed {remainder} samples.")

            # 5. Export Temporary WAV
            # Save as 16-bit PCM WAV (required by psxavenc)
            temp_wav = os.path.join(os.path.dirname(input_path), "temp_psx_ready.wav")
            sf.write(temp_wav, data, TARGET_SAMPLE_RATE, subtype='PCM_16')

            # 6. Encode to VAG
            self.status_label.config(text="Encoding VAG...", fg="orange")
            self.root.update()

            output_vag = os.path.splitext(input_path)[0] + ".vag"
            
            # Construct command line arguments
            cmd = [PSX_TOOL_PATH, "-t", "vag", "-f", str(TARGET_SAMPLE_RATE)]
            
            if self.loop_var.get():
                # -l 0 sets the loop start point to the beginning.
                # Since the file is block-aligned, the end point is implicit.
                cmd.extend(["-l", "0"])

            cmd.extend([temp_wav, output_vag])

            # Suppress console window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # Execute encoder
            process = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)

            # Cleanup
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass

            # Check result
            if process.returncode == 0:
                self.status_label.config(text="Conversion Complete", fg="#4caf50")
                messagebox.showinfo("Success", f"File converted successfully!\nLocation: {output_vag}")
            else:
                self.status_label.config(text="Encoding Failed", fg="red")
                messagebox.showerror("Encoder Error", f"PSXAvenc returned an error:\n{process.stderr}")

        except Exception as e:
            self.status_label.config(text="Critical System Error", fg="red")
            messagebox.showerror("System Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = PSXConverterApp(root)
    root.mainloop()