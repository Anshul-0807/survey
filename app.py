"""
Khasra Number → Latitude/Longitude
MP Bhulekh WebGIS 2.0 — Full Automation
========================================
Features:
  ✅ Auto captcha solve using SambaNova Llama-4 Vision (FREE)
  ✅ Auto District/Tehsil/Village select (MAT-SELECT fixed)
  ✅ Lat/Long from OSM tiles
  ✅ Minimum manual steps

Setup:
  pip install playwright openai
  python -m playwright install chromium
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.sync_api import sync_playwright
import openai
import base64
import math
import time
import re
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────
# ⚙️  CONFIG
# ─────────────────────────────────────────────────────────
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")
HEADLESS          = os.getenv("HEADLESS", "true").strip().lower() in ("1", "true", "yes", "on")
SLOW_MO           = 400
TIMEOUT           = 45000
BASE_URL          = "https://webgis2.mpbhulekh.gov.in"
MAX_CAPTCHA_RETRY = 5
AUTO_RETRY         = 15
MAP_SCREENSHOT     = "map_polygon_screenshot.png"


def running_on_streamlit_cloud() -> bool:
    return (
        os.getenv("STREAMLIT_SHARING_MODE") is not None
        or os.getenv("STREAMLIT_SERVER_PORT") is not None
        or Path("/mount/src").exists()
    )


def system_chromium_executable_path() -> str | None:
    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if Path(path).exists():
            return path
    return None


def get_browser_launch_options(executable_path: str | None = None) -> dict:
    args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-zygote",
        "--disable-software-rasterizer",
        "--disable-extensions",
    ]
    if running_on_streamlit_cloud():
        args.extend([
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-features=Translate,BackForwardCache",
        ])

    options = {
        "headless": HEADLESS,
        "chromium_sandbox": False,
        "slow_mo": SLOW_MO,
        "args": (args if HEADLESS else []),
    }

    if executable_path:
        options["executable_path"] = executable_path

    return options


def launch_chromium(browser_type):
    errors = []
    launch_attempts = [("Playwright Chromium", get_browser_launch_options())]

    if running_on_streamlit_cloud():
        executable_path = system_chromium_executable_path()
        if executable_path:
            launch_attempts.append(
                ("system Chromium", get_browser_launch_options(executable_path))
            )

    for label, options in launch_attempts:
        try:
            print(f"  Launch attempt: {label}")
            if options.get("executable_path"):
                print(f"  Using executable: {options['executable_path']}")
            return browser_type.launch(**options)
        except Exception as e:
            errors.append(f"{label}: {e}")
            print(f"  Browser launch failed with {label}: {e}")

    raise RuntimeError("Chromium launch failed. " + " | ".join(errors))


def open_portal(page) -> bool:
    if running_on_streamlit_cloud():
        wait_modes = ("domcontentloaded", "load", "commit")
        timeout = 90000
    else:
        wait_modes = ("networkidle", "domcontentloaded")
        timeout = TIMEOUT

    last_error = None
    for wait_until in wait_modes:
        try:
            page.goto(BASE_URL, wait_until=wait_until, timeout=timeout)
            page.wait_for_selector("body", timeout=15000)
            print(f"  ✓ Loaded with wait_until={wait_until}: {page.url}")
            time.sleep(5 if running_on_streamlit_cloud() else 3)
            return True
        except Exception as e:
            last_error = e
            print(f"  ⚠ Load attempt failed with wait_until={wait_until}: {e}")

    print(f"  ✗ Portal load failed: {last_error}")
    return False


# ═══════════════════════════════════════════════════════
# 🤖 SAMBANOVA OCR — Captcha Solver
# ═══════════════════════════════════════════════════════

def solve_captcha_with_llm(img_path: str) -> str:
    client = openai.OpenAI(
        base_url="https://api.sambanova.ai/v1",
        api_key=SAMBANOVA_API_KEY,
    )
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gemma-4-31B-it",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "This is a CAPTCHA image from an Indian government website. "
                        "The captcha contains 4-6 alphanumeric characters (A-Z, 0-9). "
                        "Read EXACTLY what is written. "
                        "Reply with ONLY the captcha characters — no spaces, no explanation."
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                }
            ]
        }],
        temperature=0.1,
        max_tokens=20,
    )
    result = response.choices[0].message.content.strip().upper()
    result = re.sub(r'[^A-Z0-9]', '', result)
    return result


# ═══════════════════════════════════════════════════════
# 🗺️  TILE MATH
# ═══════════════════════════════════════════════════════

def tile_to_latlng(z, x, y):
    n = 2 ** z
    lon1 = (x / n) * 360.0 - 180.0
    lon2 = ((x + 1) / n) * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat2 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (lat1 + lat2) / 2, (lon1 + lon2) / 2

def is_mp_coords(lat, lon):
    return 21 <= lat <= 27 and 74 <= lon <= 83


# ═══════════════════════════════════════════════════════
# 🔧 MAT-SELECT HANDLER (Key Fix!)
# ═══════════════════════════════════════════════════════

def select_mat_option(page, mat_select_id: str, value: str) -> bool:
    """
    Angular Material mat-select ko handle karna:
    1. mat-select click karo (dropdown open ho)
    2. mat-option list mein se value dhundho
    3. Click karo
    """
    try:
        # mat-select click karo
        selector = f"#{mat_select_id}"
        el = page.locator(selector)
        el.click()
        time.sleep(1.5)  # dropdown animation wait

        # Options ab DOM mein aate hain (mat-option)
        # Yeh globally render hote hain body mein
        options = page.locator("mat-option").all()
        print(f"    Found {len(options)} options in dropdown")

        for opt in options:
            try:
                txt = opt.inner_text().strip()
                if value.lower() in txt.lower():
                    opt.click()
                    print(f"    ✓ Selected: '{txt}'")
                    time.sleep(1.5)
                    return True
            except Exception:
                pass

        # Close dropdown if nothing matched
        page.keyboard.press("Escape")
        print(f"    ✗ '{value}' not found in options")
        return False

    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


def get_mat_options(page, mat_select_id: str) -> list:
    """Available options list karo (debugging ke liye)."""
    try:
        page.locator(f"#{mat_select_id}").click()
        time.sleep(1.5)
        options = [opt.inner_text().strip() for opt in page.locator("mat-option").all()]
        page.keyboard.press("Escape")
        time.sleep(0.5)
        return options
    except Exception:
        return []


def click_visible_text(page, texts, timeout=2500) -> bool:
    for txt in texts:
        try:
            el = page.get_by_text(txt, exact=False).first
            if el.is_visible(timeout=timeout):
                el.click()
                print(f"  ✓ Clicked: '{txt}'")
                time.sleep(1.5)
                return True
        except Exception:
            pass
    return False


def click_visible_selector(page, selectors, timeout=2000) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=timeout):
                el.click()
                print(f"  ✓ Clicked selector: {sel}")
                time.sleep(1.5)
                return True
        except Exception:
            pass
    return False


def click_button_by_text(page, texts, timeout=1500) -> bool:
    if click_visible_text(page, texts, timeout=timeout):
        return True
    selectors = [
        "button[type='submit']",
        "button.mat-raised-button",
        "button.mat-button",
        "button",
        "[role='button']",
    ]
    return click_visible_selector(page, selectors, timeout=timeout)


def click_khasra_search_button(page, khasra_no: str) -> bool:
    try:
        clicked_text = page.evaluate(
            """(khasraNo) => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const hasSearchText = (el) => {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    return (text.includes('search') || text.includes('खोज'))
                        && !text.includes('नक्शा')
                        && !text.includes('view map');
                };

                const filledInputs = Array.from(document.querySelectorAll('input'))
                    .filter((el) => visible(el) && (el.value || '').trim() === khasraNo);

                for (const input of filledInputs.reverse()) {
                    let panel = input.closest('form, mat-expansion-panel, .mat-expansion-panel, mat-card, .mat-card, [class*="search"], [class*="parcel"]');
                    if (!panel) panel = input.parentElement;

                    while (panel) {
                        const buttons = Array.from(panel.querySelectorAll('button, [role="button"]'))
                            .filter((el) => visible(el) && hasSearchText(el));
                        if (buttons.length) {
                            const btn = buttons[buttons.length - 1];
                            const text = (btn.innerText || btn.textContent || '').trim();
                            btn.click();
                            return text || 'matched search button';
                        }
                        panel = panel.parentElement;
                    }
                }

                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
                    .filter((el) => visible(el) && hasSearchText(el));
                if (buttons.length) {
                    const btn = buttons[buttons.length - 1];
                    const text = (btn.innerText || btn.textContent || '').trim();
                    btn.click();
                    return text || 'last visible search button';
                }
                return null;
            }""",
            khasra_no,
        )
        if clicked_text:
            print(f"  ✓ Khasra search clicked: '{clicked_text}'")
            time.sleep(1.5)
            return True
    except Exception as e:
        print(f"  ⚠ Khasra search click error: {e}")
    return False


def refresh_captcha(page) -> bool:
    selectors = [
        "mat-icon:has-text('refresh')",
        "[id*='refresh']",
        "[class*='refresh']",
        "button:has(mat-icon)",
    ]
    return click_visible_selector(page, selectors, timeout=1000)


def run_required_step(label: str, action, retries=AUTO_RETRY) -> bool:
    for attempt in range(1, retries + 1):
        print(f"  {label} attempt {attempt}/{retries}")
        try:
            if action():
                return True
        except Exception as e:
            print(f"  ⚠ {label} error: {e}")
        time.sleep(1.5)
    print(f"  ✗ {label} automate nahi ho paya")
    return False


def fill_khasra_number(page, khasra_no: str) -> bool:
    preferred = [
        "input[placeholder*='खसरा']",
        "input[placeholder*='भूखंड']",
        "input[placeholder*='Survey']",
        "input[placeholder*='Parcel']",
        "input[placeholder*='Plot']",
    ]
    for sel in preferred:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=800) and inp.is_enabled(timeout=800):
                inp.clear()
                inp.fill(khasra_no)
                print(f"  ✓ Khasra filled: '{khasra_no}'")
                return True
        except Exception:
            pass

    for inp in page.locator("input[type='text']").all():
        try:
            ph = (inp.get_attribute("placeholder") or "").lower()
            if any(kw in ph for kw in ["parcel", "survey", "khasra", "plot", "खसरा", "भाग", "भूखंड"]):
                if inp.is_visible(timeout=500) and inp.is_enabled(timeout=500):
                    inp.clear()
                    inp.fill(khasra_no)
                    print(f"  ✓ Khasra filled: '{khasra_no}'")
                    return True
        except Exception:
            pass
    return False


def save_map_screenshot(page, path=MAP_SCREENSHOT) -> str | None:
    selectors = [
        ".leaflet-container",
        ".ol-viewport",
        "canvas",
        "#map",
        "[id*='map']",
        "[class*='map']",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1200):
                el.screenshot(path=path)
                print(f"  ✓ Map polygon screenshot saved: {path}")
                return path
        except Exception:
            pass

    try:
        page.screenshot(path=path, full_page=True)
        print(f"  ✓ Full-page screenshot saved: {path}")
        return path
    except Exception as e:
        print(f"  ✗ Screenshot save nahi hua: {e}")
        return None


# ═══════════════════════════════════════════════════════
# 🔧 CAPTCHA HELPERS
# ═══════════════════════════════════════════════════════

def find_captcha_image(page):
    selectors = [
        "img[src*='captcha']", "img[id*='captcha']", "img[id*='Captcha']",
        ".captcha img", "img[src*='Captcha']", "img[alt*='captcha']",
        "img[alt*='Captcha']", "img[src*='kaptcha']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            for idx in range(loc.count() - 1, -1, -1):
                el = loc.nth(idx)
                if el.is_visible(timeout=500):
                    return el
        except Exception:
            pass
    return None


def find_captcha_input(page):
    # placeholder "कैप्चा दर्ज करें" hai portal par
    try:
        loc = page.locator("input[placeholder='कैप्चा दर्ज करें']")
        for idx in range(loc.count() - 1, -1, -1):
            el = loc.nth(idx)
            if el.is_visible(timeout=500) and el.is_enabled(timeout=500):
                return el
    except Exception:
        pass
    # Fallback selectors
    for sel in ["input[id*='captcha']", "input[id*='Captcha']", "#mat-input-1"]:
        try:
            loc = page.locator(sel)
            for idx in range(loc.count() - 1, -1, -1):
                el = loc.nth(idx)
                if el.is_visible(timeout=500) and el.is_enabled(timeout=500):
                    return el
        except Exception:
            pass
    return None


def solve_and_fill_captcha(page, img_path="captcha_temp.png") -> bool:
    captcha_img = find_captcha_image(page)
    if not captcha_img:
        print("    ⚠ Captcha image nahi mili")
        return False

    captcha_img.screenshot(path=img_path)
    print("    📸 Captcha screenshot liya")

    print("    🤖 SambaNova Llama-4 se solve kar raha hai...")
    solved = solve_captcha_with_llm(img_path)
    print(f"    ✓ Solved: '{solved}'")

    captcha_input = find_captcha_input(page)
    if not captcha_input:
        print("    ⚠ Captcha input field nahi mila")
        return False

    captcha_input.clear()
    captcha_input.fill(solved)
    print(f"    ✓ Captcha filled: '{solved}'")
    return True


# ═══════════════════════════════════════════════════════
# 📄 KHASRA DETAILS (Owner / Area / Parcel ID) EXTRACTOR
# ═══════════════════════════════════════════════════════

def parse_captured_parcel_details(captured: dict) -> dict:
    """
    Portal ka `/tcgis/v1/parcel/details/search` API seedha structured JSON
    deta hai (owner name, parcel id, area/extent, ownership type, etc.) —
    isliye ab DOM scrape karne ki zaroorat nahi. Yeh function us captured
    response ko (network listener se) normalize karke standard dict me
    convert karta hai.

    Expected input shape (ek "ownerDetails[0]" item):
        {
          "parcel_no": "68/2", "parcel_id": "1081171361", "parcel_type": "S",
          "extent": "1.2320", "total_extent": "1.2320",
          "owner_names": [
            {"name_en": "...", "gender_en": "...", "owner_share": "1",
             "rel_name_en": "...", "relation_en": "Father",
             "ownership_type_en": "Bhumiswami", ...}
          ]
        }
    """
    details = {
        "owner_name": None,
        "owner_relation": None,   # e.g. "Father: गनपत सिंह"
        "ownership_type": None,   # e.g. "Bhumiswami / भूमि स्वामी"
        "owner_share": None,
        "area": None,
        "parcel_id": None,
        "parcel_no": None,
        "khata_no": None,
        "raw_pairs": {},
    }
    if not captured:
        return details

    details["raw_pairs"] = captured
    details["parcel_id"] = captured.get("parcel_id")
    details["parcel_no"] = captured.get("parcel_no")
    if captured.get("extent"):
        details["area"] = f"{captured['extent']} Hectare"

    owners = captured.get("owner_names") or []
    if owners:
        o = owners[0]  # primary owner (multiple co-owners shown via raw_pairs)
        details["owner_name"] = o.get("name_en") or o.get("name_ll")
        rel = o.get("relation_en") or o.get("relation_ll")
        rel_name = o.get("rel_name_en") or o.get("rel_name_ll")
        if rel and rel_name:
            details["owner_relation"] = f"{rel}: {rel_name}"
        own_en = o.get("ownership_type_en")
        own_ll = o.get("ownership_type_ll")
        if own_en or own_ll:
            details["ownership_type"] = " / ".join(filter(None, [own_en, own_ll]))
        details["owner_share"] = o.get("owner_share")
        if len(owners) > 1:
            details["owner_name"] += f"  (+{len(owners) - 1} more co-owner(s), see raw data)"

    if any(details[k] for k in ("owner_name", "area", "parcel_id")):
        print("  ✓ Khasra details mile (direct API se):")
        for k in ("owner_name", "owner_relation", "ownership_type", "area", "parcel_id"):
            if details[k]:
                print(f"    {k}: {details[k]}")
    else:
        print("  ⚠ Khasra details capture nahi ho paye — search API response is intercept nahi hua.")

    return details


# ═══════════════════════════════════════════════════════
# 🚀 MAIN AUTOMATION
# ═══════════════════════════════════════════════════════

def khasra_to_latlong(district, tehsil, village, khasra_no=None):
    if not SAMBANOVA_API_KEY:
        raise RuntimeError(
            "SAMBANOVA_API_KEY is not set. Add it in Streamlit Cloud: "
            "Manage app -> Settings -> Secrets."
        )

    print("\n" + "═"*55)
    location_text = f"{district} → {tehsil} → {village}"
    if khasra_no:
        location_text += f" → {khasra_no}"
    print(f"  🔍 {location_text}")
    print("═"*55)

    with sync_playwright() as p:
        print("\n► Browser launch ho raha hai...")
        browser = launch_chromium(p.chromium)
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()

        # Tile tracker (fallback coordinate method)
        latest_tile = {}
        # Direct API captures — much more reliable than tile-math / DOM scraping
        captured_parcel_details = {}
        captured_bbox = {}

        def on_response(resp):
            url = resp.url
            m = re.search(r'/(\d+)/(\d+)/(\d+)\.png', url)
            if m:
                z = int(m.group(1))
                if 15 <= z <= 20:
                    latest_tile.update(z=z, x=int(m.group(2)), y=int(m.group(3)))
                return

            if "/parcel/details/search" in url:
                try:
                    body = resp.json()
                    if body.get("success"):
                        owners = (
                            body.get("data", {})
                            .get("ownerDetails", [])
                        )
                        if owners:
                            captured_parcel_details.update(owners[0])
                except Exception as e:
                    print(f"  ⚠ parcel/details/search parse error: {e}")
                return

            if re.search(r'/bbox(\?|$|/)', url) or url.rstrip("/").endswith("bbox"):
                try:
                    body = resp.json()
                    if body.get("success") and body.get("data"):
                        box = body["data"][0] if isinstance(body["data"], list) else body["data"]
                        if all(k in box for k in ("minx", "miny", "maxx", "maxy")):
                            captured_bbox.update(box)
                except Exception as e:
                    print(f"  ⚠ bbox parse error: {e}")

        page.on("response", on_response)

        # ── Step 1: Portal open ───────────────────────────────
        print("\n[1/7] Portal khul raha hai...")
        if not open_portal(page):
            save_map_screenshot(page)
            browser.close()
            return None, None, None

        # ── Step 2: भू-भाग नक्शा click ───────────────────────
        print("\n[2/7] 'भू-भाग नक्शा' click kar raha hai...")
        found = run_required_step(
            "'भू-भाग नक्शा' click",
            lambda: click_visible_text(page, ["भू-भाग नक्शा", "Land Parcel Map", "भू नक्शा", "Parcel"]),
        )
        if not found:
            save_map_screenshot(page)
            browser.close()
            return None, None, None

        # ── Step 3: Popup ─────────────────────────────────────
        print("\n[3/7] Popup check kar raha hai...")
        click_visible_text(page, ["साधारण", "Ordinary", "हाँ", "Yes", "OK"], timeout=2000)
        time.sleep(2)

        # ── Step 3.5: 'ग्राम चयन करें' expand karo ───────────
        print("\n  'ग्राम चयन करें' expand kar raha hai...")
        gram_clicked = run_required_step(
            "'ग्राम चयन करें' expand",
            lambda: (
                click_visible_text(page, ["ग्राम चयन करें", "ग्राम चयन", "gram chayan", "Select Village"], timeout=3000)
                or click_visible_selector(page, ["mat-expansion-panel", "mat-panel-title", ".mat-expansion-panel-header"], timeout=2000)
            ),
        )
        if not gram_clicked:
            browser.close()
            return None, None, None
        time.sleep(1)

        # ── Step 4: District select (mat-select-0) ────────────
        print(f"\n[4/7] District select kar raha hai: '{district}'")
        ok = select_mat_option(page, "mat-select-0", district)
        if not ok:
            print("  Available districts:")
            opts = get_mat_options(page, "mat-select-0")
            for o in opts[:10]:
                print(f"    - {o}")
            browser.close()
            return None, None, None
        time.sleep(1)

        # ── Step 5: Tehsil select (mat-select-2) ─────────────
        print(f"\n[5/7] Tehsil select kar raha hai: '{tehsil}'")
        ok = select_mat_option(page, "mat-select-2", tehsil)
        if not ok:
            print("  Available tehsils:")
            opts = get_mat_options(page, "mat-select-2")
            for o in opts[:10]:
                print(f"    - {o}")
            browser.close()
            return None, None, None
        time.sleep(1)

        # ── Step 6: Village select (mat-select-4) ────────────
        print(f"\n[6/7] Village select kar raha hai: '{village}'")
        ok = select_mat_option(page, "mat-select-4", village)
        if not ok:
            print("  Available villages:")
            opts = get_mat_options(page, "mat-select-4")
            for o in opts[:15]:
                print(f"    - {o}")
            browser.close()
            return None, None, None
        time.sleep(1)

        # ── Step 7: Survey No radio ───────────────────────────
        print("\n  Survey No radio select kar raha hai...")
        try:
            # mat-radio-2-input = Survey No (first radio)
            page.locator("#mat-radio-2-input").check()
            print("  ✓ Survey No selected")
        except Exception:
            try:
                page.locator("input[type='radio']").first.check()
                print("  ✓ First radio selected")
            except Exception:
                pass

        # ── Step 8: Captcha solve + View Map ─────────────────
        print("\n[7/7] Captcha solve + View Map...")
        captcha_solved = False

        for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
            print(f"\n  Attempt {attempt}/{MAX_CAPTCHA_RETRY}:")
            try:
                ok = solve_and_fill_captcha(page, "captcha_viewmap.png")
                if not ok:
                    print("  ✗ Captcha auto-fill nahi hua, refresh karke retry...")
                    refresh_captcha(page)
                    continue

                # View Map button click
                clicked = click_button_by_text(page, ["नक्शा देखें", "View Map", "खोजें", "Submit"])
                if not clicked:
                    print("  ✗ View Map button auto-click nahi hua, retry...")
                    refresh_captcha(page)
                    continue

                time.sleep(5)

                if latest_tile.get("z"):
                    print("  ✓ Map loaded!")
                    captcha_solved = True
                    break
                else:
                    print("  ✗ Map load nahi hua, captcha galat tha — retry...")
                    # Refresh captcha
                    refresh_captcha(page)

            except Exception as e:
                print(f"  ⚠ Error: {e}")

        if not captcha_solved:
            print("  ✗ View Map captcha/button automation fail hua")
            browser.close()
            return None, None, None

        time.sleep(3)

        # ── Khasra Search ─────────────────────────────────────
        if khasra_no:
            print(f"\n  Khasra '{khasra_no}' search kar raha hai...")

            # 'भूखंड खोजें' section expand karo
            print("  Bhu-Khand section expand kar raha hai...")
            click_visible_text(page, ["भूखंड खोजें", "भूखंड", "Search Parcel"], timeout=2000)

            # Parcel No fill karo
            filled = run_required_step("Khasra fill", lambda: fill_khasra_number(page, khasra_no))
            if not filled:
                browser.close()
                return None, None, None

            # Search captcha
            print("  Search captcha solve kar raha hai...")
            for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
                print(f"\n  Attempt {attempt}/{MAX_CAPTCHA_RETRY}:")
                try:
                    ok = solve_and_fill_captcha(page, "captcha_search.png")
                    if not ok:
                        print("  ✗ Search captcha auto-fill nahi hua, refresh karke retry...")
                        refresh_captcha(page)
                        continue

                    clicked = click_khasra_search_button(page, khasra_no)
                    if not clicked:
                        print("  ✗ Search button auto-click nahi hua, retry...")
                        refresh_captcha(page)
                        continue

                    time.sleep(5)

                    if latest_tile.get("z", 0) >= 17:
                        print("  ✓ Map zoomed to plot!")
                        break
                    else:
                        print("  ✗ Zoom nahi hua, retry...")
                        refresh_captcha(page)

                except Exception as e:
                    print(f"  ⚠ Error: {e}")
        else:
            print("\n  Khasra number nahi diya gaya, village map coordinates use honge.")

        time.sleep(3)

        # ── Khasra details extract (owner / area / parcel id) ─
        khasra_details = None
        if khasra_no:
            print("\n  Khasra details (owner/area/parcel id) — captured API response se parse kar raha hai...")
            khasra_details = parse_captured_parcel_details(captured_parcel_details)

        # ── Coordinates extract ───────────────────────────────
        lat, lon = None, None
        if captured_bbox:
            minx, miny = captured_bbox["minx"], captured_bbox["miny"]
            maxx, maxy = captured_bbox["maxx"], captured_bbox["maxy"]
            lat, lon = (miny + maxy) / 2, (minx + maxx) / 2
            if not is_mp_coords(lat, lon):
                lat, lon = None, None
            else:
                print(f"\n  ✓ Coordinates (bbox center se): {lat:.6f}, {lon:.6f}")

        if not lat and latest_tile.get("z"):
            z, x, y = latest_tile["z"], latest_tile["x"], latest_tile["y"]
            lat, lon = tile_to_latlng(z, x, y)
            if not is_mp_coords(lat, lon):
                lat, lon = None, None
            else:
                print(f"\n  ✓ Coordinates (tile fallback se): {lat:.6f}, {lon:.6f}")

        if not lat:
            print("  ✗ Coordinates auto-extract nahi ho paye")

        save_map_screenshot(page)

        for f in ["captcha_viewmap.png", "captcha_search.png"]:
            try: os.remove(f)
            except Exception: pass

        browser.close()
        return lat, lon, khasra_details


# ═══════════════════════════════════════════════════════
# 📋 MAIN
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="MP Bhulekh WebGIS automation")
    parser.add_argument("--district", help="District name")
    parser.add_argument("--tehsil", help="Tehsil name")
    parser.add_argument("--village", help="Village name")
    parser.add_argument("--khasra", default=os.getenv("KHASRA_NO", "").strip(), help="Optional khasra number")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════╗
║   🗺️  Khasra → Lat/Long Finder              ║
║   MP Bhulekh WebGIS 2.0                     ║
║   Powered by SambaNova gemma-4
╚══════════════════════════════════════════════╝
""")
    district  = (args.district or input("  District  (e.g. Narsinghpur) : ")).strip()
    tehsil    = (args.tehsil or input("  Tehsil    (e.g. Kareli)      : ")).strip()
    village   = (args.village or input("  Village   (e.g. Deguwan)     : ")).strip()
    khasra_no = (args.khasra or input("  Khasra No (optional, Enter to skip): ")).strip()

    lat, lon, khasra_details = khasra_to_latlong(district, tehsil, village, khasra_no)

    print("\n" + "═"*55)
    if lat and lon:
        print("  ✅  RESULT")
        print("═"*55)
        if khasra_no:
            print(f"  Khasra      : {khasra_no}")
        print(f"  Village     : {village}, {tehsil}, {district}")
        print(f"  Latitude    : {lat:.6f}")
        print(f"  Longitude   : {lon:.6f}")
        print(f"\n  📍 Google Maps:")
        print(f"  https://maps.google.com/?q={lat},{lon}")
    else:
        print("  ❌  Coordinates nahi mile")

    if khasra_details:
        print("\n  📄  KHASRA DETAILS")
        print("─"*55)
        print(f"  Owner       : {khasra_details.get('owner_name') or 'Nahi mila'}")
        if khasra_details.get('owner_relation'):
            print(f"  Relation    : {khasra_details.get('owner_relation')}")
        if khasra_details.get('ownership_type'):
            print(f"  Ownership   : {khasra_details.get('ownership_type')}")
        print(f"  Area/Size   : {khasra_details.get('area') or 'Nahi mila'}")
        print(f"  Parcel ID   : {khasra_details.get('parcel_id') or 'Nahi mila'}")
        if khasra_details.get('owner_share'):
            print(f"  Owner Share : {khasra_details.get('owner_share')}")
    print("═"*55)


if __name__ == "__main__":
    main()