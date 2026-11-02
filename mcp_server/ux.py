"""
UI / UX / accessibility / performance / visual checks against a live Page.

Every function here takes a Playwright sync Page and must run on the browser
thread (see browser.BrowserSession.call).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import Page

from config.settings import settings
from mcp_server.browser import DESKTOP, locate
from pages.base_page import BasePage
from utils.assertions import FULL_ACCOUNT_RE

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "reports" / "screenshots"
BASELINES = ROOT / "reports" / "baselines"
CACHE = Path(__file__).resolve().parent / ".cache"

AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"

VIEWPORTS = {
    "mobile": {"width": 375, "height": 812},
    "tablet": {"width": 768, "height": 1024},
    "laptop": {"width": 1280, "height": 800},
    "desktop": DESKTOP,
}


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")[:80] or "page"


def screenshot(page: Page, name: str, full_page: bool = False) -> Path:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug(name)}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path


# ------------------------------------------------------------------- snapshot
SNAPSHOT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = s => (s || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const labelOf = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    const p = el.closest('label'); return p ? clean(p.innerText) : '';
  };
  const nameOf = el => {
    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    const btnValue = el.tagName === 'INPUT' && ['button', 'submit'].includes(el.type) ? el.value : '';
    return clean(el.getAttribute('aria-label') || (isInput ? '' : el.innerText) || btnValue ||
                 el.placeholder || el.title || el.name || el.id);
  };
  const items = [];
  document.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],' +
                            '[role=menuitem],[role=checkbox],[role=combobox],[contenteditable=true]').forEach(el => {
    if (items.length >= 150 || !vis(el) || el.type === 'hidden') return;
    const it = { tag: el.tagName.toLowerCase(), name: nameOf(el) };
    if (el.type && el.tagName !== 'BUTTON') it.type = el.type;
    if (el.getAttribute('role')) it.role = el.getAttribute('role');
    const lbl = labelOf(el); if (lbl) it.label = lbl;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') it.disabled = true;
    if (el.required) it.required = true;
    if (el.tagName === 'A') it.href = el.getAttribute('href');
    items.push(it);
  });
  const headings = [...document.querySelectorAll('h1,h2,h3')].filter(vis)
    .map(h => `${h.tagName}: ${clean(h.innerText)}`).slice(0, 30);
  return { title: document.title, headings, interactive: items,
           text: document.body.innerText.replace(/\n{3,}/g, '\n\n').slice(0, 4000) };
}
"""


def snapshot(page: Page) -> dict:
    data = page.evaluate(SNAPSHOT_JS)
    return {"url": page.url, **data, "toast": BasePage(page).toast_text()}


# -------------------------------------------------------------- accessibility
FALLBACK_A11Y_JS = r"""
() => {
  const out = [];
  const add = (id, impact, help, els) => { if (els.length) out.push({ id, impact, help, nodes: els.length,
    targets: els.slice(0, 3).map(e => e.outerHTML.slice(0, 120)) }); };
  add('image-alt', 'critical', 'Images must have alt text', [...document.querySelectorAll('img:not([alt])')]);
  add('label', 'critical', 'Form inputs must have a label', [...document.querySelectorAll(
      'input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea')].filter(el =>
      !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.closest('label') &&
      !(el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`))));
  add('button-name', 'critical', 'Buttons must have discernible text', [...document.querySelectorAll(
      'button,[role=button]')].filter(b => !(b.innerText.trim() || b.getAttribute('aria-label') || b.title)));
  add('link-name', 'serious', 'Links must have discernible text', [...document.querySelectorAll('a[href]')]
      .filter(a => !(a.innerText.trim() || a.getAttribute('aria-label') || a.querySelector('img[alt]'))));
  add('html-has-lang', 'serious', '<html> must have a lang attribute',
      document.documentElement.lang ? [] : [document.documentElement]);
  add('document-title', 'serious', 'Document must have a title', document.title ? [] : [document.documentElement]);
  const ids = {}; document.querySelectorAll('[id]').forEach(e => (ids[e.id] = (ids[e.id] || []).concat(e)));
  add('duplicate-id', 'minor', 'IDs must be unique', Object.values(ids).filter(a => a.length > 1).map(a => a[0]));
  let last = 0; const skipped = [];
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => { const l = +h.tagName[1];
    if (last && l > last + 1) skipped.push(h); last = l; });
  add('heading-order', 'moderate', 'Heading levels should only increase by one', skipped);
  return out;
}
"""


def _axe_source() -> str | None:
    cached = CACHE / "axe.min.js"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    try:
        r = requests.get(AXE_URL, timeout=20)
        r.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(r.text, encoding="utf-8")
        return r.text
    except requests.RequestException:
        return None


