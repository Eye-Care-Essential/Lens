# PriceLens — Camera-Based Product Price Lookup (Windows Desktop App)

## 1. Goal

A Windows desktop app that watches a live USB/external camera feed. When a product
is placed in front of the camera, the app automatically identifies it with a vision
LLM and opens price-comparison search pages in the default browser so the user can
check market price / original price themselves.

**Pain point being solved:** today the user must photograph and upload products one
by one. The app must make this hands-free: place item → wait ~1 s → pages open.

**Primary use case:** mostly second-hand items, often without barcodes. AI image
recognition is the primary identification method; barcode reading is a secondary
shortcut when a barcode happens to be visible.

The user runs it on multiple Windows PCs, so it must ship as a portable build
and an installer. The user prefers GUIs and does not want any CLI steps.

## 2. Non-goals

- No web scraping of prices. The app only **opens search URLs** in the browser.
- No confidence score display, no "rotate the item" prompts.
- No user accounts, cloud sync, or server component.
- No macOS/Linux support.

## 3. Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| GUI | PySide6 (Qt 6) |
| Camera enumeration + capture | `PySide6.QtMultimedia` (`QMediaDevices`, `QCamera`, `QMediaCaptureSession`, `QVideoSink`), so device **names** are shown, not just indices |
| Image processing | OpenCV (`opencv-python`) + NumPy (motion detection, resize, JPEG encode, barcode) |
| Barcode | OpenCV built-in `cv2.barcode.BarcodeDetector` (no extra native DLLs) |
| Dedupe | `imagehash` (perceptual hash) or a simple dHash implemented in NumPy |
| AI SDKs | `anthropic`, `google-genai`, `openai` (the `openai` SDK also covers "Custom/OpenAI-compatible") |
| Packaging | PyInstaller (**onedir** mode) + Inno Setup |
| CI | GitHub Actions on `windows-latest` → GitHub Releases |

## 4. Project Structure

```
pricelens/
├─ app/
│  ├─ main.py                 # entry point, QApplication, load config
│  ├─ config.py               # load/save/import/export config.json
│  ├─ paths.py                # resolve app dir (works frozen + source)
│  ├─ ui/
│  │  ├─ main_window.py       # live view, Start/Stop, history list, status bar
│  │  ├─ settings_dialog.py   # tabs: AI, Camera, Sites, Detection, General
│  │  ├─ selftest_dialog.py   # one-click checks with green/red rows
│  │  └─ widgets.py           # history item widget, status LED, etc.
│  ├─ camera/
│  │  └─ camera_service.py    # list devices, open/close, emit frames (np.ndarray)
│  ├─ detection/
│  │  ├─ motion_trigger.py    # IDLE→MOTION→STABLE state machine
│  │  ├─ dedupe.py            # perceptual hash + cooldown
│  │  └─ barcode.py           # optional barcode decode
│  ├─ ai/
│  │  ├─ base.py              # VisionProvider interface + ProductResult dataclass
│  │  ├─ anthropic_provider.py
│  │  ├─ gemini_provider.py
│  │  ├─ openai_provider.py   # also used for Custom (base_url override)
│  │  ├─ prompt.py            # shared system prompt + JSON schema
│  │  └─ factory.py
│  ├─ search/
│  │  └─ sites.py             # site registry, URL templating, open in browser
│  ├─ history/
│  │  └─ store.py             # history.json + thumbnails folder
│  └─ workers.py              # QThread/QRunnable workers for AI calls
├─ assets/icon.ico
├─ installer/pricelens.iss    # Inno Setup script
├─ pricelens.spec             # PyInstaller spec
├─ requirements.txt
├─ .github/workflows/release.yml
└─ README.md                  # end-user instructions (download, run, settings)
```

## 5. Configuration (`config.json`)

- Stored **next to the executable** (portable). If that folder is not writable
  (e.g. installed under Program Files), fall back to `%APPDATA%\PriceLens\config.json`.
  `paths.py` owns this logic.
- Settings → General has **Export config** and **Import config** buttons (file dialogs)
  so the user can set up one PC and copy settings to others.
- API keys are stored in the config file (required for portability). Show a one-line
  warning in the UI that the exported file contains keys.

```json
{
  "ai": {
    "provider": "gemini",                 // claude | gemini | openai | custom
    "claude":  { "api_key": "", "model": "" },
    "gemini":  { "api_key": "", "model": "" },
    "openai":  { "api_key": "", "model": "" },
    "custom":  { "api_key": "", "model": "", "base_url": "" },
    "timeout_sec": 30
  },
  "camera": { "device_id": "", "resolution": "1280x720" },
  "detection": {
    "auto_enabled": true,
    "motion_threshold": 0.02,             // fraction of changed pixels to count as motion
    "stable_ms": 1000,                    // scene must be still this long to trigger
    "cooldown_ms": 3000,
    "dedupe_hamming": 6,                  // pHash distance below which frame = same item
    "barcode_enabled": true
  },
  "search": {
    "secondhand_mode": false,             // appends "二手" to Shopee/Ruten queries
    "sites": [ /* see section 9; enabled flag + url_template per site */ ]
  },
  "general": { "max_history": 200, "open_tabs_delay_ms": 150 }
}
```

