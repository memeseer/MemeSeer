function parseMarkdown(md) {
    if (!md) return "";

    let text = md;

    // Simple markdown rules
    text = text
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
        .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
        .replace(/\*(.*?)\*/g, '<i>$1</i>')
        .replace(/^> (.*$)/gim, '<blockquote>$1</blockquote>')
        .replace(/\n/g, '<br>');

    return text;
}

document.addEventListener('DOMContentLoaded', async () => {
    const edgeEl = document.getElementById('edge');
    const moodEl = document.getElementById('mood');
    const bucketEl = document.getElementById('bucket');
    const treasuryEl = document.getElementById('treasury');
    const lastDecisionEl = document.getElementById('last-decision');
    const tokenIdeaContainer = document.getElementById('token-idea');
    const tokenNameEl = document.getElementById('token-name');
    const tokenTickerEl = document.getElementById('token-ticker');
    const tokenNarrativeEl = document.getElementById('token-narrative');
    const positionsGrid = document.getElementById('positions-grid');
    const outboxList = document.getElementById('outbox-list');

    // Helper to safety-check memory fields
    const getVal = (obj, path, fallback = "-") => {
        if (!obj) return fallback;
        const val = path.split('.').reduce((o, i) => (o ? o[i] : undefined), obj);
        return val !== undefined ? val : fallback;
    };

    /**
     * Attempts to fetch memory.json from multiple candidate paths.
     */
    async function fetchMemory() {
        const candidates = ['public/memory.json', './public/memory.json', '../memory.json', './memory.json', 'memory.json'];
        for (const path of candidates) {
            try {
                const resp = await fetch(path);
                if (resp.ok) return await resp.json();
            } catch (e) {
                console.warn(`Failed to fetch from ${path}:`, e);
            }
        }
        throw new Error("Could not load memory.json from any known location.");
    }

    // 1. Load Memory and update World/Decision/Portfolio
    try {
        const memory = await fetchMemory();

        // 1.1 World Status
        try {
            const world = memory.world || {};
            edgeEl.textContent = typeof world.edge === 'number' ? world.edge.toFixed(4) : '-';
            moodEl.textContent = world.mood || '-';
            bucketEl.textContent = world.bucket || '-';
            treasuryEl.textContent = typeof memory.economy?.treasury_mon === 'number'
                ? memory.economy.treasury_mon.toFixed(2) : '0.00';
        } catch (e) {
            console.error("Error rendering world status:", e);
        }

        // 1.2 Last Decision
        try {
            const events = memory.events || [];
            const runEvents = events.filter(e => e.type === 'run').reverse();
            if (runEvents.length > 0) {
                const lastRun = runEvents[0].record || {};
                const decision = lastRun.decision || {};
                lastDecisionEl.textContent = decision.launch ? "🚀 LAUNCH!" : "😴 NO LAUNCH";

                if (decision.launch && lastRun.token_idea) {
                    tokenIdeaContainer.classList.remove('hidden');
                    tokenNameEl.textContent = lastRun.token_idea.name || '-';
                    tokenTickerEl.textContent = lastRun.token_idea.ticker || '-';
                    tokenNarrativeEl.textContent = lastRun.token_idea.narrative || '-';
                }
            }
        } catch (e) {
            console.error("Error rendering last decision:", e);
        }

        // 1.3 Portfolio
        try {
            const activePositions = memory.portfolio?.active_positions || [];
            if (activePositions.length === 0) {
                positionsGrid.innerHTML = '<p>No active gems... yet.</p>';
            } else {
                positionsGrid.innerHTML = '';
                activePositions.forEach(pos => {
                    const roi = typeof pos.roi === 'number' ? pos.roi : 0;
                    const card = document.createElement('div');
                    card.className = 'position-card';
                    card.innerHTML = `
                        <h3>$${pos.ticker || '???'}</h3>
                        <p class="roi ${roi >= 0 ? 'positive-roi' : ''}">${roi >= 0 ? '+' : ''}${roi.toFixed(2)}%</p>
                        <p><strong>Status:</strong> ${pos.status || '-'}</p>
                        <p><strong>Entry:</strong> ${typeof pos.entry_mon === 'number' ? pos.entry_mon.toFixed(2) : '-'} MON</p>
                        <p><strong>Alloc:</strong> ${typeof pos.allocation_pct === 'number' ? pos.allocation_pct.toFixed(1) : '-'}%</p>
                    `;
                    positionsGrid.appendChild(card);
                });
            }
        } catch (e) {
            console.error("Error rendering portfolio:", e);
            positionsGrid.innerHTML = '<p>Error loading portfolio data.</p>';
        }

    } catch (err) {
        console.error("Memory critical failure:", err);
        // Don't show "NO DATA" globally yet, let Outbox try to load
        const statusSection = document.querySelector('.world-status');
        if (statusSection) {
            statusSection.innerHTML += `<p style="color:red; font-size:0.8rem;">⚠️ Failed to load world data: ${err.message}</p>`;
        }
    }

    // 2. Outbox Fetch and Render (Decoupled from memory.json)
    try {
        async function fetchIndex() {
            const candidates = [
                'public/outbox/index.json',
                './public/outbox/index.json',
                '../outbox/index.json',
                './outbox/index.json',
                'outbox/index.json'
            ];
            for (const path of candidates) {
                try {
                    const resp = await fetch(path);
                    if (resp.ok) return await resp.json();
                } catch (e) {
                    console.warn(`Failed to fetch index from ${path}:`, e);
                }
            }
            throw new Error("No index.json found.");
        }

        const index = await fetchIndex();
        const posts = index.posts || [];

        if (posts.length === 0) {
            outboxList.innerHTML = '<p>No transmissions yet.</p>';
        } else {
            outboxList.innerHTML = '';
            // Try different base paths for posts
            const possibleBase = ['public/outbox/', './public/outbox/', '../outbox/', './outbox/', 'outbox/'];

            for (let i = 0; i < posts.length; i++) {
                const filename = posts[i];
                let content = null;

                for (const base of possibleBase) {
                    try {
                        const postResp = await fetch(`${base}${filename}`);
                        if (postResp.ok) {
                            content = await postResp.text();
                            break;
                        }
                    } catch (e) { }
                }

                if (content) {
                    const card = document.createElement('div');
                    card.className = `paper-card ${i % 2 === 0 ? 'rotate-plus' : 'rotate-minus'}`;
                    card.innerHTML = `
                        <div class="post-content">${parseMarkdown(content)}</div>
                        <div class="post-footer">${filename}</div>
                    `;
                    outboxList.appendChild(card);
                } else {
                    console.warn(`Could not load post content for ${filename}`);
                }
            }

            if (outboxList.innerHTML === '') {
                outboxList.innerHTML = '<p>Transmissions found but could not be loaded.</p>';
            }
        }
    } catch (e) {
        console.error("Outbox critical failure:", e);
        outboxList.innerHTML = `<p>⚠️ No transmissions yet or index missing: ${e.message}</p>`;
    }
});
