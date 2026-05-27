// landing-warm.jsx — Direction B: "Warm Note"
// Friendly, handwritten accents, like a note from a friend. Lora + Nunito + Caveat.

const warmTokens = {
  cream: '#FFF6F0',
  cream2: '#FCEAE0',
  cream3: '#F8DDD0',
  ink: '#3A1F25',
  ink2: '#6B4751',
  coral: '#E76A8B',
  coralDeep: '#C84A6F',
  blush: '#FFE0E9',
  hairline: 'rgba(58,31,37,.10)',
  serif: '"Lora", "Cormorant Garamond", Georgia, serif',
  sans: '"Nunito", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  hand: '"Caveat", "Bradley Hand", cursive',
};

// Darken a hex color by `amount` (0–1) — used for the hard-shadow under buttons,
// so the shadow always tracks the chosen accent instead of a fixed coralDeep.
function darken(hex, amount = 0.22) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
  if (!m) return hex;
  const r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
  const d = (v) => Math.max(0, Math.min(255, Math.round(v * (1 - amount))));
  return '#' + [d(r), d(g), d(b)].map(v => v.toString(16).padStart(2, '0')).join('');
}

function WarmLanding({ tweaks = {} }) {
  const t = warmTokens;
  const accent = tweaks.pinkB || t.coral;
  const accentDeep = darken(accent, 0.28); // shadow shade that tracks the accent
  const showHand = false; // Removed per design direction — Warm Note no longer uses handwritten accents.
  const headline = tweaks.headlineB || (<>Run your business <em style={{ color: accent }}>by chat.</em></>);

  return (
    <div className="mpa-landing" style={{ background: t.cream, color: t.ink, fontFamily: t.sans, fontSize: 16, lineHeight: 1.55, width: '100%', position: 'relative', overflow: 'hidden' }}>
      {/* Subtle blob backdrop */}
      <div aria-hidden data-hide-mobile style={{
        position: 'absolute', top: 200, right: -120, width: 480, height: 480,
        borderRadius: '50%', background: `${accent}15`, filter: 'blur(60px)', zIndex: 0,
      }} />

      <WarmNav t={t} accent={accent} accentDeep={accentDeep} />

      {/* HERO */}
      <section data-pad data-grid-2 style={{
        padding: '56px 64px 72px',
        display: 'grid', gridTemplateColumns: '1.15fr .85fr', gap: 56, alignItems: 'center',
        position: 'relative', zIndex: 1,
      }}>
        <Reveal>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '6px 12px', borderRadius: 999,
            background: '#fff', border: `1px solid ${t.hairline}`,
            fontSize: 12, letterSpacing: '.08em', textTransform: 'uppercase',
            color: t.ink2, fontWeight: 700, marginBottom: 22,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: accent }} />
            For Mary Kay consultants
          </div>
          {showHand && (
            <div style={{
              fontFamily: t.hand, fontSize: 28, color: accent, marginBottom: 6,
              transform: 'rotate(-3deg)', display: 'inline-block',
            }}>hey friend —</div>
          )}
          <h1 data-h1 style={{
            fontFamily: t.serif, fontSize: 68, lineHeight: 1.05,
            margin: '4px 0 22px', letterSpacing: '-.015em', fontWeight: 500,
            textWrap: 'balance', color: t.ink,
          }}>{headline}</h1>
          <p data-hero-sub style={{ fontSize: 18, color: t.ink2, maxWidth: 500, margin: '0 0 32px', textWrap: 'pretty' }}>
            Add a customer. Take an order. Find who hasn&rsquo;t reordered in 3 months.
            Your whole business, by message &mdash; like texting an assistant who already knows everyone.
          </p>

          {/* Hand-drawn underline detail */}
          {showHand && (
            <div style={{ position: 'relative', display: 'inline-block', marginBottom: 24 }}>
              <a href="#" style={{
                background: accent, color: '#fff', padding: '15px 28px',
                borderRadius: 14, fontWeight: 700, fontSize: 15,
                textDecoration: 'none', display: 'inline-block',
                boxShadow: `0 6px 0 0 ${accentDeep}, 0 14px 30px -10px ${accent}80`,
                transform: 'translateY(-2px)',
              }}>Start free trial &nbsp;→</a>
              <svg viewBox="0 0 200 14" style={{ position: 'absolute', bottom: -18, left: 10, width: 200, height: 14, pointerEvents: 'none' }}>
                <path d="M5 8 Q 50 2, 100 7 T 195 6" stroke={accent} strokeWidth="2.5" fill="none" strokeLinecap="round" opacity=".55" />
              </svg>
            </div>
          )}
          {!showHand && (
            <a href="#" style={{
              background: accent, color: '#fff', padding: '15px 28px',
              borderRadius: 14, fontWeight: 700, fontSize: 15,
              textDecoration: 'none', display: 'inline-block', marginBottom: 24,
              boxShadow: `0 6px 0 0 ${accentDeep}`,
            }}>Start free trial &nbsp;→</a>
          )}
          <a href="#" style={{
            padding: '13px 22px', color: t.ink, fontWeight: 700, fontSize: 15,
            textDecoration: 'none', marginLeft: 8,
            border: `1.5px solid ${t.ink}26`, borderRadius: 12,
            background: '#fff', display: 'inline-block',
            boxShadow: `0 3px 0 ${t.ink}1a`,
          }}>I already have an account &rarr;</a>

          <p style={{ fontSize: 13.5, color: t.ink2, margin: '14px 0 0' }}>
            <strong style={{ color: t.ink }}>$5.99 / month.</strong> 7-day free trial. Cancel anytime.
          </p>

          {/* Mobile-only demo video — hidden on desktop, full-width on mobile.
              No bezel — the user is already on a phone. */}
          <div data-show-mobile style={{ marginTop: 28 }}>
            <div style={{
              borderRadius: 22, overflow: 'hidden',
              background: '#0e0a0c',
              boxShadow: `0 18px 40px -16px ${accent}55, 0 4px 12px -4px rgba(0,0,0,.15)`,
              border: `1px solid ${t.hairline}`,
              position: 'relative',
              aspectRatio: '9 / 19.5',
              maxWidth: 360, marginLeft: 'auto', marginRight: 'auto',
            }}>
              <video
                src="demo.mp4"
                autoPlay muted loop playsInline preload="auto"
                style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              />
            </div>
          </div>
        </Reveal>

        <Reveal delay={120}>
          <div data-hero-phone style={{ position: 'relative', display: 'grid', placeItems: 'center', padding: '20px 0' }}>
            {/* Hand-drawn arrow + note */}
            {showHand && (
              <>
                <div style={{
                  position: 'absolute', top: -10, left: -30, transform: 'rotate(-8deg)',
                  fontFamily: t.hand, fontSize: 24, color: accent, lineHeight: 1.1, zIndex: 2, maxWidth: 140,
                }}>
                  the whole<br/>thing fits<br/>in a text!
                </div>
                <svg viewBox="0 0 120 80" style={{ position: 'absolute', top: 30, left: 30, width: 100, height: 70, zIndex: 2 }}>
                  <path d="M10 10 Q 50 30, 80 60" stroke={accent} strokeWidth="2.2" fill="none" strokeLinecap="round" opacity=".7" strokeDasharray="0" />
                  <path d="M72 56 L 82 62 L 76 70" stroke={accent} strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" opacity=".7" />
                </svg>
              </>
            )}

            {/* Soft blob behind phone */}
            <div style={{
              position: 'absolute', inset: '-5% -15%',
              background: `radial-gradient(60% 60% at 50% 50%, ${t.blush}, transparent 70%)`,
            }} />
            <div style={{ position: 'relative' }}>
              <IPhoneMock scale={.86} accent={accent} videoSrc="demo.mp4" />
            </div>
          </div>
        </Reveal>
      </section>

      {/* Trust strip */}
      <Reveal>
        <div data-trust style={{
          padding: '18px 64px', background: '#fff', borderTop: `1px dashed ${t.hairline}`, borderBottom: `1px dashed ${t.hairline}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 36, flexWrap: 'wrap',
          fontSize: 13.5, color: t.ink2, fontWeight: 600, position: 'relative', zIndex: 1,
        }}>
          <TrustItem accent={accent} icon="sync">Syncs directly with MyCustomers</TrustItem>
          <Dot />
          <TrustItem accent={accent} icon="sparkle">Personal inventory tracked automatically</TrustItem>
          <Dot />
          <TrustItem accent={accent} icon="phone">Works on every device</TrustItem>
        </div>
      </Reveal>

      {/* HOW IT WORKS */}
      <section data-pad style={{ padding: '88px 64px 80px', position: 'relative', zIndex: 1 }}>
        <Reveal>
          {showHand && <HandLabel t={t} accent={accent}>three little steps</HandLabel>}
          <h2 data-h2 style={{ fontFamily: t.serif, fontSize: 48, lineHeight: 1.05, margin: '12px 0 56px', fontWeight: 500, letterSpacing: '-.01em', maxWidth: 720, color: t.ink }}>
            From chat to <em style={{ color: accent }}>MyCustomers</em><br/>in under a minute.
          </h2>
        </Reveal>
        <div data-grid-3 style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24, alignItems: 'stretch' }}>
          {[
            { n: '1', h: 'Chat it', d: '"New order for Jane Doe, Satin Lips Set and Lash Love Mascara."', rot: -1.5 },
            { n: '2', h: 'Confirm it', d: 'Quick glance — products matched, totals look right? Tap confirm.', rot: 1 },
            { n: '3', h: 'Done.', d: 'Securely sent to MyCustomers. On hand inventory updated. Ready for what’s next.', rot: -.5 },
          ].map((step, i) => (
            <Reveal key={step.n} delay={i * 100}>
              <div data-card data-card-tilt style={{
                background: '#fff', borderRadius: 20, padding: '28px 26px',
                border: `1px solid ${t.hairline}`,
                boxShadow: `0 4px 0 ${t.cream3}`,
                transform: `rotate(${step.rot}deg)`,
                minHeight: 210, display: 'flex', flexDirection: 'column',
                position: 'relative',
              }}>
                <div style={{
                  position: 'absolute', top: -16, left: 20,
                  width: 36, height: 36, borderRadius: '50%',
                  background: accent, color: '#fff',
                  display: 'grid', placeItems: 'center',
                  fontFamily: t.serif, fontWeight: 600, fontSize: 18,
                  boxShadow: `0 4px 0 ${accentDeep}`,
                }}>{step.n}</div>
                <h3 style={{ fontFamily: t.serif, fontSize: 26, margin: '12px 0 10px', fontWeight: 500, color: t.ink }}>{step.h}</h3>
                <p style={{ margin: 0, color: t.ink2, fontSize: 15, lineHeight: 1.55 }}>{step.d}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* TWO MODES — Do / Know */}
      <section data-pad style={{ padding: '32px 64px 64px', position: 'relative', zIndex: 1 }}>
        <Reveal>
          {showHand && <HandLabel t={t} accent={accent}>here&rsquo;s the thing —</HandLabel>}
          <h2 data-h2 style={{ fontFamily: t.serif, fontSize: 52, lineHeight: 1.02, margin: '12px 0 16px', fontWeight: 500, letterSpacing: '-.01em', maxWidth: 720, color: t.ink }}>
            <em style={{ color: accent }}>Do</em> things. <em style={{ color: accent }}>Know</em> things.
          </h2>
          <p style={{ fontSize: 18, color: t.ink2, maxWidth: 560, margin: '0 0 48px', textWrap: 'pretty' }}>
            MyPinkAssistant doesn&rsquo;t just do the work. It tells you what work matters.
          </p>
        </Reveal>

        <div data-grid-2 style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          {/* DO */}
          <Reveal>
            <div data-card data-card-tilt style={{
              background: '#fff', borderRadius: 22, padding: 32,
              border: `1px solid ${t.hairline}`, minHeight: 460,
              display: 'flex', flexDirection: 'column',
              transform: 'rotate(-.6deg)',
              boxShadow: `0 6px 0 ${t.cream3}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 4 }}>
                <span style={{
                  width: 32, height: 32, borderRadius: '50%', background: accent, color: '#fff',
                  display: 'grid', placeItems: 'center', fontFamily: t.serif, fontWeight: 600, fontSize: 16,
                }}>1</span>
                <h3 style={{ fontFamily: t.serif, fontSize: 28, margin: 0, fontWeight: 600, color: t.ink }}>Do things.</h3>
              </div>
              <p style={{ margin: '8px 0 20px', color: t.ink2, fontSize: 15 }}>
                Add a customer, place an order, update inventory &mdash; without ever opening MyCustomers.
              </p>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <ChatSnippet
                  ask="New customer Jane Doe, 214-555-0188, birthday Aug 3"
                  answer={(<>Added Jane Doe. Sent to MyCustomers <GreenCheck/></>)}
                  accent={accent} tone="warm" font={t.sans}
                />
                <ChatSnippet
                  ask="Mary ordered a CC cream light to medium and a charcoal mask"
                  answer={(
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <div>Okay &mdash; I have this order for Mary:</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, margin: '2px 0' }}>
                        <div>&bull; Mary Kay CC Cream Sunscreen Broad Spectrum SPF 15 &mdash; Light to Medium <strong>$22.00</strong></div>
                        <div>&bull; Clear Proof Deep-Cleansing Charcoal Mask <strong>$26.00</strong></div>
                      </div>
                      <div>Estimated retail total: <strong>$48.00</strong></div>
                      <div style={{ marginTop: 2 }}>Does that sound right?</div>
                    </div>
                  )}
                  accent={accent} tone="warm" font={t.sans}
                />
              </div>
            </div>
          </Reveal>

          {/* KNOW */}
          <Reveal delay={120}>
            <div data-card data-card-tilt style={{
              background: t.blush, borderRadius: 22, padding: 32,
              border: `1px solid ${t.hairline}`, minHeight: 460,
              display: 'flex', flexDirection: 'column',
              transform: 'rotate(.5deg)',
              boxShadow: `0 6px 0 ${t.cream3}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 4 }}>
                <span style={{
                  width: 32, height: 32, borderRadius: '50%', background: accent, color: '#fff',
                  display: 'grid', placeItems: 'center', fontFamily: t.serif, fontWeight: 600, fontSize: 16,
                }}>2</span>
                <h3 style={{ fontFamily: t.serif, fontSize: 28, margin: 0, fontWeight: 600, color: t.ink }}>Know things.</h3>
              </div>
              <p style={{ margin: '8px 0 20px', color: t.ink2, fontSize: 15 }}>
                Ask anything about your business. She already knows.
              </p>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <ChatSnippet
                  ask="Who hasn't reordered in 3 months?"
                  answer={(<>7 customers: Linda P., Sarah K., Mary J., Tasha R., Aisha N., Brittany M., Diane S. <em>Want to message them?</em></>)}
                  accent={accent} tone="warm" font={t.sans}
                />
                <ChatSnippet
                  ask="Who has a birthday this month?"
                  answer={(<>3 birthdays: <strong>Jane Doe</strong> Jun 8 · <strong>Mary J.</strong> Jun 14 · <strong>Aisha N.</strong> Jun 22 🎉</>)}
                  accent={accent} tone="warm" font={t.sans}
                />
                <ChatSnippet
                  ask="Who's enrolled in PCP this quarter?"
                  answer={(<>42 customers active in Q2 PCP. <strong>11</strong> haven&rsquo;t engaged yet &mdash; want the list?</>)}
                  accent={accent} tone="warm" font={t.sans}
                />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* DAY-ONE IMPORT */}
      <section data-pad style={{ padding: '32px 64px 64px', position: 'relative', zIndex: 1 }}>
        <Reveal>
          <div data-dayone data-grid-2 style={{
            background: '#fff', borderRadius: 24, padding: '40px 44px',
            border: `1px solid ${t.hairline}`,
            boxShadow: `0 8px 0 ${t.cream3}`,
            display: 'grid', gridTemplateColumns: '1fr auto', gap: 32, alignItems: 'center',
            position: 'relative', overflow: 'hidden',
          }}>
            {/* Soft decoration */}
            <div aria-hidden style={{
              position: 'absolute', right: -60, top: -40, width: 220, height: 220,
              borderRadius: '50%', background: `${accent}1a`, filter: 'blur(40px)',
            }} />
            <div style={{ position: 'relative' }}>
              {showHand && (
                <div style={{ fontFamily: t.hand, fontSize: 24, color: accent, marginBottom: 4, transform: 'rotate(-2deg)', display: 'inline-block' }}>
                  no setup, promise —
                </div>
              )}
              <h3 data-h3 style={{ fontFamily: t.serif, fontSize: 34, lineHeight: 1.1, margin: '4px 0 8px', fontWeight: 500, color: t.ink }}>
                Your whole customer base, <em style={{ color: accent }}>already here.</em>
              </h3>
              <p style={{ margin: 0, color: t.ink2, fontSize: 15.5, maxWidth: 540 }}>
                The day you sign up, your full MyCustomers customer base and order history
                imports automatically. No exports, no spreadsheets &mdash; just sign in and ask away.
              </p>
            </div>
            <div data-dayone-num style={{ position: 'relative', textAlign: 'right' }}>
              <div style={{ fontFamily: t.serif, fontSize: 72, lineHeight: .95, color: accent, fontWeight: 500, letterSpacing: '-.02em' }}>
                &lt;2 min
              </div>
              <div style={{ color: t.ink2, fontSize: 13.5, letterSpacing: '.06em', textTransform: 'uppercase', fontWeight: 700, marginTop: 4 }}>automated setup</div>
            </div>
          </div>
        </Reveal>
      </section>

      {/* TESTIMONIALS */}
      <section data-pad style={{ padding: '64px 64px 88px', background: '#fff', position: 'relative', zIndex: 1 }}>
        <Reveal>
          {showHand && <HandLabel t={t} accent={accent}>from the pink road</HandLabel>}
          <h2 data-h2 style={{ fontFamily: t.serif, fontSize: 48, lineHeight: 1.05, margin: '12px 0 56px', fontWeight: 500, letterSpacing: '-.01em', maxWidth: 720, color: t.ink, textAlign: 'center', marginLeft: 'auto', marginRight: 'auto' }}>
            Consultants are <em style={{ color: accent }}>obsessed</em>.
          </h2>
        </Reveal>
        <div data-grid-3 style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 22 }}>
          {TESTIMONIALS.map((q, i) => {
            const rot = [-1.5, 1, -.5][i];
            const bg = [t.cream, t.blush, t.cream2][i];
            return (
              <Reveal key={q.name} delay={i * 100}>
                <figure data-card data-card-tilt style={{
                  margin: 0, padding: 28,
                  background: bg, borderRadius: 18,
                  border: `1px solid ${t.hairline}`,
                  transform: `rotate(${rot}deg)`,
                  display: 'flex', flexDirection: 'column', gap: 18, minHeight: 260,
                  boxShadow: `0 6px 0 ${t.cream3}`,
                }}>
                  <div style={{ display: 'flex', gap: 2, color: accent }}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <svg key={j} width="18" height="18" viewBox="0 0 24 24" fill={accent}>
                        <path d="M12 2l2.9 6.9 7.1.6-5.4 4.7 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 9.5l7.1-.6z" />
                      </svg>
                    ))}
                  </div>
                  <blockquote style={{ margin: 0, fontFamily: t.serif, fontSize: 18, lineHeight: 1.4, fontWeight: 400, flex: 1, color: t.ink, textWrap: 'pretty' }}>
                    &ldquo;{q.quote}&rdquo;
                  </blockquote>
                  <figcaption style={{ display: 'flex', alignItems: 'center', gap: 12, borderTop: `1px dashed ${t.hairline}`, paddingTop: 14 }}>
                    <div style={{
                      width: 38, height: 38, borderRadius: '50%',
                      background: accent, color: '#fff',
                      display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 13,
                    }}>{q.initials}</div>
                    <div>
                      <div style={{ fontWeight: 800, fontSize: 14, color: t.ink }}>{q.name}</div>
                      <div style={{ fontSize: 12.5, color: t.ink2 }}>{q.role}</div>
                    </div>
                  </figcaption>
                </figure>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* CTA */}
      <section data-pad style={{ padding: '88px 64px 80px', position: 'relative', zIndex: 1 }}>
        <Reveal>
          <div data-pricing style={{
            background: `linear-gradient(135deg, ${accent} 0%, ${accentDeep} 100%)`,
            borderRadius: 28, padding: '64px 56px',
            color: '#fff', textAlign: 'center', position: 'relative', overflow: 'hidden',
          }}>
            {/* Decorative confetti dots */}
            <div aria-hidden style={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: .35 }}>
              {[[15,20,6],[88,15,8],[82,75,5],[10,72,7],[50,12,4],[92,42,5],[8,38,5]].map(([x,y,r], i) => (
                <div key={i} style={{
                  position: 'absolute', left: `${x}%`, top: `${y}%`,
                  width: r * 2, height: r * 2, borderRadius: '50%', background: '#fff',
                }} />
              ))}
            </div>
            {showHand && (
              <div style={{ fontFamily: t.hand, fontSize: 30, color: '#fff', opacity: .9, marginBottom: 4 }}>
                ready when you are —
              </div>
            )}
            <h2 data-h2 style={{ fontFamily: t.serif, fontSize: 60, lineHeight: 1.05, margin: '0 0 16px', fontWeight: 500, letterSpacing: '-.01em', position: 'relative' }}>
              Try it free for 7 days.
            </h2>
            <p style={{ margin: '0 auto 32px', fontSize: 18, maxWidth: 480, opacity: .92, position: 'relative' }}>
              $5.99/month after trial &middot; cancel anytime
            </p>
            <a href="#" style={{
              display: 'inline-block', background: '#fff', color: accentDeep,
              padding: '17px 32px', borderRadius: 14, fontWeight: 800, fontSize: 16,
              textDecoration: 'none', position: 'relative',
              boxShadow: `0 6px 0 rgba(0,0,0,.15)`,
            }}>Start free trial &nbsp;→</a>
          </div>
        </Reveal>
      </section>

      {/* FOOTER */}
      <footer data-footer style={{ padding: '40px 64px 56px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: t.ink2, fontSize: 13, position: 'relative', zIndex: 1, borderTop: `1px dashed ${t.hairline}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <WarmLogo accent={accent} t={t} small />
          <span>&copy; 2026 MyPinkAssistant.</span>
        </div>
        <div style={{ display: 'flex', gap: 22 }}>
          <a href="#" style={{ color: t.ink2, textDecoration: 'none' }}>FAQ</a>
          <a href="#" style={{ color: t.ink2, textDecoration: 'none' }}>Legal</a>
          <a href="#" style={{ color: t.ink2, textDecoration: 'none' }}>Privacy</a>
          <a href="#" style={{ color: t.ink2, textDecoration: 'none' }}>Terms</a>
          <a href="#" style={{ color: t.ink2, textDecoration: 'none' }}>Support</a>
        </div>
      </footer>
    </div>
  );
}

