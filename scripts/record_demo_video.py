import os
import sys
import time
import asyncio
from playwright.async_api import async_playwright

async def record_demo():
    print("[*] Starting Playwright browser automation for screen recording...")
    video_dir = "/Users/aswinpotta/Downloads/NLP_CASESTUDY/temp_video"
    os.makedirs(video_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--window-size=1920,1080",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--hide-scrollbars",
                "--font-render-hinting=none"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=video_dir,
            record_video_size={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        async def show_label(title, subtitle, duration=4.0):
            print(f"  [SCENE] {title} - {subtitle}")
            await page.evaluate("""([title, subtitle]) => {
                let b = document.getElementById('demo-feature-banner');
                if (!b) {
                    b = document.createElement('div');
                    b.id = 'demo-feature-banner';
                    b.style.cssText = 'position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:99999; background:rgba(15,23,42,0.92); backdrop-filter:blur(16px); border:1px solid rgba(99,102,241,0.6); border-radius:12px; padding:10px 28px; box-shadow:0 12px 35px rgba(0,0,0,0.6); text-align:center; pointer-events:none; transition:opacity 0.4s ease; font-family:system-ui, -apple-system, sans-serif;';
                    document.body.appendChild(b);
                }
                b.innerHTML = `<div style="font-size:16px; font-weight:700; color:#38bdf8; letter-spacing:0.5px;">${title}</div><div style="font-size:13px; font-weight:500; color:#e2e8f0; margin-top:3px;">${subtitle}</div>`;
                b.style.opacity = '1';
            }""", [title, subtitle])
            await asyncio.sleep(duration)

        async def hide_label():
            await page.evaluate("""() => {
                let b = document.getElementById('demo-feature-banner');
                if (b) b.style.opacity = '0';
            }""")

        async def type_query(query_text):
            input_el = page.locator("#queryInput")
            await input_el.click()
            await input_el.fill("")
            await asyncio.sleep(0.5)
            # Realistic typing
            for char in query_text:
                await input_el.type(char, delay=40)
            await asyncio.sleep(0.8)

        # 1. Introduction: Open homepage
        await show_label("TraceSpot: NLP Geospatial Search", "Fine-Tuned T5-Small & OpenStreetMap Spatial Reasoner", 2.0)
        await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await asyncio.sleep(3.0)

        # Show Homepage Interface
        await show_label("1. System Overview", "Web-based natural-language interface with interactive Leaflet map", 5.0)
        await asyncio.sleep(3.0)

        # 2. Natural Language Proximity Search
        await show_label("2. Natural-Language Proximity Search", "Query: 'cafe within 100 m of a park in Berlin'", 4.0)
        await type_query("cafe within 100 m of a park in Berlin")
        await page.click("#submitSearchBtn")
        await asyncio.sleep(4.0)

        # 3. Search Results & Spatial Validation
        await show_label("3. Geospatial Search Results", "Strict distance verification, place coordinates, and spatial relation lines", 6.0)
        # Click first place card to trigger map popup and relation line
        first_card = page.locator(".place-card").first
        if await first_card.count() > 0:
            await first_card.click()
            await asyncio.sleep(4.0)

        # 4. Model Interpretation & Explain Tab
        await show_label("4. NLP Pipeline Interpretation", "Inspecting structured JSON, RapidFuzz whitelist tags, and Overpass QL", 4.0)
        await page.click("#tabBtnExplain")
        await asyncio.sleep(6.0)

        # Scroll inside the explain container to show JSON & Overpass QL
        await page.evaluate("""() => {
            const el = document.getElementById('tabContentExplain');
            if (el) el.scrollTop = 250;
        }""")
        await asyncio.sleep(4.0)
        await page.evaluate("""() => {
            const el = document.getElementById('tabContentExplain');
            if (el) el.scrollTop = 0;
        }""")
        await asyncio.sleep(2.0)

        # 5. Model Toggle
        await show_label("5. Model Architecture & Fallback Mode", "Toggling between Fine-Tuned T5 and Rule-Based Baseline", 4.0)
        await page.locator("#forceBaselineToggle").click(force=True)
        await asyncio.sleep(3.0)
        await page.locator("#forceBaselineToggle").click(force=True)
        await asyncio.sleep(3.0)

        # 6. Multi-City Searches
        # Search Paris
        await page.click("#tabBtnResults")
        await show_label("6. Multi-City Cross-Lingual Evaluation", "Testing Paris: 'restaurants near a museum in Paris'", 4.0)
        await type_query("restaurants near a museum in Paris")
        await page.click("#submitSearchBtn")
        await asyncio.sleep(4.5)
        first_card = page.locator(".place-card").first
        if await first_card.count() > 0:
            await first_card.click()
            await asyncio.sleep(3.5)

        # Search Hyderabad
        await show_label("6. Multi-City Search (Hyderabad)", "Testing Asian metro: 'cafes near a park in Hyderabad'", 4.0)
        await type_query("cafes near a park in Hyderabad")
        await page.click("#submitSearchBtn")
        await asyncio.sleep(4.5)
        first_card = page.locator(".place-card").first
        if await first_card.count() > 0:
            await first_card.click()
            await asyncio.sleep(3.5)

        # 7. Map Controls (Basemaps: Dark, OSM, Satellite)
        await show_label("7. Multi-Layer Map Controls", "Switching between Dark OSM, Standard OpenStreetMap, and Satellite Imagery", 4.0)
        await page.click("#bmOSM")
        await asyncio.sleep(3.5)
        await page.click("#bmSatellite")
        await asyncio.sleep(4.0)
        await page.click("#bmDark")
        await asyncio.sleep(3.0)

        # 8. Feature 1: Walking-Time Reach Slider
        await show_label("8. Feature 1: Walking-Time Reach", "Dynamic pedestrian isochrone & walking-distance calculation", 4.0)
        await page.evaluate("""() => {
            const slider = document.getElementById('walkingSlider');
            if (slider) {
                slider.value = 5;
                slider.dispatchEvent(new Event('input'));
            }
        }""")
        await asyncio.sleep(3.0)
        await page.evaluate("""() => {
            const slider = document.getElementById('walkingSlider');
            if (slider) {
                slider.value = 15;
                slider.dispatchEvent(new Event('input'));
            }
        }""")
        await asyncio.sleep(3.0)
        await page.evaluate("""() => {
            const slider = document.getElementById('walkingSlider');
            if (slider) {
                slider.value = 10;
                slider.dispatchEvent(new Event('input'));
            }
        }""")
        await asyncio.sleep(2.0)

        # 9. Feature 2: Multi-Stop Itinerary Planner
        await show_label("9. Feature 2: Multi-Stop Walking Itinerary", "Sentence-to-Itinerary Beam Search with OSRM routing", 4.0)
        await type_query("cafe, then a park, then a restaurant, each within a 10 minute walk in Paris")
        await page.click("#submitSearchBtn")
        await asyncio.sleep(5.0)
        # Show itinerary card and timeline
        await asyncio.sleep(5.0)

        # 10. History and Saved Spots
        await show_label("10. Search History & Saved Spots Board", "Persistent SQLite storage of queries and bookmarked spots", 4.0)
        await page.click("#tabBtnHistory")
        await asyncio.sleep(4.0)
        await page.click("#tabBtnSaved")
        await asyncio.sleep(4.0)

        # 11. Export Functionality
        await show_label("11. Data Export Capabilities", "GeoJSON FeatureCollection and CSV spreadsheet exports", 4.0)
        await page.hover("#exportBtn")
        await asyncio.sleep(3.5)

        # 12. Research Metrics & Ablation Study
        await show_label("12. Empirical Research Metrics & Ablation", "Model accuracy, tag precision/recall, and component ablation analysis", 4.0)
        await page.click("#tabBtnEval")
        await asyncio.sleep(6.0)
        # Scroll in eval tab to view ablation table
        await page.evaluate("""() => {
            const el = document.getElementById('tabContentEval');
            if (el) el.scrollTop = 300;
        }""")
        await asyncio.sleep(5.0)
        await page.evaluate("""() => {
            const el = document.getElementById('tabContentEval');
            if (el) el.scrollTop = 0;
        }""")
        await asyncio.sleep(2.0)

        # 13. Ending: Return to main view
        await show_label("13. Conclusion", "TraceSpot: End-to-End Natural-Language Geospatial Search on OpenStreetMap", 5.0)
        await page.click("#tabBtnResults")
        await asyncio.sleep(4.0)
        await hide_label()
        await asyncio.sleep(3.0)

        await page.close()
        video_path = await page.video.path()
        print(f"[OK] Raw video recorded to: {video_path}")
        await context.close()
        await browser.close()
        return video_path

if __name__ == "__main__":
    vpath = asyncio.run(record_demo())
    print(f"RECORDED_VIDEO_PATH={vpath}")
