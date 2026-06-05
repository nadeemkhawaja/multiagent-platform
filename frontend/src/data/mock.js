// ============================================================================
// mock.js — realistic fallback datasets (from the design's data.jsx).
// Used to render a populated UI when the backend has not yet produced real data.
// ============================================================================
export const AI_NEWS = [
  { id: "n1", title: "Qwen3 235B benchmarks leak ahead of official release", ch: "AI Frontier", dur: "12:04", date: "5h ago", views: "184K", c: "#e5484d" },
  { id: "n2", title: "Open-weights models close the gap with frontier labs in 2026", ch: "The Gradient", dur: "18:41", date: "9h ago", views: "97K", c: "#2f6feb" },
  { id: "n3", title: "On-device agents: the new battleground for local inference", ch: "Latent Space", dur: "24:17", date: "14h ago", views: "212K", c: "#16a34a" },
  { id: "n4", title: "Why every startup is shipping multi-agent orchestration", ch: "Sequoia AI", dur: "09:52", date: "20h ago", views: "63K", c: "#f59e0b" },
  { id: "n5", title: "Regulators draft new rules for autonomous AI systems", ch: "AI Policy Daily", dur: "15:30", date: "1d ago", views: "41K", c: "#0d9488" },
];
export const AI_PEOPLE = [
  { id: "p1", title: "Andrej Karpathy on building software 3.0 with agents", ch: "Lex Fridman", dur: "2:41:09", date: "6h ago", views: "1.2M", c: "#7c5cf6" },
  { id: "p2", title: "Fei-Fei Li: spatial intelligence and the next decade", ch: "No Priors", dur: "58:22", date: "12h ago", views: "284K", c: "#e5484d" },
  { id: "p3", title: "Demis Hassabis on the road to AGI and scientific discovery", ch: "Dwarkesh", dur: "1:34:55", date: "18h ago", views: "512K", c: "#2f6feb" },
  { id: "p4", title: "A founder's guide to local LLMs with the Ollama team", ch: "Cognitive Rev", dur: "1:07:14", date: "22h ago", views: "88K", c: "#16a34a" },
  { id: "p5", title: "Inside a one-person company running 40 agents", ch: "My First Million", dur: "1:12:48", date: "1d ago", views: "156K", c: "#f59e0b" },
];

export const MAIL_CATS = [
  { k: "Urgent", n: 3, c: "#e5484d" },
  { k: "Action Required", n: 7, c: "#f59e0b" },
  { k: "Follow-Up", n: 5, c: "#7c5cf6" },
  { k: "Personal", n: 4, c: "#0d9488" },
  { k: "Newsletter", n: 18, c: "#2f6feb" },
  { k: "Notification", n: 22, c: "#94a3b8" },
  { k: "Other", n: 6, c: "#c0c6d0" },
];
export const CAT_PALETTE = {
  Urgent: "#e5484d", "Action Required": "#f59e0b", "Follow-Up": "#7c5cf6",
  Personal: "#0d9488", Newsletter: "#2f6feb", Notification: "#94a3b8", Other: "#c0c6d0",
};
export const MAILS = [
  { id: "m1", from: "Sarah Chen", email: "sarah@northwind.vc", subj: "Re: term sheet — need answer by EOD", cat: "Urgent", star: true, key: true, sum: "Sarah needs your countersignature on the revised term sheet before close of business; she flags the updated liquidation pref.", t: "08:41" },
  { id: "m2", from: "AWS Billing", email: "no-reply@aws.amazon.com", subj: "Your invoice is now available", cat: "Notification", star: false, key: false, sum: "Monthly AWS invoice of $1,284.50 is ready. No action needed unless disputing.", t: "08:12" },
  { id: "m3", from: "Marcus Webb", email: "marcus@acme.io", subj: "Can we move the 3pm to Thursday?", cat: "Action Required", star: false, key: true, sum: "Marcus requests rescheduling today's 3pm sync to Thursday; asks you to confirm a slot.", t: "07:58" },
  { id: "m4", from: "The Neuron", email: "hello@theneurondaily.com", subj: "🧠 GPT-6 rumors and 4 tools to try", cat: "Newsletter", star: false, key: false, sum: "Daily AI newsletter covering GPT-6 speculation and new agent tooling. Skimmable.", t: "07:30" },
  { id: "m5", from: "Dr. Alvarez", email: "office@bayhealth.com", subj: "Appointment confirmation — June 11", cat: "Personal", star: true, key: false, sum: "Confirms your annual physical for June 11 at 9:15am; arrive 15 min early.", t: "Yesterday" },
  { id: "m6", from: "Priya Nair", email: "priya@acme.io", subj: "Follow-up: design review notes", cat: "Follow-Up", star: false, key: false, sum: "Priya shares notes from the design review and asks for your comments by Friday.", t: "Yesterday" },
];
export const KEY_PEOPLE = ["Sarah Chen", "Marcus Webb", "David Okafor", "Mom"];

