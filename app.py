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
        print(f"  Using system Chromium: {executable_path}")

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
            return browser_type.launch(**options)
        except Exception as e:
            errors.append(f"{label}: {e}")
            print(f"  Browser launch failed with {label}: {e}")

    raise RuntimeError("Chromium launch failed. " + " | ".join(errors))


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
# 🚀 MAIN AUTOMATION
# ═══════════════════════════════════════════════════════

def khasra_to_latlong(district, tehsil, village, khasra_no=None):
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

        # Tile tracker
        latest_tile = {}
        def on_response(resp):
            m = re.search(r'/(\d+)/(\d+)/(\d+)\.png', resp.url)
            if m:
                z = int(m.group(1))
                if 15 <= z <= 20:
                    latest_tile.update(z=z, x=int(m.group(2)), y=int(m.group(3)))
        page.on("response", on_response)

        # ── Step 1: Portal open ───────────────────────────────
        print("\n[1/7] Portal khul raha hai...")
        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=TIMEOUT)
            print(f"  ✓ Loaded: {page.url}")
        except Exception as e:
            print(f"  ⚠ Warning: {e}")
        time.sleep(3)

        # ── Step 2: भू-भाग नक्शा click ───────────────────────
        print("\n[2/7] 'भू-भाग नक्शा' click kar raha hai...")
        found = run_required_step(
            "'भू-भाग नक्शा' click",
            lambda: click_visible_text(page, ["भू-भाग नक्शा", "Land Parcel Map", "भू नक्शा", "Parcel"]),
        )
        if not found:
            browser.close()
            return None, None

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
            return None, None
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
            return None, None
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
            return None, None
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
            return None, None
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
            return None, None

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
                return None, None

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

        # ── Coordinates extract ───────────────────────────────
        lat, lon = None, None
        if latest_tile.get("z"):
            z, x, y = latest_tile["z"], latest_tile["x"], latest_tile["y"]
            lat, lon = tile_to_latlng(z, x, y)
            if not is_mp_coords(lat, lon):
                lat, lon = None, None
            else:
                print(f"\n  ✓ Coordinates: {lat:.6f}, {lon:.6f}")

        if not lat:
            print("  ✗ Coordinates auto-extract nahi ho paye")

        save_map_screenshot(page)

        for f in ["captcha_viewmap.png", "captcha_search.png"]:
            try: os.remove(f)
            except Exception: pass

        browser.close()
        return lat, lon


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
║   Powered by SambaNova Llama-4 Vision       ║
╚══════════════════════════════════════════════╝
""")
    district  = (args.district or input("  District  (e.g. Narsinghpur) : ")).strip()
    tehsil    = (args.tehsil or input("  Tehsil    (e.g. Kareli)      : ")).strip()
    village   = (args.village or input("  Village   (e.g. Deguwan)     : ")).strip()
    khasra_no = (args.khasra or input("  Khasra No (optional, Enter to skip): ")).strip()

    lat, lon = khasra_to_latlong(district, tehsil, village, khasra_no)

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
    print("═"*55)


if __name__ == "__main__":
    main()
