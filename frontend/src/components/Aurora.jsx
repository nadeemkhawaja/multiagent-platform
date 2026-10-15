// ============================================================================
// Aurora.jsx — the board's ground.
//
// This was four drifting radial-gradient blobs in violet, blue, teal and plum,
// blurred 70px at 0.5 opacity, animated on a 19-28s loop behind the entire app.
// In dark mode it swallowed the interface: equity figures, the session rail and
// the funnel table all sat on a moving coloured cloud, and the one thing a
// cockpit must never do is make a number hard to read at a glance.
//
// A painted board has no aurora. What it has is tooth — the grain of primer and
// paint under the chalk — so the ground is now a static, nearly invisible
// texture: a fine diagonal hatch at ~2% contrast, plus a vignette that drops
// the corners a few percent so the centre of the board reads as lit. No
// animation, no blur, no hue. The file keeps its name and its single call site
// in App.jsx; what changed is what it draws.
// ============================================================================
import { T } from "../theme/tokens";

export default function Aurora() {
  const dark = T.mode === "dark";
  // Paint tooth. Two hairline hatches crossing at 45°, far below the threshold
  // where they read as a pattern — they read as a surface that isn't flat.
  const ink = dark ? "#ffffff" : "#1a1d1f";
  const tooth = dark ? "07" : "06";
  return (
    <div aria-hidden="true" style={{
      position: "fixed", inset: 0, zIndex: 0, overflow: "hidden", pointerEvents: "none",
      background: T.bg,
    }}>
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage:
          `repeating-linear-gradient(45deg, ${ink}${tooth} 0 1px, transparent 1px 7px),` +
          `repeating-linear-gradient(-45deg, ${ink}${tooth} 0 1px, transparent 1px 11px)`,
      }} />
      {/* The board is lit from the front: corners fall off, centre stays open. */}
      <div style={{
        position: "absolute", inset: 0,
        background: dark
          ? "radial-gradient(ellipse 120% 100% at 50% 32%, transparent 42%, rgba(0,0,0,.42) 100%)"
          : "radial-gradient(ellipse 120% 100% at 50% 32%, transparent 48%, rgba(26,29,31,.10) 100%)",
      }} />
    </div>
  );
}
