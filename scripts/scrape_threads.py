#!/usr/bin/env python3
"""Scrape all posts from a Threads profile with login."""

import os, time, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

PROFILE_URL = "https://www.threads.com/@re.branding96"
OUTPUT_FILE = "/Users/cdiseetheeye/Desktop/Onlime/이승석 모음.md"
DEBUG_DIR = "/Users/cdiseetheeye/Desktop/Onlime/.firecrawl"
USERNAME = os.environ.get("THREADS_USERNAME", "")
PASSWORD = os.environ.get("THREADS_PASSWORD", "")
os.makedirs(DEBUG_DIR, exist_ok=True)


def ss(page, name):
    try: page.screenshot(path=f"{DEBUG_DIR}/{name}.png")
    except: pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ko-KR",
        )
        page = ctx.new_page()

        # ===== STEP 1: Instagram Login =====
        print("=== Step 1: Instagram Login ===")
        page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # Accept cookies if present
        for t in ["Accept All", "Allow All Cookies", "모두 허용"]:
            try:
                b = page.locator(f'button:has-text("{t}")')
                if b.count() > 0: b.first.click(); time.sleep(1)
            except: pass

        page.wait_for_selector('input', timeout=15000)
        page.fill('input[name="email"], input[name="username"], input[type="text"]', USERNAME)
        time.sleep(0.5)
        page.fill('input[name="pass"], input[type="password"]', PASSWORD)
        time.sleep(0.5)

        btn = page.locator('button[type="submit"]')
        if btn.count() > 0: btn.first.click()
        else: page.keyboard.press("Enter")

        time.sleep(10)
        print(f"  After login: {page.url}")

        # Dismiss "Save info" popup
        for _ in range(3):
            for t in ["나중에 하기", "Not Now", "Not now", "Skip"]:
                try:
                    b = page.locator(f'button:has-text("{t}")').or_(page.locator(f'div[role="button"]:has-text("{t}")'))
                    if b.count() > 0: b.first.click(); time.sleep(2); print(f"  Dismissed: {t}")
                except: pass
        ss(page, "01_instagram_done")
        print(f"  Instagram: {page.url}")

        # ===== STEP 2: Threads OAuth Login =====
        print("\n=== Step 2: Threads OAuth ===")
        page.goto("https://www.threads.com/login", wait_until="domcontentloaded", timeout=60000)
        time.sleep(8)
        ss(page, "02_threads_login")
        print(f"  Threads login URL: {page.url}")

        # Click "Instagram으로 계속하기" with force=True to bypass overlay
        try:
            ig_btn = page.locator('text=Instagram으로 계속하기').or_(
                page.locator('text=Continue with Instagram')
            )
            if ig_btn.count() > 0:
                ig_btn.first.click(force=True, timeout=10000)
                print("  Clicked 'Instagram으로 계속하기' (force)")
                time.sleep(10)
        except Exception as e:
            print(f"  Click failed: {e}")
            # Fallback: use JS to find and navigate the href
            page.evaluate("""
            () => {
                const els = document.querySelectorAll('a, div[role="button"], button');
                for (const el of els) {
                    if ((el.innerText || '').includes('Instagram')) {
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                        break;
                    }
                }
            }
            """)
            time.sleep(10)

        ss(page, "03_after_oauth_click")
        print(f"  After OAuth click: {page.url}")

        # If on Instagram consent page, authorize
        if "instagram.com" in page.url:
            print("  On Instagram OAuth consent...")
            ss(page, "03b_ig_consent")
            time.sleep(3)
            # Check for authorize button or auto-redirect
            for t in ["Authorize", "Continue", "계속", "허용"]:
                try:
                    b = page.locator(f'button:has-text("{t}")')
                    if b.count() > 0: b.first.click(); time.sleep(5); print(f"  Auth: {t}"); break
                except: pass
            # May need to handle another login form if session expired
            try:
                if page.locator('input[name="username"]').count() > 0:
                    page.fill('input[name="username"]', USERNAME)
                    page.fill('input[name="password"]', PASSWORD)
                    page.locator('button[type="submit"]').first.click()
                    time.sleep(10)
                    print("  Re-authenticated on Instagram")
            except: pass

        # Wait for redirect to Threads
        time.sleep(5)
        ss(page, "04_threads_state")
        print(f"  Current URL: {page.url}")

        # If not on threads, navigate there
        if "threads.com" not in page.url:
            page.goto("https://www.threads.com/", wait_until="networkidle", timeout=60000)
            time.sleep(5)

        # Verify login state
        page_text = page.evaluate("() => document.body.innerText.substring(0, 300)")
        print(f"  Threads home: {page_text[:150]}")

        # ===== STEP 3: Scrape Profile =====
        print(f"\n=== Step 3: Scrape {PROFILE_URL} ===")

        all_api = []
        def on_resp(response):
            if "api/graphql" in response.url or "graphql" in response.url:
                try: all_api.append(response.text())
                except: pass
        page.on("response", on_resp)

        page.goto(PROFILE_URL, wait_until="networkidle", timeout=60000)
        time.sleep(5)

        # Remove any login popups/overlays via JS
        page.evaluate("""
        () => {
            // Remove modal overlays
            document.querySelectorAll('div[role="dialog"]').forEach(e => e.remove());
            // Remove fixed overlays
            const all = document.querySelectorAll('div');
            all.forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.position === 'fixed' && el.innerText && el.innerText.includes('소통해보세요')) {
                    el.remove();
                }
            });
        }
        """)
        time.sleep(2)

        ss(page, "05_profile")
        page_text = page.evaluate("() => document.body.innerText")
        print(f"  Profile page length: {len(page_text)}")

        # Scroll to load all posts
        prev_h = 0
        stale = 0
        for i in range(300):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            h = page.evaluate("document.body.scrollHeight")
            if i % 20 == 0:
                print(f"  Scroll {i+1}: h={h}, api={len(all_api)}")
            if h == prev_h:
                stale += 1
                if stale >= 10:
                    print(f"  Done at scroll {i+1}")
                    break
            else:
                stale = 0
            prev_h = h

        print(f"\n  API responses: {len(all_api)}")

        # Extract from API
        posts = []
        seen = set()
        for body in all_api:
            try: extract(json.loads(body), posts, seen)
            except: pass

        # Extract from visible text
        vis = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
        for vp in parse_visible(vis):
            s = vp["text"].strip()[:100]
            if s not in seen and len(vp["text"]) > 20:
                posts.append(vp); seen.add(s)

        print(f"  Total posts: {len(posts)}")
        browser.close()

        # Write output
        write_md(posts)