def accessibility_audit(page: Page, standard: str = "wcag21aa") -> dict:
    tags = {"wcag2a": ["wcag2a"], "wcag2aa": ["wcag2a", "wcag2aa"],
            "wcag21aa": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
            "wcag22aa": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]}.get(standard, ["wcag2a", "wcag2aa"])
    src = _axe_source()
    if src:
        page.add_script_tag(content=src)
        result = page.evaluate(
            """async (tags) => {
                const r = await axe.run(document, { runOnly: { type: 'tag', values: tags.concat(['best-practice']) } });
                return { violations: r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help,
                           helpUrl: v.helpUrl, nodes: v.nodes.length,
                           targets: v.nodes.slice(0, 3).map(n => n.target.join(' ')) })),
                         passes: r.passes.length, incomplete: r.incomplete.length };
            }""", tags)
        engine = "axe-core 4.10.2"
    else:
        result = {"violations": page.evaluate(FALLBACK_A11Y_JS)}
        engine = "built-in fallback (axe-core could not be downloaded)"
    order = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
    result["violations"].sort(key=lambda v: order.get(v.get("impact"), 4))
    counts: dict[str, int] = {}
    for v in result["violations"]:
        counts[v.get("impact") or "unknown"] = counts.get(v.get("impact") or "unknown", 0) + 1
    return {"url": page.url, "engine": engine, "standard": standard, "by_impact": counts, **result}


