# PriceLens

PriceLens is a Windows desktop app for identifying a product from a live camera
image and opening price-comparison searches. It asks Gemini to identify the item;
the app opens search pages and does not collect prices.

## M1: manual identification

The current MVP provides:

- A live preview and dropdown for connected cameras.
- An **Identify now** button and SPACE shortcut.
- Gemini image identification on a background thread.
- Seven search tabs: Google Shopping, BigGo, feebee, momo, PChome 24h, Shopee,
  and Ruten.
- Local storage for the Gemini key, model, and selected camera.

Automatic motion detection, barcode reading, history, other AI providers, and
installers belong to later milestones in [PLAN.md](PLAN.md).

## Gemini API key

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey),
then open **Gemini settings** in PriceLens and paste the key. The key is stored in
the app's local `config.json`; it is not sent anywhere except Google's Gemini API.

## Development

Requires Python 3.12 on Windows. Install dependencies from `requirements.txt`,
then launch the GUI with `python -m app.main` from this directory. Packaging and a
GUI installer are planned for M4.