function WarmNav({ t, accent, accentDeep }) {
  return (
    <header data-nav style={{
      padding: '20px 64px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      position: 'relative', zIndex: 2,
    }}>
        <WarmLogo accent={accent} accentDeep={accentDeep} t={t} />
      <nav style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
        <a href="#" style={{
          color: t.ink, fontWeight: 700, fontSize: 14, textDecoration: 'none',
          padding: '8px 18px', border: `1.5px solid ${t.ink}26`, borderRadius: 12,
          background: '#fff',
          boxShadow: `0 3px 0 ${t.ink}1a`,
        }}>Log in</a>
        <a data-nav-cta href="#" style={{
          background: accent, color: '#fff', padding: '10px 18px', borderRadius: 12,
          fontWeight: 700, fontSize: 14, textDecoration: 'none',
          boxShadow: `0 3px 0 ${accentDeep}`,
        }}>Start free trial</a>
      </nav>
    </header>
  );
}

function WarmLogo({ accent, accentDeep, t, small }) {
  const size = small ? 30 : 38;
  const shadow = accentDeep || darken(accent || '#E76A8B', 0.28);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{
        width: size, height: size, borderRadius: '50%',
        background: accent, display: 'grid', placeItems: 'center',
        color: '#fff',
        fontFamily: t.serif, fontStyle: 'italic', fontWeight: 600,
        fontSize: size * .42, letterSpacing: '-.02em', lineHeight: 1,
        boxShadow: `0 3px 0 ${shadow}`,
        paddingTop: 1,
      }}>mpa</div>
      {!small && (
        <span style={{ fontFamily: t.serif, fontSize: 22, fontWeight: 600, letterSpacing: '-.01em', color: t.ink }}>
          <span style={{ color: accent }}>MyPink</span><em>Assistant</em>
        </span>
      )}
    </div>
  );
}