Model fields are editable text boxes, and each one has a "default" button. Pick current
vision-capable default models for each provider at implementation time. Don't hardcode
model IDs outside `config.py` defaults.

## 6. Main Window

Layout (left/right split):

- **Left (≈65%)**: live camera preview, scaled with aspect ratio kept. Overlay text
  in the corner shows state: `IDLE`, `MOTION`, `STABLE…`, `IDENTIFYING…`, `DONE`.
- **Right top**: big **Start Detection / Stop** toggle button. Below it, the active
  provider and camera name. Below that, a hint: "Press SPACE to identify now".
- **Right bottom**: history list (newest first). Each row shows a thumbnail, product name,
  brand/model, and an AI-estimated original price (labelled "AI estimate").
  - Double-click a row: re-open the search tabs.
  - Right-click a row: copy the search query, delete the row.
- **Toolbar / menu**: Settings, Self-Test, Open history folder.
- **Status bar**: last error (if any) and call count for this session.

### Trigger behaviour: auto and manual work at the same time
- When detection is **started**, the auto motion trigger runs continuously.
- **SPACE** (window-level shortcut, works whenever the main window has focus) forces
  identification of the current frame immediately. It works whether auto is running or not,
  and it **bypasses dedupe and cooldown**.
- Only one AI request can be in flight at a time. A trigger that arrives while a request is
  busy is dropped, and the status bar shows "busy".

## 7. Auto-Detection Algorithm (`motion_trigger.py`, `dedupe.py`)

Processing runs on a downscaled grayscale frame (e.g. 320 px wide) at about 10 fps
to keep CPU use low.

1. Blur the frame and compute the absolute difference from the previous processed frame. The
   changed-pixel ratio is the share of pixels whose diff exceeds a threshold.
2. State machine:
   - `IDLE`: ratio > `motion_threshold` → `MOTION`
   - `MOTION`: ratio stays below the threshold for `stable_ms` → `STABLE` → **trigger**
   - After a trigger → `IDLE`
3. Before calling the AI, check the guards:
   - **Empty-scene check**: keep a "background" reference, captured when detection starts or
     with a "Reset background" button. If the stable frame is near-identical to the background,
     don't trigger (the item was removed).
   - **Dedupe**: compute a pHash of the stable frame. If its Hamming distance to the last
     identified frame is ≤ `dedupe_hamming`, skip it (same item still sitting there).
   - **Cooldown**: no auto trigger within `cooldown_ms` of the previous one.
4. **Barcode** (if enabled): run the barcode detector on the full-res frame first.
   - If a code is decoded, still call the AI with the image (needed for the second-hand
     context), and also pass the barcode string in the prompt so the AI can use it.
   - Barcode is a hint, never a requirement.

## 8. AI Identification (`ai/`)

Interface:

```python
class VisionProvider(Protocol):
    def identify(self, jpeg_bytes: bytes, barcode: str | None) -> ProductResult: ...
    def test_connection(self) -> tuple[bool, str]: ...   # used by Self-Test

@dataclass
class ProductResult:
    name_zh: str            # Traditional Chinese product name
    name_en: str
    brand: str
    model: str
    category: str
    query_zh: str           # best search query for Taiwanese sites
    query_en: str           # best search query for Google/global
    msrp_estimate: str      # e.g. "NT$ 12,900 (launch price)" or "" if unknown
    raw: dict
```

- Image handling: resize so the longest side is 1024 px, JPEG quality about 85.
- The prompt (`prompt.py`) asks the model to identify the product as specifically as possible
  (brand + model/series), and to return **JSON only** that matches the schema. Use each SDK's
  structured-output / JSON mode where available, and use a tolerant JSON extractor as a
  fallback.
- If the product cannot be identified, the model returns a generic descriptive query
  (e.g. "黑色 皮革 後背包").
- Run every call in a worker thread. Never block the UI thread.
- Errors (bad key, quota, timeout, network) appear in the status bar and as a
  history row marked "failed". Never crash.
- `test_connection()` sends a minimal text-only request to validate the key and model.

## 9. Search Sites (`search/sites.py`)

Each site has: `id`, display name, `enabled`, `url_template` with `{q}`, and
`query_field` (`zh` or `en`). Templates live in config so the user can fix them
if a site changes its URL.

| Site | Default template (verify during implementation) | Query |
|---|---|---|
| Google Shopping | `https://www.google.com/search?tbm=shop&q={q}` | en (fallback zh) |
| BigGo | `https://biggo.com.tw/s/?q={q}` | zh |
| feebee 飛比 | `https://feebee.com.tw/s/?q={q}` | zh |
| momo | `https://www.momoshop.com.tw/search/searchShop.jsp?keyword={q}` | zh |
| PChome 24h | `https://24h.pchome.com.tw/search/?q={q}` | zh |
| Shopee 蝦皮 | `https://shopee.tw/search?keyword={q}` | zh |
| Ruten 露天 | `https://www.ruten.com.tw/find/?q={q}` | zh |

