async function loadMemeSeer() {
    try {
        const response = await fetch('../memory.json');
        const memory = await response.json();

        // 1. Status Grid
        const world = memory.world || {};
        document.getElementById('mood-val').innerText = world.mood || 'Unknown';
        document.getElementById('edge-val').innerText = (world.edge || 0).toFixed(4);

        const balances = (memory.economy && memory.economy.balances) || {};
        document.getElementById('mon-val').innerText = `${Number(balances.mon || 0).toFixed(2)} MON`;
        document.getElementById('seer-val').innerText = `${Number(balances.seer || 0).toFixed(2)} SEER`;

        // 2. Portfolio Table
        const portfolioTable = document.getElementById('portfolio-table').querySelector('tbody');
        const activePositions = (memory.portfolio && memory.portfolio.active_positions) || [];

        if (activePositions.length === 0) {
            portfolioTable.innerHTML = '<tr><td colspan="4" style="text-align:center">No active positions</td></tr>';
        } else {
            portfolioTable.innerHTML = '';
            // Only show relevant ones (ACTIVE, EXITING)
            activePositions.slice(-5).reverse().forEach(pos => {
                const tr = document.createElement('tr');

                // For ROI, if we don't have real-time here, we show progress
                const roi = pos.ladder_hits ? (pos.ladder_hits.length > 0 ? `+${pos.ladder_hits[pos.ladder_hits.length - 1]}%` : 'Targeting...') : 'N/A';

                tr.innerHTML = `
                    <td style="font-weight: 600;">$${pos.ticker || '???'}</td>
                    <td>${Number(pos.entry_cost_mon || 0).toFixed(2)} MON</td>
                    <td>${roi}</td>
                    <td><span class="status-badge" style="background: ${pos.status === 'EXITING' ? 'rgba(255, 69, 58, 0.1)' : 'rgba(0, 255, 127, 0.1)'}; color: ${pos.status === 'EXITING' ? '#ff453a' : '#00ff7f'}">${pos.status || 'ACTIVE'}</span></td>
                `;
                portfolioTable.appendChild(tr);
            });
        }

        // 3. Last Decision
        const events = memory.events || [];
        const runEvents = events.filter(e => e.type === 'run').reverse();
        if (runEvents.length > 0) {
            const lastRun = runEvents[0].record || {};
            const decision = lastRun.decision || {};
            const tokenIdea = lastRun.token_idea || {};

            document.getElementById('decision-text').innerText = `"${decision.reason || 'No reason provided.'}"`;

            if (decision.launch && tokenIdea.name) {
                document.getElementById('token-header').innerText = `${tokenIdea.name} ($${tokenIdea.ticker})`;
                document.getElementById('token-narrative').innerText = tokenIdea.narrative || 'No narrative.';
            } else {
                document.getElementById('token-header').innerText = "Gated / No Launch";
                document.getElementById('token-narrative').innerText = "MemeSeer decided to stay on the sidelines.";
            }
        }

        // 4. Outbox Links (Recent Rituals)
        const outboxList = document.getElementById('outbox-list');
        outboxList.innerHTML = '';

        // Find recent launches in memory
        const launches = Object.values(memory.launches || {}).reverse();
        launches.slice(0, 10).forEach(launch => {
            if (launch.outbox_path) {
                const li = document.createElement('li');
                li.className = 'outbox-item';

                // path is f:\NADFUN2\outbox\... -> relative link
                const parts = launch.outbox_path.split('\\');
                const filename = parts[parts.length - 1];

                const a = document.createElement('a');
                a.href = `../outbox/${filename}`;
                a.target = '_blank';
                a.innerText = `Ritual for $${launch.token_idea.ticker} - ${new Date(launch.ts * 1000).toLocaleDateString()}`;

                li.appendChild(a);
                outboxList.appendChild(li);
            }
        });

    } catch (err) {
        console.error('Failed to load MemeSeer data:', err);
    }
}

// Main Loop
loadMemeSeer();
setInterval(loadMemeSeer, 60000); // Update every minute