function HandLabel({ children, t, accent }) {
  return (
    <div style={{ fontFamily: t.hand, fontSize: 26, color: accent, transform: 'rotate(-2deg)', display: 'inline-block' }}>
      {children}
    </div>
  );
}

function TrustItem({ children, accent, icon }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <TrustIcon kind={icon} accent={accent} />
      {children}
    </span>
  );
}
function Dot() { return <span data-trust-dot style={{ width: 4, height: 4, borderRadius: '50%', background: 'rgba(0,0,0,.18)' }} />; }

function TrustIcon({ kind, accent }) {
  const s = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: accent, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (kind === 'heart') return <svg {...s}><path d="M12 21s-7-4.5-9-9c-1.5-3.5 1-7 4.5-7 1.8 0 3.4 1 4.5 2.5C13.1 6 14.7 5 16.5 5 20 5 22.5 8.5 21 12c-2 4.5-9 9-9 9z"/></svg>;
  if (kind === 'sync') return <svg {...s}><path d="M21 12a9 9 0 0 1-15 6.7M3 12a9 9 0 0 1 15-6.7"/><path d="M21 5v5h-5M3 19v-5h5"/></svg>;
  if (kind === 'phone') return <svg {...s}><rect x="7" y="2" width="10" height="20" rx="2"/><line x1="12" y1="18" x2="12" y2="18"/></svg>;
  if (kind === 'sparkle') return <svg {...s}><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>;
  return <svg {...s}><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>;
}

