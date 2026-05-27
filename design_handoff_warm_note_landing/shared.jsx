// shared.jsx — bits used by both landing-page variants

// ---------- One-time stylesheet for container-query responsive overrides ----------
// Both landings wrap their root in className="mpa-landing" (container-type: inline-size).
// When the artboard is narrow (≤700px), data-* rules collapse multi-col grids,
// shrink type, hide the hero phone mock (because we're already INSIDE a phone
// frame in mobile artboards), and stack the footer.
if (typeof document !== 'undefined' && !document.getElementById('mpa-styles')) {
  const s = document.createElement('style');
  s.id = 'mpa-styles';
  s.textContent = `
    .mpa-landing { container-type: inline-size; width: 100%; }
    [data-show-mobile] { display: none; }
    @container (max-width: 700px) {
      [data-pad-x]     { padding-left: 20px !important; padding-right: 20px !important; }
      [data-pad]       { padding: 28px 20px !important; }
      [data-grid-2],
      [data-grid-3]    { grid-template-columns: 1fr !important; gap: 18px !important; }
      [data-h1]        { font-size: 36px !important; line-height: 1.05 !important; }
      [data-h2]        { font-size: 28px !important; line-height: 1.08 !important; margin-bottom: 24px !important; }
      [data-h3]        { font-size: 22px !important; }
      [data-hero-phone]{ display: none !important; }
      [data-nav]       { padding: 14px 18px !important; }
      [data-nav-cta]   { padding: 8px 14px !important; font-size: 13px !important; }
      [data-trust]     { flex-wrap: wrap !important; justify-content: center !important;
                         padding: 14px 18px !important; font-size: 10.5px !important; gap: 8px 14px !important; }
      [data-trust-dot] { display: none !important; }
      [data-footer]    { flex-direction: column !important; gap: 14px !important;
                         text-align: center !important; padding: 28px 20px !important; }
      [data-footer] > div:last-child { flex-wrap: wrap !important; justify-content: center !important; gap: 10px 14px !important; }
      [data-pricing-num]{ font-size: 64px !important; }
      [data-card]      { padding: 24px !important; min-height: 0 !important; }
      [data-card-tilt] { transform: rotate(0deg) !important; }
      [data-hide-mobile]{ display: none !important; }
      [data-hero-sub]  { font-size: 16px !important; }
      [data-hero-cta]  { padding: 14px 22px !important; }
      [data-dayone-num]{ font-size: 56px !important; text-align: left !important; }
      [data-dayone]    { padding: 28px 22px !important; }
      [data-pricing]   { padding: 36px 24px !important; }
      [data-show-mobile]{ display: block !important; }
    }
  `;
  document.head.appendChild(s);
}

