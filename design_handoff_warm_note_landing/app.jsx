// app.jsx — root render; loads last so all window globals are populated.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "pinkA": "#C2185B",
  "pinkB": "#E76A8B",
  "handwritten": true,
  "headlineA": "",
  "headlineB": ""
}/*EDITMODE-END*/;

function App() {
  const [state, setTweak] = useTweaks(TWEAK_DEFAULTS);

  return (
    <>
      <DesignCanvas>
        <DCSection
          id="desktop"
          title="MyPinkAssistant — Desktop"
          subtitle="Two directions for the desktop landing page. Click ⤢ on any artboard to view full-screen."
        >
          <DCArtboard
            id="refined"
            label="A · Refined Rose"
            width={1180}
            height={4180}
          >
            <RefinedLanding tweaks={state} />
          </DCArtboard>

          <DCArtboard
            id="warm"
            label="B · Warm Note"
            width={1180}
            height={4280}
          >
            <WarmLanding tweaks={state} />
          </DCArtboard>
        </DCSection>

        <DCSection
          id="mobile"
          title="MyPinkAssistant — iPhone"
          subtitle="Same components, rendered inside an iPhone bezel. Scroll inside each phone to see the full page — container queries collapse the layout to one column."
        >
          <DCArtboard
            id="refined-mobile"
            label="A · Refined Rose"
            width={440}
            height={920}
          >
            <div style={{ display: 'grid', placeItems: 'center', padding: 16 }}>
              <IOSDevice width={402} height={874}>
                <div style={{ paddingTop: 54 }}>
                  <RefinedLanding tweaks={state} />
                </div>
              </IOSDevice>
            </div>
          </DCArtboard>

          <DCArtboard
            id="warm-mobile"
            label="B · Warm Note"
            width={440}
            height={920}
          >
            <div style={{ display: 'grid', placeItems: 'center', padding: 16 }}>
              <IOSDevice width={402} height={874}>
                <div style={{ paddingTop: 54 }}>
                  <WarmLanding tweaks={state} />
                </div>
              </IOSDevice>
            </div>
          </DCArtboard>
        </DCSection>
      </DesignCanvas>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Headline overrides">
          <TweakText
            label="Direction A headline"
            value={state.headlineA}
            onChange={(v) => setTweak('headlineA', v)}
            placeholder="Enter customers & orders…"
          />
          <TweakText
            label="Direction B headline"
            value={state.headlineB}
            onChange={(v) => setTweak('headlineB', v)}
            placeholder="Stop typing orders…"
          />
        </TweakSection>

        <TweakSection label="A · Refined Rose">
          <TweakColor
            label="Pink intensity"
            value={state.pinkA}
            onChange={(v) => setTweak('pinkA', v)}
            options={['#E91E63', '#C2185B', '#8E1141', '#D14080']}
          />
        </TweakSection>

        <TweakSection label="B · Warm Note">
          <TweakColor
            label="Pink intensity"
            value={state.pinkB}
            onChange={(v) => setTweak('pinkB', v)}
            options={['#F08CA8', '#E76A8B', '#C84A6F', '#C2185B', '#A93860']}
          />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
