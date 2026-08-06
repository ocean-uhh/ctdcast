"""Shared CSS for all ctdcast HTML pages.

Import ``SHARED_CSS`` and concatenate it into each page template's ``<style>`` block.
"""

from __future__ import annotations

SHARED_CSS: str = """\
:root {
  --ocean: #1a3a5c;
  --seafoam: #e8f4f8;
  --muted: #95a5a6;
  --text: #2c3e50;
  --warn: #e67e22;
}
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; color: var(--text);
  max-width: 1150px; margin: 0 auto;
  padding: 1.5rem 2rem 4rem; line-height: 1.5;
}
.masthead {
  background: var(--ocean); color: #fff;
  padding: 1.6rem 2rem; border-radius: 8px; margin-bottom: 2rem;
}
.masthead h1 { margin: 0 0 0.3rem; font-size: 1.75rem; font-weight: 700; }
.masthead .sub { font-size: 0.9rem; opacity: 0.85; margin: 0 0 0.15rem; }
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 0.5rem 2rem; font-size: 0.84rem; margin-top: 0.9rem;
}
.meta-grid dt {
  opacity: 0.7; text-transform: uppercase; font-size: 0.7rem;
  letter-spacing: 0.06em; margin-bottom: 0.1rem;
}
.meta-grid dd { margin: 0; font-weight: 600; }
h2 {
  color: var(--ocean); font-size: 1rem;
  border-bottom: 2px solid var(--seafoam);
  padding-bottom: 0.3rem; margin: 2.5rem 0 1rem;
  display: flex; justify-content: space-between; align-items: baseline;
}
.top-link {
  font-size: 0.72rem; font-weight: 400; color: var(--muted);
  text-decoration: none; margin-left: auto;
}
.top-link:hover { color: var(--ocean); text-decoration: underline; }
.note {
  color: #555; font-size: 0.82rem;
  margin-top: -0.5rem; margin-bottom: 0.75rem;
}
.jump-nav {
  background: var(--seafoam); padding: 0.55rem 1rem;
  border-radius: 6px; margin-bottom: 1.5rem;
  font-size: 0.8rem; line-height: 2.2;
}
.jump-nav::before { content: "Jump to: "; opacity: 0.55; font-size: 0.75rem; margin-right: 0.25rem; }
.jump-nav a {
  color: var(--ocean); text-decoration: none;
  font-weight: 600; margin: 0 0.5rem 0 0;
}
.jump-nav a::before { content: "▸ "; font-size: 0.7rem; }
.fig-row {
  display: flex; gap: 1rem; margin-bottom: 1.5rem;
  align-items: flex-start;
}
.fig-col { display: flex; flex-direction: column; gap: 0.75rem; }
figure { margin: 0; }
figure img {
  border: 1px solid #dce; border-radius: 4px;
  display: block; width: 100%; height: auto;
}
figcaption { font-size: 0.76rem; color: #555; margin-top: 0.25rem; }
.slot-full         { width: 100%; }
.slot-twothirds    { width: calc(66.67% - 0.33rem); }
.slot-three-fifths { width: calc(60% - 0.4rem); }
.slot-half         { width: calc(50% - 0.5rem); }
.slot-two-fifths   { width: calc(40% - 0.6rem); }
.slot-third        { width: calc(33.33% - 0.67rem); }
.masthead-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 0.3rem;
}
.masthead-header h1 { margin: 0 0 0.1rem; font-size: 1.75rem; font-weight: 700; }
.masthead-type {
  font-size: 1.35rem; font-weight: 700; opacity: 0.88; line-height: 1.35;
  padding-top: 0.25rem;
}
.nav-btns { display: flex; gap: 0.5rem; }
.btn-nav {
  background: var(--ocean); color: #fff; padding: 0.25rem 0.75rem;
  border-radius: 999px; text-decoration: none; font-size: 0.8rem;
}
.btn-nav:hover { opacity: 0.85; }
footer {
  text-align: center; padding: 1rem;
  font-size: 0.75rem; color: var(--muted);
}
footer a { color: var(--muted); }
@media print {
  body { max-width: 100%; }
  .masthead { -webkit-print-color-adjust: exact; print-color-adjust: exact; padding: 0.9rem 1.25rem; }
  .masthead-header h1, .masthead h1 { font-size: 1.35rem; }
  .meta-grid { grid-template-columns: repeat(4, 1fr); gap: 0.3rem 1rem; font-size: 0.78rem; }
  h2 { page-break-after: avoid; }
  .jump-nav { display: none; }
}
"""

_JS_TOP_LINKS: str = """\
<script>
document.querySelectorAll('h2').forEach(h => {
  const a = document.createElement('a');
  a.href = '#top'; a.className = 'top-link'; a.textContent = '↑ top';
  h.appendChild(a);
});
</script>
"""
