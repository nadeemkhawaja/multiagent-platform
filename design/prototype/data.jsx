// ============================================================================
// data.jsx — mock datasets + the live simulation store (Sim)
// One interval random-walks resource metrics, rotates the LLM semaphore,
// counts down agent schedules, and emits events. Components subscribe via
// useSim(). Demo hooks: Sim.spike() and Sim.crash(id) drive the alarm/restart.
// ============================================================================

// ---- agent accent palette ----
const AGENT_COLOR = {
  orchestrator: "#7c5cf6",
  "ai-times": "#e5484d",
  mailman: "#2f6feb",
  wolf: "#16a34a",
  compass: "#f59e0b",
  aegis: "#0d9488",
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const rnd = (a, b) => a + Math.random() * (b - a);
const nowHM = () => {
  const d = new Date();
  return d.toTimeString().slice(0, 5);
};

// ---------------------------------------------------------------------------
// AI-Times — videos
// ---------------------------------------------------------------------------
const AI_NEWS = [
  { id: "n1", title: "Qwen3 235B benchmarks leak ahead of official release", ch: "AI Frontier", dur: "12:04", date: "5h ago", views: "184K", c: "#e5484d" },
  { id: "n2", title: "Open-weights models close the gap with frontier labs in 2026", ch: "The Gradient", dur: "18:41", date: "9h ago", views: "97K", c: "#2f6feb" },
  { id: "n3", title: "On-device agents: the new battleground for local inference", ch: "Latent Space", dur: "24:17", date: "14h ago", views: "212K", c: "#16a34a" },
  { id: "n4", title: "Why every startup is shipping multi-agent orchestration", ch: "Sequoia AI", dur: "09:52", date: "20h ago", views: "63K", c: "#f59e0b" },
  { id: "n5", title: "Regulators draft new rules for autonomous AI systems", ch: "AI Policy Daily", dur: "15:30", date: "1d ago", views: "41K", c: "#0d9488" },
];
const AI_PEOPLE = [
  { id: "p1", title: "Andrej Karpathy on building software 3.0 with agents", ch: "Lex Fridman", dur: "2:41:09", date: "6h ago", views: "1.2M", c: "#7c5cf6" },
  { id: "p2", title: "Fei-Fei Li: spatial intelligence and the next decade", ch: "No Priors", dur: "58:22", date: "12h ago", views: "284K", c: "#e5484d" },
  { id: "p3", title: "Demis Hassabis on the road to AGI and scientific discovery", ch: "Dwarkesh", dur: "1:34:55", date: "18h ago", views: "512K", c: "#2f6feb" },
  { id: "p4", title: "A founder's guide to local LLMs with the Ollama team", ch: "Cognitive Rev", dur: "1:07:14", date: "22h ago", views: "88K", c: "#16a34a" },
  { id: "p5", title: "Inside a one-person company running 40 agents", ch: "My First Million", dur: "1:12:48", date: "1d ago", views: "156K", c: "#f59e0b" },
];

// ---------------------------------------------------------------------------
// Mailman — categories + inbox
// ---------------------------------------------------------------------------
const MAIL_CATS = [
  { k: "Urgent", n: 3, c: "#e5484d" },
  { k: "Action Required", n: 7, c: "#f59e0b" },
  { k: "Follow-Up", n: 5, c: "#7c5cf6" },
  { k: "Personal", n: 4, c: "#0d9488" },
  { k: "Newsletter", n: 18, c: "#2f6feb" },
  { k: "Notification", n: 22, c: "#94a3b8" },
  { k: "Other", n: 6, c: "#c0c6d0" },
];
const MAILS = [
  { id: "m1", from: "Sarah Chen", email: "sarah@northwind.vc", subj: "Re: term sheet — need answer by EOD", cat: "Urgent", star: true, key: true, sum: "Sarah needs your countersignature on the revised term sheet before close of business; she flags the updated liquidation pref.", t: "08:41" },
  { id: "m2", from: "AWS Billing", email: "no-reply@aws.amazon.com", subj: "Your invoice is now available", cat: "Notification", star: false, key: false, sum: "Monthly AWS invoice of $1,284.50 is ready. No action needed unless disputing.", t: "08:12" },
  { id: "m3", from: "Marcus Webb", email: "marcus@acme.io", subj: "Can we move the 3pm to Thursday?", cat: "Action Required", star: false, key: true, sum: "Marcus requests rescheduling today's 3pm sync to Thursday; asks you to confirm a slot.", t: "07:58" },
  { id: "m4", from: "The Neuron", email: "hello@theneurondaily.com", subj: "🧠 GPT-6 rumors and 4 tools to try", cat: "Newsletter", star: false, key: false, sum: "Daily AI newsletter covering GPT-6 speculation and new agent tooling. Skimmable.", t: "07:30" },
  { id: "m5", from: "Dr. Alvarez", email: "office@bayhealth.com", subj: "Appointment confirmation — June 11", cat: "Personal", star: true, key: false, sum: "Confirms your annual physical for June 11 at 9:15am; arrive 15 min early.", t: "Yesterday" },
  { id: "m6", from: "Priya Nair", email: "priya@acme.io", subj: "Follow-up: design review notes", cat: "Follow-Up", star: false, key: false, sum: "Priya shares notes from the design review and asks for your comments by Friday.", t: "Yesterday" },
  { id: "m7", from: "LinkedIn", email: "notifications@linkedin.com", subj: "You appeared in 14 searches", cat: "Notification", star: false, key: false, sum: "Weekly LinkedIn activity summary. Low priority.", t: "Yesterday" },
  { id: "m8", from: "Jordan Blake", email: "jordan@stripe.com", subj: "Intro to the payments team", cat: "Follow-Up", star: false, key: false, sum: "Jordan offers to introduce you to Stripe's payments team next week.", t: "Yesterday" },
];
const KEY_PEOPLE = ["Sarah Chen", "Marcus Webb", "David Okafor", "Mom"];

// ---------------------------------------------------------------------------
// Wallstreet Wolf — watchlist (20+), FX, metals
// ---------------------------------------------------------------------------
const WATCH = [
  { t: "NVDA", n: "NVIDIA", p: 1284.30, ch: 4.82 },
  { t: "MSFT", n: "Microsoft", p: 498.12, ch: 1.24 },
  { t: "AAPL", n: "Apple", p: 241.55, ch: -0.63 },
  { t: "AMZN", n: "Amazon", p: 224.90, ch: 2.11 },
  { t: "GOOGL", n: "Alphabet", p: 198.44, ch: 0.92 },
  { t: "META", n: "Meta", p: 712.08, ch: 3.45 },
  { t: "TSLA", n: "Tesla", p: 348.77, ch: -3.18 },
  { t: "AMD", n: "AMD", p: 186.20, ch: 5.34 },
  { t: "AVGO", n: "Broadcom", p: 1742.55, ch: 2.88 },
  { t: "NFLX", n: "Netflix", p: 1024.60, ch: -1.42 },
  { t: "JPM", n: "JPMorgan", p: 268.40, ch: 0.51 },
  { t: "V", n: "Visa", p: 342.18, ch: -0.28 },
  { t: "COST", n: "Costco", p: 1058.90, ch: 0.74 },
  { t: "LLY", n: "Eli Lilly", p: 894.22, ch: -2.06 },
  { t: "XOM", n: "Exxon", p: 118.65, ch: 1.93 },
  { t: "JNJ", n: "J&J", p: 162.30, ch: -0.44 },
  { t: "WMT", n: "Walmart", p: 98.74, ch: 0.66 },
  { t: "PLTR", n: "Palantir", p: 142.88, ch: 6.21 },
  { t: "CRM", n: "Salesforce", p: 312.45, ch: -1.77 },
  { t: "ORCL", n: "Oracle", p: 204.16, ch: 2.34 },
  { t: "UBER", n: "Uber", p: 88.92, ch: -2.55 },
  { t: "COIN", n: "Coinbase", p: 312.70, ch: 7.84 },
];
const FX = [
  { p: "EUR/USD", v: 1.0942, ch: 0.18 },
  { p: "USD/JPY", v: 152.34, ch: -0.42 },
  { p: "GBP/USD", v: 1.2785, ch: 0.24 },
  { p: "USD/CHF", v: 0.8841, ch: -0.11 },
];
const METALS = [
  { p: "Gold", sym: "XAU/USD", v: 2418.60, ch: 0.88 },
  { p: "Silver", sym: "XAG/USD", v: 31.42, ch: 1.64 },
];

// ---------------------------------------------------------------------------
// Compass — sector bias, news, key levels
// ---------------------------------------------------------------------------
const SECTORS = [
  { k: "Technology", bias: 64, why: "Semis extend leadership on AI capex; breadth improving." },
  { k: "Energy", bias: 28, why: "Crude firms on supply risk; rotation interest building." },
  { k: "Financials", bias: 12, why: "Yields range-bound; banks await CPI for direction." },
  { k: "Healthcare", bias: -18, why: "GLP-1 names cooling; defensive bid fading." },
  { k: "Consumer", bias: -34, why: "Soft retail prints; discretionary under pressure." },
  { k: "Industrials", bias: 8, why: "Mixed PMIs keep the group neutral near highs." },
];
const NEWS = [
  { src: "Reuters", t: "Fed minutes signal patience as inflation cools toward target", s: "bull", min: "22m" },
  { src: "Bloomberg", t: "Nvidia supplier guides Q3 above estimates on data-center demand", s: "bull", min: "41m" },
  { src: "WSJ", t: "Retail sales miss; consumer caution deepens into summer", s: "bear", min: "1h" },
  { src: "CNBC", t: "Oil jumps 3% on Middle East supply disruption headlines", s: "bull", min: "1h" },
  { src: "FT", t: "Treasury yields steady ahead of Friday's payrolls report", s: "neutral", min: "2h" },
];
const FUTURES = [
  { t: "/ES", n: "E-mini S&P 500", px: 5948.5, piv: 5942, r1: 5967, r2: 5988, s1: 5921, s2: 5896, bias: "bull" },
  { t: "/NQ", n: "E-mini Nasdaq-100", px: 21512, piv: 21470, r1: 21640, r2: 21805, s1: 21305, s2: 21140, bias: "bull" },
];
const LEVELS = [
  { t: "NVDA", px: 1284, piv: 1271, r1: 1308, s1: 1244, bias: "bull" },
  { t: "MSFT", px: 498, piv: 495, r1: 506, s1: 487, bias: "bull" },
  { t: "AAPL", px: 241, piv: 243, r1: 248, s1: 236, bias: "bear" },
  { t: "AMZN", px: 225, piv: 222, r1: 229, s1: 217, bias: "bull" },
  { t: "GOOGL", px: 198, piv: 197, r1: 203, s1: 192, bias: "neutral" },
  { t: "META", px: 712, piv: 704, r1: 726, s1: 688, bias: "bull" },
  { t: "TSLA", px: 349, piv: 354, r1: 366, s1: 338, bias: "bear" },
  { t: "AMD", px: 186, piv: 182, r1: 191, s1: 176, bias: "bull" },
  { t: "AVGO", px: 1743, piv: 1722, r1: 1780, s1: 1688, bias: "bull" },
  { t: "NFLX", px: 1025, piv: 1031, r1: 1058, s1: 1004, bias: "neutral" },
];

// ---------------------------------------------------------------------------
// Aegis — reputation mentions
// ---------------------------------------------------------------------------
const MENTIONS = [
  { id: "g1", src: "Reddit", sub: "r/startups", author: "u/throwaway_842", risk: "high", sent: -78,
    text: "Heard the founder of Northwind basically lied about their revenue numbers to investors. Anyone else seeing red flags?",
    why: "Unverified accusation of fraud naming you directly — defamatory and spreading.",
    reply: "Hi — I run Northwind. Happy to clear this up transparently: our revenue figures are third-party audited and I'm glad to walk through them. DMs open." },
  { id: "g2", src: "X", sub: "@techgossip", author: "@techgossip", risk: "med", sent: -42,
    text: "Northwind's new pricing is a cash grab. Doubling prices overnight with no warning is wild.",
    why: "Negative sentiment about pricing gaining traction (340 reposts).",
    reply: "We hear you — the rollout communication missed the mark. Existing customers keep legacy pricing for 12 months; details in your inbox today." },
  { id: "g3", src: "News", sub: "TechCrunch comments", author: "Anon", risk: "low", sent: -15,
    text: "Their support response time has slipped lately. Used to be great.",
    why: "Mild service complaint; worth a courteous acknowledgement.",
    reply: "Thanks for the honest feedback — we added two support engineers this month and are watching response times closely." },
  { id: "g4", src: "Mastodon", sub: "fosstodon.org", author: "@dev_anna", risk: "low", sent: 34,
    text: "Actually really impressed with how the Northwind team handled the outage. Transparent post-mortem.",
    why: "Positive mention — consider amplifying / thanking.",
    reply: "Thank you, that means a lot. The post-mortem is public here and we're shipping the reliability fixes this sprint." },
];

// ============================================================================
// Sim — the live store
// ============================================================================
const Sim = {
  subs: new Set(),
  state: null,

  init() {
    const mkHist = (v) => Array.from({ length: 24 }, () => clamp(v + rnd(-6, 6), 2, 98));
    this.state = {
      uptimeS: 4 * 86400 + 12 * 3600,
      res: {
        cpu: { v: 38, hist: mkHist(36) },
        ram: { v: 61, hist: mkHist(60) },
        disk: { v: 44, hist: Array(24).fill(44) },
        gpu: { v: 72, hist: mkHist(60) },
      },
      threads: 42,
      agents: [
        { id: "ai-times", n: "AI-Times", glyph: "▶", desc: "AI YouTube digest", status: "idle", cpu: 2, mem: 180, nextS: 51240, schedule: "Daily · 08:00", restarts: 0 },
        { id: "mailman", n: "Mailman", glyph: "✉", desc: "Gmail triage", status: "running", cpu: 11, mem: 240, nextS: 780, schedule: "Every 15 min", restarts: 0 },
        { id: "wolf", n: "Wallstreet Wolf", glyph: "$", desc: "Market tracker", status: "running", cpu: 7, mem: 210, nextS: 240, schedule: "Every 5 min", restarts: 0 },
        { id: "compass", n: "Compass", glyph: "◎", desc: "Bias & key levels", status: "idle", cpu: 1, mem: 132, nextS: 1860, schedule: "Every 30 min", restarts: 1 },
        { id: "aegis", n: "Aegis", glyph: "❖", desc: "Reputation guardian", status: "queued", cpu: 0, mem: 118, nextS: 120, schedule: "Every 10 min", restarts: 0 },
      ],
      llm: { holder: "wolf", heldS: 1.8, tokens: 612, rate: 34, queue: ["mailman", "aegis"] },
      events: [
        { t: nowHM(), m: "AI-Times digest emailed to you", c: "#16a34a" },
        { t: nowHM(), m: "Wolf refreshed 22 tickers", c: "#5b6472" },
        { t: nowHM(), m: "Mailman flagged 2 urgent emails", c: "#f59e0b" },
        { t: nowHM(), m: "Compass auto-restarted after timeout", c: "#e5484d" },
      ],
      alarm: null, // { resource, value, action }
      // live market mirror (for ticking prices)
      watch: WATCH.map((w) => ({ ...w })),
      tick: 0,
    };
  },

  subscribe(fn) { this.subs.add(fn); return () => this.subs.delete(fn); },
  emit() { this.subs.forEach((f) => f()); },

  log(m, c = "#5b6472") {
    this.state.events.unshift({ t: nowHM(), m, c });
    this.state.events = this.state.events.slice(0, 12);
  },

  step() {
    const s = this.state;
    s.tick++;
    s.uptimeS += 2;

    // resource random walk (unless alarm pinning a value high)
    for (const k of ["cpu", "ram", "gpu"]) {
      const r = s.res[k];
      if (!(s.alarm && s.alarm.resource === k)) {
        r.v = Math.round(clamp(r.v + rnd(-5, 5), 4, 88));
      }
      r.hist = [...r.hist.slice(1), r.v];
    }
    s.threads = clamp(s.threads + Math.round(rnd(-2, 2)), 32, 64);

    // semaphore: advance held time / token count; finish & rotate
    const llm = s.llm;
    llm.heldS = Math.round((llm.heldS + 2) * 10) / 10;
    llm.tokens += Math.round(rnd(40, 80));
    llm.rate = Math.round(clamp(llm.rate + rnd(-4, 4), 22, 48));
    if (llm.heldS >= 6 && llm.queue.length) {
      const finished = llm.holder;
      const fa = s.agents.find((a) => a.id === finished);
      if (fa && fa.status === "running") this.log(`${fa.n} finished LLM call (${llm.tokens} tok)`, "#16a34a");
      llm.holder = llm.queue.shift();
      llm.queue.push(finished);
      llm.heldS = 0;
      llm.tokens = 0;
      const ha = s.agents.find((a) => a.id === llm.holder);
      if (ha) ha.status = "running";
    }

    // agent countdowns
    for (const a of s.agents) {
      if (a.status === "crashed") continue;
      a.nextS = Math.max(0, a.nextS - 2);
      if (a.status === "running") a.cpu = clamp(Math.round(a.cpu + rnd(-2, 2)), 3, 24);
      if (a.nextS === 0) {
        a.nextS = ({ mailman: 900, wolf: 300, compass: 1800, aegis: 600, "ai-times": 86400 })[a.id] || 600;
        this.log(`${a.n} run completed`, "#5b6472");
      }
    }

    // auto-restart crashed agents
    for (const a of s.agents) {
      if (a.status === "crashed") {
        a._down = (a._down || 0) + 2;
        if (a._down >= 4) {
          a.status = "running";
          a.restarts++;
          a._down = 0;
          a.cpu = 6;
          this.log(`Orchestrator restarted ${a.n} (auto-recovery)`, "#16a34a");
        }
      }
    }

    // auto-resolve alarm after a while
    if (s.alarm) {
      s.alarm._age = (s.alarm._age || 0) + 2;
      if (s.alarm._age >= 10) {
        s.res[s.alarm.resource].v = 62;
        this.log(`${s.alarm.label} recovered to normal range`, "#16a34a");
        s.alarm = null;
      }
    }

    // tick market prices
    for (const w of s.watch) {
      const drift = rnd(-0.35, 0.35);
      w.p = Math.round((w.p * (1 + drift / 100)) * 100) / 100;
      w.ch = Math.round((w.ch + drift) * 100) / 100;
    }

    this.emit();
  },

  // ---- demo controls ----
  spike(resource = "cpu") {
    const s = this.state;
    const labels = { cpu: "CPU", ram: "Memory", gpu: "GPU" };
    const actions = {
      cpu: "Throttle Wolf's 5-min poll and pause non-critical agents until load < 75%.",
      ram: "Flush LLM KV-cache and reduce Qwen3 context window to free ~2.1 GB.",
      gpu: "Queue depth high — serialize inference further and lower batch size.",
    };
    s.res[resource].v = Math.round(rnd(91, 97));
    s.alarm = { resource, value: s.res[resource].v, label: labels[resource], action: actions[resource], _age: 0 };
    this.log(`⚠ ${labels[resource]} exceeded 90% — alarm raised`, "#e5484d");
    this.emit();
  },
  clearAlarm() {
    const s = this.state;
    if (s.alarm) { s.res[s.alarm.resource].v = 60; this.log(`${s.alarm.label} alarm cleared by operator`, "#5b6472"); s.alarm = null; }
    this.emit();
  },
  crash(id) {
    const a = this.state.agents.find((x) => x.id === id);
    if (!a || a.status === "crashed") return;
    a.status = "crashed";
    a._down = 0;
    a.cpu = 0;
    // remove from semaphore if holding
    const llm = this.state.llm;
    if (llm.holder === id && llm.queue.length) { llm.holder = llm.queue.shift(); llm.heldS = 0; llm.tokens = 0; }
    llm.queue = llm.queue.filter((q) => q !== id);
    this.log(`✕ ${a.n} crashed (exit 1) — orchestrator recovering`, "#e5484d");
    this.emit();
  },

  start() {
    if (this._timer) return;
    this._timer = setInterval(() => this.step(), 2000);
  },
};
Sim.init();

// useSim — subscribe a component to the store
function useSim() {
  const [, force] = React.useState(0);
  React.useEffect(() => Sim.subscribe(() => force((x) => x + 1)), []);
  return Sim.state;
}

Object.assign(window, {
  Sim, useSim, AGENT_COLOR, clamp,
  AI_NEWS, AI_PEOPLE, MAIL_CATS, MAILS, KEY_PEOPLE,
  WATCH, FX, METALS, SECTORS, NEWS, FUTURES, LEVELS, MENTIONS,
});