- URL-encode the query with `urllib.parse.quote`.
- When **secondhand_mode** is on, append ` 二手` to the Shopee and Ruten queries only.
- Open the tabs with `webbrowser.open_new_tab`, with a small delay between tabs.
- Settings → Sites tab: checkbox list, editable template field, "Test open" button
  per site (opens it with the query "iPhone 13").

## 10. Settings Dialog

Tabs:
- **AI**: provider dropdown (Claude / Gemini / ChatGPT / Custom), plus API key (password
  field with a show toggle), model, base URL (Custom only), and a **Test connection**
  button with an inline ✅/❌ result.
- **Camera**: device dropdown (from `QMediaDevices.videoInputs()`), resolution dropdown,
  **Refresh devices** button, and a small live preview of the selected camera.
- **Sites**: as described in section 9, plus the second-hand mode toggle.
- **Detection**: sliders/spinboxes for motion threshold, stable ms, cooldown, dedupe
  distance; barcode toggle; **Reset background** button.
- **General**: export/import config, open config folder, max history.

## 11. Self-Test Dialog

One button: **Run all checks**. Each check is a row with a status LED and a message.
1. Config file is readable and writable.
2. At least one camera is found; the selected camera opens and delivers a frame within 3 s
   (show the thumbnail).
3. Internet is reachable (HTTPS GET to a well-known host, 5 s timeout).
4. An API key is set for the active provider, and `test_connection()` succeeds.
5. A default browser is available (`webbrowser.get()` doesn't raise).
6. Barcode detector initialises (if enabled).

If any check fails, show a plain-language fix hint (e.g. "Close other apps using the camera").
Run the self-test automatically on first launch, when no config exists yet.

## 12. History (`history/store.py`)

- `history.json` plus a `thumbs/` folder in the app data dir, holding the last N entries.
- Fields per entry: timestamp, thumbnail path, ProductResult fields, barcode, provider, status.
- Load the history on startup.

## 13. Packaging & Release

### PyInstaller
- Use `onedir` mode (faster startup, fewer antivirus false positives than onefile), windowed
  (no console), with `assets/icon.ico`.
- Include the Qt multimedia plugins. Verify that the camera works in the frozen build.

### Portable build
- Zip the `dist/PriceLens/` folder as `PriceLens-portable-vX.Y.Z.zip`. The config is written
  next to the exe.

### Installer (Inno Setup, `installer/pricelens.iss`)
- Installs per-user by default (`{localappdata}\Programs\PriceLens`), so the config next to
  the exe stays writable.
- Creates Start Menu and optional desktop shortcuts, and registers an uninstaller.
- Output: `PriceLens-Setup-vX.Y.Z.exe`.

### GitHub Actions (`.github/workflows/release.yml`)
- Triggers: push of a tag `v*`, plus `workflow_dispatch` (manual run button in the GitHub UI).
- Runner: `windows-latest`. Steps:
  1. Set up Python 3.12 and `pip install -r requirements.txt pyinstaller`.
  2. Run PyInstaller.
  3. Zip the portable build.
  4. Install Inno Setup (via `choco install innosetup` if it isn't present) and compile the `.iss`.
  5. Create a GitHub Release and upload both the zip and the setup exe.
- Also upload the outputs as workflow artifacts on `workflow_dispatch` runs.
- The README explains how to get a build without the CLI: go to the GitHub **Actions** tab,
  click **Run workflow**, then download from **Releases**.

## 14. Milestones & Acceptance Criteria

### M1: MVP (manual flow, end to end)
- Live camera preview with the camera chosen from a basic dropdown.
- SPACE / "Identify now" button → AI call → search tabs open.
- At least one provider works (Gemini or Claude), with the key entered in a minimal settings field.
- **Done when:** the user holds up an item, presses SPACE, and the 7 search tabs open with a
  sensible query within about 5 s.

### M2: Hands-free detection
- Motion state machine, background/empty check, dedupe, cooldown, and optional barcode.
- Start/Stop toggle. Auto and SPACE work at the same time.
- **Done when:** placing 5 different items one after another opens tabs 5 times, a still item
  doesn't re-trigger, and removing an item doesn't trigger.

### M3: Full settings, providers, self-test
- All 4 providers, including Custom with base_url.
- Full Settings dialog, Self-Test dialog, config export/import, second-hand mode, history list.
- **Done when:** switching providers in the UI works without a restart, and the self-test
  correctly flags an unplugged camera and a wrong API key.

### M4: Packaging & CI
- PyInstaller spec, Inno Setup script, GitHub Actions release workflow, end-user README.
- **Done when:** a tag push produces a Release with the portable zip and the setup exe, and both
  run on a clean Windows 11 machine with no Python installed.

## 15. Engineering Notes

- Keep all UI updates on the Qt main thread. Workers communicate via signals.
- Handle camera disconnects without crashing: show "Camera lost". Retry and Refresh should recover.
- Never log API keys. Mask them in error messages.
- Write unit tests (pytest) for the motion state machine (feed synthetic frames), dedupe, URL
  templating/encoding, config load/migrate, and JSON extraction from AI responses.
- Code style: type hints, small modules, no global state except the config object passed
  via dependency injection.
