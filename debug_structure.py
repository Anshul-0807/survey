"""
Debug Script — MP Bhulekh Portal HTML Structure Inspector
Run this on YOUR PC to find exact dropdown selectors
"""
from playwright.sync_api import sync_playwright
import time
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    context = browser.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()
    
    print("Opening portal...")
    page.goto("https://webgis2.mpbhulekh.gov.in", wait_until="networkidle", timeout=40000)
    time.sleep(3)
    
    print("\n" + "="*60)
    print("STEP 1: Click 'भू-भाग नक्शा' manually in browser")
    print("STEP 2: Close any popup that appears")  
    print("STEP 3: Wait for District/Tehsil/Village form to appear")
    input("Then press ENTER here...")
    time.sleep(2)
    
    print("\n=== Inspecting page structure ===\n")
    
    result = page.evaluate("""() => {
        let info = {
            selects: [],
            ngSelects: [],
            inputs: [],
            dropdowns: [],
            allText: []
        };
        
        // Standard selects
        document.querySelectorAll('select').forEach(el => {
            info.selects.push({
                id: el.id,
                name: el.name,
                class: el.className.substring(0, 80),
                options: Array.from(el.options).slice(0, 5).map(o => o.text)
            });
        });
        
        // ng-select (Angular)
        document.querySelectorAll('ng-select').forEach(el => {
            info.ngSelects.push({
                id: el.id,
                class: el.className.substring(0, 80),
                formControlName: el.getAttribute('formcontrolname'),
                ngModel: el.getAttribute('ng-model'),
                placeholder: el.getAttribute('placeholder'),
                innerText: el.innerText.substring(0, 50)
            });
        });
        
        // All inputs
        document.querySelectorAll('input').forEach(el => {
            info.inputs.push({
                id: el.id,
                name: el.name,
                type: el.type,
                placeholder: el.placeholder,
                class: el.className.substring(0, 60)
            });
        });
        
        // Role-based dropdowns
        document.querySelectorAll('[role="combobox"],[role="listbox"],[role="option"],[role="dropdown"]').forEach(el => {
            info.dropdowns.push({
                tag: el.tagName,
                role: el.getAttribute('role'),
                id: el.id,
                class: el.className.substring(0, 60),
                text: el.innerText.substring(0, 50)
            });
        });
        
        return info;
    }""")
    
    print("📋 SELECT elements:", len(result['selects']))
    for s in result['selects']:
        print(f"   id='{s['id']}' name='{s['name']}'")
        print(f"   options: {s['options']}")
    
    print("\n📋 NG-SELECT elements:", len(result['ngSelects']))
    for s in result['ngSelects']:
        print(f"   id='{s['id']}' formControlName='{s['formControlName']}' placeholder='{s['placeholder']}'")
        print(f"   text: '{s['innerText']}'")
    
    print("\n📋 INPUT elements:", len(result['inputs']))
    for s in result['inputs']:
        print(f"   id='{s['id']}' name='{s['name']}' type='{s['type']}' placeholder='{s['placeholder']}'")
    
    print("\n📋 ROLE-based dropdowns:", len(result['dropdowns']))
    for s in result['dropdowns']:
        print(f"   tag={s['tag']} role='{s['role']}' id='{s['id']}' text='{s['text']}'")
    
    # Also get full HTML of the form
    form_html = page.evaluate("""() => {
        // Try to find the form/panel area
        let selectors = ['app-land-parcel', 'app-root', 'mat-sidenav', '.sidebar', 
                        '.left-panel', 'form', '[class*="form"]', '[class*="search"]'];
        for(let sel of selectors) {
            let el = document.querySelector(sel);
            if(el) return {selector: sel, html: el.innerHTML.substring(0, 3000)};
        }
        return {selector: 'body', html: document.body.innerHTML.substring(0, 3000)};
    }""")
    
    print(f"\n📄 Form HTML (from '{form_html['selector']}'):")
    print(form_html['html'])
    
    # Save to file
    with open("portal_structure.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n✅ Full structure saved to portal_structure.json")
    
    input("\nPress ENTER to close browser...")
    browser.close()