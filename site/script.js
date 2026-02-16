function parseMarkdown(md) {
    if (!md) return "";

    let text = md;

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

    // ================================
    // 1️⃣ LOAD MEMORY
    // ================================
    async function fetchMemory() {
        const resp = await fetch('/memory.json');
        if (!resp.ok) throw new Error("memory.json not found");
        return await resp.json();
    }

    try {
        const memory = await fetchMemory();

        // -------- WORLD STATUS --------
        const world = memory.world || {};

        edgeEl.textContent =
            typeof world.edge === 'number'
                ? world.edge.toFixed(4)
                : '-';

        moodEl.textContent = world.mood || '-';
        bucketEl.textContent = world.bucket || '-';

        treasuryEl.textContent =
            typeof memory.economy?.treasury_mon === 'number'
                ? memory.economy.treasury_mon.toFixed(2)
                : '0.00';

        // -------- LAST DECISION --------
        const events = memory.events || [];
        const runEvents = events.filter(e => e.type === 'run').reverse();

        if (runEvents.length > 0) {
            const lastRun = runEvents[0].record || {};
            const decision = lastRun.decision || {};

            lastDecisionEl.textContent =
                decision.launch ? "🚀 LAUNCH!" : "😴 NO LAUNCH";

            if (decision.launch && lastRun.token_idea) {
                tokenIdeaContainer.classList.remove('hidden');
                tokenNameEl.textContent = lastRun.token_idea.name || '-';
                tokenTickerEl.textContent = lastRun.token_idea.ticker || '-';
                tokenNarrativeEl.textContent = lastRun.token_idea.narrative || '-';
            }
        }

        // -------- PORTFOLIO --------
        const activePositions = memory.portfolio?.active_positions || [];

        if (activePositions.length === 0) {
            positionsGrid.innerHTML = '<p>No active gems... yet.</p>';
        } else {
            positionsGrid.innerHTML = '';

            activePositions.forEach(pos => {
                const card = document.createElement('div');
                card.className = 'position-card';

                card.innerHTML = `
                    <h3>$${pos.ticker || '???'}</h3>
                    <p><strong>Status:</strong> ${pos.status || '-'}</p>
                    <p><strong>Entry:</strong> ${pos.entry_cost_mon?.toFixed(2) || '-'} MON</p>
                `;

                positionsGrid.appendChild(card);
            });
        }

    } catch (err) {
        console.error("Memory load error:", err);
        document.querySelector('.world-status').innerHTML +=
            `<p style="color:red">⚠️ Failed to load memory.json</p>`;
    }

    // ================================
    // 2️⃣ LOAD OUTBOX
    // ================================
    try {
        const indexResp = await fetch('/outbox/index.json');
        if (!indexResp.ok) throw new Error("index.json missing");

        const index = await indexResp.json();
        const posts = index.posts || [];

        if (posts.length === 0) {
            outboxList.innerHTML = '<p>No transmissions yet.</p>';
            return;
        }

        outboxList.innerHTML = '';

        for (let i = 0; i < posts.length; i++) {
            const filename = posts[i];

            try {
                const postResp = await fetch(`/outbox/${filename}`);
                if (!postResp.ok) continue;

                const content = await postResp.text();

                const card = document.createElement('div');
                card.className =
                    `paper-card ${i % 2 === 0 ? 'rotate-plus' : 'rotate-minus'}`;

                card.innerHTML = `
                    <div class="post-content">${parseMarkdown(content)}</div>
                    <div class="post-footer">${filename}</div>
                `;

                outboxList.appendChild(card);

            } catch (e) {
                console.warn("Post load failed:", filename);
            }
        }

    } catch (err) {
        console.error("Outbox load error:", err);
        outboxList.innerHTML =
            `<p>⚠️ No transmissions yet.</p>`;
    }

});

