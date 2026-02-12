function parseMarkdown(md) {
    if (!md) return "";

    // Limit to 500 chars
    let text = md.substring(0, 500);
    if (md.length > 500) text += "...";

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
        const val = path.split('.').reduce((o, i) => (o ? o[i] : undefined), obj);
        return val !== undefined ? val : fallback;
    };

    try {
        const memoryResp = await fetch('../memory.json');
        const memory = await memoryResp.json();

        // 1. World Status
        const world = memory.world || {};
        edgeEl.textContent = typeof world.edge === 'number' ? world.edge.toFixed(4) : '-';
        moodEl.textContent = world.mood || '-';
        bucketEl.textContent = world.bucket || '-';
        treasuryEl.textContent = typeof memory.economy?.treasury_mon === 'number'
            ? memory.economy.treasury_mon.toFixed(2) : '0.00';

        // 2. Last Decision
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

        // 3. Portfolio
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

        // 4. Outbox Fetch and Render
        try {
            const indexResp = await fetch('../outbox/index.json');
            if (!indexResp.ok) throw new Error("No index");
            const index = await indexResp.json();
            const posts = index.posts || [];

            if (posts.length === 0) {
                outboxList.innerHTML = '<p>No transmissions yet.</p>';
            } else {
                outboxList.innerHTML = '';
                for (let i = 0; i < posts.length; i++) {
                    const filename = posts[i];
                    try {
                        const postResp = await fetch(`../outbox/${filename}`);
                        if (!postResp.ok) continue;
                        const content = await postResp.text();

                        const card = document.createElement('div');
                        card.className = `paper-card ${i % 2 === 0 ? 'rotate-plus' : 'rotate-minus'}`;
                        card.innerHTML = `
                            <div class="post-content">${parseMarkdown(content)}</div>
                            <div class="post-footer">${filename}</div>
                        `;
                        outboxList.appendChild(card);
                    } catch (e) {
                        console.error(`Failed to fetch post ${filename}`, e);
                    }
                }
            }
        } catch (e) {
            outboxList.innerHTML = '<p>No transmissions yet.</p>';
        }

    } catch (err) {
        console.error(err);
        document.body.innerHTML = `
            <div class="container" style="text-align:center; padding-top:100px;">
                <h1>😵‍💫 NO DATA</h1>
                <p>MemeSeer is offline or memory is missing.</p>
            </div>
        `;
    }
});
