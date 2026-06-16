# ============================================================================
# Agent 12 — Cisco Pulse
# Monitors Cisco PSIRT security advisories, ACI/NDFC release notes,
# DevNet blog. Weekly digest email for Cisco Solution Architects.
# ============================================================================
import asyncio, datetime, logging, re, html as html_lib
from xml.etree import ElementTree as ET
import httpx
from database import save_agent_data, get_agent_data, get_config
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

log = logging.getLogger("cisco_pulse")

FEEDS = [
    {
        "id": "psirt",
        "name": "Cisco Security Advisories",
        "url": "https://tools.cisco.com/security/center/psirt.rss",
        "category": "security",
        "icon": "🔒",
    },
    {
        "id": "devnet",
        "name": "Cisco DevNet Blog",
        "url": "https://blogs.cisco.com/developer/feed",
        "category": "devnet",
        "icon": "⚙",
    },
    {
        "id": "cloud",
        "name": "Cisco Cloud & Network",
        "url": "https://blogs.cisco.com/networking/feed",
        "category": "networking",
        "icon": "☁",
    },
    {
        "id": "datacenter",
        "name": "Cisco Data Center Blog",
        "url": "https://blogs.cisco.com/datacenter/feed",
        "category": "datacenter",
        "icon": "🏢",
    },
    {
        "id": "security",
        "name": "Cisco Security Blog",
        "url": "https://blogs.cisco.com/security/feed",
        "category": "security",
        "icon": "🔒",
    },
    {
        "id": "innovation",
        "name": "Cisco Innovation Blog",
        "url": "https://blogs.cisco.com/innovation/feed",
        "category": "news",
        "icon": "🚀",
    },
    {
        "id": "newsroom",
        "name": "Cisco Newsroom & Events",
        "url": "https://newsroom.cisco.com/c/r/newsroom/en/us/rss.xml",
        "category": "news",
        "icon": "📰",
    },
]

# Keywords most relevant to a Cisco ACI/NDFC/Nexus SA
PRIORITY_KEYWORDS = [
    "ACI", "NDFC", "Nexus", "APIC", "VXLAN", "BGP EVPN", "Nexus 9", "N9K",
    "NX-OS", "Data Center", "fabric", "spine", "leaf", "overlay", "underlay",
    "CVE", "critical", "high severity", "remote code", "authentication bypass",
    "Intersight", "UCS", "HyperFlex", "9300", "9500",
    "AI", "Hypershield", "HyperFabric", "Silicon One", "AI POD", "GPU", "AI infrastructure",
    "Nexus Dashboard", "Cisco Live", "keynote", "announcement", "launch",
]

# Conference / event / product-announcement signals — surfaced as a separate
# "Conferences & News" stream on top of the security/advisory feed.
EVENT_KEYWORDS = [
    "cisco live", "ciscolive", "keynote", "conference", "announce", "announced",
    "announcement", "unveil", "unveiled", "launch", "launches", "general availability",
    "now available", "introduc", "partner summit", "rsac", "mwc", "webinar", "event",
]

SEVERITY_KEYWORDS = {
    "critical": ["critical", "remote code execution", "unauthenticated", "9.0", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "10.0"],
    "high":     ["high", "privilege escalation", "sql injection", "8.", "7.5", "7.6", "7.7", "7.8", "7.9"],
    "medium":   ["medium", "information disclosure", "denial of service", "5.", "6."],
    "low":      ["low", "cosmetic", "minor"],
}