// ---------- Reveal-on-scroll (intersection observer) ----------
function Reveal({ children, delay = 0, y = 16, as = 'div', className = '', style = {} }) {
  const ref = React.useRef(null);
  const [seen, setSeen] = React.useState(false);
  React.useEffect(() => {
    if (!ref.current) return;
    // If IO unavailable or parent isn't scrollable, just show.
    if (typeof IntersectionObserver === 'undefined') { setSeen(true); return; }
    const io = new IntersectionObserver(
      (entries) => entries.forEach(e => { if (e.isIntersecting) { setSeen(true); io.disconnect(); }}),
      { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
    );
    io.observe(ref.current);
    // Safety: in static canvas views with no scroll, reveal after a beat.
    const t = setTimeout(() => setSeen(true), 600 + delay);
    return () => { io.disconnect(); clearTimeout(t); };
  }, [delay]);
  const Comp = as;
  return (
    <Comp
      ref={ref}
      className={className}
      style={{
        opacity: seen ? 1 : 0,
        transform: seen ? 'translateY(0)' : `translateY(${y}px)`,
        transition: `opacity .7s cubic-bezier(.2,.7,.2,1) ${delay}ms, transform .7s cubic-bezier(.2,.7,.2,1) ${delay}ms`,
        ...style,
      }}
    >
      {children}
    </Comp>
  );
}

// ---------- iPhone placeholder (static SVG-ish CSS frame) ----------
// scale prop multiplies the base 280 x 568 frame
// videoSrc, if provided, replaces the fake bubble screen with a real <video>.
function IPhoneMock({ scale = 1, screenLabel = 'screen recording', tone = 'pink', accent = '#E91E63', screenBg = '#FFF5F8', videoSrc }) {
  const W = 280 * scale, H = 568 * scale;
  const radius = 42 * scale;
  return (
    <div style={{
      width: W, height: H, position: 'relative',
      background: 'linear-gradient(160deg, #1f1a1c 0%, #3a2f33 100%)',
      borderRadius: radius,
      padding: 7 * scale,
      boxShadow: `0 30px 60px -20px rgba(40,10,25,.35), 0 8px 20px -8px rgba(40,10,25,.2), inset 0 0 0 1px rgba(255,255,255,.08)`,
    }}>
      {/* Inner bezel */}
      <div style={{
        width: '100%', height: '100%',
        background: screenBg,
        borderRadius: radius - 7 * scale,
        position: 'relative', overflow: 'hidden',
        boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.12)',
      }}>
        {videoSrc ? (
          <>
            <video
              src={videoSrc}
              autoPlay
              muted
              loop
              playsInline
              preload="auto"
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
            {/* Dynamic island overlay (kept on top of the video) */}
            <div style={{
              position: 'absolute', top: 10 * scale, left: '50%', transform: 'translateX(-50%)',
              width: 92 * scale, height: 26 * scale, background: '#0e0a0c', borderRadius: 999,
              zIndex: 3,
            }} />
          </>
        ) : (
          <FakeScreen scale={scale} screenLabel={screenLabel} accent={accent} />
        )}
      </div>
    </div>
  );
}

// Original fake-screen content extracted so we keep the placeholder for cases
// where no videoSrc is provided.
function FakeScreen({ scale, screenLabel, accent }) {
  return (
    <>
      {/* Dynamic island */}
      <div style={{
        position: 'absolute', top: 10 * scale, left: '50%', transform: 'translateX(-50%)',
        width: 92 * scale, height: 26 * scale, background: '#0e0a0c', borderRadius: 999,
        zIndex: 3,
      }} />

      {/* Status bar */}
      <div style={{
        position: 'absolute', top: 14 * scale, left: 20 * scale, right: 20 * scale,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif',
        fontSize: 13 * scale, fontWeight: 600, color: '#2a1f24', zIndex: 2,
      }}>
        <span>9:41</span>
        <span style={{ display: 'inline-flex', gap: 4 * scale }}>
          <span>􀙇</span><span>􀛨</span><span>􀛪</span>
        </span>
      </div>

      <div style={{
        position: 'absolute', inset: 0, paddingTop: 50 * scale,
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          padding: `${14 * scale}px ${18 * scale}px ${10 * scale}px`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: `1px solid ${accent}1a`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 * scale }}>
            <div style={{ width: 28 * scale, height: 28 * scale, borderRadius: 8 * scale, background: accent, display: 'grid', placeItems: 'center', color: '#fff', fontWeight: 800, fontSize: 14 * scale, fontFamily: 'system-ui' }}>m</div>
            <span style={{ fontFamily: 'system-ui', fontSize: 13 * scale, fontWeight: 600, color: '#2a1f24' }}>MyPinkAssistant</span>
          </div>
          <div style={{ width: 28 * scale, height: 28 * scale, borderRadius: '50%', background: `${accent}26` }} />
        </div>

        <div style={{ flex: 1, padding: `${14 * scale}px ${16 * scale}px`, display: 'flex', flexDirection: 'column', gap: 8 * scale }}>
          <Bubble side="in" w={170 * scale} h={36 * scale} accent={accent} />
          <Bubble side="out" w={210 * scale} h={50 * scale} accent={accent} solid />
          <Bubble side="in" w={140 * scale} h={36 * scale} accent={accent} />
          <Bubble side="out" w={195 * scale} h={64 * scale} accent={accent} solid />
          <Bubble side="in" w={120 * scale} h={28 * scale} accent={accent} />
          <div style={{ flex: 1 }} />
          <div style={{
            border: `1.5px dashed ${accent}55`, borderRadius: 14 * scale,
            padding: `${10 * scale}px ${14 * scale}px`,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: 10 * scale, color: `${accent}cc`, letterSpacing: '.04em',
            textTransform: 'uppercase', textAlign: 'center',
            background: `${accent}08`,
          }}>{screenLabel}</div>
        </div>

        <div style={{
          margin: `0 ${14 * scale}px ${22 * scale}px`,
          background: '#fff', borderRadius: 999, padding: `${10 * scale}px ${14 * scale}px`,
          display: 'flex', alignItems: 'center', gap: 8 * scale,
          boxShadow: `0 2px 10px ${accent}22, inset 0 0 0 1px ${accent}33`,
        }}>
          <span style={{ flex: 1, fontFamily: 'system-ui', fontSize: 12 * scale, color: '#9a8a90' }}>New customer Jane Doe…</span>
          <div style={{ width: 26 * scale, height: 26 * scale, borderRadius: '50%', background: accent }} />
        </div>
        <div style={{ position: 'absolute', bottom: 8 * scale, left: '50%', transform: 'translateX(-50%)', width: 110 * scale, height: 4 * scale, borderRadius: 2 * scale, background: '#0e0a0c' }} />
      </div>
    </>
  );
}

