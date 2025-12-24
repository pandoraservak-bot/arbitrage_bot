// NVDA Arbitrage Bot - Web Dashboard Client
class DashboardClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.updateInterval = null;
        this.isConnected = false;
        
        this.init();
    }

    init() {
        this.connect();
        this.setupEventListeners();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        console.log('Connecting to WebSocket:', wsUrl);
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.updateModeBadge('connected');
            this.requestFullUpdate();
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('Error parsing message:', e);
            }
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.isConnected = false;
            this.updateModeBadge('disconnected');
            this.attemptReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.isConnected = false;
        };
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            this.updateModeBadge('reconnecting');
            setTimeout(() => this.connect(), delay);
        } else {
            console.error('Max reconnection attempts reached');
            this.updateModeBadge('failed');
        }
    }

    handleMessage(data) {
        if (!data) return;
        
        const type = data.type;
        
        switch (type) {
            case 'full_update':
                this.renderFullUpdate(data.payload);
                break;
            case 'status':
                this.updateStatus(data.payload);
                break;
            case 'spread':
                this.updateSpread(data.payload);
                break;
            case 'positions':
                this.updatePositions(data.payload);
                break;
            case 'portfolio':
                this.updatePortfolio(data.payload);
                break;
            case 'records':
                this.updateRecords(data.payload);
                break;
            case 'exit_spreads':
                this.updateExitSpreads(data.payload);
                break;
            case 'pong':
                // Server acknowledged our ping
                break;
            default:
                console.log('Unknown message type:', type);
        }
    }

    renderFullUpdate(data) {
        if (!data) return;
        
        // Update runtime
        this.updateRuntime(data.runtime);
        
        // Update server time
        if (data.timestamp) {
            document.getElementById('serverTime').textContent = data.timestamp;
        }
        
        // Update status bar
        this.updateStatus(data);
        
        // Update prices
        this.updatePrices(data);
        
        // Update spreads
        this.updateSpread(data);
        
        // Update exit spreads
        this.updateExitSpreads(data);
        
        // Update records
        this.updateRecords(data);
        
        // Update portfolio
        this.updatePortfolio(data);
        
        // Update positions
        this.updatePositions(data);
        
        // Update statistics
        this.updateStats(data);
        
        // Update spread chart
        if (data.spread_chart_data) {
            updateSpreadChart(data.spread_chart_data);
        }
        
        // Update last update time
        document.getElementById('lastUpdate').textContent = 
            `Last update: ${new Date().toLocaleTimeString()}`;
    }

    updateStatus(data) {
        if (!data) return;
        
        // Trading mode
        const mode = data.trading_mode || 'STOPPED';
        this.updateModeBadge(mode.toLowerCase());
        
        // Connection status
        const bitgetHealthy = data.bitget_healthy || false;
        const hyperHealthy = data.hyper_healthy || false;
        
        const bitgetDot = document.getElementById('bitgetDot');
        const hyperDot = document.getElementById('hyperDot');
        
        bitgetDot.className = `status-dot ${bitgetHealthy ? 'healthy' : 'unhealthy'}`;
        hyperDot.className = `status-dot ${hyperHealthy ? 'healthy' : 'unhealthy'}`;
        
        // Trade counts
        document.getElementById('totalTrades').textContent = 
            (data.session_stats?.total_trades || 0).toLocaleString();
        document.getElementById('totalChecks').textContent = 
            (data.session_stats?.total_checks || 0).toLocaleString();
    }

    updateRuntime(seconds) {
        if (seconds === undefined || seconds === null) return;
        
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        
        document.getElementById('runtime').textContent = 
            `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    updateModeBadge(mode) {
        const badge = document.getElementById('modeBadge');
        badge.className = 'mode-badge';
        
        switch (mode) {
            case 'active':
                badge.textContent = '● ACTIVE';
                badge.classList.add('active');
                break;
            case 'partial':
                badge.textContent = '● PARTIAL';
                badge.classList.add('partial');
                break;
            case 'stopped':
                badge.textContent = '● STOPPED';
                badge.classList.add('stopped');
                break;
            case 'connecting':
                badge.textContent = 'CONNECTING...';
                break;
            case 'reconnecting':
                badge.textContent = 'RECONNECTING...';
                break;
            case 'disconnected':
                badge.textContent = 'DISCONNECTED';
                badge.classList.add('stopped');
                break;
            case 'failed':
                badge.textContent = 'CONNECTION FAILED';
                badge.classList.add('stopped');
                break;
            default:
                badge.textContent = mode.toUpperCase();
        }
    }

    updatePrices(data) {
        if (!data) return;
        
        const bitget = data.bitget_data || {};
        const hyper = data.hyper_data || {};
        
        // Bitget
        if (bitget.bid && bitget.ask) {
            const avgPrice = (bitget.bid + bitget.ask) / 2;
            document.getElementById('bitgetPrice').textContent = `$${avgPrice.toFixed(2)}`;
            document.getElementById('bitgetBid').textContent = `$${bitget.bid.toFixed(2)}`;
            document.getElementById('bitgetAsk').textContent = `$${bitget.ask.toFixed(2)}`;
        }
        
        // Hyperliquid
        if (hyper.bid && hyper.ask) {
            const avgPrice = (hyper.bid + hyper.ask) / 2;
            document.getElementById('hyperPrice').textContent = `$${avgPrice.toFixed(2)}`;
            document.getElementById('hyperBid').textContent = `$${hyper.bid.toFixed(2)}`;
            document.getElementById('hyperAsk').textContent = `$${hyper.ask.toFixed(2)}`;
        }
    }

    updateSpread(data) {
        if (!data) return;
        
        const spreads = data.spreads || {};
        
        // B -> H spread
        const bhSpread = spreads.b_to_h?.gross_spread;
        if (bhSpread !== undefined) {
            document.getElementById('spreadBH').textContent = `${bhSpread.toFixed(3)}%`;
            this.updateSpreadBar('spreadBarBH', bhSpread);
        }
        
        // H -> B spread
        const hbSpread = spreads.h_to_b?.gross_spread;
        if (hbSpread !== undefined) {
            document.getElementById('spreadHB').textContent = `${hbSpread.toFixed(3)}%`;
            this.updateSpreadBar('spreadBarHB', hbSpread);
        }
        
        // Best entry
        const bestEntry = data.best_entry_spread;
        const bestDirection = data.best_entry_direction;
        if (bestEntry !== undefined) {
            const bestEl = document.getElementById('bestEntry');
            bestEl.textContent = `${bestEntry.toFixed(3)}%`;
            bestEl.className = `best-value ${bestEntry >= 0.1 ? 'value-positive' : bestEntry > 0 ? 'value-neutral' : 'value-negative'}`;
            
            const dirEl = document.getElementById('bestEntryDirection');
            if (bestDirection) {
                dirEl.textContent = bestDirection;
            }
        }
        
        // Target
        const target = data.config?.MIN_SPREAD_ENTER * 100;
        if (target) {
            document.getElementById('spreadTarget').textContent = target.toFixed(2);
        }
    }

    updateSpreadBar(elementId, value) {
        const bar = document.getElementById(elementId);
        if (!bar) return;
        
        const maxPercent = 1.0;
        const width = Math.min(Math.abs(value) / maxPercent * 100, 100);
        bar.style.width = `${width}%`;
        
        bar.className = 'spread-bar-fill';
        if (value >= 0.3) {
            bar.classList.add('good');
        } else if (value > 0) {
            bar.classList.add('low');
        } else {
            bar.classList.add('negative');
        }
    }

    updateExitSpreads(data) {
        if (!data) return;
        
        const exitSpreads = data.exit_spreads || {};
        
        const bhExit = exitSpreads.b_to_h;
        const hbExit = exitSpreads.h_to_b;
        
        if (bhExit !== undefined) {
            document.getElementById('marketExitBH').textContent = `${bhExit.toFixed(3)}%`;
            document.getElementById('marketExitBH').className = `exit-value ${this.getExitSpreadClass(bhExit)}`;
        }
        
        if (hbExit !== undefined) {
            document.getElementById('marketExitHB').textContent = `${hbExit.toFixed(3)}%`;
            document.getElementById('marketExitHB').className = `exit-value ${this.getExitSpreadClass(hbExit)}`;
        }
        
        // Best market exit
        const bestExit = data.best_exit_overall;
        if (bestExit !== undefined && bestExit !== Infinity) {
            const bestEl = document.getElementById('bestMarketExit');
            bestEl.textContent = `${bestExit.toFixed(3)}%`;
            bestEl.className = `best-value ${this.getExitSpreadClass(bestExit)}`;
        }
        
        // Exit target
        const exitTarget = data.config?.MIN_SPREAD_EXIT * 100;
        if (exitTarget) {
            document.getElementById('exitTarget').textContent = Math.abs(exitTarget).toFixed(2);
        }
    }

    getExitSpreadClass(spread) {
        if (spread <= -0.1) return 'value-positive';
        if (spread <= 0) return 'value-neutral';
        return 'value-negative';
    }

    updateRecords(data) {
        if (!data) return;
        
        // Best entry record
        const bestEntry = data.best_entry_spread;
        if (bestEntry !== undefined && bestEntry > 0) {
            document.getElementById('bestEntryRecord').textContent = `${bestEntry.toFixed(3)}%`;
            
            const entryTime = data.best_entry_time;
            if (entryTime) {
                const ago = this.formatTimeAgo(entryTime);
                document.getElementById('bestEntryTime').textContent = ago;
            }
        } else {
            document.getElementById('bestEntryRecord').textContent = '---';
            document.getElementById('bestEntryTime').textContent = '---';
        }
        
        // Best exit record
        const bestExit = data.best_exit_overall;
        if (bestExit !== undefined && bestExit !== Infinity) {
            document.getElementById('bestExitRecord').textContent = `${bestExit.toFixed(3)}%`;
            
            const exitTime = data.best_exit_time;
            if (exitTime) {
                const ago = this.formatTimeAgo(exitTime);
                document.getElementById('bestExitTime').textContent = ago;
            }
        } else {
            document.getElementById('bestExitRecord').textContent = '---';
            document.getElementById('bestExitTime').textContent = '---';
        }
    }

    updatePortfolio(data) {
        if (!data) return;
        
        const portfolio = data.portfolio || {};
        const usdt = portfolio.USDT || 0;
        const nvda = portfolio.NVDA || 0;
        
        document.getElementById('portfolioUSDT').textContent = `$${usdt.toFixed(2)}`;
        document.getElementById('portfolioNVDA').textContent = nvda.toFixed(4);
        
        // Total value and PnL
        const totalValue = data.total_value || 0;
        const pnl = data.pnl || 0;
        
        document.getElementById('totalValue').textContent = `$${totalValue.toFixed(2)}`;
        
        const pnlEl = document.getElementById('pnlValue');
        pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
        pnlEl.className = `total-value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    }

    updatePositions(data) {
        if (!data) return;
        
        const positions = data.positions || [];
        const positionsList = document.getElementById('positionsList');
        document.getElementById('positionsCount').textContent = positions.length;
        
        if (positions.length === 0) {
            positionsList.innerHTML = '<div class="no-positions">No open positions</div>';
            return;
        }
        
        positionsList.innerHTML = positions.map(pos => {
            const dirClass = pos.direction === 'B_TO_H' ? 'b-to-h' : 'h-to-b';
            const dirLabel = pos.direction === 'B_TO_H' ? 'B → H' : 'H → B';
            
            let statusClass = 'normal';
            let statusText = 'Active';
            
            if (pos.should_close) {
                statusClass = 'ready';
                statusText = 'Ready!';
            } else if (pos.current_exit_spread <= pos.exit_target) {
                statusClass = 'warning';
                statusText = 'Target';
            }
            
            return `
                <div class="position-item ${dirClass}">
                    <span class="position-id">#${pos.id}</span>
                    <span class="position-direction">${dirLabel}</span>
                    <div class="position-details">
                        <div class="position-detail">
                            <span class="position-detail-label">Age:</span>
                            <span class="position-detail-value">${pos.age || '--'}</span>
                        </div>
                        <div class="position-detail">
                            <span class="position-detail-label">Exit:</span>
                            <span class="position-detail-value">${pos.exit_spread.toFixed(3)}%</span>
                        </div>
                        <div class="position-detail">
                            <span class="position-detail-label">Target:</span>
                            <span class="position-detail-value">≤${pos.exit_target.toFixed(3)}%</span>
                        </div>
                    </div>
                    <span class="exit-status ${statusClass}">${statusText}</span>
                </div>
            `;
        }).join('');
    }

    updateStats(data) {
        if (!data) return;
        
        const stats = data.session_stats || {};
        const runtime = data.runtime || 1;
        
        // Time percentages
        const activePct = (stats.time_in_active || 0) / runtime * 100;
        const partialPct = (stats.time_in_partial || 0) / runtime * 100;
        
        document.getElementById('activeTime').textContent = `${activePct.toFixed(1)}%`;
        document.getElementById('partialTime').textContent = `${partialPct.toFixed(1)}%`;
        
        // Spread stats
        const maxSpread = stats.max_spread || 0;
        const avgSpread = stats.avg_spread || 0;
        
        document.getElementById('maxSpread').textContent = `${maxSpread.toFixed(3)}%`;
        document.getElementById('avgSpread').textContent = `${avgSpread.toFixed(3)}%`;
    }

    formatTimeAgo(timestamp) {
        const now = Date.now() / 1000;
        const diff = now - timestamp;
        
        if (diff < 60) return `${Math.floor(diff)}s ago`;
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        return `${Math.floor(diff / 3600)}h ago`;
    }

    requestFullUpdate() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'request_full_update' }));
        }
    }

    setupEventListeners() {
        // Keyboard shortcut for refresh
        document.addEventListener('keydown', (e) => {
            if (e.key === 'r' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.requestFullUpdate();
            }
        });
    }
}

