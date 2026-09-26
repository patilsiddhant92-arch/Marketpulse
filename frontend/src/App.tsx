import React, { useState, useEffect } from 'react';
import { MarketRegimeResponse } from './types';
import { ExposureGateHeader } from './components/ExposureGateHeader';
import { InspectorSidecar } from './components/InspectorSidecar';
import { CockpitWorkspace } from './components/CockpitWorkspace';
import { MomentumWorkspace } from './components/MomentumWorkspace';
import { DealsWorkspace } from './components/DealsWorkspace';
import { VcpWorkbenchWorkspace } from './components/VcpWorkbenchWorkspace';
import { SectorWorkspace } from './components/SectorWorkspace';
import { StagingBasketDrawer } from './components/StagingBasketDrawer';
import { MultiChartModal } from './components/MultiChartModal';
import { MarketBreadthDrawer } from './components/MarketBreadthDrawer';
import { CapitalFlowDashboard } from './components/CapitalFlowDashboard';
import {
  LayoutDashboard,
  Zap,
  TrendingUp,
  Layers,
  PieChart,
  Keyboard,
  Grid,
  BarChart2,
  Landmark,
} from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'cockpit' | 'momentum' | 'deals' | 'vcp' | 'sector' | 'flow'>('cockpit');
  const [regime, setRegime] = useState<MarketRegimeResponse | null>(null);
  const [loadingRegime, setLoadingRegime] = useState<boolean>(true);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>('HAL');
  const [stagingBasket, setStagingBasket] = useState<string[]>([]);

  // Multi-Chart Tiled Window State
  const [isMultiChartOpen, setIsMultiChartOpen] = useState<boolean>(false);
  const [multiChartSymbols, setMultiChartSymbols] = useState<string[]>(['HAL', 'MTARTECH', 'ROSSTECH', 'PARAS']);

  // Historical Market Breadth Drawer State
  const [isBreadthDrawerOpen, setIsBreadthDrawerOpen] = useState<boolean>(false);

  useEffect(() => {
    fetch('/api/market/regime')
      .then((res) => res.json())
      .then((data) => setRegime(data))
      .catch((err) => console.error('Regime error:', err))
      .finally(() => setLoadingRegime(false));
  }, []);

  const handleToggleStage = (symbol: string) => {
    if (stagingBasket.includes(symbol)) {
      setStagingBasket(stagingBasket.filter((s) => s !== symbol));
    } else {
      setStagingBasket([...stagingBasket, symbol]);
    }
  };

  const handleOpenMultiChart = (symbols?: string[]) => {
    if (symbols && symbols.length > 0) {
      setMultiChartSymbols(symbols);
    } else if (selectedSymbol) {
      setMultiChartSymbols([selectedSymbol, 'MTARTECH', 'ROSSTECH', 'PARAS']);
    }
    setIsMultiChartOpen(true);
  };

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is typing in an input
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return;

      if (e.key === 'c' || e.key === 'C') {
        if (selectedSymbol) {
          navigator.clipboard.writeText(`NSE:${selectedSymbol}`);
        }
      } else if (e.key === 't' || e.key === 'T') {
        if (selectedSymbol) {
          window.open(`https://www.tradingview.com/chart/?symbol=NSE:${selectedSymbol.replace('-', '_')}`, '_blank');
        }
      } else if (e.key === 'm' || e.key === 'M') {
        setIsMultiChartOpen((prev) => !prev);
      } else if (e.key === ' ') {
        e.preventDefault();
        if (selectedSymbol) {
          handleToggleStage(selectedSymbol);
        }
      } else if (e.key === 'Escape') {
        setIsMultiChartOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedSymbol, stagingBasket]);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#080c14] text-[#f1f4f8] font-sans select-none">
      {/* 1. Market Exposure Gate & Regime Strip */}
      <ExposureGateHeader
        regime={regime}
        loading={loadingRegime}
        onOpenBreadth={() => setIsBreadthDrawerOpen(true)}
        onNavigateTab={setActiveTab}
      />

      {/* 2. Workspace Navigation Bar */}
      <nav className="bg-[#0e1522] border-b border-[#1f2b3c] px-4 flex items-center justify-between">
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-2 mr-4 py-2">
            <span className="font-extrabold text-sm tracking-tight text-[#f1f4f8] flex items-center gap-1">
              <span className="text-[#f0be58]">MARKET</span>PULSE
            </span>
            <span className="px-1.5 py-0.2 text-[9px] font-mono rounded bg-[#f0be58]/20 text-[#f0be58] border border-[#f0be58]/40 font-bold">
              3.0 TERMINAL
            </span>
          </div>

          {[
            { id: 'cockpit', label: '1. Action Desk (Cockpit)', icon: LayoutDashboard },
            { id: 'momentum', label: '2. Momentum Screener', icon: Zap },
            { id: 'deals', label: '3. Institutional Deals Desk', icon: TrendingUp },
            { id: 'vcp', label: '4. VCP Workbench', icon: Layers },
            { id: 'sector', label: '5. Sector Matrix', icon: PieChart },
            { id: 'flow', label: '6. Capital Flow Radar', icon: Landmark },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-semibold border-b-2 transition ${
                  isActive
                    ? 'border-[#f0be58] text-[#f0be58] bg-[#151f2b]/60'
                    : 'border-transparent text-[#98a7ba] hover:text-[#f1f4f8] hover:bg-[#151f2b]/30'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}

          {/* Tiles Window Header Button */}
          <button
            onClick={() => handleOpenMultiChart()}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#132238] text-[#38bdf8] hover:bg-[#38bdf8] hover:text-[#080c14] border border-[#233d60] text-xs font-bold transition ml-2 shadow-sm"
            title="Open Multi-Chart Tiled Window (M)"
          >
            <Grid className="w-3.5 h-3.5" />
            <span>⊞ Tiles Window</span>
          </button>

          {/* 180D Market Breadth Radar Header Button */}
          <button
            onClick={() => setIsBreadthDrawerOpen(true)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#16291e] text-[#45d483] hover:bg-[#45d483] hover:text-[#080c14] border border-[#235338] text-xs font-bold transition ml-1 shadow-sm"
            title="Open 180-Session Market Breadth & Liquidity Radar"
          >
            <BarChart2 className="w-3.5 h-3.5" />
            <span>📊 Breadth Radar</span>
          </button>
        </div>

        {/* Keyboard Shortcuts Hint */}
        <div className="hidden xl:flex items-center gap-3 text-[10px] text-[#7888a0] font-mono">
          <span className="flex items-center gap-1">
            <Keyboard className="w-3 h-3 text-[#f0be58]" />
            <kbd className="px-1 rounded bg-[#151f2b] border border-[#263447]">C</kbd> Copy
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-[#151f2b] border border-[#263447]">T</kbd> TV Chart
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-[#151f2b] border border-[#263447]">M</kbd> Tiles
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-[#151f2b] border border-[#263447]">Space</kbd> Watchlist
          </span>
        </div>
      </nav>

      {/* 3. Main Workspace Area + Docked Inspector Sidecar */}
      <div className="flex-1 flex overflow-hidden">
        {activeTab === 'cockpit' && (
          <CockpitWorkspace
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            onAddToBasket={handleToggleStage}
          />
        )}

        {activeTab === 'momentum' && (
          <MomentumWorkspace
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            onAddToBasket={handleToggleStage}
          />
        )}

        {activeTab === 'deals' && (
          <DealsWorkspace
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            onAddToBasket={handleToggleStage}
          />
        )}

        {activeTab === 'vcp' && (
          <VcpWorkbenchWorkspace
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            onAddToBasket={handleToggleStage}
          />
        )}

        {activeTab === 'sector' && (
          <SectorWorkspace
            onSelectSymbol={setSelectedSymbol}
            onOpenMultiChart={handleOpenMultiChart}
          />
        )}

        {activeTab === 'flow' && (
          <CapitalFlowDashboard
            onSelectSymbol={setSelectedSymbol}
            onOpenMultiChart={handleOpenMultiChart}
            onAddToBasket={handleToggleStage}
          />
        )}

        {/* Persistent 360° Stock Inspector Sidecar (Zero Modals) */}
        <InspectorSidecar
          symbol={selectedSymbol}
          onAddToBasket={handleToggleStage}
          isStaged={selectedSymbol ? stagingBasket.includes(selectedSymbol) : false}
          onSelectSymbol={setSelectedSymbol}
          onOpenMultiChart={handleOpenMultiChart}
        />
      </div>

      {/* 4. Multi-Chart Tiled Canvas Modal */}
      <MultiChartModal
        isOpen={isMultiChartOpen}
        onClose={() => setIsMultiChartOpen(false)}
        initialSymbols={multiChartSymbols}
        onSelectSymbol={(sym) => {
          setSelectedSymbol(sym);
          setIsMultiChartOpen(false);
        }}
      />

      {/* 5. Bottom Active Watchlist Drawer */}
      <StagingBasketDrawer
        basket={stagingBasket}
        onRemove={(sym) => setStagingBasket(stagingBasket.filter((s) => s !== sym))}
        onClear={() => setStagingBasket([])}
      />

      {/* 6. 180-Session Market Breadth Drawer */}
      <MarketBreadthDrawer
        isOpen={isBreadthDrawerOpen}
        onClose={() => setIsBreadthDrawerOpen(false)}
      />
    </div>
  );
};

export default App;
