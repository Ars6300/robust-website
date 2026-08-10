# Robust catalogue sync

`sync_catalog.py` rebuilds the products page on robust.bg from МойСклад. It pulls the
product list, downloads product photos, translates the Russian names to English, and
writes `assets/data/products.json`, which `products.html` fetches at runtime.

Nothing on the page is hand-written. To change the catalogue you change МойСклад (or the
dictionaries in this script) and re-run the sync.

## Running it

```bash
export MS_LOGIN="your-moysklad-login"
export MS_PASSWORD="your-moysklad-password"

python tools/sync_catalog.py
```

On Windows PowerShell:

```powershell
$env:MS_LOGIN="your-moysklad-login"
$env:MS_PASSWORD="your-moysklad-password"
python tools\sync_catalog.py
```

Requires `pillow` (`pip install pillow`). Takes about 30 seconds when nothing changed;
most of that is asking МойСклад for image metadata, not downloading.

**Never put the login or password in a file in this repo — it is public.** The script
reads them from the environment and refuses to start without them.

### Flags

| Flag | Effect |
|---|---|
| *(none)* | Incremental. Downloads only photos that changed in МойСклад. |
| `--full` | Re-downloads every photo, ignoring the cache. |
| `--no-images` | Rebuilds `products.json` from photos already on disk. No downloads. |

`tools/.cache/` holds the fetched product list and per-product image timestamps. It is
git-ignored and safe to delete — deleting it just forces a full re-download.

## What it does

1. **Fetches** every product whose name matches `SEARCH` (`"ROBUST"`) — currently 213.
2. **Downloads one photo per product**, resized to max 760 px, saved as WebP quality 86.
   Products with no photo in МойСклад are skipped, so the site never shows a blank card.
3. **Prunes** photos whose product no longer exists in МойСклад.
4. **Translates** the Russian product name into an English type + fitment string.
5. **Writes** `assets/data/products.json` with categories, brands and OEM cross numbers.

Then commit and push to `main`. GitHub Pages rebuilds and robust.bg updates in 1–2 minutes.

## Cache busting — important

Image URLs in `products.json` carry a content fingerprint:

```
assets/products/rb57169mn.webp?v=637b9195
```

The `?v=` is the md5 of the file. **Do not remove it.** robust.bg sits behind Cloudflare,
which caches images for 4 hours keyed on the URL. Replacing a photo in place without
changing the URL means the CDN keeps serving the old one and the site looks unchanged —
this happened on 2026-08-10 and cost an afternoon of confusion. The fingerprint changes
whenever the file changes, so a new photo is always a new URL and can never be stale.

`products.json` itself is `cf-cache-status: DYNAMIC` (Cloudflare does not cache it), so it
propagates within its 10-minute browser cache.

## Fixing names

The script prints anything it could not translate. Two cases:

**`NO ENGLISH NAME RULE`** — the product's Russian name doesn't start with a known part
type. Add it to `TYPES`, longest phrase first, since matching is first-hit:

```python
("Клапан ограничения давления", "Pressure Limiting Valve"),
```

**`RUSSIAN LEFT IN NAME`** — the type matched but a word in the fitment tail didn't. Add
it to `TOKENS`:

```python
(r"\bпод\s+клинья\b", "for wedges"),
```

Run again until it prints `all names translated cleanly`. Both lists are ordered, so put
specific phrases above general ones.

Other dictionaries you may need:

- `CATS` / `SUBS` — МойСклад folder name to English category. A folder with no mapping
  falls back to the parent category name.
- `SUB_ORDER` / `CAT_ORDER` — the order categories and subcategories appear. This decides
  what a visitor sees first; brake discs lead, brass fittings do not.
- `BLURB` / `TYPE_BLURB` — the descriptive paragraph on each card, per subcategory or per
  part type. `TYPE_BLURB` wins where both apply.
- `EXCLUDE` — product codes to keep off the site entirely (currently the work gloves and
  the cargo strap).

## `IMAGE_INDEX`

By default the script takes the **first** photo attached to a product. `IMAGE_INDEX` picks
a different one:

```python
"RB0273295": 2,
```

This exists because many first photos carry an **EAP watermark** while a later photo of the
same product is clean. 33 products are currently overridden this way. If someone reorders
photos in МойСклад these indexes drift, so check the card after changing photos.

## Known issues

- **Watermarks.** Around 19 products still show a watermark burned into the photo: mostly
  EAP, plus `ttt-auto.com` on some caliper parts and **HENGST** on `rb82kpd36` — a
  competitor's brand on your own site, worth fixing first. Software removal was tried and
  abandoned: the overlay can be solved mathematically (near-white, α≈0.34) but inverting it
  turns dark backgrounds into a dark inverted logo, and inpainting smears worse than the
  watermark. **The fix is to re-shoot or re-upload the photo in МойСклад**, exactly as was
  done on 2026-08-10 for 18 products. Then run the sync; it picks them up automatically.
- **Low-resolution photos.** A handful of products have source images as small as
  112×150 and look soft on the card. Only a better source photo fixes this.
- **Vendor JS error.** `assets/dropdown/js/navbar-dropdown.js` throws
  `Cannot read properties of null` on its own global click handler. Pre-existing Mobirise
  theme bug, harmless, unrelated to the catalogue.
- **Brand flags in МойСклад are unreliable.** The `Марка MAN` / `Марка VOLVO` checkboxes are
  false on most products, so brands are parsed from the product name instead and only
  unioned with the checkboxes. Do not switch to trusting the checkboxes.

## МойСклад API notes

Worth knowing if you touch the fetching code:

- `Accept-Encoding: gzip` is **required on every request**. Without it the download
  endpoint returns `415 Unsupported Media Type`.
- `/download/{id}` replies `302` to storage. The redirect must be followed **without** the
  `Authorization` header or storage returns `403`. The script disables automatic redirects
  and follows manually for this reason.
- Concurrency above ~6 workers triggers `429 Too Many Requests`. The script retries with
  exponential backoff.
- The `Фото` boolean attribute on products is **not** maintained — 13 products have it
  ticked while 170+ actually have photos. Ignore it; read the images collection.
- Article numbers are OEM cross-references glued with `/`. The first token is the Robust
  code, the rest become the searchable cross list (1,687 numbers site-wide).