# ----------------------------------------------------------------- responsive
RESPONSIVE_JS = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const sel = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '');
  const offenders = [];
  if (document.documentElement.scrollWidth > vw + 1) {
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > vw + 1 && getComputedStyle(el).position !== 'fixed') {
        offenders.push({ el: sel(el), right: Math.round(r.right) }); if (offenders.length >= 10) break; }
    }
  }
  const small = [];
  document.querySelectorAll('a[href],button,input:not([type=hidden]),select,[role=button]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24) && small.length < 15)
      small.push({ el: sel(el), w: Math.round(r.width), h: Math.round(r.height) });
  });
  let tinyText = 0;
  document.querySelectorAll('p,span,a,td,th,li,label,button,div').forEach(el => {
    if ([...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) &&
        parseFloat(getComputedStyle(el).fontSize) < 12) tinyText++;
  });
  return { viewport_width: vw, page_width: document.documentElement.scrollWidth,
           horizontal_overflow: document.documentElement.scrollWidth > vw + 1,
           overflowing_elements: offenders, small_tap_targets: small, text_under_12px: tinyText };
}
"""


def responsive_check(page: Page, viewports: list[str] | None = None) -> dict:
    names = viewports or list(VIEWPORTS)
    results = []
    try:
        for name in names:
            size = VIEWPORTS.get(name)
            if not size:
                m = re.fullmatch(r"(\d+)x(\d+)", name)
                if not m:
                    continue
                size = {"width": int(m[1]), "height": int(m[2])}
            page.set_viewport_size(size)
            page.wait_for_timeout(600)
            data = page.evaluate(RESPONSIVE_JS)
            data["viewport"] = f"{name} {size['width']}x{size['height']}"
            data["screenshot"] = str(screenshot(page, f"responsive_{name}", full_page=True))
            issues = []
            if data["horizontal_overflow"]:
                issues.append("horizontal scroll")
            if data["small_tap_targets"] and size["width"] < 1024:
                issues.append(f"{len(data['small_tap_targets'])} tap targets < 24px")
            if data["text_under_12px"]:
                issues.append(f"{data['text_under_12px']} text elements < 12px")
            data["issues"] = issues
            results.append(data)
    finally:
        page.set_viewport_size(DESKTOP)
    return {"url": page.url, "results": results}


# ---------------------------------------------------------------- performance
PERF_JS = r"""
async () => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, Math.round(p.startTime)]));
  const observe = (type, fold, init) => new Promise(res => { let acc = init;
    try { new PerformanceObserver(l => { for (const e of l.getEntries()) acc = fold(acc, e); })
            .observe({ type, buffered: true }); } catch (e) {}
    setTimeout(() => res(acc), 400); });
  const lcp = await observe('largest-contentful-paint', (_, e) => e, null);
  const cls = await observe('layout-shift', (s, e) => e.hadRecentInput ? s : s + e.value, 0);
  const res = performance.getEntriesByType('resource');
  // transferSize is 0 for cache hits, so fall back to the encoded body size
  const size = r => r.transferSize || r.encodedBodySize || 0;
  const view = r => ({ url: r.name.slice(0, 160), kb: Math.round(size(r) / 1024), ms: Math.round(r.duration) });
  return {
    ttfb_ms: Math.round((nav.responseStart || 0) - (nav.requestStart || 0)),
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
    load_ms: Math.round(nav.loadEventEnd || 0),
    first_contentful_paint_ms: paint['first-contentful-paint'] ?? null,
    lcp_ms: lcp ? Math.round(lcp.startTime) : null,
    lcp_element: lcp && lcp.element ? lcp.element.tagName.toLowerCase() : null,
    cls: Math.round(cls * 1000) / 1000,
    resource_count: res.length,
    transfer_kb: Math.round(res.reduce((a, r) => a + size(r), 0) / 1024),
    dom_nodes: document.getElementsByTagName('*').length,
    largest: [...res].sort((a, b) => size(b) - size(a)).slice(0, 5).map(view),
    slowest: [...res].sort((a, b) => b.duration - a.duration).slice(0, 5).map(view),
  };
}
"""

# Core Web Vitals "good" thresholds
BUDGET = {"ttfb_ms": 800, "first_contentful_paint_ms": 1800, "lcp_ms": 2500, "cls": 0.1,
          "load_ms": 5000, "transfer_kb": 3000, "dom_nodes": 1500}


def performance_metrics(page: Page, reload: bool = True) -> dict:
    if reload:
        page.reload(wait_until="load")
        page.wait_for_timeout(500)
    m = page.evaluate(PERF_JS)
    over = {k: f"{m[k]} > {limit}" for k, limit in BUDGET.items()
            if isinstance(m.get(k), (int, float)) and m[k] > limit}
    return {"url": page.url, "metrics": m, "over_budget": over, "budget": BUDGET}


# ----------------------------------------------------------------- link check
def broken_links(page: Page, same_origin_only: bool = True, limit: int = 80) -> dict:
    urls = page.evaluate("""() => [...new Set([
        ...[...document.querySelectorAll('a[href]')].map(a => a.href),
        ...[...document.querySelectorAll('img[src],script[src]')].map(e => e.src),
        ...[...document.querySelectorAll('link[rel=stylesheet][href]')].map(e => e.href)])]""")
    origin = urlparse(page.url).netloc
    urls = [u for u in urls if u.startswith("http") and (not same_origin_only or urlparse(u).netloc == origin)]
    checked, broken = 0, []
    for u in urls[:limit]:
        checked += 1
        try:
            r = page.context.request.head(u, timeout=15000, max_redirects=5)
            if r.status in (405, 501):
                r = page.context.request.get(u, timeout=15000, max_redirects=5)
            if r.status >= 400:
                broken.append({"url": u, "status": r.status})
        except Exception as exc:  # noqa: BLE001
            broken.append({"url": u, "error": str(exc).splitlines()[0][:150]})
    return {"url": page.url, "found": len(urls), "checked": checked, "broken": broken}


# ------------------------------------------------------------ visual regression
def visual_compare(page: Page, name: str, full_page: bool = True, mask: list[str] | None = None,
                   threshold_pct: float = 0.5, update_baseline: bool = False) -> dict:
    from PIL import Image, ImageChops

    BASELINES.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    base = BASELINES / f"{slug(name)}.png"
    current = SHOTS / f"{slug(name)}_current.png"
    diff_path = SHOTS / f"{slug(name)}_diff.png"
    page.screenshot(path=str(current), full_page=full_page, animations="disabled",
                    mask=[locate(page, m) for m in (mask or [])])

    if update_baseline or not base.exists():
        base.write_bytes(current.read_bytes())
        return {"name": name, "baseline": str(base), "status": "baseline saved",
                "note": "Run again later to compare against this baseline."}

    a, b = Image.open(base).convert("RGB"), Image.open(current).convert("RGB")
    size = (max(a.width, b.width), max(a.height, b.height))
    pad = lambda im: im if im.size == size else _padded(im, size)  # noqa: E731
    a, b = pad(a), pad(b)
    mask_img = ImageChops.difference(a, b).convert("L").point(lambda p: 255 if p > 25 else 0)
    changed = mask_img.histogram()[255]
    pct = round(changed / (size[0] * size[1]) * 100, 3)
    overlay = Image.blend(b, Image.new("RGB", size, "white"), 0.6)
    overlay.paste(Image.new("RGB", size, (255, 0, 0)), mask=mask_img)
    overlay.save(diff_path)
    return {"name": name, "diff_pct": pct, "threshold_pct": threshold_pct,
            "passed": pct <= threshold_pct, "size_changed": Image.open(base).size != Image.open(current).size,
            "changed_region": mask_img.getbbox(), "baseline": str(base), "current": str(current),
            "diff_image": str(diff_path)}


def _padded(im, size):
    from PIL import Image
    canvas = Image.new("RGB", size, (255, 0, 255))
    canvas.paste(im, (0, 0))
    return canvas


# --------------------------------------------------------------- UI security
def ui_security_scan(page: Page, console: list[dict]) -> dict:
    checks = []

    def add(name, ok, detail="", level="fail"):
        checks.append({"check": name, "result": "pass" if ok else level, "detail": detail})

    add("served over HTTPS", page.url.startswith("https://"), page.url)

    session_cookies = [c for c in page.context.cookies()
                       if any(k in c["name"].lower() for k in ("sess", "token", "auth", "jwt", "sid"))]
    for c in session_cookies:
        weak = [f for f, ok in (("HttpOnly", c.get("httpOnly")), ("Secure", c.get("secure")),
                                ("SameSite", c.get("sameSite") in ("Lax", "Strict"))) if not ok]
        add(f"cookie {c['name']} flags", not weak, "missing " + ", ".join(weak) if weak else "")
    if not session_cookies:
        add("session cookie flags", True, "no session-like cookie (token likely header-based)")

    storage = page.evaluate("""() => { const grab = s => { const o = {}; for (let i = 0; i < s.length; i++) {
        const k = s.key(i); o[k] = s.getItem(k); } return o; };
        return { local: grab(localStorage), session: grab(sessionStorage) }; }""")
    blob = str(storage).lower()
    hits = [w for w in ("password", "otp", "cvv", "'pin'") if w in blob]
    add("no passwords/OTPs in web storage", not hits, ", ".join(hits))
    add("no full account numbers in web storage", not FULL_ACCOUNT_RE.search(str(storage)))
    jwt_keys = [k for area in storage.values() for k, v in area.items()
                if isinstance(v, str) and re.search(r"eyJ[\w-]+\.[\w-]+\.", v)]
    add("auth token not in JS-readable storage", not jwt_keys,
        f"JWT found under {jwt_keys} (readable by any XSS)" if jwt_keys else "", level="warn")

    leaked = [m["text"][:120] for m in console if re.search(r"password|otp|bearer |eyJ[\w-]+\.", m["text"], re.I)]
    add("no secrets in console output", not leaked, "; ".join(leaked[:3]))

    mixed = page.evaluate("() => performance.getEntriesByType('resource').map(r => r.name).filter(u => u.startsWith('http:'))")
    add("no mixed (http) content", not mixed, "; ".join(mixed[:5]))

    # only an *explicit* method="get" counts - SPA forms omit it and submit via JS
    insecure_forms = page.evaluate("""() => [...document.querySelectorAll('form')].filter(f =>
        f.querySelector('input[type=password]') && ((f.getAttribute('method') || '').toLowerCase() === 'get' ||
        (f.getAttribute('action') || '').startsWith('http:'))).length""")
    add("password forms not sent via GET/http", not insecure_forms, f"{insecure_forms} form(s)")

    counts: dict[str, int] = {}
    for c in checks:
        counts[c["result"]] = counts.get(c["result"], 0) + 1
    return {"url": page.url, "summary": counts, "checks": checks}


# ------------------------------------------------------------ input probing
def input_probe(page: Page, field: str, values: list[str], submit: str | None,
                dialogs, reload_between: bool = False) -> dict:
    """Fill `field` with each value, submit, and record what the app did."""
    bp = BasePage(page)
    start_url = page.url
    results = []
    for value in values:
        if reload_between and page.url != start_url:
            page.goto(start_url)
        elif reload_between:
            page.reload()
        before_dialogs = len(dialogs)
        el = locate(page, field)
        el.fill(value)
        if submit:
            locate(page, submit).click()
        else:
            el.press("Enter")
        page.wait_for_timeout(800)
        el = locate(page, field)
        native = el.evaluate("e => e.validationMessage || ''") if el.count() else ""
        invalid = el.get_attribute("aria-invalid") if el.count() else None
        errors = page.evaluate("""() => [...document.querySelectorAll(
            '.error,.invalid-feedback,[class*=error],[class*=helper-text],[role=alert]')]
            .filter(e => e.offsetParent && e.innerText.trim()).slice(0, 3).map(e => e.innerText.trim().slice(0, 150))""")
        results.append({
            "value": value,
            "accepted_without_error": not (native or invalid == "true" or errors or bp.toast_text()),
            "native_validation": native or None,
            "aria_invalid": invalid,
            "error_texts": errors,
            "toast": bp.toast_text() or None,
            "navigated_to": page.url if page.url != start_url else None,
            "script_dialog_fired": list(dialogs)[before_dialogs:] or None,
        })
    return {"field": field, "url": start_url, "results": results}
