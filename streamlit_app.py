import json
import subprocess
import sys
from pathlib import Path

import streamlit as st


@st.cache_resource
def ensure_playwright_browsers():
    """Install Chromium for Playwright once per container instance."""
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        st.error(f"Playwright browser install failed: {e.stderr}")
        st.stop()


ensure_playwright_browsers()

from app import MAP_SCREENSHOT, khasra_to_latlong

LOCATIONS_FILE = Path(__file__).parent / "mp_locations.json"


@st.cache_data
def load_locations():
    if not LOCATIONS_FILE.exists():
        return None
    with open(LOCATIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def main():
    st.set_page_config(page_title="Khasra Map Demo", layout="centered")

    st.title("Khasra Map Demo")
    st.caption("Select District → Tehsil → Village, then run the automation.")

    locations = load_locations()
    if not locations:
        st.error(f"Locations file not found: {LOCATIONS_FILE.name}. Run convert_data.py first.")
        st.stop()

    districts = sorted(locations.keys())
    district = st.selectbox("District", districts)

    tehsils = sorted(locations.get(district, {}).keys())
    if not tehsils:
        st.warning(f"No tehsils found for '{district}' in the data.")
        st.stop()
    tehsil = st.selectbox("Tehsil", tehsils)

    villages = sorted(locations.get(district, {}).get(tehsil, []))
    if not villages:
        st.warning(f"No villages found for '{tehsil}' in the data.")
        st.stop()
    village = st.selectbox("Village", villages)

    khasra_no = st.text_input("Khasra number", placeholder="Example: 76/3")

    run_clicked = st.button("Run automation", type="primary", use_container_width=True)

    if run_clicked:
        screenshot_path = Path(MAP_SCREENSHOT)
        if screenshot_path.exists():
            screenshot_path.unlink()

        with st.spinner("Automation running. please wait..."):
            try:
                lat, lon = khasra_to_latlong(
                    district=district,
                    tehsil=tehsil,
                    village=village,
                    khasra_no=khasra_no.strip() or None,
                )
            except Exception as e:
                st.error("Automation failed before coordinates could be found.")
                st.code(str(e))
                st.stop()

        if lat and lon:
            st.success("Coordinates found")
            col1, col2 = st.columns(2)
            col1.metric("Latitude", f"{lat:.6f}")
            col2.metric("Longitude", f"{lon:.6f}")
            st.link_button("Open in Google Maps", f"https://maps.google.com/?q={lat},{lon}")
        else:
            st.error(
                "Coordinates not found. This can happen if the portal's dropdown text "
                "doesn't exactly match the selected value, or the captcha/view-map step failed."
            )

        if screenshot_path.exists():
            st.subheader("Map screenshot")
            st.image(str(screenshot_path), use_container_width=True)
            st.download_button(
                "Download screenshot",
                data=screenshot_path.read_bytes(),
                file_name=screenshot_path.name,
                mime="image/png",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