// Small green checkmark badge (matches the "delivered" indicator style in the app).
function GreenCheck() {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 16, height: 16, borderRadius: '50%',
      background: '#22c55e', color: '#fff', verticalAlign: '-3px',
      marginLeft: 4, flexShrink: 0,
    }}>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 13l4 4L19 7"/>
      </svg>
    </span>
  );
}

function WarmGlyph({ kind, accent }) {
  const s = { width: 40, height: 40, viewBox: '0 0 40 40', fill: 'none' };
  if (kind === 'spark') return (
    <svg {...s}><path d="M20 6v8M20 26v8M6 20h8M26 20h8M11 11l5 5M24 24l5 5M11 29l5-5M24 16l5-5" stroke={accent} strokeWidth="2.2" strokeLinecap="round"/></svg>
  );
  if (kind === 'sparkle') return (
    <svg {...s}><path d="M14 8l2 5 5 2-5 2-2 5-2-5-5-2 5-2 2-5z" fill={accent} opacity=".85"/><circle cx="28" cy="14" r="2" fill={accent}/><circle cx="30" cy="28" r="3" fill={accent} opacity=".6"/></svg>
  );
  return (
    <svg {...s}><path d="M6 12a4 4 0 0 1 4-4h16a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H16l-7 6v-6a4 4 0 0 1-3-4V12z" stroke={accent} strokeWidth="2.2" fill="none" strokeLinejoin="round"/></svg>
  );
}

Object.assign(window, { WarmLanding });