function Bubble({ side, w, h, accent, solid }) {
  const align = side === 'out' ? 'flex-end' : 'flex-start';
  return (
    <div style={{ display: 'flex', justifyContent: align }}>
      <div style={{
        width: w, height: h,
        borderRadius: 14,
        background: solid ? accent : `${accent}1a`,
        borderTopLeftRadius: side === 'in' ? 4 : 14,
        borderTopRightRadius: side === 'out' ? 4 : 14,
      }} />
    </div>
  );
}

// ---------- Placeholder testimonials (edit these in source) ----------
const TESTIMONIALS = [
  {
    quote: "I used to dread Sunday order entry. Now I knock it out from the school pickup line — three orders in the time it takes to find my pen.",
    name: "Brittany M.",
    role: "Senior Consultant · 9 yrs",
    initials: "BM",
  },
  {
    quote: "It feels like texting an assistant who actually knows my customers. \u2018Who hasn\u2019t reordered foundation in 60 days?\u2019 — and there\u2019s my list.",
    name: "Tasha R.",
    role: "Director · Atlanta unit",
    initials: "TR",
  },
  {
    quote: "I stopped keeping a separate inventory spreadsheet last month. That alone is worth it. The sync to MyCustomers is the cherry on top.",
    name: "Linda P.",
    role: "Consultant · 4 yrs",
    initials: "LP",
  },
];

// ---------- ChatSnippet — example exchange used in feature sections ----------
// Renders a stylized "you ask, it answers" bubble pair.
function ChatSnippet({ ask, answer, accent = '#E91E63', tone = 'cool', font = 'system-ui' }) {
  const askBg = tone === 'warm' ? '#FFFFFF' : '#F4EBE5';
  const askInk = '#2A1F24';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontFamily: font }}>
      {/* User message */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div style={{
          background: accent, color: '#fff',
          borderRadius: 16, borderTopRightRadius: 4,
          padding: '10px 14px', fontSize: 14.5, lineHeight: 1.4,
          maxWidth: '85%', boxShadow: `0 2px 8px ${accent}33`,
        }}>{ask}</div>
      </div>
      {/* Answer */}
      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
        <div style={{
          background: askBg, color: askInk,
          borderRadius: 16, borderTopLeftRadius: 4,
          padding: '12px 16px', fontSize: 14.5, lineHeight: 1.5,
          maxWidth: '92%', border: tone === 'warm' ? '1px solid rgba(58,31,37,.08)' : 'none',
        }}>{answer}</div>
      </div>
    </div>
  );
}

// Make available everywhere
Object.assign(window, { Reveal, IPhoneMock, Bubble, TESTIMONIALS, ChatSnippet });
