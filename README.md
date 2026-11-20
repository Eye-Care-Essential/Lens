# PriceLens

PriceLens identifies a product from a live camera image and opens enabled
price-comparison searches in your browser. It does not collect prices.

## Download and install

PriceLens runs on 64-bit Windows 11 and does not require Python.

### Recommended: setup program

1. Open the repository's **Releases** page and download
   `PriceLens-Setup-vX.Y.Z.exe` from the latest release.
2. Run the setup program. It installs PriceLens for your Windows user and adds a
   Start menu shortcut. A desktop shortcut is optional.
3. Start PriceLens from the Start menu.

### Portable version

1. Download `PriceLens-portable-vX.Y.Z.zip` from **Releases**.
2. Extract the ZIP to a folder you can write to.
3. Open the extracted `PriceLens` folder and run `PriceLens.exe`.

Your settings, API keys, and history are kept next to the app when that folder is
writable. Otherwise, PriceLens stores them in your Windows application data
folder. Keep exported configuration files private because they contain API keys.

## Build from GitHub Actions

To create a build without using a command line:

1. Open the repository on GitHub and select **Actions**.
2. Choose **Windows release** and select **Run workflow**.
3. Enter a version such as `1.0.0`, then select **Run workflow**.
4. When the run completes, open it and download the
   `PriceLens-Windows-v1.0.0` artifact.

Tagging a version as `vX.Y.Z` also builds and publishes the ZIP and setup program
on the repository's **Releases** page.

## First launch

PriceLens opens **自我檢查** on the first launch. Connect a camera, select the
AI provider you want under **設定 → AI 供應商**, enter its API key, and use
**測試連線**. The camera preview, provider, browser, internet, barcode, and
configuration checks are also available later from **自我檢查**.

Select **立即辨識** or press the space bar to identify the current frame. For hands-free
use, select **開始偵測** and place an item in view. PriceLens opens search
pages in the default browser and does not scrape listings. Any original-price
figure it displays is an AI estimate.

## Included features

- Claude, Gemini, OpenAI, and custom OpenAI-compatible vision providers.
- Camera selection and resolution, motion detection, optional barcode hints, and
  duplicate/cooldown handling.
- Editable shopping sites, second-hand search mode, and AI identification
  history with replay, copy, and delete actions.
- Settings import/export and **自我檢查** for camera and provider setup.

## Source development

The source project uses Python 3.12. Install `requirements.txt` and run
`python -m app.main` from the repository directory. The Windows release workflow
builds the onedir executable with PyInstaller and creates the installer with
Inno Setup.
