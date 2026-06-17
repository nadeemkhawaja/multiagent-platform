// ============================================================================
// Aurora.jsx — ambient animated background. Fixed full-viewport layer of soft,
// slowly-drifting color blobs that sit behind the whole app, so content cards
// appear to float on a living surface. Theme-aware (calmer in light, richer in
// dark) and motion is auto-disabled by the prefers-reduced-motion guard in
// index.css. pointer-events:none so it never blocks clicks.
// ============================================================================
import { T } from "../theme/tokens";

export default function Aurora() {
  const dark = T.mode === "dark";
  // Opacity of each blob — kept low so data stays legible on top.
  const o = dark ? 0.5 : 0.42;
  const blobs = [
    { c: T.violet, top: "-12%", left: "-8%",  size: "46vw", anim: "omDriftA 19s", o },
    { c: T.blue,   top: "8%",   right: "-10%", size: "42vw", anim: "omDriftB 24s", o: o * 0.95 },
    { c: T.teal,   bottom: "-16%", left: "12%", size: "40vw", anim: "omDriftC 22s", o: o * 0.85 },
    { c: dark ? "#3b1d6e" : "#f5b8c8", bottom: "-10%", right: "4%", size: "34vw", anim: "omDriftA 28s", o: o * 0.8 },
  ];
  return (
    <div aria-hidden="true" style={{
      position: "fixed", inset: 0, zIndex: 0, overflow: "hidden", pointerEvents: "none",
    }}>
      {blobs.map((b, i) => (
        <div key={i} style={{
          position: "absolute",
          top: b.top, left: b.left, right: b.right, bottom: b.bottom,
          width: b.size, height: b.size, borderRadius: "50%",
          background: `radial-gradient(circle at 50% 50%, ${b.c}, transparent 68%)`,
          opacity: b.o,
          filter: dark ? "blur(70px)" : "blur(80px)",
          animation: `${b.anim} ease-in-out infinite`,
          animationDelay: `${i * -4}s`,
          willChange: "transform",
        }} />
      ))}
      {/* faint dot-grid + vignette to add texture without hurting readability */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: `radial-gradient(${dark ? "#ffffff0a" : "#1418280a"} 1px, transparent 1px)`,
        backgroundSize: "26px 26px",
        maskImage: "radial-gradient(ellipse 90% 80% at 50% 40%, #000 55%, transparent 100%)",
        WebkitMaskImage: "radial-gradient(ellipse 90% 80% at 50% 40%, #000 55%, transparent 100%)",
      }} />
    </div>
  );
}
