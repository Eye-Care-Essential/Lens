IDENTIFICATION_PROMPT = """Identify the main consumer product in this image as specifically as the visual evidence allows.
Prefer the brand and exact model or product series. Do not guess an exact model when it is not visible.
Return JSON only, using exactly these string fields:
{
  "name_zh": "Concise Traditional Chinese product name",
  "name_en": "Concise English product name",
  "brand": "Brand, or empty string if unknown",
  "model": "Model or series, or empty string if unknown",
  "category": "Product category",
  "query_zh": "Best concise Traditional Chinese search query for Taiwan shopping sites",
  "query_en": "Best concise English search query for Google Shopping",
  "msrp_estimate": "Likely original retail price, with currency and context, or empty string if unknown"
}
If you cannot identify a specific product, describe visible attributes in both search queries.
Do not invent a price. Use Traditional Chinese for Chinese fields."""