export const WATCH = [
  { t: "NVDA", n: "NVIDIA", p: 1284.30, ch: 4.82 }, { t: "MSFT", n: "Microsoft", p: 498.12, ch: 1.24 },
  { t: "AAPL", n: "Apple", p: 241.55, ch: -0.63 }, { t: "AMZN", n: "Amazon", p: 224.90, ch: 2.11 },
  { t: "GOOGL", n: "Alphabet", p: 198.44, ch: 0.92 }, { t: "META", n: "Meta", p: 712.08, ch: 3.45 },
  { t: "TSLA", n: "Tesla", p: 348.77, ch: -3.18 }, { t: "AMD", n: "AMD", p: 186.20, ch: 5.34 },
  { t: "AVGO", n: "Broadcom", p: 1742.55, ch: 2.88 }, { t: "NFLX", n: "Netflix", p: 1024.60, ch: -1.42 },
  { t: "JPM", n: "JPMorgan", p: 268.40, ch: 0.51 }, { t: "V", n: "Visa", p: 342.18, ch: -0.28 },
  { t: "COST", n: "Costco", p: 1058.90, ch: 0.74 }, { t: "LLY", n: "Eli Lilly", p: 894.22, ch: -2.06 },
  { t: "XOM", n: "Exxon", p: 118.65, ch: 1.93 }, { t: "JNJ", n: "J&J", p: 162.30, ch: -0.44 },
  { t: "WMT", n: "Walmart", p: 98.74, ch: 0.66 }, { t: "PLTR", n: "Palantir", p: 142.88, ch: 6.21 },
  { t: "CRM", n: "Salesforce", p: 312.45, ch: -1.77 }, { t: "ORCL", n: "Oracle", p: 204.16, ch: 2.34 },
  { t: "UBER", n: "Uber", p: 88.92, ch: -2.55 }, { t: "COIN", n: "Coinbase", p: 312.70, ch: 7.84 },
];
export const FX = [
  { p: "EUR/USD", v: 1.0942, ch: 0.18 }, { p: "USD/JPY", v: 152.34, ch: -0.42 },
  { p: "GBP/USD", v: 1.2785, ch: 0.24 }, { p: "USD/CHF", v: 0.8841, ch: -0.11 },
];
export const METALS = [
  { p: "Gold", sym: "XAU/USD", v: 2418.60, ch: 0.88 },
  { p: "Silver", sym: "XAG/USD", v: 31.42, ch: 1.64 },
];