def _parse_feed(xml_text: str, feed: dict) -> list[dict]:
    """Parse RSS/Atom feed into normalized items."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item"):
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link")  or "").strip()
            desc    = html_lib.unescape(re.sub(r"<[^>]+>", "", item.findtext("description") or "")).strip()[:400]
            pubdate = (item.findtext("pubDate") or "").strip()[:30]
            items.append({"title": title, "link": link, "desc": desc, "date": pubdate, "category": feed["category"], "source": feed["name"], "icon": feed["icon"]})

        # Atom
        if not items:
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                summary = html_lib.unescape(re.sub(r"<[^>]+>", "", entry.findtext("atom:summary", namespaces=ns) or "")).strip()[:400]
                pubdate = (entry.findtext("atom:updated", namespaces=ns) or "").strip()[:30]
                items.append({"title": title, "link": link, "desc": summary, "date": pubdate, "category": feed["category"], "source": feed["name"], "icon": feed["icon"]})
    except Exception as e:
        log.warning(f"Feed parse error ({feed['id']}): {e}")
    return items

def _score_item(item: dict) -> tuple[int, str]:
    """Score relevance and severity of an item."""
    combined = (item["title"] + " " + item["desc"]).lower()
    severity = "info"
    for sev, kws in SEVERITY_KEYWORDS.items():
        if any(k.lower() in combined for k in kws):
            severity = sev
            break
    priority_score = sum(3 for k in PRIORITY_KEYWORDS if k.lower() in combined)
    sev_score = {"critical": 100, "high": 60, "medium": 30, "low": 10, "info": 5}[severity]
    return priority_score + sev_score, severity

async def _fetch_feed(feed: dict, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(feed["url"], timeout=15, follow_redirects=True)
        r.raise_for_status()
        items = _parse_feed(r.text, feed)
        # Score and annotate
        scored = []
        for item in items[:30]:
            score, severity = _score_item(item)
            combined = (item["title"] + " " + item["desc"]).lower()
            is_event = item.get("category") == "news" or any(k in combined for k in EVENT_KEYWORDS)
            if is_event:
                score += 20
            scored.append({**item, "score": score, "severity": severity, "event": is_event})
        return scored
    except Exception as e:
        log.warning(f"Feed fetch failed ({feed['id']}): {e}")
        return []

async def build_llm_commentary(items: list, events: list = None) -> str:
    if not items and not events:
        return "No Cisco advisories or blog posts retrieved this week."
    lines = [f"[{i['severity'].upper()}] {i['title']} ({i['source']})" for i in (items or [])[:6]]
    ev_lines = [f"[EVENT] {e['title']} ({e['source']})" for e in (events or [])[:4]]
    block = chr(10).join(lines + ev_lines)
    prompt = f"""You are a Cisco ACI/NDFC Solution Architect reviewing this week's Cisco security advisories, blog posts, and conference/product news. Summarize the most important items as 3-5 bullet points. Each bullet starts with '• ' on its own line, max 12 words, crisp and specific. Focus on anything affecting ACI, NDFC, Nexus 9K, NX-OS, or AI/data-center infrastructure; call out major Cisco Live / conference announcements or product launches and critical CVEs by number. No paragraphs, no intro/outro text. /no_think

