# 🎵 PSX Sample Forge

[![Release](https://img.shields.io/github/v/release/satifiedx/PSX-auto?color=blue)](https://github.com/satifiedx/PSX-auto/releases)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)]()

**[English]**  
The ultimate "One-Click" tool for creating PlayStation 1 (PSX) compatible samples (.vag).  
This tool automates the tedious math and command-line work required for "Elder Brother Core" / Jungle / Breakcore production.

**[Русский]**  
Идеальный инструмент "в один клик" для создания сэмплов PlayStation 1 (.vag).  
Программа автоматизирует математические расчеты и работу с командной строкой, необходимые для продакшена в стиле "Elder Brother Core" / Jungle / Breakcore.

---

## 🇬🇧 English Documentation

### Features
*   **Auto-Conversion**: Converts any audio (WAV, FLAC, MP3) to PSX standard: **Mono, 16-bit, 22050Hz**.
*   **Loop Alignment**: Automatically trims audio length to be a multiple of **28 samples** (SPU block requirement) for seamless looping.
*   **Portable**: Single `.exe` file, no installation needed.
*   **Simple GUI**: No more command line arguments.

### ⚠️ IMPORTANT: Looping Note
This tool handles the **mathematical alignment** of the loop (Length % 28 = 0). It does **not** edit the audio content itself.
*   If your sample has a click or a pop at the loop point, **you must apply a crossfade or de-click it in your DAW** (FL Studio, Ableton, Audacity) before exporting the WAV.
*   The tool ensures the file *technically* loops correctly on the hardware, but it assumes your source audio is already seamless.

### How to Use
1.  **Download** the latest `.exe` from Releases.
2.  **Open** the application.
3.  **Browse** for your source audio file.
4.  **Select Mode**:
    *   🔲 **Unchecked (One-Shot):** For Kicks, Snares, Hats, SFX.
    *   ✅ **Checked (Loop Mode):** For Pads, Leads, Breaks, Textures.
5.  Click **CONVERT**. The `.vag` file will be saved next to your source file.

---

## 🇷🇺 Документация на Русском

### Возможности
*   **Авто-конвертация**: Любой формат (WAV, FLAC, MP3) преобразуется в стандарт PS1: **Моно, 16-бит, 22050Гц**.
*   **Выравнивание Лупа**: Автоматически обрезает длину файла так, чтобы она делилась на **28 сэмплов** (требование аудиочипа PS1/SPU).
*   **Портативность**: Один `.exe` файл, установка не требуется.
*   **Простой интерфейс**: Больше никакой командной строки.

### ⚠️ ВАЖНО: О зацикливании (Looping)
Эта программа выполняет **математическое выравнивание** файла (Длина % 28 = 0). Она **не** редактирует содержимое звука.
*   Если ваш сэмпл "щелкает" на стыке начала и конца, **вы должны сделать кроссфейд (crossfade) или декликинг в вашей DAW** (FL Studio, Ableton, Audacity) перед экспортом.
*   Программа гарантирует, что файл *технически* корректно зациклится на железе, но она подразумевает, что исходный аудиофайл уже подготовлен и звучит бесшовно.

### Как пользоваться
1.  **Скачайте** последний `.exe` из раздела Releases.
2.  **Запустите** приложение.
3.  **Выберите** ваш аудиофайл.
4.  **Выберите режим**:
    *   🔲 **Без галочки (One-Shot):** Для ваншотов (бочка, снейр, эффекты).
    *   ✅ **С галочкой (Loop Mode):** Для пэдов, лидов, брейков, текстур.
5.  Нажмите **CONVERT**. Готовый `.vag` файл появится в той же папке, где лежит исходник.

---

## 🛠 Build from Source / Сборка из исходников

If you want to modify the code:
1.  Install Python 3.x.
2.  Place `psxavenc.exe` into the `/bin` folder.
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Build EXE:
    ```bash
    pyinstaller --noconsole --onefile --add-data "bin;bin" main.py
    ```

## Credits
*   Tool created for the "Elder Brother Core" community.
*   Uses `psxavenc` by WonderfulToolchain.
*   Built with Python, Numpy, SoundFile, and Tkinter.