def extract(data, posts, seen, depth=0):
    if depth > 30: return
    if isinstance(data, dict):
        txt = None; ts = None
        for f in ["text", "caption"]:
            if f in data:
                v = data[f]
                if isinstance(v, str) and len(v) > 5: txt = v
                elif isinstance(v, dict) and "text" in v and len(str(v["text"])) > 5: txt = v["text"]
        for f in ["taken_at", "created_at", "timestamp"]:
            if f in data and data[f]: ts = data[f]
        if txt:
            s = txt.strip()[:100]
            if s not in seen: seen.add(s); posts.append({"text": txt, "timestamp": ts})
        for v in data.values():
            if isinstance(v, (dict, list)): extract(v, posts, seen, depth+1)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)): extract(item, posts, seen, depth+1)


def parse_visible(text):
    posts = []; lines = text.split("\n")
    cur = {"lines": [], "date": None}
    skip = ["로그인", "팔로워", "팔로우", "스레드", "답글", "미디어", "리포스트",
            "Instagram", "©", "약관", "개인정보", "쿠키", "좋아요", "공유", "더 보기"]
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln == "re.branding96":
            if cur["lines"]:
                t = "\n".join(cur["lines"]).strip()
                if len(t) > 10: posts.append({"text": t, "timestamp": cur.get("date")})
            cur = {"lines": [], "date": None}
            if i+1 < len(lines) and re.match(r"\d{4}-\d{2}-\d{2}", lines[i+1].strip()):
                cur["date"] = lines[i+1].strip(); i += 2; continue
            i += 1; continue
        if any(p in ln for p in skip): i += 1; continue
        if ln and not re.match(r"^\d+$", ln): cur["lines"].append(ln)
        i += 1
    if cur["lines"]:
        t = "\n".join(cur["lines"]).strip()
        if len(t) > 10: posts.append({"text": t, "timestamp": cur.get("date")})
    return posts


def write_md(posts):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# 이승석 (@re.branding96) Threads 게시글 모음\n\n")
        f.write(f"> 크롤링 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"> 프로필: {PROFILE_URL}\n")
        f.write(f"> 총 게시글 수: {len(posts)}개\n\n---\n\n")
        for i, post in enumerate(posts, 1):
            f.write(f"## 게시글 {i}")
            ts = post.get("timestamp")
            if ts:
                if isinstance(ts, (int, float)) and ts > 1e9:
                    ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
                f.write(f" ({ts})")
            f.write(f"\n\n{post['text'].strip()}\n\n---\n\n")
    print(f"\nSaved {len(posts)} posts to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