{block}"""
    try:
        return await generate_completion(prompt, agent_id="cisco_pulse")
    except Exception:
        return "Several Cisco advisories, updates, and announcements were retrieved this week. Review critical and high severity items first."

async def cisco_pulse_job():
    log.info("Cisco Pulse starting")
    orchestrator.update_agent_status("cisco_pulse", "running")
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 CiscoPulse/1.0"}) as client:
            results = await asyncio.gather(*[_fetch_feed(f, client) for f in FEEDS], return_exceptions=True)

        all_items = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)

        # Deduplicate by title similarity, sort by score
        seen_titles = set()
        unique = []
        for item in sorted(all_items, key=lambda x: x.get("score", 0), reverse=True):
            t = item["title"].lower()[:60]
            if t not in seen_titles:
                seen_titles.add(t)
                unique.append(item)

        critical = [i for i in unique if i["severity"] == "critical"]
        high     = [i for i in unique if i["severity"] == "high"]
        medium   = [i for i in unique if i["severity"] == "medium"]
        other    = [i for i in unique if i["severity"] not in ("critical","high","medium")]

        top_items = (critical + high + medium)[:20]
        events = [i for i in unique if i.get("event")][:12]
        commentary = await build_llm_commentary(top_items[:6], events[:4])

        now = datetime.datetime.now()
        payload = {
            "pulse": {
                "all_items":   unique[:50],
                "critical":    critical,
                "high":        high,
                "medium":      medium,
                "other":       other[:10],
                "events":      events,
                "commentary":  commentary,
                "total":       len(unique),
                "generated_at": now.strftime("%Y-%m-%d %H:%M"),
                "week_of":     now.strftime("Week of %B %-d, %Y"),
            }
        }
        save_agent_data("cisco_pulse", payload)
        orchestrator.update_agent_status("cisco_pulse", "idle")

        # Send weekly digest
        recipient = get_config("recipient", "")
        if recipient:
            html = _build_email(payload["pulse"])
            send_html_email(recipient, f"◈ Cisco Pulse — {payload['pulse']['week_of']}", html)

        log.info(f"Cisco Pulse complete — {len(unique)} items ({len(critical)} critical, {len(high)} high)")
    except Exception as e:
        log.error(f"Cisco Pulse error: {e}", exc_info=True)
        orchestrator.update_agent_status("cisco_pulse", "error", str(e))
        raise

SEV_COLORS = {
    "critical": ("#dc2626", "#fef2f2"),
    "high":     ("#d97706", "#fffbeb"),
    "medium":   ("#2563eb", "#eff6ff"),
    "low":      ("#6b7280", "#f9fafb"),
    "info":     ("#6b7280", "#f9fafb"),
}

def _item_rows(items: list, limit=8) -> str:
    rows = ""
    for item in items[:limit]:
        fc, bg = SEV_COLORS.get(item["severity"], ("#6b7280", "#f9fafb"))
        rows += f"""
        <div style='padding:12px 0;border-bottom:1px solid #f0f0f0'>
          <div style='display:flex;align-items:flex-start;gap:10px'>
            <span style='font-size:10px;font-weight:700;color:{fc};background:{bg};padding:2px 8px;border-radius:4px;white-space:nowrap;flex-shrink:0;margin-top:2px'>{item['severity'].upper()}</span>
            <div>
              <a href='{item.get("link","")}' style='font-size:13px;font-weight:600;color:#1a1a2e;text-decoration:none'>{item['icon']} {item['title']}</a>
              <div style='font-size:11px;color:#888;margin-top:2px'>{item['source']} · {item.get("date","")[:16]}</div>
              {f'<div style="font-size:12px;color:#555;margin-top:4px;line-height:1.4">{item["desc"][:200]}…</div>' if item.get("desc") else ""}
            </div>
          </div>
        </div>"""
    return rows

def _build_email(pulse: dict) -> str:
    events_section = ""
    if pulse.get("events"):
        events_section = f"""
        <div style='background:#f5f3ff;border-left:4px solid #7c3aed;padding:14px 20px;margin-bottom:16px;border-radius:0 8px 8px 0'>
          <div style='font-size:12px;font-weight:700;color:#7c3aed;margin-bottom:8px'>📰 CONFERENCES &amp; PRODUCT NEWS</div>
          {_item_rows(pulse['events'], 5)}
        </div>"""
    critical_section = ""
    if pulse["critical"]:
        critical_section = f"""
        <div style='background:#fef2f2;border-left:4px solid #dc2626;padding:14px 20px;margin-bottom:16px;border-radius:0 8px 8px 0'>
          <div style='font-size:12px;font-weight:700;color:#dc2626;margin-bottom:8px'>🔴 CRITICAL ADVISORIES — ACTION REQUIRED</div>
          {_item_rows(pulse['critical'], 5)}
        </div>"""

    return f"""<!DOCTYPE html><html><body style='font-family:Helvetica,sans-serif;background:#f6f7f9;margin:0;padding:0'>
<div style='max-width:640px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb'>
  <div style='background:linear-gradient(135deg,#0a3d5c,#0d9488);padding:26px 32px'>
    <div style='font-size:22px;font-weight:800;color:#fff'>◈ Cisco Pulse</div>
    <div style='font-size:13px;color:#99f6e4;margin-top:4px'>{pulse.get("week_of","—")} · ACI · NDFC · PSIRT · Conferences &amp; News</div>
  </div>
  <div style='padding:20px 32px;background:#f0fdfa;border-bottom:1px solid #e5e7eb'>
    <div style='font-size:14px;line-height:1.6;color:#134e4a'>{pulse.get("commentary","")}</div>
    <div style='font-size:11px;color:#888;margin-top:8px'>{pulse.get("total",0)} items fetched · {len(pulse.get("critical",[]))} critical · {len(pulse.get("high",[]))} high</div>
  </div>
  <div style='padding:20px 32px;border-bottom:1px solid #e5e7eb'>
    {events_section}
    {critical_section}
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px'>HIGH SEVERITY</div>
    {_item_rows(pulse.get("high",[]), 6)}
    <div style='font-size:12px;font-weight:700;color:#8a909c;text-transform:uppercase;letter-spacing:.5px;margin:16px 0 12px'>NOTABLE UPDATES</div>
    {_item_rows(pulse.get("medium",[]) + pulse.get("other",[]), 6)}
  </div>
  <div style='padding:14px 32px;text-align:center;font-size:11px;color:#aeb4bf'>
    Cisco Pulse · Multi-Agent Platform · For Vzure Solutions SA use
  </div>
</div></body></html>"""

def email_preview() -> dict:
    data = get_agent_data("cisco_pulse") or {}
    pulse = data.get("pulse", {})
    if not pulse:
        return {"html": "<p>No Cisco Pulse data yet. Run the agent first.</p>"}
    return {"html": _build_email(pulse)}