// Initialize dashboard when page loads
let dashboard = null;
let spreadChart = null;

document.addEventListener('DOMContentLoaded', () => {
    dashboard = new DashboardClient();
    initSpreadChart();
});

// Expose for external use
window.dashboard = dashboard;

function initSpreadChart() {
    const ctx = document.getElementById('spreadChart');
    if (!ctx) return;
    
    spreadChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Entry B→H',
                    data: [],
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Entry H→B',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Exit B→H',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Exit H→B',
                    data: [],
                    borderColor: '#f97316',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        usePointStyle: true,
                        pointStyle: 'line',
                        font: {
                            size: 11
                        }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    titleColor: '#f3f4f6',
                    bodyColor: '#d1d5db',
                    borderColor: '#374151',
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toFixed(3)}%`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        color: 'rgba(55, 65, 81, 0.3)'
                    },
                    ticks: {
                        color: '#6b7280',
                        maxTicksLimit: 10,
                        font: {
                            size: 10
                        }
                    }
                },
                y: {
                    display: true,
                    grid: {
                        color: 'rgba(55, 65, 81, 0.3)'
                    },
                    ticks: {
                        color: '#6b7280',
                        callback: function(value) {
                            return value.toFixed(2) + '%';
                        },
                        font: {
                            size: 10
                        }
                    },
                    suggestedMin: -0.2,
                    suggestedMax: 0.2
                }
            }
        }
    });
}

function updateSpreadChart(data) {
    if (!spreadChart) return;
    
    const labels = data.labels || [];
    const datasets = data.datasets || {};
    
    spreadChart.data.labels = labels;
    spreadChart.data.datasets[0].data = datasets.entry_bh || [];
    spreadChart.data.datasets[1].data = datasets.entry_hb || [];
    spreadChart.data.datasets[2].data = datasets.exit_bh || [];
    spreadChart.data.datasets[3].data = datasets.exit_hb || [];
    
    spreadChart.update('none');
}

function changeChartRange() {
    if (dashboard && dashboard.requestFullUpdate) {
        dashboard.requestFullUpdate();
    }
}