export const SECTORS = [
  { k: "Technology", bias: 64, why: "Semis extend leadership on AI capex; breadth improving." },
  { k: "Energy", bias: 28, why: "Crude firms on supply risk; rotation interest building." },
  { k: "Financials", bias: 12, why: "Yields range-bound; banks await CPI for direction." },
  { k: "Healthcare", bias: -18, why: "GLP-1 names cooling; defensive bid fading." },
  { k: "Consumer", bias: -34, why: "Soft retail prints; discretionary under pressure." },
  { k: "Industrials", bias: 8, why: "Mixed PMIs keep the group neutral near highs." },
];
export const NEWS = [
  { src: "Reuters", t: "Fed minutes signal patience as inflation cools toward target", s: "bull", min: "22m" },
  { src: "Bloomberg", t: "Nvidia supplier guides Q3 above estimates on data-center demand", s: "bull", min: "41m" },
  { src: "WSJ", t: "Retail sales miss; consumer caution deepens into summer", s: "bear", min: "1h" },
  { src: "CNBC", t: "Oil jumps 3% on Middle East supply disruption headlines", s: "bull", min: "1h" },
  { src: "FT", t: "Treasury yields steady ahead of Friday's payrolls report", s: "neutral", min: "2h" },
];
export const FUTURES = [
  { t: "/ES", n: "E-mini S&P 500", px: 5948.5, piv: 5942, r1: 5967, r2: 5988, s1: 5921, s2: 5896, bias: "bull" },
  { t: "/NQ", n: "E-mini Nasdaq-100", px: 21512, piv: 21470, r1: 21640, r2: 21805, s1: 21305, s2: 21140, bias: "bull" },
];
export const LEVELS = [
  { t: "NVDA", px: 1284, piv: 1271, r1: 1308, s1: 1244, bias: "bull" }, { t: "MSFT", px: 498, piv: 495, r1: 506, s1: 487, bias: "bull" },
  { t: "AAPL", px: 241, piv: 243, r1: 248, s1: 236, bias: "bear" }, { t: "AMZN", px: 225, piv: 222, r1: 229, s1: 217, bias: "bull" },
  { t: "GOOGL", px: 198, piv: 197, r1: 203, s1: 192, bias: "neutral" }, { t: "META", px: 712, piv: 704, r1: 726, s1: 688, bias: "bull" },
  { t: "TSLA", px: 349, piv: 354, r1: 366, s1: 338, bias: "bear" }, { t: "AMD", px: 186, piv: 182, r1: 191, s1: 176, bias: "bull" },
  { t: "AVGO", px: 1743, piv: 1722, r1: 1780, s1: 1688, bias: "bull" }, { t: "NFLX", px: 1025, piv: 1031, r1: 1058, s1: 1004, bias: "neutral" },
];

export const MENTIONS = [
  { id: "g1", src: "Reddit", sub: "r/startups", author: "u/throwaway_842", risk: "high", sent: -78,
    text: "Heard the founder of Northwind basically lied about their revenue numbers to investors. Anyone else seeing red flags?",
    why: "Unverified accusation of fraud naming you directly — defamatory and spreading.",
    reply: "Hi — I run Northwind. Happy to clear this up transparently: our revenue figures are third-party audited and I'm glad to walk through them. DMs open.", status: "new" },
  { id: "g2", src: "X", sub: "@techgossip", author: "@techgossip", risk: "med", sent: -42,
    text: "Northwind's new pricing is a cash grab. Doubling prices overnight with no warning is wild.",
    why: "Negative sentiment about pricing gaining traction (340 reposts).",
    reply: "We hear you — the rollout communication missed the mark. Existing customers keep legacy pricing for 12 months; details in your inbox today.", status: "new" },
  { id: "g3", src: "News", sub: "TechCrunch comments", author: "Anon", risk: "low", sent: -15,
    text: "Their support response time has slipped lately. Used to be great.",
    why: "Mild service complaint; worth a courteous acknowledgement.",
    reply: "Thanks for the honest feedback — we added two support engineers this month and are watching response times closely.", status: "new" },
  { id: "g4", src: "Mastodon", sub: "fosstodon.org", author: "@dev_anna", risk: "low", sent: 34,
    text: "Actually really impressed with how the Northwind team handled the outage. Transparent post-mortem.",
    why: "Positive mention — consider amplifying / thanking.",
    reply: "Thank you, that means a lot. The post-mortem is public here and we're shipping the reliability fixes this sprint.", status: "new" },
];
