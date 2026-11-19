# PriceLens

PriceLens is a Windows desktop app for identifying a product from a live camera
image and opening price-comparison searches. The app opens search pages; it does
not collect prices.

## Current features

- Live camera preview, camera selection, and configurable resolution.
- Manual identification with the **Identify now** button or SPACE shortcut.
- Hands-free detection with a motion trigger, empty-scene reference, duplicate
  filter, cooldown, and optional barcode hint.
- Vision identification through Claude, Gemini, OpenAI, or a custom
  OpenAI-compatible endpoint.
- Editable search sites and query languages, with an optional second-hand search
  suffix for Shopee and Ruten.
- Local history with thumbnails, query replay, copy, and delete actions.
- A Self-Test dialog for camera, internet, provider credentials, browser,
  barcode support, and config-folder access.
- Settings import/export. Exported configuration files include API keys; keep
  them private.

AI requests run in a worker thread. Each successful identification opens the
enabled search URLs in the default browser. API keys and history are stored
locally beside the app config (or in the user application-data folder if the
app directory is read-only).

## API keys

Add a key for the selected provider in **Settings → AI**, then use **Test
connection** to check the key and model. For a custom OpenAI-compatible API,
also enter its base URL. **Self-Test** repeats a minimal provider request and
reports authentication failures with a plain-language hint.

## Development

Requires Python 3.12 on Windows. Install dependencies from `requirements.txt`,
then launch the GUI with `python -m app.main` from this directory. Packaging and
a GUI installer are planned for M4.
