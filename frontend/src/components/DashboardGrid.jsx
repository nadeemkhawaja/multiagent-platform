import React, { useState } from "react";
import ReactGridLayout, { WidthProvider } from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { T } from "../theme/tokens";

const ResponsiveGridLayout = WidthProvider(ReactGridLayout);

export default function DashboardGrid({ id, children, defaultLayout, cols = 12, rowHeight = 30 }) {
  const storageKey = `om-layout-${id}`;

  const [layout, setLayout] = useState(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) return JSON.parse(saved);
    } catch (e) {}
    return defaultLayout;
  });

  const onLayoutChange = (newLayout) => {
    setLayout(newLayout);
    localStorage.setItem(storageKey, JSON.stringify(newLayout));
  };

  const resetLayout = () => {
    setLayout(defaultLayout);
    localStorage.removeItem(storageKey);
  };

  // Children must be wrapped in a div with a matching key
  const gridChildren = React.Children.toArray(children).filter(Boolean).map((child) => {
    const key = child.key;
    if (!key) return null;
    return (
      <div key={key} style={{ display: "flex", flexDirection: "column", background: T.card, borderRadius: 12, border: `1px solid ${T.line}`, overflow: "hidden" }}>
        <div className="drag-handle" style={{ padding: "6px 12px", background: T.cardAlt, borderBottom: `1px solid ${T.line2}`, cursor: "grab", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: T.ink4, letterSpacing: -1 }}>⋮⋮</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: "uppercase", letterSpacing: 0.5 }}>{child.props["data-title"] || key}</span>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: 15 }}>
          {child}
        </div>
      </div>
    );
  }).filter(Boolean);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", padding: "4px 16px 0" }}>
        <button onClick={resetLayout} style={{
          fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 6, cursor: "pointer",
          border: `1px solid ${T.line}`, background: T.card, color: T.ink3, zIndex: 10
        }}>Reset Layout</button>
      </div>
      <ResponsiveGridLayout
        className="layout"
        layout={layout}
        cols={cols}
        rowHeight={rowHeight}
        onLayoutChange={onLayoutChange}
        draggableHandle=".drag-handle"
        margin={[16, 16]}
      >
        {gridChildren}
      </ResponsiveGridLayout>
    </div>
  );
}
